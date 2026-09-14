"""Two-tier page extraction: HTTP-first, browser only when needed.

Tier 0 (URL-specialized): github.com PR/issues/repo-root URLs never hit the
generic tiers — `gh` CLI turns their first-class structure (title/state/body/
reviews/comments/files, repo tree, README) into a prioritized markdown
document (ideas-borrowed.md §3, borrowed from pi-web-access). Missing `gh` or
any gh failure falls back to the tiers below, never an error.

Tier 1 (default first try): plain httpx GET — zero browser, milliseconds,
covers the majority of pages (articles, docs, blogs, wikis).
Tier 2: headless Chromium (Crawl4AI) — only for pages that require JS:
SPA shells, client-side rendered content, hard anti-bot walls.

The tier decision is automatic per page: tier 1 parses and inspects the HTML;
if it looks like a JS shell (near-empty body, app-root-only markup), the dive
retries in the browser. `BATHYS_BROWSER=off` forces tier-1-only, `always`
forces tier-2 for every dive (slow path, for debugging).
"""

from __future__ import annotations

import asyncio
import json
import re
import shutil
from dataclasses import dataclass
from urllib.parse import urlsplit

import httpx

from .config import Config


@dataclass
class Page:
    url: str
    status: int
    title: str
    text: str
    raw_chars: int
    tier: str = "browser"  # "http" | "http-pdf" | "github" | "browser" — provenance


_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

_EXCLUDED_TAGS = [
    "nav",
    "footer",
    "header",
    "aside",
    "form",
    "noscript",
    "button",
    "svg",
    "iframe",
    "style",
    "script",
]

_EXCLUDED_SELECTOR = (
    "nav,footer,header,aside,.sidebar,.cookie,#cookie-banner,.ads,[aria-hidden='true']"
)

_SCRIPT_RE = re.compile(r"<script\b[^>]*>.*?</script>", re.S | re.I)
_STYLE_RE = re.compile(r"<style\b[^>]*>.*?</style>", re.S | re.I)
_COMMENT_RE = re.compile(r"<!--.*?-->", re.S)
_TAG_RE = re.compile(r"<[^>]+>")
_TITLE_RE = re.compile(r"<title\b[^>]*>(.*?)</title>", re.S | re.I)
_WS_RE = re.compile(r"\s+")


class _FinalTierError(RuntimeError):
    """Tier-1 error that must NOT escalate to the browser tier."""


_APP_ROOT_RE = re.compile(
    r"<body[^>]*>\s*(<div[^>]*id=[\"']?(app|root|__next|__nuxt)[\"']?[^>]*>\s*"
    r"(</div>)?\s*</body>)",
    re.I,
)


def html_to_text(html: str) -> str:
    """Minimal HTML -> text: drop script/style/comments, strip tags, squeeze ws."""
    t = _SCRIPT_RE.sub(" ", html)
    t = _STYLE_RE.sub(" ", t)
    t = _COMMENT_RE.sub(" ", t)
    t = _TAG_RE.sub(" ", t)
    return _WS_RE.sub(" ", t).strip()


def _looks_like_js_shell(html: str, text: str) -> bool:
    """Heuristic: server returned an app shell, not content."""
    if not html:
        return True
    if _APP_ROOT_RE.search(html):
        return True
    # meaningful content already present -> not a shell
    if len(text) >= 800:
        return False
    # tiny text with heavy markup hints a loader screen
    return len(text) < 200


def _pdf_text(content: bytes) -> str | None:
    """Extract the text layer from PDF bytes; None when there is no text."""
    try:
        import pymupdf  # optional dependency, lazy import
    except ImportError:
        raise _FinalTierError(
            "crawl failed: PDF support needs `pip install pymupdf` (local, no ML)"
        )
    try:
        doc = pymupdf.open(stream=content, filetype="pdf")
        parts = [page.get_text() for page in doc]
        doc.close()
    except Exception as e:
        raise RuntimeError(f"crawl failed: pdf parse error ({e.__class__.__name__})")
    text = "\n\n".join(parts).strip()
    return text if len(text) >= 40 else None  # <40 chars => likely a scan


