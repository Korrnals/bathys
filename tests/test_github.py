"""Unit tests for the GitHub specialization tier (crawler._github_special,
ideas-borrowed.md §3 — borrowed from pi-web-access):

  3a  PR/issues -> `gh pr|issue view` -> prioritized markdown document
  3b  repo root -> `gh api` (repo, contents, raw readme) -> markdown
  3c  raw.githubusercontent.com is NOT specialized — the HTTP tier already
      handles plain-text responses (library_docs phase 3 proved it live)

Fallback contract: a non-GitHub URL, missing gh binary, gh exit != 0 or a
gh timeout all return None — "continue with the normal HTTP path", never
an error. No network: subprocess execution and shutil.which are mocked.
"""

import asyncio
import unittest
from unittest import mock

import httpx

from bathys.config import Config
from bathys.crawler import (
    Crawler,
    Page,
    _gh_fetch_pull_or_issue,
    _gh_fetch_repo,
    _gh_match,
    _gh_run,
    _render_pr_or_issue,
    _render_repo,
)


class _FakeProc:
    """Minimal stand-in for the asyncio subprocess object _gh_run expects."""

    def __init__(self, *, rc: int = 0, out: bytes = b"{}", err: bytes = b"") -> None:
        self.returncode = rc
        self._out = out
        self._err = err
        self.killed = False

    def kill(self) -> None:  # timeout path
        self.killed = True

    async def communicate(self) -> tuple[bytes, bytes]:
        return self._out, self._err


class _GhScript:
    """Callable answering create_subprocess_exec calls in sequence."""

    def __init__(self, procs: list[_FakeProc]) -> None:
        self.procs = list(procs)
        self.calls: list[tuple[str, ...]] = []

    def __call__(self, *argv: str, **_kwargs) -> _FakeProc:
        self.calls.append(argv)
        return self.procs.pop(0)


def _crawler() -> Crawler:
    return Crawler(mock.Mock(spec=Config, browser_mode="auto"))


def _patch_exec(script: _GhScript):
    return mock.patch(
        "bathys.crawler.asyncio.create_subprocess_exec",
        side_effect=script,
        autospec=True,
    )


def _patch_which(found: bool):
    return mock.patch(
        "bathys.crawler.shutil.which", return_value="/usr/bin/gh" if found else None
    )


# ------------------------------------------------------------------ detect ---


class GhMatchTest(unittest.TestCase):
    """URL detector: only github.com PR/issues/repo-root URLs are ours."""

    def test_pull_issues_and_repo_root(self):
        self.assertEqual(
            _gh_match("https://github.com/o/r/pull/12"), ("pull", "o", "r", "12")
        )
        self.assertEqual(
            _gh_match("https://github.com/o/r/issues/5"), ("issues", "o", "r", "5")
        )
        self.assertEqual(
            _gh_match("https://github.com/Korrnals/bathys"),
            ("repo", "Korrnals", "bathys", ""),
        )
        self.assertEqual(
            _gh_match("https://github.com/Korrnals/bathys/"),
            ("repo", "Korrnals", "bathys", ""),
        )

    def test_subpage_variants_still_match_the_object(self):
        # github.com/o/r/pull/12/files describes the same PR
        self.assertEqual(
            _gh_match("https://github.com/o/r/pull/12/files"), ("pull", "o", "r", "12")
        )

    def test_non_special_paths_return_none(self):
        for url in (
            "https://raw.githubusercontent.com/o/r/main/x.py",  # 3c: plain HTTP
            "https://gist.github.com/o/r",
            "https://api.github.com/repos/o/r",
            "https://github.com/o/r/tree/main",
            "https://github.com/o/r/blob/main/x.py",
            "https://github.com/o/r/releases",
            "https://github.com/o",  # no repo
            "https://github.com/o/r/pull",  # no number
            "https://github.com/o/r/pull/abc",  # non-numeric
            "https://example.com/o/r/pull/1",  # wrong host
        ):
            self.assertIsNone(_gh_match(url), url)

    def test_scheme_and_host_variants(self):
        self.assertEqual(_gh_match("http://github.com/o/r"), ("repo", "o", "r", ""))
        self.assertEqual(
            _gh_match("https://www.github.com/o/r"), ("repo", "o", "r", "")
        )


