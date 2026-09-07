# Подключение клиента и playbook агента

Bathys — stdio-сервер: клиент запускает его как дочерний процесс и общается по JSON-RPC. Конфиг везде одинаков по форме — блок `mcpServers` с путём до `.venv/bin/bathys`; отличается только файл, куда его кладут.

Полные гайды по харнессам — zcode (включая субагента `bathys-researcher` и скиллы), Claude Code и Claude Desktop, Cursor и любой другой MCP-клиент — вынесены в раздел [docs/integrations/](../integrations/overview.md). Эта страница — базовый конфиг и примеры диалогов с инструментами.

## zcode

В конфиг MCP-серверов zcode (`command` — абсолютный путь к вашему клону bathys; `~` внутри JSON не раскрывается):

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

## claude desktop

Тот же блок — в `claude_desktop_config.json` (меню Settings → Developer → Edit Config).

## cursor

Тот же блок — в `~/.cursor/mcp.json` (или Settings → MCP → Add server).

## Про путь BATHYS_SEARXNG_HOME

`BATHYS_SEARXNG_HOME` указывает на уже собранный нативный SearXNG в `.runtime/searxng-home` — переиспользует готовый клон и venv. Без этой переменной первый вызов поиска сам склонирует и соберёт SearXNG в `~/.local/share/bathys/searxng-home` — это сработает, но первый поиск займёт несколько минут. Переменные окружения перечислены в [configure.md](configure.md).

## Playbook агента

Инструкции сервера подсказывают модели то же правило выбора — держите его в уме при ручных вызовах:

| Ситуация | Инструмент | Почему |
|---|---|---|
| Нужен ресёрч-ответ на вопрос | `deep_research(query)` | ищет и читает топ-источники одним вызовом вместо цепочки |
| Нужен только список ссылок | `web_search(query)` | не тратит токены на содержимое страниц |
| Вызывающий — программа, а не LLM | `web_search(query, as_json=true)` | чистый JSON `{query, count, hits[], answer?}` без футера — парсится без регекспов по строке ответа |
| Нужна конкретная страница | `read_url(url, query)` | возвращает дистиллят страницы, с фокусом — только релевантные пассажи |
| Несколько известных URL, нужен текст каждой | `read_urls(urls, query)` | один вызов вместо N `read_url`; общий бюджет `total_chars`, сбой страницы не валит вызов |

Фильтры `time_range` / `category` / `language` / `engines` сужают выдачу до вызова. Строки `[bathys: …]` в конце ответов (футеры) показывают сжатие и `cache HIT`/`MISS` — по ним видно, пришёл ответ из сети или из кэша (термины — в [glossary.md](../meta/glossary.md)).

## Пример 1. Ресёрч одним вызовом

> **Пользователь:** сравни SearXNG и Brave Search API для локального ресёрч-агента.
>
> **Агент:** вызывает `deep_research("SearXNG vs Brave Search API for local research agent", max_sources=3)` — один вызов вместо «поиск + три чтения».
>
> **Ответ:** заголовок, секции `## 1…3` с пассажами каждого источника, блок «More hits (not fetched)» с запасными ссылками и футер вида `[bathys: 41 raw hits, top 3 considered · dove 3 pages · 35669 ch fetched → 7508 ch returned · 3.2s]`.

Агент отвечает кратким сравнением; если фактов не хватило, дочитывает конкретный источник через `read_url` с уточняющим `query`.

## Пример 2. Чтение страницы с фокусом

> **Пользователь:** вытащи из документации Crawl4AI параметры `PruningContentFilter`.
>
> **Агент:** вызывает `read_url("https://docs.crawl4ai.com/...", query="PruningContentFilter parameters")`.
>
> **Ответ:** заголовок страницы, только пассажи про фильтр и футер `[bathys: page 17k tok → 581 tok · query-distilled · cache MISS]`.

Повторный вопрос про ту же страницу под другим углом отдаётся мгновенно с `cache HIT`: сырой текст уже в кэше, дистилляция бесплатна (механика — в [data-flow.md](../architecture/data-flow.md)).

## Пример 3. Пакет известных ссылок

> **Пользователь:** вот пять ссылок по теме — вытащи главное из каждой.
>
> **Агент:** вызывает `read_urls([...], query="…", total_chars=12000)` — один вызов вместо пяти `read_url`; страницы читаются параллельно, бюджет делится между успешными, сбойная страница остаётся строкой `(not fetched — …)` и не срывает вызов.
>
> **Ответ:** секции `## 1…5` с дистиллятом каждой страницы и футер вида `[bathys: batch 5 urls · 4/5 ok · 330857 ch fetched → 1248 ch returned · 1.8s]`.

Кэш-флаг пакета (`HIT`/`MISS`/`MIX` — все из кэша / все из сети / вперемешку) в футер не пишется: он уходит в журнал метрик `metrics.jsonl` (см. [runbook.md](../operations/runbook.md)).

## Если что-то не завелось

Первый запуск собирает SearXNG и Chromium — это минуты, не секунды. Разбор типовых аварий: [runbook.md](../operations/runbook.md).
