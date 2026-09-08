# Third-Party Notices

Bathys is MIT-licensed (see [LICENSE](LICENSE)); this file gives credit to
the projects it builds on and states how each is used. Without them, Bathys
would not exist.

## SearXNG — метапоиск

- **Project:** <https://github.com/searxng/searxng>
- **License:** GNU Affero General Public License v3.0 (AGPL-3.0) —
  <https://www.gnu.org/licenses/agpl-3.0.html>
- **How Bathys uses it:** SearXNG is the pluggable metasearch *engine*. It is
  never bundled inside the Bathys distribution: Bathys clones the upstream
  repository at a pinned commit (or uses the official docker image, or an
  external instance you already run), starts it as a **separate process**, and
  talks to it over its local JSON API. Bathys does not modify SearXNG source
  and does not distribute it. If you run SearXNG via Bathys, your use of
  SearXNG is governed by AGPL-3.0 — its source (including any local
  modifications you make yourself) must remain available to the users of that
  instance. Thank you, SearXNG team, for the magnificent metasearch engine.

## Crawl4AI — browser-based extraction

- **Project:** <https://github.com/unclecode/crawl4ai>
- **License:** Apache License 2.0 —
  <https://www.apache.org/licenses/LICENSE-2.0>
- **How Bathys uses it:** a pip dependency (`crawl4ai`) used as a library for
  the browser tier of the two-tier extractor (headless Chromium for
  JS-rendered pages). The default tier is Bathys' own HTTP engine; Crawl4AI is
  the heavy tier. Thank you, Unclecode, for the pragmatic LLM-first extractor.

## Other dependencies

- **MCP Python SDK** (`mcp`, <https://github.com/modelcontextprotocol/python-sdk>)
  — MIT, Model Context Protocol / Anthropic. The protocol layer Bathys speaks.
- **httpx** (<https://www.python-httpx.org/>) — BSD-3-Clause. HTTP client of
  the first-tier extractor and the SearXNG API caller.
- **Playwright for Python** (<https://playwright.dev/python/>) — Apache-2.0,
  Microsoft. Browser runtime beneath the extraction tier.
- **tokenizers / onnxruntime / numpy** — optional future extras of the
  semantic-reranking initiative (Apache-2.0 / MIT); not installed by default.

Each package ships its full license text inside the wheel Bathys installs
(`site-packages/<package>*/`), as required by its license.