# ---------------------------------------------------------------- markdown ---

_PR_JSON = {
    "title": "Add retry support",
    "state": "OPEN",
    "author": {"login": "alice"},
    "body": "Retries outgoing  requests  with backoff.",
    "files": [{"path": "src/a.py"}, {"path": "src/b.py"}],
    "reviews": [{"author": {"login": "bob"}, "state": "APPROVED", "body": "LGTM"}],
    "comments": [
        {"author": {"login": "carol"}, "body": "Nice work!"},
        {"author": {"login": "dave"}, "body": "Rebased."},
    ],
    "statusCheckRollup": [
        {
            "name": "py-test",
            "workflowName": "CI",
            "conclusion": "SUCCESS",
            "status": "COMPLETED",
        },
        {
            "name": "lint",
            "workflowName": "",
            "conclusion": "FAILURE",
            "status": "COMPLETED",
        },
    ],
}


class RenderPrOrIssueTest(unittest.TestCase):
    def test_section_set_and_order(self):
        md = _render_pr_or_issue("pull", _PR_JSON)
        self.assertTrue(md.startswith("# [PR] Add retry support (OPEN)\n"))
        order = [
            md.index(s)
            for s in ("## Body", "## Files", "## Reviews", "## Checks", "## Comments")
        ]
        self.assertEqual(order, sorted(order), md)
        self.assertIn("- Author: alice", md)
        self.assertIn("src/a.py, src/b.py", md)
        self.assertIn("- bob (APPROVED): LGTM", md)
        self.assertIn("- carol: Nice work!", md)
        self.assertIn("- dave: Rebased.", md)
        self.assertIn("CI / py-test: SUCCESS", md)
        self.assertIn("- lint: FAILURE", md)

    def test_comments_preserve_server_order(self):
        md = _render_pr_or_issue("pull", _PR_JSON)
        self.assertLess(md.index("carol"), md.index("dave"))

    def test_issue_header_and_missing_sections_omitted(self):
        md = _render_pr_or_issue(
            "issues", {"title": "Bug", "state": "CLOSED", "body": "It breaks."}
        )
        self.assertTrue(md.startswith("# [Issue] Bug (CLOSED)\n"))
        self.assertNotIn("## Files", md)
        self.assertNotIn("## Reviews", md)
        self.assertNotIn("## Comments", md)
        self.assertIn("## Body\nIt breaks.", md)

    def test_empty_body_is_honest(self):
        md = _render_pr_or_issue("issues", {"title": "T", "state": "OPEN", "body": ""})
        self.assertIn("## Body\n(no description)", md)


class RenderRepoTest(unittest.TestCase):
    _REPO = {
        "name": "bathys",
        "full_name": "Korrnals/bathys",
        "html_url": "https://github.com/Korrnals/bathys",
        "description": "Local  deep-research  service",
        "default_branch": "main",
        "topics": ["mcp", "search"],
    }
    _TREE = [{"name": "src", "type": "dir"}, {"name": "README.md", "type": "file"}]

    def test_structure(self):
        md = _render_repo(self._REPO, self._TREE, "# Bathys\nUnified local.")
        self.assertTrue(md.startswith("# bathys\n"))
        self.assertIn("- Description: Local deep-research service", md)
        self.assertIn("- Topics: mcp, search", md)
        self.assertIn("- Default branch: main", md)
        self.assertIn("## Root", md)
        self.assertIn("src/", md)
        self.assertIn("README.md", md)
        self.assertIn("## README\n# Bathys", md)

    def test_empty_repo_renders_without_root_and_readme(self):
        md = _render_repo({"name": "empty", "full_name": "o/empty"}, None, "")
        self.assertIn("# empty", md)
        self.assertNotIn("## Root", md)
        self.assertNotIn("## README", md)


# ----------------------------------------------------------------- gh run ---


