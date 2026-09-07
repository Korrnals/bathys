# ADR 0001 — Python + Crawl4AI как ядро извлечения

| Поле | Значение |
|---|---|
| Статус | Accepted |
| Дата | 2026-09-06 |
| Применимо к | Bathys v0.1.0 |
| Затрагивает | `src/bathys/crawler.py`, `src/bathys/distill.py`, `pyproject.toml` |

## Context

Bathys читает веб-страницы как данные для дистилляции, поэтому ядро извлечения обязано:

- рендерить JS (SPA и ленивый контент отдают пустой HTML без браузера);
- вырезать boilerplate (nav/footer/ads) до передачи текста в пайплайн;
- выдавать markdown, пригодный для чанкования и BM25-скоринга;
- держать один разделяемый браузер на процесс — подъём chromium дороже самого fetch.

## Decision

CPython + `crawl4ai>=0.6` (факт: `requires-python = ">=3.10"` в `pyproject.toml`; разработка и e2e-прогон — на 3.12, venv — `python3.12`).

- `AsyncWebCrawler` с `BrowserConfig(headless=True, text_mode=True, light_mode=True)` и фиксированным UA Chrome/126 — один экземпляр на процесс, ленивая инициализация под `asyncio.Lock` (`Crawler._ensure`).
- На каждый fetch — `CrawlerRunConfig`: `cache_mode=CacheMode.BYPASS` (кэширование — собственное, см. [ADR 0005](0005-cache-raw-before-distill.md)), `page_timeout=crawl_timeout*1000`, `excluded_tags`/`excluded_selector`, `word_count_threshold=8`.
- Контент-фильтр `PruningContentFilter(threshold=0.48, threshold_type="fixed")` внутри `DefaultMarkdownGenerator`; берётся `fit_markdown`, фолбэк — `raw_markdown`.
- Импорты crawl4ai отложены в `_imports()` с фолбэком на старую раскладку модулей — ускорение старта и устойчивость к переименованиям между версиями.

## Alternatives

| Альтернатива | Почему отклонена |
|---|---|
| Node/TS MCP-стек | нет зрелого аналога Crawl4AI: pruning, markdown-генерация и browser-оркестрация собрались бы из кусков |
| httpx + selectolax без браузера | не тянет JS-страницы; значимая доля целей — SPA, результат — пустой или неполный текст |
| сырой Playwright | слишком низкоуровнево: нет pruning/markdown; пришлось бы поддерживать собственный extraction-слой |

## Consequences

- Положительные: JS-рендер и очистка «из коробки»; краткий путь от `fit_markdown` к дистилляции; один браузер экономит память и время на повторных dive.
- Отрицательные: тяжёлая зависимость (headless chromium ставится отдельно); библиотека пишет логи в stdout — требуется `_hush_stdout_logs` в `server.py` (чистота stdio-канала MCP); раскладка модулей crawl4ai нестабильна между версиями — компенсируется фолбэк-импортом.

## Источники

`src/bathys/crawler.py`; `pyproject.toml`; venv: `crawl4ai 0.9.3`, `python3.12`.
