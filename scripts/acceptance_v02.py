"""v0.2 acceptance run (F-101 and friends): 20 diverse queries, fresh (refresh).

Criterion (roadmap v0.2): >= 18 of 20 queries return >= 3 non-empty hits.
Run:  BATHYS_SEARXNG_HOME=... .venv/bin/python scripts/acceptance_v02.py
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from bathys.config import Config
from bathys.core import Engine

# (query, category, language, time_range)
QUERIES = [
    ("python asyncio task group tutorial", "it", None, None),
    ("как настроить samba на arch linux", None, "ru", None),
    ("rust vs go performance 2026 benchmark", "it", None, None),
    ("SearXNG docker compose setup", "it", None, None),
    ("модель контекста протокола MCP объяснение", None, "ru", None),
    ("sqlite wal mode concurrency", "it", None, None),
    ("квантовые вычисления новости", "news", "ru", "week"),
    ("playwright headless chromium memory usage", "it", None, None),
    ("лучшая замена google search приватность", None, "ru", None),
    ("llm context window comparison 2026", "it", None, "month"),
    ("глубоководные аппараты история батискаф триест", None, "ru", None),
    ("httpx vs aiohttp performance", "it", None, None),
    ("fedora silverblue day to day experience", None, None, None),
    ("bm25 ranking function explained", "science", None, None),
    ("open source metasearch engine comparison", "it", None, None),
    ("дистрибутивы linux для старых ноутбуков", None, "ru", "year"),
    ("crawl4ai vs firecrawl features", "it", None, None),
    ("омнитекс транспорт безопасность новости", "news", "ru", None),
    ("vector database benchmark ann index", "science", None, None),
    ("roдовые тренды веб-разработки", None, "ru", "month"),
]


async def main() -> None:
    eng = Engine(Config.load())
    await eng.start()
    passed = 0
    results = []
    try:
        for i, (q, cat, lang, tr) in enumerate(QUERIES, 1):
            try:
                out = await eng.search(q, max_results=5, category=cat, language=lang,
                                       time_range=tr, refresh=True)
                footer = out.rsplit("[bathys:", 1)[-1]
                hits = int(footer.split(" hits")[0]) if " hits" in footer else 0
                empty = "No results" in out.split("[bathys:")[0]
                ok = (not empty) and hits >= 3
                passed += ok
                results.append((i, q, hits, "PASS" if ok else "FAIL"))
                print(f"{i:2}. [{'PASS' if ok else 'FAIL'}] hits={hits} · {q}")
            except Exception as e:
                results.append((i, q, 0, f"ERROR {e.__class__.__name__}"))
                print(f"{i:2}. [ERROR] {q} — {e.__class__.__name__}: {str(e)[:80]}")
    finally:
        await eng.stop()
    print(f"\ncriterion: >=18/20 with >=3 hits → got {passed}/20 →",
          "PASS ✅" if passed >= 18 else "FAIL ❌")
    print("bad engines observed:", eng.bad_engines() or "-")


if __name__ == "__main__":
    asyncio.run(main())