class GhRunTest(unittest.TestCase):
    def test_missing_binary_raises_unavailable(self):
        with _patch_which(False):
            with self.assertRaisesRegex(Exception, "gh CLI not found"):
                asyncio.run(_gh_run(["api", "x"]))

    def test_nonzero_exit_raises_with_stderr_excerpt(self):
        script = _GhScript([_FakeProc(rc=1, err=b"gh: Not Found")])
        with _patch_which(True), _patch_exec(script):
            with self.assertRaisesRegex(Exception, "exit 1"):
                asyncio.run(_gh_run(["api", "x"]))

    def test_bad_json_raises_unavailable(self):
        script = _GhScript([_FakeProc(out=b"<html>oops")])
        with _patch_which(True), _patch_exec(script):
            with self.assertRaisesRegex(Exception, "not valid JSON"):
                asyncio.run(_gh_run(["api", "x"]))

    def test_raw_mode_returns_bytes_decoded(self):
        script = _GhScript([_FakeProc(out=b"# readme")])
        with _patch_which(True), _patch_exec(script):
            out = asyncio.run(_gh_run(["api", "x"], raw=True))
        self.assertEqual(out, "# readme")


# ------------------------------------------------------------------ retry ----


class OldGhRetryTest(unittest.TestCase):
    """Old gh rejects newer --json fields with exit 1; the full-set failure
    retries once with the minimal set every gh knows."""

    def test_full_field_failure_retries_with_minimal(self):
        ok = _FakeProc(
            out=b'{"title": "T", "state": "OPEN", "body": "B", '
            b'"author": {"login": "a"}, "comments": [], '
            b'"url": "u"}'
        )
        script = _GhScript([_FakeProc(rc=1, err=b"Unknown JSON field"), ok])
        with _patch_which(True), _patch_exec(script):
            d = asyncio.run(_gh_fetch_pull_or_issue("pull", "o", "r", "7"))
        self.assertEqual(d["title"], "T")
        self.assertEqual(len(script.calls), 2)
        first = " ".join(script.calls[0])
        second = " ".join(script.calls[1])
        self.assertIn("reviews", first)  # full set attempted first
        self.assertIn("statusCheckRollup", first)
        self.assertNotIn("reviews", second)  # minimal set on retry
        self.assertNotIn("statusCheckRollup", second)
        self.assertIn("pr view 7", second)

    def test_both_sets_failing_raises(self):
        script = _GhScript([_FakeProc(rc=1, err=b"boom")] * 2)
        with _patch_which(True), _patch_exec(script):
            with self.assertRaisesRegex(Exception, "exit 1"):
                asyncio.run(_gh_fetch_pull_or_issue("pull", "o", "r", "7"))
        self.assertEqual(len(script.calls), 2)

    def test_issue_view_single_attempt_minimal_fields(self):
        ok = _FakeProc(
            out=b'{"title": "T", "state": "OPEN", "body": "", '
            b'"author": {"login": "a"}, "comments": [], '
            b'"url": "u"}'
        )
        script = _GhScript([ok])
        with _patch_which(True), _patch_exec(script):
            asyncio.run(_gh_fetch_pull_or_issue("issues", "o", "r", "3"))
        argv = " ".join(script.calls[0])
        self.assertIn("issue view 3", argv)
        self.assertNotIn("reviews", argv)
        self.assertNotIn("statusCheckRollup", argv)


# ------------------------------------------------------------ repo fetch ----


class GhFetchRepoTest(unittest.TestCase):
    def test_three_calls_and_readme_cap(self):
        long_readme = "R" * 20_000
        script = _GhScript(
            [
                _FakeProc(out=b'{"name": "r", "description": "d"}'),
                _FakeProc(out=b'[{"name": "src", "type": "dir"}]'),
                _FakeProc(out=long_readme.encode()),
            ]
        )
        with _patch_which(True), _patch_exec(script):
            repo, tree, readme = asyncio.run(_gh_fetch_repo("o", "r"))
        self.assertEqual(repo["name"], "r")
        self.assertEqual(tree, [{"name": "src", "type": "dir"}])
        self.assertEqual(len(readme), 8000)  # first ~8000 chars, per contract
        self.assertEqual(len(script.calls), 3)
        raw_call = " ".join(script.calls[2])
        self.assertIn("Accept: application/vnd.github.raw", raw_call)

    def test_missing_readme_and_tree_do_not_fail_the_doc(self):
        script = _GhScript(
            [
                _FakeProc(out=b'{"name": "r"}'),  # repo ok
                _FakeProc(rc=1, err=b"gh: Not Found"),  # contents 404 -> omitted
                _FakeProc(rc=1, err=b"gh: Not Found"),  # readme 404 -> omitted
            ]
        )
        with _patch_which(True), _patch_exec(script):
            repo, tree, readme = asyncio.run(_gh_fetch_repo("o", "r"))
        self.assertEqual(repo["name"], "r")
        self.assertIsNone(tree)
        self.assertEqual(readme, "")


