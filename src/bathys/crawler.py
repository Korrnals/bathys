"""Two-tier page extraction: HTTP-first, browser only when needed.

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
from dataclasses import dataclass

import httpx

from .config import Config


@dataclass
class Page:
    url: str
    status: int
    title: str
    text: str
    raw_chars: int
    tier: str = "browser"  # "http" | "browser" — provenance for metrics/footers


_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

_EXCLUDED_TAGS = [
    "nav", "footer", "header", "aside", "form", "noscript", "button",
    "svg", "iframe", "style", "script",
]

_EXCLUDED_SELECTOR = (
    "nav,footer,header,aside,.sidebar,.cookie,#cookie-banner,.ads,"
    "[aria-hidden='true']"
)

import re

_SCRIPT_RE = re.compile(r"<script\b[^>]*>.*?</script>", re.S | re.I)
_STYLE_RE = re.compile(r"<style\b[^>]*>.*?</style>", re.S | re.I)
_COMMENT_RE = re.compile(r"<!--.*?-->", re.S)
_TAG_RE = re.compile(r"<[^>]+>")
_TITLE_RE = re.compile(r"<title\b[^>]*>(.*?)</title>", re.S | re.I)
_WS_RE = re.compile(r"\s+")
_APP_ROOT_RE = re.compile(
    r"<body[^>]*>\s*(<div[^>]*id=[\"']?(app|root|__next|__nuxt)[\"']?[^>]*>\s*"
    r"(</div>)?\s*</body>)", re.I)


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
        _, _, CacheMode, CrawlerRunConfig, DefaultMarkdownGenerator, PruningContentFilter = _imports()
        run = CrawlerRunConfig(
            cache_mode=CacheMode.BYPASS,
            page_timeout=int(self._cfg.crawl_timeout * 1000),
            excluded_tags=_EXCLUDED_TAGS,
            excluded_selector=_EXCLUDED_SELECTOR,
            word_count_threshold=8,
            verbose=False,
            markdown_generator=DefaultMarkdownGenerator(
                content_filter=PruningContentFilter(threshold=0.48, threshold_type="fixed")
            ),
        )
        result = await crawler.arun(url=url, config=run)
        if not getattr(result, "success", False):
            reason = getattr(result, "error_message", "") or f"status {getattr(result, 'status_code', '?')}"
            raise RuntimeError(f"crawl failed: {reason}")
        md = result.markdown
        text = getattr(md, "fit_markdown", None) or getattr(md, "raw_markdown", None) or str(md or "")
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

    async def _fetch_http(self, url: str, http: httpx.AsyncClient | None) -> tuple[Page, str]:
        """Plain HTTP GET + server-side HTML->text. Returns (page, raw_html)."""
        if http is None:
            # read tool calls may carry the engine client; scripts pass None
            async with httpx.AsyncClient(follow_redirects=True, timeout=20.0,
                                        headers={"User-Agent": _UA}) as own:
                resp = await own.get(url)
        else:
            resp = await http.get(url, headers={"User-Agent": _UA})
        ctype = resp.headers.get("content-type", "")
        if resp.status_code >= 400:
            raise RuntimeError(f"crawl failed: http {resp.status_code}")
        if "html" not in ctype and "xml" not in ctype and ctype:
            # non-HTML (pdf/json/etc) — not tier-1 material
            raise RuntimeError(f"crawl failed: unsupported content-type {ctype.split(';')[0]}")
        html = resp.text
        title_m = _TITLE_RE.search(html)
        text = html_to_text(html)
        return (
            Page(url=str(resp.url), status=resp.status_code,
                 title=(title_m.group(1).strip() if title_m else ""),
                 text=text, raw_chars=len(html), tier="http"),
            html,
        )

    # ----------------------------------------------------------- facade ----

    async def fetch(self, url: str, http: httpx.AsyncClient | None = None) -> Page:
        mode = getattr(self._cfg, "browser_mode", "auto")
        if mode == "always":
            return await self._fetch_browser(url)
        if mode == "off":
            page, _ = await self._fetch_http(url, http)
            return page
        # auto: try tier 1, escalate to tier 2 on JS-shell or failure
        try:
            page, html = await self._fetch_http(url, http)
        except RuntimeError:
            if mode == "auto":
                return await self._fetch_browser(url)
            raise
        if not _looks_like_js_shell(html, page.text):
            return page
        return await self._fetch_browser(url)


def _imports():
    from crawl4ai import AsyncWebCrawler, BrowserConfig, CacheMode, CrawlerRunConfig
    try:
        from crawl4ai import DefaultMarkdownGenerator, PruningContentFilter
    except ImportError:  # older layout
        from crawl4ai.content_filter_strategy import PruningContentFilter
        from crawl4ai.markdown_generation_strategy import DefaultMarkdownGenerator
    return AsyncWebCrawler, BrowserConfig, CacheMode, CrawlerRunConfig, DefaultMarkdownGenerator, PruningContentFilter