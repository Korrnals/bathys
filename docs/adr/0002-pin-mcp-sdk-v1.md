# ADR 0002 — Пин MCP SDK на v1: `mcp>=1.2,<2`

| Поле | Значение |
|---|---|
| Статус | Accepted |
| Дата | 2026-09-06 |
| Применимо к | Bathys v0.1.0 |
| Затрагивает | `pyproject.toml`, `src/bathys/server.py` |

## Context

`server.py` построен на FastMCP-слое официального SDK: `from mcp.server.fastmcp import Context, FastMCP`, декларативные `@mcp.tool()`, `lifespan`-хук и `mcp.run(transport="stdio")` (см. [ADR 0006](0006-three-tool-string-surface.md)). Линейка mcp 2.x ломает v1-API: `FastMCP` переименован в `MCPServer`, сигнатуры и соглашения v1 не сохранены. Без пина очередное `pip install`/`pip sync` молча подтянуло бы 2.x и сломало сервер на импорте.

## Decision

Пин в `pyproject.toml`: `"mcp>=1.2.0,<2"`. Нижняя граница 1.2 — минимальный FastMCP-слой, на котором стабильны `lifespan` и `Context`. Разрешение зависимостей проекта закреплено за v1 (факт: в venv проекта установлен `mcp 1.29.1`).

Обновление до 2.x — осознанное отдельное решение (новый ADR), а не побочный эффект `pip install -U`.

## Поверхность v1, используемая Bathys

Миграционный чек-лист будущего ADR — всё, что завязано на v1-API:

| Элемент v1 | Где |
|---|---|
| `from mcp.server.fastmcp import FastMCP, Context` | `server.py` |
| `FastMCP(name, instructions=…, lifespan=…)` | `server.py` |
| декоратор `@mcp.tool()` с docstring-схемой | `server.py` (три инструмента) |
| `ctx.request_context.lifespan_context` (доступ к `Engine`) | `server._engine` |
| `mcp.run(transport="stdio")` | `server.main` |
| поведение `ToolError → isError` с текстом `Error executing tool {tool}: …` | SDK, фиксируется `output-format.md` |

## Alternatives

| Альтернатива | Почему отклонена |
|---|---|
| Миграция на mcp 2.x | переписывание `server.py` без выгоды: v1 закрывает все потребности (tools, stdio, lifespan) |
| Сторонний пакет `fastmcp` 2.x | лишняя зависимость при том же API; третья сторона в критическом пути протокола |
| Без пина (`mcp>=1.2`) | ломкое обновление: 2.xresolution роняет сервер на импорте `FastMCP` |

## Consequences

- Положительные: воспроизводимая установка; стабильный контракт инструментов и ошибки-поведения SDK (`ToolError → isError`) не плывут под ногами.
- Отрицательные: дрейф от мейнстрима SDK; техдолг миграции на 2.x, который надо погасить отдельным ADR до того, как v1 перестанет получать security-фиксы.

## Источники

`pyproject.toml` (`dependencies`); `src/bathys/server.py`; venv проекта: `mcp 1.29.1`.