# ------------------------------------------------------- _github_special ----


class _GhAnswer:
    """Scripted gh answers by URL substring, most-specific needle first
    (readable scenario tests)."""

    def __init__(self, mapping: dict[str, bytes]) -> None:
        self.mapping = mapping
        self.calls: list[tuple[str, ...]] = []

    def __call__(self, *argv: str, **_kwargs) -> _FakeProc:
        self.calls.append(argv)
        key = " ".join(argv)
        for needle in sorted(self.mapping, key=len, reverse=True):
            if needle in key:
                return _FakeProc(out=self.mapping[needle])
        return _FakeProc(rc=1, err=b"gh: no scripted answer")


_PR_VIEW = (
    b'{"title": "Fix X", "state": "MERGED", '
    b'"author": {"login": "dalf"}, "body": "Outgoing networks.", '
    b'"comments": [{"author": {"login": "u1"}, "body": "c1"}], '
    b'"url": "https://github.com/o/r/pull/1"}'
)

_REPO_API = (
    b'{"name": "bathys", "full_name": "Korrnals/bathys", '
    b'"html_url": "https://github.com/Korrnals/bathys", '
    b'"description": "Deep research", "default_branch": "main", '
    b'"topics": ["mcp"]}'
)


class GithubSpecialTest(unittest.TestCase):
    def test_pull_url_yields_github_tier_page(self):
        script = _GhAnswer({"pr view": _PR_VIEW})
        with _patch_which(True), _patch_exec(script):
            page = asyncio.run(
                _crawler()._github_special("https://github.com/searxng/searxng/pull/1")
            )
        self.assertIsNotNone(page)
        self.assertEqual(page.tier, "github")
        self.assertEqual(page.status, 200)
        self.assertEqual(page.title, "[PR] Fix X")
        self.assertTrue(page.text.startswith("# [PR] Fix X (MERGED)"))
        self.assertEqual(page.raw_chars, len(page.text))
        self.assertIn("- u1: c1", page.text)

    def test_issue_url_uses_issue_view(self):
        script = _GhAnswer({"issue view": _PR_VIEW})
        with _patch_which(True), _patch_exec(script):
            page = asyncio.run(
                _crawler()._github_special("https://github.com/o/r/issues/9")
            )
        self.assertIsNotNone(page)
        self.assertEqual(page.tier, "github")
        argv = " ".join(script.calls[0])
        self.assertIn("issue view 9", argv)

    def test_repo_root_yields_repo_doc(self):
        script = _GhAnswer(
            {
                "repos/Korrnals/bathys/contents": b'[{"name": "src", "type": "dir"}]',
                "repos/Korrnals/bathys/readme": b"# Bathys",
                "repos/Korrnals/bathys": _REPO_API,  # shortest needle: the bare repo call
            }
        )
        with _patch_which(True), _patch_exec(script):
            page = asyncio.run(
                _crawler()._github_special("https://github.com/Korrnals/bathys")
            )
        self.assertIsNotNone(page)
        self.assertEqual(page.tier, "github")
        self.assertEqual(page.title, "Korrnals/bathys")
        self.assertTrue(page.text.startswith("# bathys\n"))
        self.assertIn("## Root\nsrc/", page.text)
        self.assertIn("## README\n# Bathys", page.text)

    def test_non_github_url_returns_none_without_gh_calls(self):
        script = _GhAnswer({})
        with _patch_which(True), _patch_exec(script):
            page = asyncio.run(
                _crawler()._github_special(
                    "https://raw.githubusercontent.com/o/r/main/x.py"
                )
            )
        self.assertIsNone(page)
        self.assertEqual(script.calls, [])

    def test_missing_binary_returns_none(self):
        with _patch_which(False):
            page = asyncio.run(
                _crawler()._github_special("https://github.com/o/r/pull/1")
            )
        self.assertIsNone(page)

    def test_gh_failure_returns_none_not_error(self):
        script = _GhScript([_FakeProc(rc=1, err=b"gh: Not Found")] * 2)
        with _patch_which(True), _patch_exec(script):
            page = asyncio.run(
                _crawler()._github_special("https://github.com/o/r/pull/1")
            )
        self.assertIsNone(page)

    def test_gh_timeout_returns_none(self):
        class _HangProc(_FakeProc):
            """communicate() blocks until kill() — like a real stuck process."""

            def __init__(self) -> None:
                super().__init__()
                self._dead = asyncio.Event()

            def kill(self) -> None:
                self.killed = True
                self._dead.set()

            async def communicate(self) -> tuple[bytes, bytes]:
                await self._dead.wait()
                return b"", b""

        hang_procs = [_HangProc(), _HangProc()]  # full set + minimal retry both hang
        script = _GhScript(hang_procs)
        with (
            _patch_which(True),
            _patch_exec(script),
            mock.patch("bathys.crawler._GH_TIMEOUT", 0.05),
        ):
            page = asyncio.run(
                _crawler()._github_special("https://github.com/o/r/pull/1")
            )
        self.assertIsNone(page)
        self.assertEqual(len(script.calls), 2)  # timeout does not skip the retry
        self.assertTrue(all(p.killed for p in hang_procs))

    def test_repo_api_answering_junk_falls_back(self):
        # junk repo json + the two best-effort calls failing -> None
        script = _GhScript(
            [
                _FakeProc(out=b'{"weird": 1}'),
                _FakeProc(rc=1, err=b"gh: Not Found"),
                _FakeProc(rc=1, err=b"gh: Not Found"),
            ]
        )
        with _patch_which(True), _patch_exec(script):
            page = asyncio.run(_crawler()._github_special("https://github.com/o/r"))
        self.assertIsNone(page)


