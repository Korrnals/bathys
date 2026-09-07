# Cursor

Подключение Bathys к Cursor: MCP-сервер в `mcp.json` плюс правило выбора
инструментов в `.cursor/rules`. Общий обзор интеграции — в [overview.md](overview.md).

## MCP-сервер

Тот же блок `mcpServers` — в `~/.cursor/mcp.json` (глобально) или в проектный
`.cursor/mcp.json`; можно и через Settings → MCP → Add server. Конфиг:

```json
{
  "mcpServers": {
    "bathys": {
      "command": "/path/to/bathys/.venv/bin/bathys",
      "env": {
        "BATHYS_SEARXNG_HOME": "/path/to/bathys/.runtime/searxng-home"
      }
    }
  }
}
```

`command` — абсолютный путь к вашему клону bathys (`~` внутри JSON не
раскрывается). `BATHYS_SEARXNG_HOME` переиспользует уже собранный нативный SearXNG из
`.runtime/`; без неё первый запуск сам соберёт свой в
`~/.local/share/bathys/searxng-home` (первые минуты работы). Остальные
переменные — в [config.md](../contracts/config.md).

## Правило: .cursor/rules

Создайте `.cursor/rules/bathys.mdc` и вставьте в него дроп-ин блок из
[agents/HARNESS-DROPIN.md](../../agents/HARNESS-DROPIN.md) — так матрица выбора
инструментов и семантика сигналов попадают в контекст агента Cursor, даже если
клиент не рендерит MCP instructions. Блок самодостаточен: после вставки агент
выбирает инструменты Bathys нативно и не ходит в интернет мимо них.

## Что получает агент

- Четыре инструмента Bathys (`deep_research`, `web_search`, `read_url`,
  `read_urls`) с annotations.
- Три стратегии-промпта: `bathys_deep_research`, `bathys_source_audit`,
  `bathys_fresh_scan` — готовые шаблоны плана исследования.
- Если что-то не завелось — первый запуск собирает SearXNG и Chromium; разбор
  типовых аварий — в [runbook.md](../operations/runbook.md).
