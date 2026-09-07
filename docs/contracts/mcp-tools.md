# Контракт MCP-инструментов — Bathys

Версия: v0.1.1. Источник истины — `src/bathys/server.py`; этот файл фиксирует наблюдаемое поведение.

## Общие правила

- Все четыре инструмента возвращают **строку** — готовый к показу текст; грамматики футеров — `output-format.md`.
- Числовые параметры **мягко клампятся**, а не отвергаются: `max_results → [1, 20]`, `max_sources → [1, 6]`, `per_source_chars → [300, 8000]`, `max_chars → [300, 50000]`, `total_chars → [300, 30000]`; невалидный `time_range` (всё, кроме `day|week|month|year`) молча становится `None`.
- Ошибка выполнения → исключение в `server.py` → SDK оборачивает в `isError=true` с текстом `Error executing tool {tool}: {сообщение}` (см. `output-format.md`, раздел «Ошибки»).
- Ключ кэша поиска включает все параметры фильтрации; ключ страницы — только `url` (пере-чтение с другим `query` бесплатно).

---

## `deep_research`

**Назначение.** Метапоиск + чтение топ-источников headless-браузером + BM25-дистилляция под запрос, одним вызовом. Рекомендованный первый вызов для любого исследовательского вопроса.

**Сигнатура.**

```python
deep_research(query: str, max_sources: int = 3, max_results: int = 10,
              per_source_chars: int = 3500, time_range: str | None = None,
              category: str | None = None, language: str | None = None) -> str
```

| Параметр | Тип | Дефолт | Диапазон | Смысл |
|---|---|---|---|---|
| `query` | `str` | обязателен | — | исследовательский вопрос (RU/EN) |
| `max_sources` | `int` | `3` | 1–6 | сколько топ-хитов прочитать полностью |
| `max_results` | `int` | `10` | 1–20 | сколько хитов поиска рассматривать |
| `per_source_chars` | `int` | `3500` | 300–8000 | символьный бюджет на источник |
| `time_range` | `str?` | `None` | day/week/month/year | фильтр свежести |
| `category` | `str?` | `None` | напр. `general`, `news`, `science`, `it` | категория SearXNG |
| `language` | `str?` | `None` | напр. `ru`, `en`, `ru-RU` | язык выдачи |

**Грамматика вывода (блоки).** `# Bathys research: {query!r}` → опционально `Answer: …` → на каждый источник `## {i}. {title}` с метастрокой (`url · engines: … · дата`) и дистиллированным текстом, либо `(not fetched — {ошибка}; snippet: {сниппет})` — отказ одного источника не валит вызов → опционально `More hits (not fetched):` (до 5 ссылок) → футер `[bathys: {raw_hits} raw hits, top {n} considered · dove {k} pages · …]`. Чтение источников параллельное, до 4 одновременно.

**Ошибки.** `SearxError` (бэкенд недоступен/не-200) и `RuntimeError` (бэкенд не поднялся) — весь вызов isError. Сбой чтения отдельной страницы в сам ответ не попадает как ошибка — секцией `(not fetched — …)`.

---

## `web_search`

**Назначение.** Только поиск: ранжированный список ссылок со сниппетами, без чтения страниц.

**Сигнатура.**

```python
web_search(query: str, max_results: int = 8, time_range: str | None = None,
           category: str | None = None, engines: str | None = None,
           language: str | None = None) -> str
```

| Параметр | Тип | Дефолт | Диапазон | Смысл |
|---|---|---|---|---|
| `query` | `str` | обязателен | — | поисковый запрос |
| `max_results` | `int` | `8` | 1–20 | размер списка |
| `time_range` | `str?` | `None` | day/week/month/year | фильтр свежести |
| `category` | `str?` | `None` | напр. `general`, `news`, `it`, `files` | категория SearXNG |
| `engines` | `str?` | `None` | CSV, напр. `google,bing,duckduckgo` | принудительный набор движков |
| `language` | `str?` | `None` | напр. `ru`, `en` | язык выдачи |

