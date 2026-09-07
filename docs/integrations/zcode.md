# zcode

Подключение Bathys к zcode: MCP-сервер в конфиг, опционально — субагент-специалист
и дроп-ин в `AGENTS.md`. Общий обзор интеграции — в [overview.md](overview.md).

## MCP-сервер

В конфиг MCP-серверов zcode добавьте блок `mcpServers`:

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
`.runtime/`; без неё первый запуск сам склонирует и соберёт свой в
`~/.local/share/bathys/searxng-home` — это сработает, но первый поиск займёт
несколько минут. Полная таблица из 19 переменных `BATHYS_*` — в
[config.md](../contracts/config.md), управление режимами бэкенда — в
[configure.md](../getting-started/configure.md).

## Инструкции: AGENTS.md

zcode показывает харнессу MCP instructions, поэтому instructions-playbook Bathys
(матрица выбора инструментов, правила, семантика сигналов) попадает в контекст
агента без ручных действий. Если нужно жёстче закрепить правило «весь веб — через
Bathys», вставьте дроп-ин блок в `AGENTS.md` (пользовательский или проектный) —
канонический блок в [agents/HARNESS-DROPIN.md](../../agents/HARNESS-DROPIN.md).

## Субагент-специалист (опционально, рекомендуется)

```bash
cp agents/bathys-researcher.md ~/.zcode/agents/
```

Скиллы `agents/skills/bathys-deep-dive/` и `agents/skills/bathys-source-audit/`
скопируйте в каталог скиллов вашего харнесса (расположение зависит от установки
zcode). Субагент и скиллы не требуют отдельных настроек: они пользуются теми же
инструментами Bathys, что и основной агент.

## Что изменится после подключения

- Агент начинает предпочитать Bathys сторонним web-инструментам: playbook из
  instructions подсказывает `deep_research` для исследовательских вопросов и
  `read_urls` для пакетов известных ссылок.
- В списке промптов появляются три стратегии: `bathys_deep_research`,
  `bathys_source_audit`, `bathys_fresh_scan` — готовые шаблоны плана.
- Инструменты видны с человекочитаемыми названиями из annotations («Глубокое
  исследование: поиск + чтение + дистиллят» вместо `deep_research`).
- С установленным субагентом глубокий ресёрч можно делегировать целиком:
  `bathys-researcher` работает только через Bathys и не тратит облачные квоты.

Если что-то не завелось — первый запуск собирает SearXNG и Chromium (минуты, не
секунды); разбор типовых аварий — в [runbook.md](../operations/runbook.md).
