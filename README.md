<p align="center"><img src="docs/assets/banner.svg" alt="Bathys" width="720"></p>

# Bathys

**Единый локальный поисковый сервис глубокого ресёрча для ИИ-агентов.** Один процесс владеет всем конвейером — поиск → извлечение → дистилляция под запрос → кэш — и всей стратегией ресёрча: что искать, какие страницы читать, сколько вернуть. Агент видит лишь интерфейс из четырёх MCP-инструментов; SearXNG и Crawl4AI работают внутри как сменные движки. Облачных квот и API-ключей нет, LLM внутри нет — дистилляция детерминированная (BM25).

Сонар находит координаты, батискаф ныряет за полными текстами, дистиллятор поднимает на палубу только то, что отвечает на вопрос.

![python](https://img.shields.io/badge/python-3.10%2B-blue)
![version](https://img.shields.io/badge/version-0.6.1-9cf)
![mcp](https://img.shields.io/badge/MCP-stdio%20server-6f42c1)
![license](https://img.shields.io/badge/license-MIT-green)

## ⚡ Quick start

Нужны Python ≥ 3.10 и `git`. В каталоге проекта:

```bash
git clone https://github.com/Korrnals/bathys.git && cd bathys
python3.12 -m venv .venv
.venv/bin/pip install -e .
.venv/bin/python -m playwright install chromium   # браузер для извлечения
.venv/bin/python -m unittest discover -s tests    # 72 теста без сети, ~0.1 c
.venv/bin/bathys-doctor                           # диагностика стека одним запуском
```

В минимальном контейнерном образе без `ensurepip` venv собирается через `get-pip.py` — ветка в [docs/getting-started/install.md](docs/getting-started/install.md). SearXNG поднимать руками не нужно: при первом поиске сервер сам пробует внешний инстанс, затем docker/podman, затем нативный режим ([docs/getting-started/configure.md](docs/getting-started/configure.md)).

## 🔌 Подключение к харнессу

**Автоматически.** Одна команда найдёт харнессы по стандартным путям, пропишет сервер с бэкапом конфига и (с `--with-agent`) скопирует субагента:

```bash
.venv/bin/bathys install            # сначала --dry-run, чтобы увидеть план
```

Детектируются zcode, Claude Code, Claude Desktop, Cursor; повторный запуск ничего не меняет — запись идемпотентна. Поддерживаются `--print-config` (готовые блоки для ручной вставки) и `--searxng-home <путь>`.

**Вручную.** Bathys — stdio MCP-сервер, конфиг везде один и тот же блок `mcpServers`; от харнесса зависит только файл, в который его кладут. `command` — абсолютный путь к вашему клону (`~` внутри JSON не раскрывается); `BATHYS_SEARXNG_HOME` опциональна.

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

| Харнесс | Гайд |
|---|---|
| zcode | [docs/integrations/zcode.md](docs/integrations/zcode.md) |
| Claude Code / Claude Desktop | [docs/integrations/claude-code.md](docs/integrations/claude-code.md) |
| Cursor | [docs/integrations/cursor.md](docs/integrations/cursor.md) |
| Любой другой MCP-клиент | [docs/integrations/generic-mcp.md](docs/integrations/generic-mcp.md) |

## 🧠 Научить агента работать эффективно

Конфиг — только половина дела. Из коробки харнесс получает **instructions-playbook** (матрицу выбора инструментов), **annotations** и **три стратегии-промпта** — `bathys_deep_research`, `bathys_source_audit`, `bathys_fresh_scan`, — так что выбирает инструменты Bathys уже нативно. Сильнее — профиль: субагент [`agents/bathys-researcher.md`](agents/bathys-researcher.md) с двумя скиллами, которому глубокий ресёрч делегируется целиком; для клиентов, не показывающих MCP instructions, — дроп-ин [`agents/HARNESS-DROPIN.md`](agents/HARNESS-DROPIN.md) в `AGENTS.md` / `CLAUDE.md` / `.cursor/rules`.

Пошаговая инструкция «из коробки → субагент → дроп-ин» и таблица сигналов футеров — в [«Живых кейсах», раздел C](docs/getting-started/cases.md#c-как-научить-харнесс-работать-с-bathys-эффективно).

## 🧭 Ходовые кейсы

**Сравнение технологий.** «Сравни SQLite WAL и PostgreSQL под нагрузку — что выбрать в 2026?» → агент вызывает `deep_research`, доуточняет запрос терминами из найденного и верифицирует вывод по двум источникам. Итог: один вызов вместо цепочки «поиск + N чтений», в контекст попадает 7.5k символов вместо ~35k.

```text
[bathys: 34 raw hits, top 8 considered · dove 3 pages · 35669 ch fetched → 7508 ch returned · 1.3s]
```

**Аудит спорного утверждения.** «Правда ли, что в X упали замеры?» → стратегия `bathys_source_audit`: пакетное чтение ссылок из обсуждения + кросс-поиск опровержений → вердикт по каждому тезису с URL. Битая ссылка стоит одну строку, а не сорванный вызов.

**Свежий срез.** «Что нового в Y за две недели?» → `bathys_fresh_scan`: поиск с `time_range=week` → пакетное чтение → сводка с датами; протухший `cache HIT` лечится одним `refresh=true`.

Все кейсы — пользовательские, автономных агентов и эксплуатация — с живыми диалогами и профитом каждого: **[«Живые кейсы» → docs/getting-started/cases.md](docs/getting-started/cases.md)**.

## 🛠 Инструменты

| Инструмент | Что делает |
|---|---|
| `deep_research(query, max_sources=3, …)` | ищет, параллельно читает топ-источники, возвращает слитый дистиллят под запрос. Первый вызов для любого ресёрч-вопроса. |
| `web_search(query, max_results=8, …)` | ранжированный список ссылок со сниппетами без содержимого страниц; `as_json=true` — чистый JSON для программ. |
| `read_url(url, query=None, max_chars=8000)` | читает одну страницу; с `query` — только релевантные пассажи. |
| `read_urls(urls, query=None, total_chars=12000)` | пакетно читает до 10 известных страниц; бюджет делится между успешными, сбой страницы — одна строка, не сорванный вызов. |

Поиск сужается общими фильтрами `time_range`, `category`, `engines`, `language`. Живой футер ответа показывает сжатие и кэш: `[bathys: 41 raw hits, top 3 considered · dove 3 pages · 35669 ch fetched → 7508 ch returned · 3.2s]`.

## 📊 Экономия токенов

Шкала честная и символьная, токены ≈ `chars/4`; каждая цифра взята из футера реального вызова.

| Вызов | Из сети | Агенту | Сжатие |
|---|---|---|---|
| `web_search` | 37 549 симв. | 1 986 симв. | 18.9× |
| `read_url` | 17 063 симв. | 2 325 симв. | 7.3× |
| `deep_research` (3 страницы) | 35 669 симв. | 7 508 симв. | 4.7× |

- **Дистилляция под запрос** — пять стадий очистки (JS-рендер → вырезание бойлерплейта → `PruningContentFilter` → схлопывание markdown → BM25-отбор пассажей) с жёсткими бюджетами символов.
- **Кэш сырца до дистилляции** — SQLite хранит сырой текст, поэтому перечитать страницу под другим углом можно бесплатно и без сети.
- **Ноль облачных квот** — `deep_research` заменяет цепочку «поиск + N чтений», то есть N+1 списаний квоты, одним локальным вызовом.

Методика и пороги — в [docs/operations/metrics.md](docs/operations/metrics.md).

## 📚 Документация

Хаб с маршрутами «с чего начать» — [docs/index.md](docs/index.md).

```
docs/
├── index.md          # хаб: дерево + три маршрута чтения
├── getting-started/  # установка · конфигурация · подключение · живые кейсы
├── integrations/     # zcode · claude-code · cursor · generic-mcp
├── architecture/     # компоненты · конвейер очистки · потоки данных
├── contracts/        # инструменты · футеры · модули · конфиг (19 env)
├── operations/       # runbook · метрики токен-экономии
├── product/          # хартия · реестр функций · роадмап · конкуренты
├── adr/              # шесть принятых архитектурных решений
└── meta/             # стайлгайд · глоссарий
```

Вне `docs/`: [agents/](agents/) (субагент `bathys-researcher`, дроп-ин для харнессов) · [tests/](tests/) (72 юнит-теста без сети) · [scripts/](scripts/) (smoke, stdio_check, метрики) · [CHANGELOG.md](CHANGELOG.md).

## 📍 Статус

**0.6.1.** Выпускная история: v0.2 «Качество выдачи» (ретраи, здоровье движков), v0.3 «Паритет с Tavily» (`read_urls`, JSON-режим), v0.4 «Эксплуатация» (robots-этика, метрики, `bathys-doctor`), v0.5 «Identity & Harness» (репозиционирование, промпты, субагент), v0.6 «Native Install» (`bathys install`) — итоги в [CHANGELOG.md](CHANGELOG.md).

Репозиторий: `github.com/Korrnals/bathys`. До 1.0 остаются публикация пакета `bathys` на PyPI (имя свободно, публикация планируется к 1.0) и первый прогон Docker-образа; CI с matrix 3.10–3.12 уже в репозитории.

## ⚖️ Лицензия

[MIT](LICENSE) — см. поле `license` в `pyproject.toml`.