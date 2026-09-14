"""library_docs — up-to-date library documentation for agents, Context7-style
but local and unlimited (initiative: docs/product/library-docs-initiative.md).

Resolution chain: seed index (docs_index.json) -> one live web_search
("<library> official documentation") -> GitHub slug guess. Extraction reuses
the two-tier crawler; distillation reuses the BM25 passage engine; the raw
page lands in the existing page cache, so follow-up questions on the same
library are instant, offline and free.
"""

from __future__ import annotations

import json
from pathlib import Path

from . import distill

_INDEX_PATH = Path(__file__).resolve().parent / "docs_index.json"


def _seed_index() -> dict[str, str]:
    try:
        return json.loads(_INDEX_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _normalize(name: str) -> str:
    return (name or "").strip().lower().lstrip("/").rstrip("/")


async def resolve_docs_url(engine, library: str) -> tuple[str, str]:
    """Return (docs_url, source) for a library name.

    source: 'index' | 'search' | 'github' — provenance for the answer header.
    Raises RuntimeError when nothing plausible is found.
    """
    idx = _seed_index()
    key = _normalize(library)
    if key in idx:
        return idx[key], "index"
    # try a few common alias shapes (js suffix, -python, etc.)
    for suffix in ("js", "-js", ".js", "-python", "py", "-dev"):
        if key + suffix in idx:
            return idx[key + suffix], "index"

    # live search fallback: one web_search call
    raw = await engine.search(f"{library} official documentation", max_results=5, refresh=False)
    lines = raw.splitlines()
    for ln in lines:
        s = ln.strip()
        if s.startswith("http://") or s.startswith("https://"):
            low = s.lower()
            if any(b in low for b in ("docs.", "/docs", "documentation.", "developer.")):
                return s.split()[0], "search"
    # last resort: github slug
    if " " not in key and "/" not in key:
        return f"https://github.com/{key}", "github"
    raise RuntimeError(f"library_docs: не удалось найти документацию для {library!r}")


async def library_docs(engine, library: str, query: str, max_chars: int = 6000,
                       refresh: bool = False) -> str:
    """Fetch and distill official docs for `library` under `query`."""
    url, source = await resolve_docs_url(engine, library)
    res = await engine._read(url, query=query, max_chars=max_chars, refresh=refresh)
    slim = distill.slim_markdown(res.page.text)
    distilled = distill.passages(slim, query, max_chars)
    head = f"# Документация: {library}\n{url}\n(источник: {source})"
    from .core import _ch

    footer = (f"[bathys: docs {_ch(res.page.raw_chars)} ch → "
              f"{_ch(len(distilled))} ch · cache {'HIT' if res.cache_hit else 'MISS'}] "
              f"— повторы бесплатны: read_url(url, query=…)")
    return head + "\n\n" + distilled + "\n\n" + footer