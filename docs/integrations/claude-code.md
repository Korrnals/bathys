# Claude Code и Claude Desktop

Подключение Bathys к Claude Code (`.mcp.json`) и Claude Desktop
(`claude_desktop_config.json`); блок один и тот же. Общий обзор интеграции — в
[overview.md](overview.md).

## Claude Code: .mcp.json

Положите блок в `.mcp.json` в корне проекта (область проекта):

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
раскрывается).

## Claude Desktop: claude_desktop_config.json

Тот же блок — в `claude_desktop_config.json` (меню Settings → Developer →
Edit Config).

`BATHYS_SEARXNG_HOME` переиспользует уже собранный нативный SearXNG из
`.runtime/`; без неё первый запуск сам соберёт свой в
`~/.local/share/bathys/searxng-home` (первые минуты работы). Остальные
переменные — в [config.md](../contracts/config.md).

## Инструкции: CLAUDE.md

Чтобы правило «весь веб-доступ — только через Bathys» попадало в контекст агента
независимо от того, рендерит ли клиент MCP instructions, вставьте дроп-ин блок в
`CLAUDE.md` (проектный или пользовательский). Канонический блок — в
[agents/HARNESS-DROPIN.md](../../agents/HARNESS-DROPIN.md); он самодостаточен и
дублирует матрицу выбора инструментов из instructions-playbook.

## Субагент-специалист (опционально, рекомендуется)

```bash
mkdir -p .claude/agents
cp agents/bathys-researcher.md .claude/agents/
```

Скиллы `agents/skills/bathys-deep-dive/` и `agents/skills/bathys-source-audit/`
скопируйте в каталог скиллов харнесса (проектный `.claude/skills/` или
пользовательский `~/.claude/skills/`).

## Что получает агент

- Четыре инструмента Bathys с annotations; три стратегии-промпта
  (`bathys_deep_research`, `bathys_source_audit`, `bathys_fresh_scan`) — в списке
  промптов с описаниями аргументов.
- Субагент `bathys-researcher` в `.claude/agents/` — глубокий ресёрч делегируется
  целиком; агент работает только через Bathys (никаких облачных web-инструментов).
- Если что-то не завелось — первый запуск собирает SearXNG и Chromium; разбор
  типовых аварий — в [runbook.md](../operations/runbook.md).
