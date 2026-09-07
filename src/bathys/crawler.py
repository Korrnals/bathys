"""Shared Crawl4AI browser: one headless instance for all dives."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from .config import Config

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


@dataclass
class Page:
    url: str
    status: int
    title: str
    text: str
    raw_chars: int


def _imports():
    from crawl4ai import AsyncWebCrawler, BrowserConfig, CacheMode, CrawlerRunConfig
    try:
        from crawl4ai import DefaultMarkdownGenerator, PruningContentFilter
    except ImportError:  # older layout
        from crawl4ai.content_filter_strategy import PruningContentFilter
        from crawl4ai.markdown_generation_strategy import DefaultMarkdownGenerator
    return AsyncWebCrawler, BrowserConfig, CacheMode, CrawlerRunConfig, DefaultMarkdownGenerator, PruningContentFilter


class Crawler:
    def __init__(self, cfg: Config) -> None:
        self._cfg = cfg
        self._crawler = None
        self._lock = asyncio.Lock()

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

    async def fetch(self, url: str) -> Page:
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
        )
