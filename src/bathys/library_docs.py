"""library_docs — up-to-date library documentation for agents, Context7-style
but local and unlimited (initiative: docs/product/library-docs-initiative.md).

Resolution chain: seed index (docs_index.json) -> one live web_search
("<library> official documentation") -> GitHub slug guess. Extraction reuses
the two-tier crawler; distillation reuses the BM25 passage engine; the raw
page lands in the existing page cache, so follow-up questions on the same
library are instant, offline and free.

Phase 2 (v0.11.0): doc HOME pages are often navigational. After the home
read, we extract same-site subpage links from the raw text, rank them against
the query (token overlap in the URL path), fetch the best matches in
parallel through the engine dive semaphore, and merge the distilled
passages — one compact digest built from the pages that actually carry
the content.
"""

from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path
from urllib.parse import urlsplit

from . import distill

_INDEX_PATH = Path(__file__).resolve().parent / "docs_index.json"
_LINK_RE = re.compile(r"\((https?://[^\s)]+)\)")


def _seed_index() -> dict[str, str]:
    try:
        data = json.loads(_INDEX_PATH.read_text(encoding="utf-8"))
        # skip non-entry keys (comments live in the same JSON namespace)
        return {k: v for k, v in data.items()
                if not k.startswith("_") and isinstance(v, str)}
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


def _same_site(base: str, cand: str) -> bool:
    try:
        b, c = urlsplit(base), urlsplit(cand)
    except ValueError:
        return False
    return b.netloc.replace("www.", "") == c.netloc.replace("www.", "")


def _q_variants(token: str) -> tuple[str, ...]:
    """Light morphology: 'dependency' also matches 'dependencies' (and vice
    versa) — final y/ies is the most common doc-path plural shape."""
    if token.endswith("y"):
        return (token, token[:-1] + "ies")
    if token.endswith("ies"):
        return (token, token[:-3] + "y")
    return (token,)


def _extract_subpages(raw_text: str, base_url: str, query: str, limit: int) -> list[str]:
    """Pick same-site doc links from the raw cached text, ranked by query
    token overlap in the path — navigation URLs carry the page topic in the
    path, a good cheap proxy for content match."""
    q_tokens = {t for t in re.findall(r"[a-z0-9]+", (query or "").lower()) if len(t) > 2}
    scored: list[tuple[float, str]] = []
    seen: set[str] = set()
    for m in _LINK_RE.finditer(raw_text or ""):
        url = m.group(1)
        if url in seen or not _same_site(base_url, url):
            continue
        seen.add(url)
        if any(url.lower().endswith(ext) for ext in
               (".png", ".jpg", ".svg", ".zip", ".css", ".js", ".ico")):
            continue
        path = urlsplit(url).path.lower()
        score = sum(1.0 for t in q_tokens
                    if any(v in path for v in _q_variants(t)))
        if any(k in path for k in ("/guide", "/docs", "/tutorial", "/how-to", "/reference", "/api")):
            score += 0.5
        if score > 0:
            scored.append((score, url))
    scored.sort(key=lambda p: -p[0])
    return [u for _, u in scored[:limit]]


def _is_navigational(distilled: str) -> bool:
    """A home distills thin BY MEANING when it is a table of contents:
    concatenated entry titles have low word diversity for their length
    (most words occur exactly once because each is a different page name).
    Raw-link counting is blind here — slim collapses links to labels and
    the HTTP tier may strip nav markup entirely (no URLs survive)."""
    if not distilled:
        return True
    words = re.findall(r"[A-Za-z]{3,}", distilled)
    if len(words) < 40:
        return False  # too short to judge; thin-length branch covers it
    uniq = len(set(w.lower() for w in words))
    # empirical (fastapi/pytorch homes): concatenated TOC titles sit at
    # ~0.73–0.77 unique-ratio; prose runs ≥0.83 (function words repeat).
    return uniq / len(words) >= 0.78


