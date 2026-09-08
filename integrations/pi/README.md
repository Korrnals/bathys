# Bathys × Pi (badlogic pi-mono)

У Pi **нет MCP-конфигурационного файла** — интеграции в нём делаются
TypeScript-расширениями (проверено по исходникам [pi-mono](https://github.com/badlogic/pi-mono),
2026-09-08: ни `mcpServers`, ни modelcontextprotocol-зависимостей в кодовой
базе). Поэтому интеграция Bathys в Pi — это **агентные тексты**, а не конфиг:

1. **Правила для `AGENTS.md` проекта** — Pi читает его как файл инструкций
   агента; блок ниже приучает агента Pi работать в интернете только через
   Bathys.
2. **Скилл-каталог** — копия профилей Bathys, которые Pi-агент подхватывает
   как документы-инструкции.

## Установка (в каталог проекта, где работает Pi)

```bash
cp integrations/pi/assets/bathys-rules.md ./AGENTS.md.appendix   # или вставьте блок в AGENTS.md
mkdir -p .pi/skills && cp -r agents/skills/* .pi/skills/
```

Правильнее — открыть `AGENTS.md` проекта и добавить блок из
[`assets/bathys-rules.md`](assets/bathys-rules.md) целиком (он самодостаточен).

## Блок для AGENTS.md (суть)

- Вся работа в интернете — через инструменты MCP-сервера `bathys`
  (`deep_research` / `web_search` / `read_url` / `read_urls`), если он
  подключён в вашей среде.
- Выбор инструмента по задаче: ресёрч-вопрос → `deep_research`; ссылки →
  `web_search`; известный URL → `read_url`; 2–10 URL → `read_urls`.
- Верификация фактов — два независимых источника; каждый нетривиальный факт —
  с URL.
- Сигналы ответов (`cache HIT`/`MISS`, `robots-refused`, `(not fetched — …)`)
  трактуются по семантике Bathys.

## Почему не установщик

MCP-сервер Bathys подключается к Pi **средой**, где Pi запущен (например,
через обёртку, которая стартует MCP-сервер), а не конфигом самого Pi. Если
ваша среда запускает Pi внутри харнесса с MCP (zcode, opencode и т.п.) —
используйте `bathys install` для этого харнесса; для чистого Pi достаточно
правил `AGENTS.md` выше.