class FetchDispatchTest(unittest.TestCase):
    """fetch(): the specialization runs first; None keeps the HTTP flow."""

    @staticmethod
    def _http_page() -> Page:
        return Page(
            url="https://example.com/doc",
            status=200,
            title="Doc",
            text="real content " * 100,
            raw_chars=1400,
            tier="http",
        )

    def test_fetch_returns_special_page_without_http_call(self):
        script = _GhAnswer({"pr view": _PR_VIEW})
        crawler = _crawler()
        with (
            _patch_which(True),
            _patch_exec(script),
            mock.patch.object(Crawler, "_fetch_http") as http,
        ):
            page = asyncio.run(crawler.fetch("https://github.com/o/r/pull/1"))
        self.assertEqual(page.tier, "github")
        http.assert_not_called()

    def test_fetch_falls_back_to_http_when_gh_fails(self):
        crawler = _crawler()
        http_page = self._http_page()
        script = _GhScript([_FakeProc(rc=1, err=b"gh: broken")] * 2)
        with (
            _patch_which(True),
            _patch_exec(script),
            mock.patch.object(
                Crawler, "_fetch_http", return_value=(http_page, "<html>x")
            ),
        ):
            page = asyncio.run(
                crawler.fetch(
                    "https://github.com/o/r/pull/1",
                    http=mock.Mock(spec=httpx.AsyncClient),
                )
            )
        self.assertIs(page, http_page)

    def test_fetch_non_github_skips_specialization(self):
        crawler = _crawler()
        http_page = self._http_page()
        script = _GhAnswer({})
        with (
            _patch_which(True),
            _patch_exec(script),
            mock.patch.object(
                Crawler, "_fetch_http", return_value=(http_page, "<html>hi")
            ),
        ):
            page = asyncio.run(crawler.fetch("https://example.com/doc"))
        self.assertIs(page, http_page)
        self.assertEqual(script.calls, [])


if __name__ == "__main__":
    unittest.main()