**Грамматика вывода (блоки).** опционально `Answer: {первый direct answer}` → по хиту: `{i}. {title}` / `{url}` / `{snippet}[ {дата}]` → опционально `Refine: {подсказки через ", "}` → при пустой выдаче тело `No results for: {query}` (не ошибка) → футер `[bathys: {n} hits · cache HIT | {секунды}s · searx json …]`. Дедупликация по host+path, сортировка по убыванию score.

**Ошибки.** `SearxError`: unreachable / `searxng http {код}` (при 403 — подсказка включить JSON: `search.formats: [html, json]`); `RuntimeError` от `ensure_running`, включая случай `BATHYS_AUTO_START=0`.

---

## `read_url`

**Назначение.** Прочитать одну страницу: JS-рендер, снятие boilerplate, дистилляция под `query`, бюджет символов.

**Сигнатура.**

```python
read_url(url: str, query: str | None = None, max_chars: int = 8000) -> str
```

| Параметр | Тип | Дефолт | Диапазон | Смысл |
|---|---|---|---|---|
| `url` | `str` | обязателен | абсолютный http(s) | адрес страницы |
| `query` | `str?` | `None` | — | фокус: вернуть только релевантные пассажи; без него — head-trimmed |
| `max_chars` | `int` | `8000` | 300–50000 | символьный бюджет вывода |

**Грамматика вывода (блоки).** `# {title | url}` + строка `{url}` → дистиллированный markdown (≤ `max_chars`) → футер `[bathys: page {in} tok → {out} tok · query-distilled | head-trimmed · cache HIT | MISS]`.

**Ошибки.** `RuntimeError` с текстом `crawl failed: {причина}` при неудаче загрузки; кэшированная ошибка URL переигрывается как есть в течение TTL ошибки (3600s).

---

## `read_urls`

**Назначение.** Пакетное чтение известных URL одним вызовом (паритет Tavily Extract): без поиска, до 10 страниц, параллельные нырки, один общий бюджет символов.

**Сигнатура.**

```python
read_urls(urls: list[str], query: str | None = None, total_chars: int = 12000,
          refresh: bool = False) -> str
```

| Параметр | Тип | Дефолт | Диапазон | Смысл |
|---|---|---|---|---|
| `urls` | `list[str]` | обязателен | 1–10 после дедупликации | адреса страниц; дубликаты (после utm/fragment-чистки по `normalize_url`) сливаются, лишние свыше 10 — строка `Skipped` |
| `query` | `str?` | `None` | — | фокус дистилляции, применяется к каждой странице |
| `total_chars` | `int` | `12000` | 300–30000 | общий бюджет вывода: делится поровну между успешными страницами, остаток — первой успешной |
| `refresh` | `bool?` | `False` | — | игнорировать кэш и перечитать все страницы |

**Грамматика вывода (блоки).** на каждый URL `## {i}. {title}` + строка `{final url}` + дистиллят (≤ доли бюджета); сбой одной страницы — секция `## {i}. {url}` + `(not fetched — {Класс}: {msg})` без бюджета → опционально одна строка `Skipped (over the 10-url limit): {url, …}` → футер `[bathys: batch {n} urls · {ok}/{n} ok · {in} ch fetched → {out} ch returned · {secs}s]`. Чтения параллельные, до `BATHYS_DIVE_CONCURRENCY` одновременно (тот же семафор, что и `deep_research`).

**Ошибки.** Сбой отдельной страницы — секцией `(not fetched — …)`, вызов не валит. Пустой список после дедупликации → `ValueError` → весь вызов isError.

---

## Playbook: какому вопросу какой инструмент

| Вопрос пользователя | Инструмент |
|---|---|
| «Разберись/исследуй/что известно о X» | `deep_research` — всегда первый выбор |
| «Найди ссылки/источники по X» | `web_search` |
| «Прочитай/процитируй вот эту страницу» | `read_url` |
| «Прочитай вот эти N страниц» (URL уже известны) | `read_urls` — один вызов и общий бюджет вместо N `read_url` |
| Нужна свежесть (новости за день/неделю) | `web_search`/`deep_research` с `time_range` |
| Нужен конкретный документ по известному URL | `read_url`, опционально с `query`-фокусом |

Связанные документы: параметры окружения — `config.md`; футеры и ошибки — `output-format.md`; внутренние контракты модулей — `module-contracts.md`.
