"""Batch reading of known URLs: no search step, one shared character budget.

The read_urls counterpart of Engine.research for the case where the caller
already holds the links (Tavily Extract parity). Dives run in parallel through
the engine dive semaphore; a failed page degrades to a one-line section and
frees its share of the budget for the pages that came back.
"""

from __future__ import annotations

import asyncio
import time

from . import distill
from .core import Engine, _ch
from .searx import normalize_url

_MAX_URLS = 10


async def read_many(engine: Engine, urls: list[str], *, query: str | None,
                    total_chars: int, refresh: bool = False) -> str:
    started = time.monotonic()
    total_chars = max(300, min(30_000, total_chars))

    # Dedup by normalized URL (utm/fragment cleanup), keep the first spelling.
    kept: list[str] = []
    seen: set[str] = set()
    for u in urls:
        u = (u or "").strip()
        if not u:
            continue
        key = normalize_url(u)
        if not key or key in seen:
            continue
        seen.add(key)
        kept.append(u)
    if not kept:
        raise ValueError("read_urls: expected 1-10 http(s) urls, got none")
    skipped, kept = kept[_MAX_URLS:], kept[:_MAX_URLS]

    async def dive(u: str):
        async with engine._dive_sem:
            try:
                # max_chars here is only an upper bound for the throwaway
                # distill inside _read; shares are cut after the gather.
                return await engine._read(u, query=query, max_chars=total_chars,
                                          refresh=refresh), None
            except Exception as e:
                # _read raises "{Class}: {msg}" both fresh and from the error cache.
                return None, str(e) or e.__class__.__name__

    results = await asyncio.gather(*(dive(u) for u in kept))

    ok = sum(1 for res, _ in results if res is not None)
    share = total_chars // ok if ok else 0
    remainder = total_chars - share * ok if ok else 0

    sections: list[str] = []
    fetched = returned = 0
    first_ok = True
    for i, ((res, err), u) in enumerate(zip(results, kept), 1):
        if res is None:
            sections.append(f"## {i}. {u}\n(not fetched — {err})")
            continue
        budget = share + (remainder if first_ok else 0)
        first_ok = False
        slim = distill.slim_markdown(res.page.text)
        distilled = distill.passages(slim, query, budget)
        fetched += res.page.raw_chars
        returned += len(distilled)
        sections.append(f"## {i}. {res.page.title or u}\n{res.page.url}\n\n{distilled}")
    if skipped:
        sections.append("Skipped (over the 10-url limit): " + ", ".join(skipped))
    secs = round(time.monotonic() - started, 1)
    cache_flags = {res.cache_hit for res, _ in results if res is not None}
    cache = ("HIT" if cache_flags == {True} else
             "MISS" if cache_flags == {False} else "MIX") if cache_flags else None
    engine._log_metrics("read_urls", cache=cache, chars_in=fetched, chars_out=returned,
                        secs=secs, ok=ok > 0,
                        error=None if ok else "all_failed")
    sections.append(
        f"[bathys: batch {len(kept)} urls · {ok}/{len(kept)} ok · "
        f"{_ch(fetched)} ch fetched → {_ch(returned)} ch returned · {secs}s]"
    )
    return "\n\n".join(sections)