async def _search_subpages(engine, library: str, base_url: str, query: str,
                           limit: int) -> list[str]:
    """Site-scoped web search as the subpage-discovery fallback for homes
    that carry no extractable links."""
    from urllib.parse import urlsplit

    host = urlsplit(base_url).netloc.replace("www.", "")
    raw = await engine.search(f"{library} {query} site:{host}", max_results=limit + 2,
                              refresh=False)
    out: list[str] = []
    for ln in raw.splitlines():
        s = ln.strip()
        if s.startswith(("http://", "https://")) and host in s:
            u = s.split()[0]
            if u != base_url and u not in out:
                out.append(u)
            if len(out) >= limit:
                break
    return out


async def library_docs(engine, library: str, query: str, max_chars: int = 6000,
                       refresh: bool = False, subpages: int = 3) -> str:
    """Fetch and distill official docs for `library` under `query`.

    Phase 2: when the home page distills thin (navigational), up to
    `subpages` same-site pages ranked by query relevance are fetched in
    parallel and merged into one digest.
    """
    url, source = await resolve_docs_url(engine, library)
    res = await engine._read(url, query=query, max_chars=max_chars, refresh=refresh)

    home_slim = distill.slim_markdown(res.page.text)
    home_distilled = distill.passages(home_slim, query, max_chars)

    sub_texts: list[str] = []
    sub_urls: list[str] = []
    sub_failed: list[str] = []
    raw = res.page.text or ""
    # Subpage follow-loading is UNCONDITIONAL for library docs (this is the
    # tool's profile): lexical navigational heuristics proved unreliable at
    # the TOC/prose boundary, so the decision is objective — always enrich
    # with query-relevant subpages; content-rich homes simply contribute
    # related pages on top. One extra searx query when links are absent is
    # a fair price for depth.
    if subpages > 0:
        pages = _extract_subpages(raw, url, query, limit=subpages)
        if not pages:
            # linkless home (nav markup stripped by the HTTP tier): discover
            # subpages with one targeted site-search through our own engine.
            pages = await _search_subpages(engine, library, url, query, limit=subpages)
        if pages:
            sem = engine._dive_sem

            async def dive(u: str):
                async with sem:
                    try:
                        r = await engine._read(u, query=query,
                                                max_chars=max(max_chars // (len(pages) + 1), 300),
                                                refresh=refresh)
                        return r, u, None
                    except Exception as e:  # noqa: BLE001 — one dead subpage is fine
                        return None, u, f"{e.__class__.__name__}"

            outs = await asyncio.gather(*(dive(u) for u in pages))
            for r, u, err in outs:
                if r is None:
                    sub_failed.append(f"{u} ({err})")
                    continue
                slim = distill.slim_markdown(r.page.text)
                d = distill.passages(slim, query, max(max_chars // (len(pages) + 1), 300))
                if d:
                    sub_texts.append(f"### {u}\n\n{d}")
                    sub_urls.append(u)

    from .core import _ch

    total_out = len(home_distilled) + sum(len(s) for s in sub_texts)
    head = f"# Документация: {library}\n{url}\n(источник: {source})"
    parts = [head]
    if home_distilled:
        parts.append(home_distilled)
    parts += sub_texts
    tail = ""
    if sub_urls or sub_failed:
        tail = "\n\nПодстраницы: " + ", ".join(sub_urls)
        if sub_failed:
            tail += " | не прочитаны: " + ", ".join(sub_failed)
    footer = (f"[bathys: docs {_ch(res.page.raw_chars)} ch → {_ch(total_out)} ch"
              f"{' · +' + str(len(sub_urls)) + ' подстр.' if sub_urls else ''} · "
              f"cache {'HIT' if res.cache_hit else 'MISS'}] — повторы бесплатны: уточняй запросом")
    return "\n\n".join(p for p in parts if p) + tail + "\n\n" + footer