# ------------------------------------------------------------- github ---
# Borrowed from pi-web-access (ideas-borrowed.md §3): github.com pages scrape
# badly (JS-heavy HTML) but their structure is first-class API data. GitHub
# URLs get a specialized tier before HTTP: PR/issues via `gh pr/issue view`,
# repo roots via `gh api` (description/topics, tree, README). Any failure —
# missing binary, old gh, exit != 0, timeout — falls back to the plain HTTP
# tier, never a hard error. The gh calls hit api.github.com (official API),
# not page scraping, so robots semantics of github.com are not involved.
# raw.githubusercontent.com needs no specialization: its responses are plain
# text files the HTTP tier already handles (library_docs phase 3 proved it).

_GH_TIMEOUT = 15.0  # seconds per gh invocation


def _gh_login(entry: dict | list | None) -> str:
    """author.login of a comment/review/... entry; tolerant of gh's variants
    (login can be None for ghost users) and of missing author on retry."""
    if isinstance(entry, list):  # [{author: {...}}] nesting in older gh
        entry = entry[0] if entry else None
    return str(((entry or {}).get("author") or {}).get("login") or "unknown")


def _gh_body(entry: dict | None) -> str:
    """body of a comment/review entry, whitespace-squeezed."""
    return _WS_RE.sub(" ", str((entry or {}).get("body") or "")).strip()


def _render_pr_or_issue(kind: str, d: dict) -> str:
    """Prioritized markdown doc for a PR/issue (pi-style: what a reader needs
    first goes first — title/state, author, body, files, reviews, comments,
    check statuses). Compact by construction (gh output is already dense):
    no budget trimming, no invented content, entries in server order."""
    kind_uc = "PR" if kind == "pull" else "Issue"
    author = str((d.get("author") or {}).get("login") or "unknown")
    state = str(d.get("state") or "?")
    out = [
        f"# [{kind_uc}] {d.get('title', '')} ({state})",
        f"- Author: {author}",
        f"- State: {state}",
    ]
    if "url" in d and d.get("url"):
        out.append(f"- URL: {d['url']}")
    body = _WS_RE.sub(" ", str(d.get("body") or "")).strip()
    out += ["", "## Body", body or "(no description)"]
    files = d.get("files") or []
    if files:
        names = [str(f.get("path") or "?") for f in files]
        out += ["", "## Files", ", ".join(names)]
    reviews = d.get("reviews") or []
    if reviews:
        out += ["", "## Reviews"]
        out += [
            f"- {_gh_login(r)} ({r.get('state', '?')}): {_gh_body(r)}" for r in reviews
        ]
    checks = d.get("statusCheckRollup") or []
    if checks:
        out += ["", "## Checks"]
        for c in checks:
            name = str(c.get("name") or "?")
            wf = str(c.get("workflowName") or "").strip()
            label = f"{wf} / {name}" if wf and wf != name else name
            out.append(f"- {label}: {c.get('conclusion') or c.get('status') or '?'}")
    comments = d.get("comments") or []
    if comments:
        out += ["", "## Comments"]
        out += [f"- {_gh_login(c)}: {_gh_body(c)}" for c in comments]
    return "\n".join(out)


def _render_repo(repo: dict, tree: list | None, readme: str) -> str:
    """Prioritized markdown doc for a repo root: what/description, topics,
    top-level tree (names), then the README lead (first ~8k chars; the read
    tool distills further, so the cut is generous)."""
    out = [f"# {repo.get('name', '?')}", f"- URL: {repo.get('html_url', '')}".rstrip()]
    if repo.get("description"):
        out.append(
            f"- Description: {_WS_RE.sub(' ', str(repo['description'])).strip()}"
        )
    if repo.get("default_branch"):
        out.append(f"- Default branch: {repo['default_branch']}")
    topics = repo.get("topics") or []
    if topics:
        out.append(f"- Topics: {', '.join(str(t) for t in topics)}")
    if tree:
        names = ", ".join(
            f"{t.get('name', '?')}{'' if t.get('type') != 'dir' else '/'}" for t in tree
        )
        out += ["", "## Root", names]
    if readme:
        out += ["", "## README", readme]
    return "\n".join(out)


class _GhUnavailable(RuntimeError):
    """gh missing or failing: NOT a page error — silent fallback to HTTP."""


