# Конфигурация Bathys

Все настройки читаются один раз при старте из переменных окружения с префиксом `BATHYS_` (дефолты — в `src/bathys/config.py`). Минимальный набор — пустой: сервер и бэкенд поднимаются сами.

## Env-переменные

| Переменная | Дефолт | Что делает |
|---|---|---|
| `BATHYS_SEARXNG_URL` | `http://127.0.0.1:8888` | задаёт адрес SearXNG-бэкенда |
| `BATHYS_AUTO_START` | `1` | разрешает серверу поднимать бэкенд самому; `0`/`false`/`off` запрещает |
| `BATHYS_START_MODE` | `auto` | выбирает способ старта: `auto` / `docker` / `native` |
| `BATHYS_START_CMD` | — | подменяет команду старта контейнера, например `docker compose -f /path/compose.yaml up -d` |
| `BATHYS_SEARXNG_REF` | пин-коммит из `config.py` | git-ref (SHA/тег/ветка) клона SearXNG в нативном режиме; дефолт — проверенный коммит, менять осознанно (ежеквартально), не `master` |
| `BATHYS_DATA_DIR` | `~/.local/share/bathys` | хранит данные проекта; база для `SEARXNG_HOME` |
| `BATHYS_CACHE_DIR` | `~/.cache/bathys` | хранит SQLite-кэш (`cache.db`) |
| `BATHYS_SEARXNG_HOME` | `$BATHYS_DATA_DIR/searxng-home` | задаёт дом нативного режима (клон SearXNG + venv + лог) |
| `BATHYS_SEARCH_TTL` | `3600` | задаёт TTL кэша поисков, сек |
| `BATHYS_PAGE_TTL` | `86400` | задаёт TTL кэша страниц, сек |
| `BATHYS_SEARCH_TIMEOUT` | `15` | ограничивает HTTP-запрос к SearXNG, сек |
| `BATHYS_CRAWL_TIMEOUT` | `40` | ограничивает нырёк одной страницы, сек |
| `BATHYS_STARTUP_TIMEOUT` | `90` | ограничивает ожидание готовности бэкенда, сек |
| `BATHYS_SEARCH_MIN_INTERVAL` | `1.0` | вежливая пауза между поисками к бэкенду, сек |
| `BATHYS_SEARCH_RETRIES` | `2` | доп. попытки при пустой выдаче (ротация движков с паузами), 0–3 |
| `BATHYS_DIVE_CONCURRENCY` | `4` | параллельные чтения страниц в `deep_research`, 1–8 |
| `BATHYS_BROWSER` | `auto` | режим | двухъярусное извлечение: `auto` — HTTP-движок первым, браузер только для JS-страниц; `off` — без браузера; `always` — только браузер (отладка) |
| `BATHYS_ROBOTS` | `1` | уважать robots.txt при чтении страниц (отказ — пометкой, не ошибкой) |
| `BATHYS_METRICS` | `1` | писать локальный журнал вызовов `~/.local/share/bathys/metrics.jsonl` |
| `BATHYS_ENGINE_BRAVE_KEY` | — | ключ Brave Search API: включает движок `brave` в настройках нативного SearXNG одним env |

Переменные передаются в блоке `env` конфига клиента (см. [integrate.md](integrate.md)) или в шелле перед запуском проверочных скриптов.

## Выбор START_MODE

`BATHYS_START_MODE` решает, что поднимать, когда пинг `BATHYS_SEARXNG_URL` не отвечает. Режим-состояние `external` отдельно не выбирается: если на URL уже кто-то отвечает, Bathys пользуется им и ничего не стартует.

| Режим | Поведение | Когда выбирать |
|---|---|---|
| `auto` (дефолт) | пробует docker/podman (`docker compose` → `podman compose` → `docker-compose` → `podman-compose`), при неудаче — нативный режим | в большинстве случаев |
| `docker` | поднимает bundled `compose.yaml`; контейнер называется `bathys-searxng`, порт `127.0.0.1:8888` | на хосте с контейнерным движком; нативный клон не нужен |
| `native` | клонирует SearXNG в `$SEARXNG_HOME/repo`, ставит venv в `$SEARXNG_HOME/venv`, запускает `python -m searx.webapp` дочерним процессом | без контейнерного движка: VPS, CI, минимальный образ |

Диагностика старта — в [runbook.md](../operations/runbook.md); анатомия автостарта — в [overview.md](../architecture/overview.md).

## Файл настроек SearXNG

Качество выдачи задаёт `src/bathys/searxng-settings.yml` — один файл обслуживает и docker-режим (монтируется read-only в контейнер), и нативный (копируется в `$SEARXNG_HOME/settings.yml`):

```yaml
use_default_settings: true
server:
  secret_key: "bathys-local-…"     # локальный ключ; бэкенд слушает 127.0.0.1
  bind_address: "127.0.0.1"
  port: 8888
  limiter: false                    # rate-limit не нужен для localhost-клиента
  image_proxy: false
search:
  safe_search: 1
  default_lang: "auto"
  formats: ["html", "json", "csv", "rss"]   # json обязателен — без него API вернёт 403
```

Правила правки:

- **JSON API включён** (`formats` содержит `json`) — без этого каждый поиск падает с 403; на чужом внешнем инстансе включите то же в его настройках.
- **Limiter выключен** — агент шлёт серии запросов, лимитер на localhost только мешает; менять на публично доступном бэкенде.
- **Привязка к `127.0.0.1`** — бэкенд не должен светиться в сеть; для другого порта правьте `port` здесь и синхронно `BATHYS_SEARXNG_URL`.

Контейнерный порт пробрасывает `src/bathys/compose.yaml` (`127.0.0.1:8888:8080`) — при смене порта правится и он.
