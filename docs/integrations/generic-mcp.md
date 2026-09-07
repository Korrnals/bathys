# Любой другой MCP-клиент

Bathys — обычный stdio MCP-сервер без внешних требований: любой клиент, умеющий
запускать stdio-серверы, подключает его одним блоком конфига. Общий обзор
интеграции — в [overview.md](overview.md).

## Команда и окружение

| Поле | Значение |
|---|---|
| Транспорт | stdio (сервер сам уводит логи библиотек в stderr — stdout занят протоколом) |
| `command` | путь до исполняемого файла `bathys`: `…/bathys/.venv/bin/bathys` из venv проекта или `bathys` из установленного wheel |
| `env` | опционально; чаще всего достаточно `BATHYS_SEARXNG_HOME` (переиспользовать собранный SearXNG из `.runtime/`) |
| Обязательные ключи | нет — ноль облачных API-ключей, сервер поднимает свой бэкенд сам (external → docker → native) |

Пример блока (`command` — абсолютный путь к вашему клону bathys; `~` внутри JSON не раскрывается):

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

Без `BATHYS_SEARXNG_HOME` первый запуск сам склонирует и соберёт нативный
SearXNG в `~/.local/share/bathys/searxng-home` — это сработает, но первый поиск
займёт несколько минут. Полная таблица из 19 переменных `BATHYS_*` — в
[config.md](../contracts/config.md).

## Что клиент получает из коробки

Без каких-либо правок системного промпта (источник — `src/bathys/server.py`):

- **Четыре инструмента** — `deep_research`, `web_search`, `read_url`,
  `read_urls` — с annotations (`title`, `readOnlyHint`, `openWorldHint`) и
  диапазонами параметров; контракт — в [mcp-tools.md](../contracts/mcp-tools.md).
- **Instructions-playbook** на рукопожатии `initialize`: матрица выбора
  инструментов, правила работы с запросами и источниками, семантика сигналов.
  Если клиент передаёт instructions модели — агент сразу выбирает инструменты
  осмысленно.
- **Три стратегии-промпта**: `bathys_deep_research`, `bathys_source_audit`,
  `bathys_fresh_scan` — рендерятся как обычные MCP-промпты с описаниями
  аргументов.

## Дроп-ин для системного промпта

Если клиент не показывает MCP instructions, вставьте канонический блок из
[agents/HARNESS-DROPIN.md](../../agents/HARNESS-DROPIN.md) в системный промпт
агента (или эквивалентный файл инструкций). Блок самодостаточен: после вставки
агент выбирает инструменты Bathys нативно и не ходит в интернет мимо них.
Субагент-специалист [bathys-researcher](../../agents/bathys-researcher.md) и
скиллы из `agents/skills/` доставляются так же, если харнесс поддерживает
субагентов и скиллы.

Если что-то не завелось — первый запуск собирает SearXNG и Chromium (минуты, не
секунды); диагностика одним запуском — `bathys-doctor`, разбор типовых аварий —
в [runbook.md](../operations/runbook.md).
