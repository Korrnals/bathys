# Контракты модулей — Bathys

Версия: v0.1.0. Источники: `src/bathys/*.py`. Каждый раздел: ответственность, публичный интерфейс, инварианты, ошибки.

## Сквозные инварианты

| # | Инвариант | Где живёт |
|---|---|---|
| I1 | **Чистота stdout**: stdout принадлежит MCP stdio-протоколу; все логи библиотек — stderr или файлы | `server._hush_stdout_logs`, лог `_Native` в `searxng.log` |
| I2 | **Бюджеты символов соблюдаются точно**: `passages()` возвращает ≤ `max_chars` (последний чанк подрезается по границе слова с `…`) | `distill.passages` |
| I3 | **Кэш хранит сырец до дистилляции**: ключ страницы — только `url`; дистилляция всегда после cache HIT | `core._read`, `cache.py` |
| I4 | **`ensure_running` идемпотентен**: ping-first; marker-файлы установки; декларативный `compose up -d`; один нативный инстанс на процесс | `services.py` |
| I5 | **Жизненный цикл дочернего SearXNG принадлежит Engine**: `lifespan` стартует Engine, `Engine.stop()` останавливает потомка (terminate → 5s → kill) | `server._lifespan`, `core.Engine.stop`, `services.stop_native` |

## `server.py`

- **Ответственность.** Обвязка FastMCP: имя, инструкции, четыре `@mcp.tool()`, lifespan, точка входа `main()`.
- **Интерфейс.** `mcp` (FastMCP), `deep_research`, `web_search`, `read_url`, `read_urls`, `main()`; внутренние `_lifespan`, `_engine(ctx)`, `_hush_stdout_logs`.
- **Инварианты.** I1; `Config.load()` — один раз на процесс в `_lifespan`; engine доступен инструментам только через `ctx.request_context.lifespan_context`.
- **Ошибки.** Не перехватывает ничего: исключения модулей уходят в SDK и превращаются в `isError` (`Error executing tool {tool}: …`).

## `core.py`

- **Ответственность.** Пайплайн search → dive → distill + кэш; `Engine` — всё, что нужно инструментам, один экземпляр на процесс.
- **Интерфейс.** `Engine(cfg)` c `start()`, `stop()`, `search()`, `read()`, `research()`; `ReadResult(page, distilled, cache_hit)`; `_backend()`.
- **Инварианты.** I2, I3, I5; клампинг параметров до логики; latch `_searx_ok`: `ensure_running` зовётся один раз на процесс и повторно только после `SearxError`; футер всегда последней строкой ответа; в `research` чтение источников — `asyncio.gather` под `Semaphore(4)`, сбой одной страницы не роняет вызов (секция `(not fetched — …)`).
- **Ошибки.** Пробрасывает `SearxError`/`RuntimeError` из `search`/`read`; в `research` изолирует ошибки dive.

## `batch.py`

- **Ответственность.** Пакетное чтение известных URL (без поиска): дедупликация, параллельные нырки, общий бюджет символов, секции + футер.
- **Интерфейс.** `read_many(engine, urls, *, query, total_chars, refresh=False) → str`.
- **Инварианты.** I2, I3 (через `core._read`); дедуп ключ — `searx.normalize_url`, хранится первое написание; лимит 10 URL, лишние — одна строка `Skipped`; чтения — `asyncio.gather` под `engine._dive_sem` ( тот же семафор, что `research`); бюджет делится поровну между успешными страницами, остаток — первой успешной (дистилляция повторно поверх кэшированного сырца — сеть одна на URL); сбой страницы — секция `(not fetched — {Класс}: {msg})`, вызов не роняет; пустой список после дедупа — `ValueError`; футер всегда последней строкой.
- **Ошибки.** Изолирует ошибки dive (как `research`); `ValueError` на пустом входе уходит в SDK как isError.

## `searx.py`

- **Ответственность.** Клиент SearXNG JSON API: запрос, нормализация, дедупликация, ранжирование.
- **Интерфейс.** `search(cfg, http, query, *, categories, engines, language, time_range, safesearch=1) → SearchOutcome`; дата-классы `SearchHit`, `SearchOutcome`; `clean_text`, `normalize_url`; `SearxError`.
- **Инварианты.** Лимиты полей: title ≤ 140, snippet ≤ 280, answer ≤ 300, suggestions ≤ 6; `safesearch=1`; отбрасываются URL без схемы и `mailto:`/`javascript:`; трекинг-параметры (`utm_*`, `gclid`, `fbclid`, …) срезаются; дедуп по `netloc (без www) + path (без хвостового /)`, сортировка по убыванию `score`.
- **Ошибки.** `SearxError`: «searxng unreachable at {url}: …» (транспорт) или «searxng http {код}» (не-200; при 403 — подсказка про `search.formats: [html, json]`).

