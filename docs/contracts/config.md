# Контракт конфигурации — переменные `BATHYS_*`

Версия: v0.1.0. Источник истины — `src/bathys/config.py` (`Config.load()`).

## Семантика

- **Приоритет: env > default.** Отсутствующая переменная даёт дефолт; пустая строка для числовых — ошибка `int`/`float` на старте.
- **Чтение один раз на процесс:** `Config.load()` вызывается в lifespan при старте сервера; изменение env требует рестарта процесса. Инфраструктура (docker/native) читает те же значения из этого снимка.
- Булево `BATHYS_AUTO_START`: false только для `""`, `0`, `false`, `no`, `off` (без учёта регистра, с обрезкой пробелов); всё остальное — true.
- Пути проходят `expanduser()`; `BATHYS_SEARXNG_HOME` по умолчанию вычисляется от итогового `BATHYS_DATA_DIR`.
- Неизвестный `BATHYS_START_MODE` не валидируется: режим, отличный от `auto|docker|native`, не предпринимает попыток автостарта — вызовы завершатся `RuntimeError` при молчащем external-инстансе.

## Таблица переменных

| Переменная | Дефолт | Тип | Смысл |
|---|---|---|---|
| `BATHYS_SEARXNG_URL` | `http://127.0.0.1:8888` | str | адрес SearXNG; нормализуется `rstrip("/")` |
| `BATHYS_AUTO_START` | `1` | bool | разрешить серверу самому поднимать бэкенд (`services.ensure_running`) |
| `BATHYS_START_MODE` | `auto` | str | режим автостарта: `auto` \| `docker` \| `native`; иное — без попыток |
| `BATHYS_START_CMD` | — (None) | str? | своя команда старта контейнера вместо авто-выбора движка; разбирается `split()` |
| `BATHYS_SEARXNG_REF` | пин-SHA (константа `SEARXNG_REF` в `config.py`) | str | git-ref (SHA/тег/ветка), на который пинится клон SearXNG в нативном режиме; апстрим не тегирует релизы, поэтому дефолт — проверенный коммит, согласованный с пином образа `compose.yaml`; переопределять осознанно (раз в квартал), не `master` |
| `BATHYS_DATA_DIR` | `~/.local/share/bathys` | path | состояние: клон+venv нативного SearXNG (в `SEARXNG_HOME`) |
| `BATHYS_CACHE_DIR` | `~/.cache/bathys` | path | кэш: `cache.db` (SQLite) |
| `BATHYS_SEARXNG_HOME` | `{DATA_DIR}/searxng-home` | path | дом нативного режима: `repo/`, `venv/`, `settings.yml`, `searxng.log` |
| `BATHYS_SEARCH_TTL` | `3600` | int, с | TTL кэша поисковых outcomes |
| `BATHYS_PAGE_TTL` | `86400` | int, с | TTL кэша страниц (очищенный markdown) |
| `BATHYS_SEARCH_TIMEOUT` | `15` | float, с | таймаут httpx-клиента поиска |
| `BATHYS_CRAWL_TIMEOUT` | `40` | float, с | таймаут загрузки страницы (`page_timeout`, мс = значение×1000) |
| `BATHYS_STARTUP_TIMEOUT` | `90` | float, с | бюджет ожидания готовности поднятого бэкенда (опрос каждые 1.5 с) |
| `BATHYS_SEARCH_MIN_INTERVAL` | `1.0` | float, с | вежливый минимальный интервал между поисками к бэкенду (F-301); 0 — без пауз |
| `BATHYS_SEARCH_RETRIES` | `2` | int | дoп. попытки при пустой/заблокированной выдаче с ротацией наборов движков и паузой 1.5s×n (F-101); 0–3 |
| `BATHYS_DIVE_CONCURRENCY` | `4` | int | параллельные нырки страниц в `deep_research` (F-301); 1–8 |
| `BATHYS_BROWSER` | `auto` | режим | двухъярусное извлечение: `auto` — HTTP-движок первым, браузер только для JS-страниц; `off` — без браузера; `always` — только браузер (отладка) |
| `BATHYS_ROBOTS` | `1` | bool | уважать robots.txt при прямых нырках страниц (F-303); fail-open при недоступном robots; поиск не затрагивается |
| `BATHYS_METRICS` | `1` | bool | локальный журнал вызовов `{DATA_DIR}/metrics.jsonl` (F-304); выключается полностью |
| `BATHYS_ENGINE_BRAVE_KEY` | — | str | API-ключ Brave Search: одним ключом включает движок `brave` в генерируемых настройках SearXNG нативного режима (F-203, `services.render_settings`); для docker-режима — пропишите движок в settings сами |

Производные значения, не настраиваемые отдельно: TTL кэшированных ошибок fetch = `max(3600, PAGE_TTL // 24)`; TTL кэша пустой выдачи = `min(SEARCH_TTL, 600)`; сессия поискового клиента = `SEARCH_TIMEOUT`, `follow_redirects=True`; порог «плохого» движка = 3 подряд пустых/молчащих ответа (F-102, in-memory, сбрасывается любым попаданием).

## Примеры

```bash
# Уже есть свой SearXNG с JSON API — Bathys только пользуется:
export BATHYS_SEARXNG_URL=http://127.0.0.1:7777
export BATHYS_AUTO_START=0

# Форсировать нативный режим и свой кэш:
export BATHYS_START_MODE=native
export BATHYS_CACHE_DIR=/tmp/bathys-cache
```

Связанные документы: режимы автостарта — [ADR 0003](../adr/0003-self-managed-searxng.md); TTL и кэш — [ADR 0005](../adr/0005-cache-raw-before-distill.md); внутренние инварианты — `module-contracts.md`.