async def _gh_run(args: list[str], *, raw: bool = False) -> str:
    """Run `gh` with a 15s timeout; GH_TOKEN inherits from the environment.
    Raises _GhUnavailable on any failure mode (missing binary, exit != 0,
    timeout) — callers translate that into the HTTP-tier fallback."""
    gh = shutil.which("gh")
    if not gh:
        raise _GhUnavailable("gh CLI not found")
    try:
        proc = await asyncio.create_subprocess_exec(
            gh, *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
    except (OSError, ValueError) as e:
        raise _GhUnavailable(f"gh spawn failed ({e.__class__.__name__})") from e
    try:
        out_b, err_b = await asyncio.wait_for(proc.communicate(), timeout=_GH_TIMEOUT)
    except TimeoutError:
        proc.kill()
        try:  # reap the killed process; guarded so a stuck pipe can't hang us
            await asyncio.wait_for(proc.communicate(), timeout=2.0)
        except TimeoutError:
            pass
        raise _GhUnavailable(f"gh timeout after {_GH_TIMEOUT:.0f}s")
    if proc.returncode != 0:
        raise _GhUnavailable(
            f"gh exit {proc.returncode}: {err_b.decode('utf-8', 'replace').strip()[:120]}"
        )
    if raw:
        return out_b.decode("utf-8", "replace")
    try:
        return json.loads(out_b.decode("utf-8", "replace"))
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise _GhUnavailable(
            f"gh output not valid JSON ({e.__class__.__name__})"
        ) from e


_GH_REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+$")  # owner/repo name charset
_GH_NUM_RE = re.compile(r"^\d+$")


def _gh_match(url: str) -> tuple[str, str, str, str] | None:
    """(kind, owner, repo, number) for github.com URLs we specialize.

    Kinds: "pull" | "issues" (with number) | "repo" (bare owner/repo root,
    optional trailing slash). Anything else — other paths (blob/tree/commit/
    releases...), other hosts (gist, api, raw...) — is not ours: None keeps
    the normal HTTP path, exactly as before."""
    try:
        parts = urlsplit(url)
    except ValueError:
        return None
    if (parts.scheme or "https") not in ("https", "http"):
        return None
    host = (parts.netloc or "").lower()
    if host != "github.com" and not host.endswith(".github.com"):
        return None  # raw.githubusercontent.com & friends: HTTP tier handles them
    host = host[4:] if host.startswith("www.") else host
    if host != "github.com":
        return None  # gist.github.com etc — no specialization
    seg = [s for s in parts.path.split("/") if s]
    if len(seg) >= 3 and seg[2] in ("pull", "issues"):
        # github.com/{owner}/{repo}/pull/{N} or /issues/{N} — plus suffixes
        # like /files, /commits that describe the same object.
        if not (_GH_REPO_RE.match(seg[0]) and _GH_REPO_RE.match(seg[1])):
            return None
        num = seg[3] if len(seg) > 3 else ""
        if not _GH_NUM_RE.match(num):
            return None
        return (seg[2], seg[0], seg[1], num)
    if len(seg) == 2:
        if not (_GH_REPO_RE.match(seg[0]) and _GH_REPO_RE.match(seg[1])):
            return None
        # repo root only — no blob/tree/wiki/releases/... subpaths
        return ("repo", seg[0], seg[1], "")
    return None


_PR_FULL_FIELDS = "title,state,body,author,reviews,comments,files,statusCheckRollup,url"
_PR_OLD_FIELDS = "title,state,body,author,comments,url"
_ISSUE_FIELDS = "title,state,body,author,comments,url"
_README_CAP = 8000


async def _gh_fetch_pull_or_issue(
    kind: str, owner: str, repo: str, number: str
) -> dict:
    """`gh pr|issue view` JSON. Old gh versions reject newer --json fields
    (exit 1, "Unknown JSON field"); a failure of the FULL field set retries
    once with the minimal set every gh knows. Only pr gets the retry — the
    issue field set here is the minimal one."""
    sub = "pr" if kind == "pull" else "issue"
    field_sets = [_PR_FULL_FIELDS, _PR_OLD_FIELDS] if sub == "pr" else [_ISSUE_FIELDS]
    last: _GhUnavailable | None = None
    for fields in field_sets:
        try:
            return await _gh_run(
                [sub, "view", number, "--repo", f"{owner}/{repo}", "--json", fields]
            )
        except _GhUnavailable as e:
            last = e
    raise last  # type: ignore[misc]


async def _gh_fetch_repo(owner: str, repo: str) -> tuple[dict, list | None, str]:
    """(repo_json, top_level_tree, readme_text) via the REST endpoints.
    The tree/readme are best-effort: a repo may have an empty root or no
    README; those degrade the doc, they don't fail it."""
    repo_json: dict = await _gh_run(["api", f"repos/{owner}/{repo}"])
    tree: list | None = None
    try:
        tree = await _gh_run(["api", f"repos/{owner}/{repo}/contents"])
    except _GhUnavailable:
        pass  # empty repo / 404 — Root section simply omitted
    readme = ""
    try:
        readme = await _gh_run(
            [
                "api",
                f"repos/{owner}/{repo}/readme",
                "-H",
                "Accept: application/vnd.github.raw",
            ],
            raw=True,
        )
    except _GhUnavailable:
        pass  # no README — honest omission, not a failure
    return repo_json, tree, readme[:_README_CAP]


class Crawler:
    """Extraction facade. One shared browser at most, started lazily."""

    def __init__(self, cfg: Config) -> None:
        self._cfg = cfg
        self._crawler = None
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------ tier 2 ---

    async def _ensure(self):
        if self._crawler is not None:
            return self._crawler
        async with self._lock:
            if self._crawler is None:
                AsyncWebCrawler, BrowserConfig, *_ = _imports()
                browser = BrowserConfig(
                    headless=True,
                    text_mode=True,
                    light_mode=True,
                    user_agent=_UA,
                    verbose=False,
                )
                self._crawler = AsyncWebCrawler(config=browser)
                await self._crawler.start()
        return self._crawler

    async def stop(self) -> None:
        if self._crawler is not None:
            try:
                await self._crawler.stop()
            except Exception:
                pass
            self._crawler = None

    async def _fetch_browser(self, url: str) -> Page:
        crawler = await self._ensure()
        (
            _,
            _,
            CacheMode,
            CrawlerRunConfig,
            DefaultMarkdownGenerator,
            PruningContentFilter,
        ) = _imports()
        run = CrawlerRunConfig(
            cache_mode=CacheMode.BYPASS,
            page_timeout=int(self._cfg.crawl_timeout * 1000),
            excluded_tags=_EXCLUDED_TAGS,
            excluded_selector=_EXCLUDED_SELECTOR,
            word_count_threshold=8,
            verbose=False,
            markdown_generator=DefaultMarkdownGenerator(
                content_filter=PruningContentFilter(
                    threshold=0.48, threshold_type="fixed"
                )
            ),
        )
        result = await crawler.arun(url=url, config=run)
        if not getattr(result, "success", False):
            reason = (
                getattr(result, "error_message", "")
                or f"status {getattr(result, 'status_code', '?')}"
            )
            raise RuntimeError(f"crawl failed: {reason}")
        md = result.markdown
        text = (
            getattr(md, "fit_markdown", None)
            or getattr(md, "raw_markdown", None)
            or str(md or "")
        )
        meta = getattr(result, "metadata", None) or {}
        raw_len = len(getattr(md, "raw_markdown", "") or "") or len(text)
        return Page(
            url=getattr(result, "url", url) or url,
            status=int(getattr(result, "status_code", 0) or 0),
            title=str(meta.get("title", "") or "").strip(),
            text=text.strip(),
            raw_chars=raw_len,
            tier="browser",
        )

    # ------------------------------------------------------------ tier 1 ---

    async def _fetch_http(
        self, url: str, http: httpx.AsyncClient | None
    ) -> tuple[Page, str]:
        """Plain HTTP GET + server-side HTML->text. Returns (page, raw_html)."""
        if http is None:
            # read tool calls may carry the engine client; scripts pass None
            async with httpx.AsyncClient(
                follow_redirects=True, timeout=20.0, headers={"User-Agent": _UA}
            ) as own:
                resp = await own.get(url)
        else:
            resp = await http.get(url, headers={"User-Agent": _UA})
        ctype = resp.headers.get("content-type", "")
        if resp.status_code >= 400:
            raise RuntimeError(f"crawl failed: http {resp.status_code}")
        if "pdf" in ctype or url.lower().endswith(".pdf"):
            # PDF text layer (v0.9, borrowed from pi-web-access's PDF handling):
            # local extraction via pymupdf — no ML, no cloud, no OCR. Scanned
            # PDFs (no text layer) fail honestly and stay out of scope until
            # the paused OCR initiative is revived.
            text = _pdf_text(resp.content)
            if text is None:
                raise _FinalTierError(
                    "crawl failed: PDF has no text layer (scanned?) — OCR initiative is paused"
                )
            return (
                Page(
                    url=str(resp.url),
                    status=resp.status_code,
                    title="",
                    text=text,
                    raw_chars=len(resp.content),
                    tier="http-pdf",
                ),
                "",
            )
        if "html" not in ctype and "xml" not in ctype and ctype:
            # non-HTML (json/etc) — not tier-1 material
            raise RuntimeError(
                f"crawl failed: unsupported content-type {ctype.split(';')[0]}"
            )
        html = resp.text
        title_m = _TITLE_RE.search(html)
        text = html_to_text(html)
        return (
            Page(
                url=str(resp.url),
                status=resp.status_code,
                title=(title_m.group(1).strip() if title_m else ""),
                text=text,
                raw_chars=len(html),
                tier="http",
            ),
            html,
        )

    # -------------------------------------------------------- github tier --

    async def _github_special(self, url: str) -> Page | None:
        """Structural fetch for github.com/{owner}/{repo}[/pull|/issues/{N}].

        Returns a tier="github" Page, or None when the URL is not ours to
        handle or gh is missing/failing — None means "continue with the
        normal HTTP path", never an error. raw_chars carries the true
        document length (pre-distillation), so the read tool's accounting
        stays honest."""
        m = _gh_match(url)
        if m is None:
            return None
        kind, owner, repo, number = m
        try:
            if kind == "repo":
                repo_json, tree, readme = await _gh_fetch_repo(owner, repo)
                if not repo_json.get("name"):  # paranoia: api answered junk
                    return None
                text = _render_repo(repo_json, tree, readme)
                title = f"{repo_json.get('full_name') or url}"
            else:
                d = await _gh_fetch_pull_or_issue(kind, owner, repo, number)
                text = _render_pr_or_issue(kind, d)
                title = f"[{'PR' if kind == 'pull' else 'Issue'}] {d.get('title', '')}"
        except _GhUnavailable:
            return None  # quiet fallback to the HTTP tier
        return Page(
            url=url,
            status=200,
            title=title,
            text=text,
            raw_chars=len(text),
            tier="github",
        )

    # ----------------------------------------------------------- facade ----

    async def fetch(self, url: str, http: httpx.AsyncClient | None = None) -> Page:
        # GitHub structure tier runs BEFORE the mode policy in every mode:
        # it is a data-source choice (official API vs page scraping), not a
        # browser-tier decision. On success it is final — a markdown document
        # with no JS-shell question. None (not a GitHub URL / gh missing /
        # gh failed) keeps the flow below exactly as before.
        page = await self._github_special(url)
        if page is not None:
            return page
        mode = getattr(self._cfg, "browser_mode", "auto")
        if mode == "always":
            return await self._fetch_browser(url)
        if mode == "off":
            page, _ = await self._fetch_http(url, http)
            return page
        # auto: try tier 1, escalate to tier 2 on JS-shell or failure.
        # PDF errors are FINAL (final): a headless browser on a PDF just hits
        # "Download is starting" — escalating would mask the honest message.
        try:
            page, html = await self._fetch_http(url, http)
        except _FinalTierError:
            raise
        except RuntimeError:
            if mode == "auto":
                return await self._fetch_browser(url)
            raise
        # PDF/extracted-content pages return empty raw html by design —
        # that is NOT a JS shell; skip the heuristic and return as-is.
        if page.tier != "http" or not _looks_like_js_shell(html, page.text):
            return page
        return await self._fetch_browser(url)


def _imports():
    from crawl4ai import AsyncWebCrawler, BrowserConfig, CacheMode, CrawlerRunConfig

    try:
        from crawl4ai import DefaultMarkdownGenerator, PruningContentFilter
    except ImportError:  # older layout
        from crawl4ai.content_filter_strategy import PruningContentFilter
        from crawl4ai.markdown_generation_strategy import DefaultMarkdownGenerator
    return (
        AsyncWebCrawler,
        BrowserConfig,
        CacheMode,
        CrawlerRunConfig,
        DefaultMarkdownGenerator,
        PruningContentFilter,
    )
