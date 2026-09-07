# Документация Bathys

Bathys — единый локальный поисковый сервис глубокого ресёрча для ИИ-агентов: собственный конвейер (метапоиск → извлечение → дистилляция под запрос → кэш) и интерфейс из четырёх инструментов; внутри — сменные движки (SearXNG, Crawl4AI). Обзор проекта — в [README](../README.md); хартия, цели и границы — в [docs/product/charter.md](product/charter.md); подключение харнессов — в [integrations/overview.md](integrations/overview.md).

## С чего начать

| Маршрут | Порядок чтения |
|---|---|
| Новичку — поставить и подключить за вечер | [charter.md](product/charter.md) → [install.md](getting-started/install.md) → [integrations/overview.md](integrations/overview.md) |
| Эксплуатация — держать работающим | [configure.md](getting-started/configure.md) → [runbook.md](operations/runbook.md) → [metrics.md](operations/metrics.md) |
| Контрибьютору — понять, как устроено | [architecture/overview.md](architecture/overview.md) → контракты (`docs/contracts/`) → [adr/0001](adr/0001-python-crawl4ai.md)…[0006](adr/0006-three-tool-string-surface.md) |

## Дерево документации

```
docs/
├── index.md                        # вы здесь: хаб и маршруты
├── getting-started/
│   ├── install.md                  # установка: venv, get-pip, playwright, проверка
│   ├── configure.md                # 19 env-переменных, настройки SearXNG, START_MODE
│   └── integrate.md                # базовый конфиг mcpServers, playbook агента
├── integrations/
│   ├── overview.md                 # харнессы: таблица, матрица инструментов, нативная интеграция, дроп-ин
│   ├── zcode.md                    # mcpServers, субагент bathys-researcher, скиллы
│   ├── claude-code.md              # .mcp.json / claude_desktop_config.json, CLAUDE.md, субагент
│   ├── cursor.md                   # mcp.json, правило .cursor/rules
│   └── generic-mcp.md              # любой stdio-клиент: команда, env, что из коробки
├── operations/
│   ├── runbook.md                  # старт/останов, логи, кэш, аварии, диагностика bathys-doctor
│   └── metrics.md                  # метрики токен-экономии, SLO, методика подсчёта
├── architecture/
│   ├── overview.md                 # компоненты, модули src/bathys, инварианты
│   ├── pipeline.md                 # 5 стадий очистки, бюджеты, стратегия кэша
│   └── data-flow.md                # sequence-диаграммы deep_research и read_url
├── product/                        # (чужая зона — смежные документы)
│   ├── charter.md                  # хартия: проблема, миссия, границы, риски
│   ├── features.md                 # реестр функций по версиям
│   ├── roadmap.md                  # роадмап v0.2 → v1.0, критерии приёмки
│   ├── competitive.md              # позиционирование против Tavily/Firecrawl
│   ├── mind-initiative.md          # инициатива: лёгкий семантический слой (re-ranker)
│   └── ocr-initiative.md           # инициатива: OCR-чтение PDF, сканов и скриншотов
├── contracts/                      # пишутся параллельно с кодом; ссылаться по путям
│   ├── mcp-tools.md                # сигнатуры четырёх инструментов и параметры
│   ├── output-format.md            # контракт футеров и форматов ответов
│   ├── module-contracts.md         # внутренние инварианты модулей src/bathys
│   └── config.md                   # полная таблица 19 env-переменных
├── adr/                            # принятые решения, нумерация NNNN-slug
│   ├── 0001-python-crawl4ai.md     # Python + Crawl4AI как ядро извлечения
│   ├── 0002-pin-mcp-sdk-v1.md      # пин mcp SDK на v1
│   ├── 0003-self-managed-searxng.md  # self-managed SearXNG: external → docker → native
│   ├── 0004-bm25-distillation.md   # BM25-дистилляция под запрос
│   ├── 0005-cache-raw-before-distill.md  # кэш сырца до дистилляции
│   └── 0006-three-tool-string-surface.md # ровно три инструмента, строковые ответы
└── meta/
    ├── style-guide.md              # правила языка, диаграмм, ссылок, «definition of done»
    └── glossary.md                 # словарь терминов: сонар, нырёк, дистиллят, футер…
```

## Репозиторий вне docs/

```
├── tests/                    # 72 юнит-теста без сети (unittest, ~0.07 c): python -m unittest discover -s tests
├── scripts/
│   ├── smoke.py              # живой прогон конвейера: поиск → нырок → дистиллят
│   ├── stdio_check.py        # проверка MCP-диалога по stdio
│   ├── batch_check.py        # live-замер пакета read_urls
│   ├── acceptance_v02.py     # приёмка v0.2: доля непустых выдач
│   └── metrics_report.py     # агрегатор metrics.jsonl в дашборд metrics.md §2
├── .github/workflows/ci.yml  # CI: matrix 3.10–3.12 + wheel-sanity
├── Dockerfile                # all-in-one: bathys + нативный SearXNG + chromium
└── CHANGELOG.md              # история выпусков v0.1 → v0.5
```

## Куда смотреть по задаче

| Задача | Документ |
|---|---|
| Установить сервер и проверить конвейер | [install.md](getting-started/install.md) |
| Переназначить порт, TTL, режим бэкенда | [configure.md](getting-started/configure.md) |
| Подключить харнесс (zcode, Claude, Cursor, другой) | [integrations/overview.md](integrations/overview.md) |
| Поставить субагента bathys-researcher и скиллы | [zcode.md](integrations/zcode.md), [claude-code.md](integrations/claude-code.md) |
| Базовый блок mcpServers и примеры диалогов | [integrate.md](getting-started/integrate.md) |
| Поднятый бэкенд не отвечает, чистить кэш | [runbook.md](operations/runbook.md) |
| Проверить стек одним запуском (`bathys-doctor`) | [runbook.md](operations/runbook.md) |
| Сверить цифру экономии | [metrics.md](operations/metrics.md) |
| Понять, почему ответ такой короткий | [pipeline.md](architecture/pipeline.md) |
| Добавить инструмент или модуль | [overview.md](architecture/overview.md), [style-guide.md](meta/style-guide.md) |
| Вспомнить термин | [glossary.md](meta/glossary.md) |
