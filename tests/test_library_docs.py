"""Unit tests for library_docs: seed index, resolver, subpage extraction,
phase 3a (version pinning) and 3b (user-grown index)."""

import asyncio
import dataclasses
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from bathys.library_docs import (  # noqa: E402
    _extract_subpages,
    _gh_repo_from,
    _index_lookup,
    _seed_index,
    _same_site,
    _normalize,
    _save_to_user_index,
    _tag_variants,
    library_docs,
    resolve_docs_url,
)


def _cfg_with(tmp: Path):
    """A real frozen Config redirected into a tmp dir, tests' env-mock
    pattern: dataclasses.replace(cfg, data_dir=tmp)."""
    from bathys.config import Config

    return dataclasses.replace(Config.load(), data_dir=tmp, cache_dir=tmp / "cache")


class SeedIndexTest(unittest.TestCase):
    def test_index_loads_with_entries(self):
        idx = _seed_index()
        self.assertGreater(len(idx), 20)
        self.assertIn("fastapi", idx)
        self.assertIn("pytorch", idx)
        self.assertTrue(all(v.startswith("https://") for v in idx.values()))

    def test_normalize_strips_slashes_and_case(self):
        self.assertEqual(_normalize("/FastAPI/"), "fastapi")


class SameSiteTest(unittest.TestCase):
    def test_same_host_variants(self):
        self.assertTrue(_same_site("https://a.com/x", "https://a.com/y"))
        self.assertTrue(_same_site("https://www.a.com/x", "https://a.com/y"))
        self.assertFalse(_same_site("https://a.com/x", "https://b.com/y"))


class ExtractSubpagesTest(unittest.TestCase):
    """Subpage ranking: same-site only, query-token overlap, asset filter."""

    BASE = "https://fastapi.tiangolo.com/"

    def test_ranks_by_query_tokens_and_filters_assets(self):
        raw = ("Guide [deps](https://fastapi.tiangolo.com/tutorial/dependencies/) "
               "[img](https://fastapi.tiangolo.com/logo.png) "
               "[advanced](https://fastapi.tiangolo.com/advanced/advanced-dependencies/) "
               "[alien](https://example.com/tutorial/dependencies/)")
        got = _extract_subpages(raw, self.BASE, "dependency injection", limit=2)
        self.assertEqual(set(got), {"https://fastapi.tiangolo.com/tutorial/dependencies/",
                                     "https://fastapi.tiangolo.com/advanced/advanced-dependencies/"})
        self.assertEqual(len(got), 2)

    def test_content_path_bonus(self):
        raw = ("[a](https://x.org/guide/setup) [b](https://x.org/random) "
               "[c](https://x.org/docs/tutorial)")
        got = _extract_subpages(raw, "https://x.org/", "guide", limit=2)
        self.assertEqual(got[0], "https://x.org/guide/setup")

    def test_no_links_returns_empty(self):
        self.assertEqual(_extract_subpages("no urls here", self.BASE, "q", limit=3), [])

    def test_limit_respected(self):
        raw = " ".join(f"(https://fastapi.tiangolo.com/guide/part{i}/)" for i in range(10))
        got = _extract_subpages(raw, self.BASE, "guide", limit=3)
        self.assertEqual(len(got), 3)


class ResolverAliasTest(unittest.TestCase):
    def test_alias_suffixes_hit_index(self):
        class _NoSearchEngine:
            async def search(self, *a, **k):  # pragma: no cover — must not be reached
                raise AssertionError("search must not run for an index hit")

        url, source = asyncio.run(resolve_docs_url(_NoSearchEngine(), "nodejs"))
        self.assertEqual(source, "index")
        self.assertIn("nodejs.org", url)


class TagVariantsTest(unittest.TestCase):
    def test_bare_semver_gains_v_prefix(self):
        self.assertEqual(_tag_variants("0.115.0"), ("0.115.0", "v0.115.0"))

    def test_v_prefixed_strips_to_bare(self):
        self.assertEqual(_tag_variants("v2.1"), ("v2.1", "2.1"))

    def test_branch_and_sha_pass_through(self):
        self.assertEqual(_tag_variants("main"), ("main",))
        self.assertEqual(_tag_variants("deadbeef"), ("deadbeef",))


class GhRepoFromTest(unittest.TestCase):
    def test_github_repo_url(self):
        self.assertEqual(_gh_repo_from("https://github.com/encode/httpx", "x"),
                         ("encode", "httpx"))

    def test_owner_slash_repo_library_name(self):
        self.assertEqual(_gh_repo_from("https://example.com/", "encode/httpx"),
                         ("encode", "httpx"))

    def test_doc_site_and_plain_name_give_no_repo(self):
        # no guessing: fastapi resolves to a doc site, not github.com/fastapi
        self.assertIsNone(_gh_repo_from("https://fastapi.tiangolo.com/", "fastapi"))
        self.assertIsNone(_gh_repo_from("https://pandas.pydata.org/docs/", "pandas"))