## `crawler.py`

- **Ответственность.** Общий headless-браузер Crawl4AI на процесс; fetch → очищенный markdown.
- **Интерфейс.** `Crawler(cfg)`: `fetch(url) → Page(url, status, title, text, raw_chars)`, `stop()`; внутреннее `_ensure()` под lock.
- **Инварианты.** Один экземпляр браузера; `CacheMode.BYPASS` (кэш — свой, I3); `page_timeout = crawl_timeout*1000`; извлечение через `PruningContentFilter(0.48)`, текст — `fit_markdown` (фолбэк `raw_markdown`); импорты crawl4ai ленивые, с фолбэком на старую раскладку.
- **Ошибки.** `RuntimeError("crawl failed: {причина}")` при `result.success == False`.

## `distill.py`

- **Ответственность.** Очистка и запрос-фокусированная дистилляция: `slim_markdown`, `passages`.
- **Интерфейс.** `slim_markdown(text) → str`; `passages(text, query | None, max_chars) → str`.
- **Инварианты.** I2; детерминизм (тот же вход → тот же выход); без LLM и сети; чанки ~320 (hard 500, разрыв >900); BM25-flavoured скоринг с RU+EN стоп-словами; отбор в порядке документа; фолбэк — lead-абзац (чанк 0) при отсутствии query или нулевом пересечении терминов; короткий текст (≤ max_chars) возвращается как есть.
- **Ошибки.** Не возбуждает: на любой вход возвращает строку.

## `cache.py`

- **Ответственность.** Крошечный SQLite TTL-кэш процесс-локального одиночки.
- **Интерфейс.** `Cache(path)`: `get(k) → (bool, object)`, `set(k, value, ttl)`; `Cache.key(*parts)` — sha256 от `"\x1f".join(parts)`.
- **Инварианты.** I3; таблица `cache(k PRIMARY KEY, exp REAL, v TEXT)`, значение — JSON; потокобезопасность через `threading.Lock`; истёкшие записи лениво игнорируются на чтении, фоновой чистки нет.
- **Ошибки.** Не маскирует ошибки sqlite3 — они поднимаются как есть.

## `services.py`

- **Ответственность.** Bootstrap SearXNG-бэкенда: external → docker → native; управление нативным потомком.
- **Интерфейс.** `ensure_running(cfg, http) → "external" | "docker" | "native"`; `stop_native()`; внутренние `_ping`, `_wait_ready`, `_start_containers`, `_Native` (`prepare`, `start`, `stop`).
- **Инварианты.** I4, I5; I1 (stdout потомка — в файл `searxng.log`); порядок попыток фиксирован, сбой попытки собирается, а не прерывает цепочку; нативный инстанс — глобальный синглтон; venv без `ensurepip` поднимается через `--without-pip` + `get-pip.py`; установка требований маркируется `.searxng-reqs-done`; клон — `--depth 1` ветки `master` (пин тега — план v0.2, см. [ADR 0003](../adr/0003-self-managed-searxng.md)).
- **Ошибки.** `RuntimeError`: при `BATHYS_AUTO_START=0` и молчащем external; «could not start searxng backend — {попытки}» после исчерпания цепочки; под-ошибки clone/venv/pip — с хвостом вывода (до 800 символов).

## `config.py`

- **Ответственность.** Иммутабельная конфигурация: чтение env один раз, дефолты, нормализация.
- **Интерфейс.** `Config` (frozen dataclass, 12 полей), `Config.load() → Config`.
- **Инварианты.** Приоритет env > default; читается один раз на процесс (в `_lifespan`); `expanduser()` на путях; `searxng_url` нормализуется (`rstrip("/")`); `start_mode` — lowercase; булево `AUTO_START`: false только для `{"", "0", "false", "no", "off"}` (в любом регистре). Полная таблица — `config.md`.
- **Ошибки.** Невалидные числовые env (`int`/`float`) падают при `load()` — на старте процесса, не в рантайме. Невалидный `start_mode` не валидируется: такой режим не предпринимает попыток автостарта (см. `config.md`).

Связанные документы: внешняя поверхность — `mcp-tools.md`; формат вывода — `output-format.md`; окружение — `config.md`.
