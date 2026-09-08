# bathys-mcp (npm wrapper)

**Unified local deep-research search service for AI agents.** This npm
package is a thin installer for the real thing: the Python `bathys` package
([PyPI](https://pypi.org/project/bathys/), [GitHub](https://github.com/Korrnals/bathys)) —
one pipeline (search → extraction → query distillation → cache), zero cloud
quotas, MCP stdio server with native harness integration.

## Install

```bash
npm install -g bathys-mcp
```

The postinstall step installs the Python package (`pip install bathys`) when
Python ≥3.10 is available, then you wire your harness:

```bash
bathys-mcp install     # auto-detect harnesses (zcode, Claude, Cursor, VS Code
                       # family, Gemini CLI, Windsurf, Zed, opencode, goose,
                       # Hermes) and register the MCP server — idempotent,
                       # timestamped backups
bathys-mcp doctor      # stack diagnostics
bathys-mcp             # run the MCP server over stdio
bathys-mcp print-config  # manual-wiring snippets for every harness
```

No Python? Install Python ≥3.10, then `pip install bathys` and `bathys install`.

## What you get

- **4 MCP tools**: `deep_research`, `web_search`, `read_url`, `read_urls`
- **3 strategy prompts**: `bathys_deep_research`, `bathys_source_audit`,
  `bathys_fresh_scan`
- built-in instructions playbook + tool annotations (harness knows how to use
  Bathys out of the box)
- researcher subagent profile + skills (`--with-agent`)
- robots.txt ethics, token budgets, SQLite cache, metrics journal

Full documentation: [github.com/Korrnals/bathys/tree/main/docs](https://github.com/Korrnals/bathys/tree/main/docs)

License: MIT