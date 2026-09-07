"""F-305: `bathys-doctor` — one-shot diagnostics of the local Bathys stack.

Checks (no MCP server needed, runs against the same env/config):
  backend ping, native pin marker, cache stats, metrics journal, robots mode,
  chromium presence (fast import probe; --full launches the browser).

Exit code: 0 = all critical checks pass, 1 = at least one failed.
"""

from __future__ import annotations

import argparse
import asyncio
import sqlite3
import sys
import time
from pathlib import Path

from . import __version__
from .config import SEARXNG_REF, Config


def _ok(name: str, ok: bool, detail: str = "") -> bool:
    mark = "OK  " if ok else "FAIL"
    line = f"[{mark}] {name}" + (f" — {detail}" if detail else "")
    print(line)
    return ok


def _cache_stats(path: Path) -> tuple[int, int]:
    if not path.is_file():
        return 0, 0
    try:
        db = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        total, alive = db.execute(
            "SELECT COUNT(*), SUM(CASE WHEN exp > ? THEN 1 ELSE 0 END) FROM cache",
            (time.time(),),
        ).fetchone()
        db.close()
        return int(total or 0), int(alive or 0)
    except sqlite3.Error:
        return -1, -1


async def _backend_ping(cfg: Config) -> tuple[bool, str]:
    import httpx

    try:
        r = await asyncio.to_thread(
            lambda: httpx.get(
                cfg.searxng_url + "/search",
                params={"q": "ping", "format": "json"}, timeout=5.0,
            )
        )
        if r.status_code == 200:
            return True, f"{cfg.searxng_url} answers JSON ({len(r.text)} chars)"
        return False, f"HTTP {r.status_code} from {cfg.searxng_url}"
    except Exception as e:
        return False, f"{e.__class__.__name__}: {str(e)[:120]}"


async def run_checks(full: bool) -> int:
    cfg = Config.load()
    results: list[bool] = []

    print(f"bathys-doctor · bathys {__version__} · python {sys.version.split()[0]}")
    print(f"data={cfg.data_dir} cache={cfg.cache_dir} mode={cfg.start_mode} "
          f"robots={'on' if cfg.respect_robots else 'off'} "
          f"metrics={'on' if cfg.metrics else 'off'}")
    print()

    results.append(_ok("config loads", True, f"backend={cfg.searxng_url}"))

    ping_ok, detail = await _backend_ping(cfg)
    results.append(_ok("searxng backend", ping_ok, detail))
    if not ping_ok and cfg.auto_start:
        print("       hint: doctor does not auto-start the backend; run any tool "
              "call once, or start SearXNG yourself")

    marker = cfg.searxng_home / "repo" / ".bathys-ref"
    if cfg.searxng_home.joinpath("repo").is_dir():
        pinned = marker.read_text().strip() if marker.is_file() else "(none)"
        results.append(_ok(
            "searxng pin (F-302)",
            pinned == cfg.searxng_ref,
            f"marker={pinned[:12]}… expected={cfg.searxng_ref[:12]}…",
        ))
    else:
        _ok("searxng pin (F-302)", True, "native home absent — external/docker mode")

    total, alive = _cache_stats(cfg.cache_dir / "cache.db")
    results.append(_ok("cache db", total >= 0,
                       "absent (first run?)" if total == 0 else
                       f"{alive}/{total} alive rows" if total > 0 else "unreadable"))

    mpath = cfg.data_dir / "metrics.jsonl"
    if mpath.is_file():
        lines = sum(1 for _ in mpath.open("rb"))
        results.append(_ok("metrics journal (F-304)", True, f"{lines} events"))
    else:
        results.append(_ok("metrics journal (F-304)", True,
                           "no events yet (appears after first tool call)"))

    try:
        from crawl4ai import AsyncWebCrawler  # noqa: F401
        results.append(_ok("crawl4ai import", True))
    except Exception as e:
        results.append(_ok("crawl4ai import", False, str(e)[:120]))

    if full:
        try:
            from playwright.sync_api import sync_playwright

            p = sync_playwright().start()
            b = p.chromium.launch(headless=True)
            b.close()
            p.stop()
            results.append(_ok("chromium launch (--full)", True))
        except Exception as e:
            results.append(_ok("chromium launch (--full)", False, str(e)[:160]))

    failed = results.count(False)
    print()
    print(f"{len(results) - failed}/{len(results)} checks passed"
          + ("" if not failed else " — see FAIL lines above"))
    return 1 if failed else 0


def main() -> None:
    ap = argparse.ArgumentParser(prog="bathys-doctor",
                                 description="Bathys local stack diagnostics")
    ap.add_argument("--full", action="store_true",
                    help="also launch headless chromium (slower)")
    args = ap.parse_args()
    raise SystemExit(asyncio.run(run_checks(args.full)))


if __name__ == "__main__":
    main()
