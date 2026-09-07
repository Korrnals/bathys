"""Direct pipeline smoke test (no MCP framing).

Run:  .venv/bin/python scripts/smoke.py
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from bathys.config import Config
from bathys.core import Engine


async def main() -> None:
    eng = Engine(Config.load())
    await eng.start()
    try:
        print("=== web_search ===", flush=True)
        print(await eng.search("что такое SearXNG метапоиск", max_results=6))

        print("\n=== read_url (query-distilled) ===", flush=True)
        print(await eng.read(
            "https://en.wikipedia.org/wiki/SearXNG",
            query="self-hosted privacy metasearch",
            max_chars=4000,
        ))

        print("\n=== deep_research ===", flush=True)
        print(await eng.research(
            "SearXNG vs Brave Search API: privacy and self-hosting",
            max_sources=3, max_results=8, per_source_chars=3000,
        ))
    finally:
        await eng.stop()


if __name__ == "__main__":
    asyncio.run(main())
