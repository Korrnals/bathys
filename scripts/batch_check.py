"""Live check for the batch read path (F-201): read_many over three real pages.

Run:  .venv/bin/python scripts/batch_check.py
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from bathys.batch import read_many
from bathys.config import Config
from bathys.core import Engine

# no Crawl4AI article on en.wikipedia — the canonical repo page is live instead
URLS = [
    "https://en.wikipedia.org/wiki/Bathyscaphe",
    "https://en.wikipedia.org/wiki/SearXNG",
    "https://github.com/unclecode/crawl4ai",
]


async def main() -> None:
    engine = Engine(Config.load())
    await engine.start()
    try:
        out = await read_many(engine, URLS, query=None, total_chars=6000)
    finally:
        await engine.stop()
    body, _, footer = out.rpartition("\n")
    print(body[:1200])
    print(footer)


if __name__ == "__main__":
    asyncio.run(main())
