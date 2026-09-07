# Конвейер очистки страницы

Здесь происходит основная экономия токенов: из страницы в 50–300k символов агенту возвращается несколько тысяч. Конвейер исполняют `crawler.py` (стадии 1–3) и `distill.py` (стадии 4–5); суммарные цифры сжатия — в [metrics.md](../operations/metrics.md).

## Пять стадий

| # | Стадия | Модуль | Параметры |
|---|---|---|---|
| 1 | JS-рендер headless-chromium | `crawler.py` | `headless`, `text_mode`, `light_mode`; таймаут `BATHYS_CRAWL_TIMEOUT` (40 c) |
| 2 | Вырезание мусора до фильтра | `crawler.py` | `excluded_tags`: nav, footer, header, aside, form, noscript, button, svg, iframe, style, script; `excluded_selector`: `.sidebar`, `.cookie`, `#cookie-banner`, `.ads`, `[aria-hidden='true']`; `word_count_threshold=8` |
| 3 | Контент-фильтр | `crawler.py` | `PruningContentFilter(threshold=0.48, threshold_type="fixed")` → берём `fit_markdown` (фолбэк — `raw_markdown`) |
| 4 | Схлопывание markdown | `distill.py` | `slim_markdown`: инлайновые ссылки и картинки → текст ярлыка, срезка сносок `[^N]:`, схлопывание пустых строк |
| 5 | BM25-дистилляция | `distill.py` | `passages(text, query, max_chars)`: отбор пассажей под запрос, сборка в порядке документа, жёсткий бюджет символов |

## Стадия 5 подробнее: passages()

- **Чанкинг.** Текст режется по абзацам до ~320 символов (потолок чанка 500); слишком длинные куски добиваются по предложениям, чанки свыше 900 символов — механически пополам.
- **Токенизация.** Слова `[a-zа-яё0-9]+` длиной больше одного символа минус стоп-слова RU+EN.
- **Скоринг BM25-flavoured.** Чанк получает `Σ qtf · (1 + ln tf) · ln(1 + N / df)` — вклад частоты терма в чанке и редкости терма по странице.
- **Сборка.** Лучшие чанки возвращаются **в порядке документа** (не по рангу), чтобы текст читался связно; суммарная длина не превышает бюджет — последний чанк при необходимости режется с «…».
- **Без `query`.** Срабатывает head-trim: возвращается текст с первого чанка — начало страницы обычно и есть суть.
- **Фолбэк.** Если ни один терм запроса не встретился на странице, отдаётся первый чанк, а не пустота.

## Бюджеты по умолчанию

| Параметр | Дефолт | Границы | Где задаётся |
|---|---|---|---|
| Сниппет хита поиска | 280 симв. | — | `searx.py`, `clean_text` |
| Заголовок хита | 140 симв. | — | `searx.py`, `clean_text` |
| Ответ SearXNG (instant answer) | 300 симв. | — | `searx.py`, `clean_text` |
| `read_url` `max_chars` | 8000 | 300–50000 | `server.py` + клампинг в `core.py` |
| `deep_research` `per_source_chars` | 3500 | 300–8000 | `server.py` + клампинг в `core.py` |
| `deep_research` `max_sources` | 3 | 1–6 | там же |
| `deep_research` / `web_search` `max_results` | 10 / 8 | 1–20 | там же |

Бюджет — свойство ответа, а не пожелание: `passages()` никогда не вернёт больше `max_chars`.

## Стратегия кэша

- **Хранилище.** Один SQLite-файл `$BATHYS_CACHE_DIR/cache.db`; ключ — sha256 от префикса и аргументов (`"search", query, max_results, …` / `"page", url`).
- **TTL.** Поиски живут `BATHYS_SEARCH_TTL` (3600 c), страницы — `BATHYS_PAGE_TTL` (86400 c); ошибки загрузки страницы кэшируются на час, чтобы не долбить мёртвый URL.
- **Сырец до дистилляции.** Кладётся текст после `fit_markdown`, но до `passages()` — повторное чтение той же страницы под другим `query` не ходит в сеть (см. [data-flow.md](data-flow.md), путь `cache HIT`).
- **Экспирация ленивая.** Протухшие записи игнорируются при чтении; физическая чистка — удалением `cache.db` ([runbook.md](../operations/runbook.md)).

## См. также

- [module-contracts.md](../contracts/module-contracts.md) — инварианты и интерфейсы каждого модуля конвейера.
- [../operations/metrics.md](../operations/metrics.md) — как стадии конвейера измеряются (compression ratio, cache hit rate).
