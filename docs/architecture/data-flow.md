# Потоки данных

Диаграммы показывают два главных пути: полный конвейер `deep_research` и кэш-HIT путь `read_url`. Компоненты и их ответственность — в [overview.md](overview.md); стадии очистки — в [pipeline.md](pipeline.md).

## deep_research: полный путь

```mermaid
sequenceDiagram
    autonumber
    participant C as Клиент (агент)
    participant S as server.py
    participant E as core.Engine
    participant K as cache.Cache
    participant X as SearXNG
    participant W as crawler.Crawler (семофор 4)
    participant D as distill

    C->>S: deep_research(query, max_sources=3)
    S->>E: research(query, ...)
    E->>K: get(ключ поиска)
    alt cache MISS
        E->>X: GET /search?format=json
        X-->>E: сырой JSON (~37k символов)
        E->>E: dedupe, clean, rank → hits
        E->>K: set(ключ поиска, TTL 3600)
    else cache HIT
        K-->>E: сохранённые hits (0.0 c)
    end
    par нырёк за каждым из топ-источников
        E->>K: get(ключ страницы)
        alt страница не в кэше
            E->>W: fetch(url)
            W->>W: рендер → вырезание → fit_markdown
            W-->>E: Page(text, raw_chars)
            E->>K: set(ключ страницы, сырец, TTL 86400)
        end
        E->>D: slim_markdown → passages(query, бюджет)
        D-->>E: пассажи ≤ per_source_chars
    end
    E->>E: секции «## i. title» + More hits (≤5) + футер
    E-->>S: один дистиллят
    S-->>C: ответ (~7k токенов вместо ~35k)
```

Детали, которых не видно на диаграмме:

- **Семофор 4** ограничивает параллельные нырки — топ-6 источников читаются не более чем четырьмя браузерными сессиями одновременно.
- **Ошибка одной страницы не валит вызов**: секция отмечается `(not fetched — …)` и дополняется сниппетом из выдачи.
- **Ответ**(instant answer) SearXNG, если есть, поднимается перед секциями; запасные хиты идут в блок «More hits (not fetched)» — не больше пяти ссылок.
- **Футер** `[bathys: …]` подводит итог: сколько хитов найдено, сколько страниц проныряно, «сырьё → ответ» в токенах и время. Контракт форматов — `docs/contracts/output-format.md`.

## read_url: кэш-HIT путь

Второе чтение той же страницы под другим `query` — самый частый «бесплатный» случай:

```mermaid
sequenceDiagram
    autonumber
    participant C as Клиент (агент)
    participant E as core.Engine
    participant K as cache.Cache
    participant D as distill

    C->>E: read_url(url, query="новый угол")
    E->>K: get(ключ страницы = sha256("page", url))
    K-->>E: HIT: сырой текст страницы
    E->>D: slim_markdown → passages(новый query, max_chars)
    D-->>E: пассажи под новый фокус
    E-->>C: дистиллят + футер «cache HIT»
```

Сеть и браузер не участвуют вовсе: сырец лежит в кэше **до** дистилляции, поэтому новая фокусировка стоит только локального пересчёта BM25. Если вместо текста в кэше лежит ошибка загрузки (её тоже кэшируем на час), `read_url` вернёт её как есть — повторный заход не дёргает мёртвый URL.
