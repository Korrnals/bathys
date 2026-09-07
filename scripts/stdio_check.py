"""End-to-end check over real MCP stdio framing.

Run:  .venv/bin/python scripts/stdio_check.py
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def main() -> None:
    params = StdioServerParameters(command=sys.executable, args=["-m", "bathys.server"])
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            tools = await session.list_tools()
            print("tools:", [t.name for t in tools.tools])
            for t in tools.tools:
                a = t.annotations
                print(
                    f"  annotations[{t.name}]: title={a.title if a else None!r} "
                    f"readOnlyHint={a.readOnlyHint if a else None} "
                    f"openWorldHint={a.openWorldHint if a else None}"
                )
                assert a and a.title and a.readOnlyHint and a.openWorldHint, (
                    f"annotations not delivered for {t.name}"
                )

            prompts = await session.list_prompts()
            print("prompts:", [p.name for p in prompts.prompts])
            for p in prompts.prompts:
                print(f"  {p.name}: {p.description}")
                for arg in p.arguments or []:
                    req = "required" if arg.required else "optional"
                    print(f"    arg {arg.name} ({req}): {arg.description}")
            assert {p.name for p in prompts.prompts} >= {
                "bathys_deep_research", "bathys_source_audit", "bathys_fresh_scan"
            }, "expected Bathys strategy prompts are missing"

            rendered = await session.get_prompt(
                "bathys_source_audit",
                {
                    "claim": "crawl4ai renders JS-heavy pages headlessly",
                    "urls": "https://docs.crawl4ai.com/, https://example.com",
                },
            )
            text = rendered.messages[0].content.text
            print(f"\n--- prompt render bathys_source_audit (first 300 chars) ---")
            print(text[:300])

            res = await session.call_tool(
                "web_search", {"query": "crawl4ai tutorial", "max_results": 4}
            )
            text = res.content[0].text
            print(text[:1500])
            res2 = await session.call_tool(
                "deep_research",
                {"query": "what is bathyscaphe", "max_sources": 2, "max_results": 6,
                 "per_source_chars": 2000},
            )
            print("\n--- deep_research (first 2500 chars) ---")
            print(res2.content[0].text[:2500])


if __name__ == "__main__":
    asyncio.run(main())