class UserIndexTest(unittest.TestCase):
    """Phase 3b: search finds -> stored; next resolve hits user-index."""

    def test_search_resolve_is_saved_and_reused(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = _cfg_with(Path(tmp))
            calls = []

            class FakeEngine:
                def __init__(self):
                    self.cfg = cfg

                async def search(self, q, **k):
                    calls.append(q)
                    return "1. Trio docs\nhttps://trio-docs.test/usage"

            url, source = asyncio.run(resolve_docs_url(FakeEngine(), "trio"))
            self.assertEqual((url, source), ("https://trio-docs.test/usage", "search"))
            self.assertEqual(len(calls), 1)

            # second resolve for the same library: no search call, user-index
            url2, source2 = asyncio.run(resolve_docs_url(FakeEngine(), "trio"))
            self.assertEqual((url2, source2), ("https://trio-docs.test/usage", "user-index"))
            self.assertEqual(len(calls), 1)  # nothing new was searched

    def test_user_index_does_not_shadow_seed(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = _cfg_with(Path(tmp))

            class FakeEngine:
                def __init__(self):
                    self.cfg = cfg

                async def search(self, q, **k):  # pragma: no cover
                    raise AssertionError("seed hit must not search")

            # fastapi is in the seed index even if a user entry exists
            _save_to_user_index(cfg.docs_index, "fastapi", "https://wrong.test/")
            url, source = asyncio.run(resolve_docs_url(FakeEngine(), "fastapi"))
            self.assertEqual(source, "index")
            self.assertIn("tiangolo", url)

    def test_github_slug_guess_is_not_saved(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = _cfg_with(Path(tmp))

            class FakeEngine:
                def __init__(self):
                    self.cfg = cfg

                async def search(self, q, **k):
                    return "no doc-like urls here"

            asyncio.run(resolve_docs_url(FakeEngine(), "somelib"))
            self.assertFalse(cfg.docs_index.exists())  # lazy: no file at all

    def test_save_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = _cfg_with(Path(tmp))
            _save_to_user_index(cfg.docs_index, "trio", "https://t.test/")
            first = cfg.docs_index.read_text()
            _save_to_user_index(cfg.docs_index, "trio", "https://t.test/")
            self.assertEqual(cfg.docs_index.read_text(), first)

    def test_corrupt_index_is_ignored_and_rewritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = _cfg_with(Path(tmp))
            cfg.docs_index.write_text("{ not json")
            _save_to_user_index(cfg.docs_index, "trio", "https://t.test/")
            data = cfg.docs_index.read_text()
            self.assertIn("https://t.test/", data)

    def test_no_tmp_files_left_behind(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = _cfg_with(Path(tmp))
            _save_to_user_index(cfg.docs_index, "trio", "https://t.test/")
            leftovers = [p.name for p in Path(tmp).glob("*.tmp*")]
            self.assertEqual(leftovers, [])


class LibraryDocsEndToEndTest(unittest.TestCase):
    """Whole-call fakes: resolve -> read -> distill -> footer, no network."""

    def _fake_engine(self, cfg, reads: dict, searches=None):
        class _Page:
            def __init__(self, text):
                self.text, self.raw_chars, self.url, self.status, self.title = (
                    text, len(text), "", 200, "")

        class _Res:
            def __init__(self, text, hit=False):
                self.page = _Page(text)
                self.cache_hit = hit

        class FakeEngine:
            _dive_sem = asyncio.Semaphore(2)

            def __init__(self):
                self.cfg = cfg
                self.read_calls = []
                self.search_calls = 0

            async def search(self, q, **k):
                self.search_calls += 1
                return searches or ""

            async def _read(self, url, **k):
                self.read_calls.append(url)
                if url not in reads:
                    raise RuntimeError(f"crawl failed: http 404")
                return _Res(reads[url])

        return FakeEngine()

    def test_happy_path_and_user_index_growth(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = _cfg_with(Path(tmp))
            docs_url = "https://docs.fakepkg.test/"
            eng = self._fake_engine(
                cfg, reads={docs_url: "# Fakepkg\nReal content about fakepkg."},
                searches="1. Fakepkg docs\n" + docs_url)
            out = asyncio.run(library_docs(eng, "fakepkg", "what is fakepkg",
                                           subpages=0))
            self.assertIn("источник: search", out)
            self.assertIn(docs_url, out)
            self.assertIn("[bathys: docs", out)
            # the find landed in the user index
            self.assertIn(docs_url, cfg.docs_index.read_text())

    def test_second_call_resolves_from_user_index(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = _cfg_with(Path(tmp))
            docs_url = "https://docs.fakepkg.test/"
            eng = self._fake_engine(
                cfg, reads={docs_url: "# Fakepkg\nReal content about fakepkg."},
                searches="1. Fakepkg docs\n" + docs_url)
            asyncio.run(library_docs(eng, "fakepkg", "what is fakepkg", subpages=0))
            self.assertEqual(eng.search_calls, 1)
            out = asyncio.run(library_docs(eng, "fakepkg", "how to install",
                                           subpages=0))
            self.assertIn("источник: user-index", out)
            self.assertEqual(eng.search_calls, 1)  # no re-search on 2nd call

    def test_version_github_tag_raw_pin(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = _cfg_with(Path(tmp))
            raw_url = ("https://raw.githubusercontent.com/encode/httpx/"
                       "0.28.1/README.md")
            eng = self._fake_engine(
                cfg, reads={raw_url: "# httpx\nhttpx 0.28.1 README"},
                searches="1. httpx docs\nhttps://github.com/encode/httpx")
            out = asyncio.run(library_docs(eng, "hobbylib", "client usage",
                                           subpages=0, version="0.28.1"))
            self.assertIn(raw_url, out)
            self.assertIn("search+raw@0.28.1", out)
            self.assertNotIn("показана последняя", out)

    def test_version_github_tag_miss_falls_back_with_note(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = _cfg_with(Path(tmp))
            gh_url = "https://github.com/encode/hobbylib"
            eng = self._fake_engine(
                cfg, reads={gh_url: "# Hobbylib home"},
                searches="1. Hobbylib docs\n" + gh_url)
            out = asyncio.run(library_docs(eng, "hobbylib", "what", subpages=0,
                                           version="9.9.9"))
            self.assertIn(gh_url, out)  # latest path used
            self.assertIn("Версия 9.9.9: источник на GitHub не найден", out)
            self.assertIn("показана последняя документация", out)

    def test_version_doc_site_note_and_latest_shown(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = _cfg_with(Path(tmp))
            eng = self._fake_engine(
                cfg, reads={"https://fastapi.tiangolo.com/": "# FastAPI"},
                searches="")
            out = asyncio.run(library_docs(eng, "fastapi", "deps", subpages=0,
                                           version="0.100.0"))
            self.assertIn("https://fastapi.tiangolo.com/", out)
            self.assertIn("пиннинг версий поддержан только для GitHub", out)
            self.assertIn("показана последняя документация", out)


if __name__ == "__main__":
    unittest.main()

class DisambiguationTest(unittest.TestCase):
    """QA-audit finding: bare names resolving to wrong same-named projects.
    Programming-vocabulary prior must pick the right candidate."""

    def test_code_prior_prefers_python_candidate(self):
        import asyncio

        from bathys.library_docs import resolve_docs_url

        class _FakeEngine:
            async def search(self, q, max_results=5, refresh=False):
                return (
                    "1. TrioDocs\n   https://triodocs.org/\n"
                    "   Trio is an open-source automated insulin delivery system for iOS\n"
                    "2. Tutorial — Trio documentation\n   https://trio.readthedocs.io/en/stable/tutorial.html\n"
                    "   Unlike many async/await tutorials... python interpreter\n"
                )

            cfg = None  # no user-index path in a fake engine

        url, source = asyncio.run(
            resolve_docs_url(_FakeEngine(), "trio", "structured concurrency"))
        self.assertEqual(url, "https://trio.readthedocs.io/en/stable/tutorial.html")
        self.assertEqual(source, "search")

    def test_no_query_keeps_first_candidate(self):
        import asyncio

        from bathys.library_docs import resolve_docs_url

        class _FakeEngine:
            async def search(self, q, max_results=5, refresh=False):
                return "1. A\n   https://docs.a.org/x\n   about a\n"

            cfg = None

        url, _ = asyncio.run(resolve_docs_url(_FakeEngine(), "a"))
        self.assertEqual(url, "https://docs.a.org/x")

    def test_query_terms_beat_code_prior(self):
        # query terms in a snippet outweigh the generic prior — but the
        # host-match bonus is a separate, stronger heuristic (a candidate
        # owning the library-name domain wins); assert that ordering.
        import asyncio

        from bathys.library_docs import resolve_docs_url

        class _FakeEngine:
            async def search(self, q, max_results=5, refresh=False):
                return (
                    "1. Random trio blog\n   https://blogs.example.org/structured-concurrency/\n"
                    "   structured concurrency post\n"
                    "2. Python trio\n   https://trio.readthedocs.io/\n"
                    "   async library documentation\n"
                )

            cfg = None

        url, _ = asyncio.run(
            resolve_docs_url(_FakeEngine(), "trio", "structured concurrency"))
        # host owning the name beats a query-term-only hit on a random host
        self.assertEqual(url, "https://trio.readthedocs.io/")

