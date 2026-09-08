<p align="center"><img src="docs/assets/banner.svg" alt="Bathys" width="720"></p>

# Bathys

**Единый локальный поисковый сервис глубокого ресёрча для ИИ-агентов.** Это самостоятельный продукт, а не обёртка над чужими сервисами: Bathys реализует весь конвейер сам — метапоиск с дедупликацией и живучестью к блокировкам, двухъярусное извлечение (HTTP-движок по умолчанию, headless-браузер только для JS-страниц), пятистадийную дистилляцию под запрос с жёсткими бюджетами, TTL-кэш сырца, robots-этику, метрики и диагностику. Метапоиск и извлечение оформлены как сменные внутренние движки (SearXNG, Crawl4AI) — их можно заменить, продукт останется Bathys. Облачных квот нет; LLM внутри нет — синтез остаётся за вызывающим агентом, дистилляция детерминированная (BM25).

Сонар находит координаты, батискаф ныряет за полными текстами, дистиллятор поднимает на палубу только то, что отвечает на вопрос.

![python](https://img.shields.io/badge/python-3.10%2B-blue)
![version](https://img.shields.io/badge/version-0.7.2-9cf)
![mcp](https://img.shields.io/badge/MCP-stdio%20server-6f42c1)
![license](https://img.shields.io/badge/license-MIT-green)

**Навигация:** [⚡ Quick start](#-quick-start) · [🧹 Удаление](#-удаление) · [🔌 Подключение](#-подключение-к-харнессу) · [🧠 Научить агента](#-научить-агента-работать-эффективно) · [🧭 Кейсы](#-ходовые-кейсы) · [🛠 Инструменты](#-инструменты) · [📊 Экономия токенов](#-экономия-токенов) · [📚 Документация](#-документация) · [📍 Статус](#-статус)

## ⚡ Quick start

**Вариант 1 — установочный скрипт** (рекомендуется; Python ≥ 3.10):

```bash
curl -fsSL https://raw.githubusercontent.com/Korrnals/bathys/main/install.sh | bash
```

Скрипт ставит пакет с PyPI в приватный venv (`~/.local/share/bathys/venv`, без sudo), добавляет его в `PATH` и запускает полную настройку. Повторный запуск — безопасное обновление.

**Вариант 2 — pip** (то же самое вручную):

```bash
pip install bathys
bathys setup
```

Что делает `bathys setup`:

| Шаг | Действие |
|---|---|
| 1 | ставит headless-браузер — нужен только для JS-страниц (обычные страницы читает встроенный HTTP-движок) |
| 2 | прописывает MCP-сервер во все найденные харнессы (zcode, Claude, Cursor, VS Code-семейство и другие — всего 14, см. [Подключение](#-подключение-к-харнессу)) |
| 3 | копирует субагента-ресёрчера в каталоги найденных харнессов |
| 4 | печатает итог и подсказки (`bathys doctor` — самодиагностика) |

SearXNG устанавливать отдельно не нужно — бэкенд поднимается автоматически при первом поиске: сначала проверяется внешний инстанс, затем docker/podman, затем нативный режим (клон в `BATHYS_SEARXNG_HOME`).

<details>
<summary><b>Альтернативные пути</b> — npm, исходники, откат версии</summary>

**npm** (Node-first окружения; обёртка ставит Python-пакет сама):

```bash
npm install -g bathys-mcp
bathys-mcp setup
```

**Из исходников** (разработка):

```bash
git clone https://github.com/Korrnals/bathys.git && cd bathys
python3.12 -m venv .venv && .venv/bin/pip install -e .
.venv/bin/bathys setup
```

**Откат на конкретную версию** — переменная установочного скрипта:

```bash
BATHYS_INSTALL_VERSION=0.7.0 bash install.sh
```

Минимальный образ без `ensurepip`: скрипт и `setup` сами бутстрапят pip через `get-pip.py` — подробности в [docs/getting-started/install.md](docs/getting-started/install.md).

</details>

### 🧹 Удаление

```bash
bathys uninstall               # снять Bathys со всех харнессов
bathys uninstall hermes zcode   # точечно, только указанные
bathys uninstall --purge        # + удалить venv, кэш и данные
```

`uninstall` удаляет **только записи `bathys`** из конфигов харнессов (перед изменением создаётся бэкап `*.bathys-backup-*`; чужие серверы и субагенты не затрагиваются). `--purge` дополнительно удаляет каталоги `~/.local/share/bathys` и `~/.cache/bathys`; строку `bathys/venv/bin` из `.profile`/`.bashrc` удалите вручную. Подробности и восстановление из бэкапа — в [runbook](docs/operations/runbook.md).

## 🔌 Подключение к харнессу

**Автоматически — весь стек:** `bathys setup` (см. выше) прописывает сервер во все найденные харнессы.

**Точечно — когда нужно именно здесь:**

```bash
bathys install                # автодетект всех установленных харнессов
bathys install hermes         # только Hermes (отсутствующий конфиг создастся)
bathys install --list         # все поддерживаемые таргеты с путями
bathys install --print-config # готовые блоки для ручной вставки
```

Детектируются zcode, Claude Code, Claude Desktop, Cursor, VS Code-семейство (Cline / Roo Code / Kilo Code), Gemini CLI, Windsurf, Zed, opencode, goose, Hermes; форматы каждого — свои (JSON-схемы и YAML-контуры goose/hermes), запись идемпотентна с бэкапом. Для Pi (badlogic pi-mono), у которого нет MCP-конфига, — дроп-ин в `AGENTS.md`. Кастомные интеграции — в каталоге [integrations/](integrations/).

<details>
<summary><b>Ручное подключение</b> (когда правите конфиги сами)</summary>

Bathys — stdio MCP-сервер: блок `mcpServers` один и тот же везде, от харнесса зависит только файл, в который его кладут. `command` — абсолютный путь к бинарнику (`~` внутри JSON не раскрывается); `BATHYS_SEARXNG_HOME` опциональна. Готовые блоки под каждый клиент: `bathys install --print-config`.

```json
{
  "mcpServers": {
    "bathys": {
      "command": "/path/to/bathys",
      "env": { "BATHYS_SEARXNG_HOME": "/path/to/searxng-home" }
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

</details>

## 🧠 Научить агента работать эффективно

Конфиг — только половина дела. Из коробки харнесс получает **instructions-playbook** (матрицу выбора инструментов), **annotations** и **три стратегии-промпта** — `bathys_deep_research`, `bathys_source_audit`, `bathys_fresh_scan`, — так что выбирает инструменты Bathys уже нативно. Сильнее — профиль: субагент [`agents/bathys-researcher.md`](agents/bathys-researcher.md) с двумя скиллами, которому глубокий ресёрч делегируется целиком; для клиентов, не показывающих MCP instructions, — дроп-ин [`agents/HARNESS-DROPIN.md`](agents/HARNESS-DROPIN.md) в `AGENTS.md` / `CLAUDE.md` / `.cursor/rules`.

Пошаговая инструкция «из коробки → субагент → дроп-ин» и таблица сигналов футеров — в [«Живых кейсах», раздел C](docs/getting-started/cases.md#c-как-научить-харнесс-работать-с-bathys-эффективно).

## 🧭 Ходовые кейсы

**Сравнение технологий.** На вопрос «что выбрать под нагрузку в 2026?» агент делает один `deep_research`, доуточняет запрос терминами из найденного и верифицирует вывод по двум источникам: один вызов вместо цепочки «поиск + N чтений», в контекст попадает 7.5k символов вместо ~35k.

```text
[bathys: 34 raw hits, top 8 considered · dove 3 pages · 35669 ch fetched → 7508 ch returned · 1.3s]
```

**Аудит спорного утверждения.** «Правда ли, что в X упали замеры?» — агент берёт стратегию `bathys_source_audit`: пакетно читает ссылки из обсуждения, ищет опровержения и выносит вердикт по каждому тезису с URL. Битая ссылка стоит одну строку, а не сорванный вызов.

**Свежий срез.** «Что нового в Y за две недели?» — стратегия `bathys_fresh_scan`: поиск с `time_range=week`, пакетное чтение, сводка с датами; протухший `cache HIT` лечится одним `refresh=true`.

Полный разбор всех кейсов — пользовательских, автономных агентов и эксплуатации — с живыми диалогами: **[docs/getting-started/cases.md](docs/getting-started/cases.md)**.

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

- **Двухъярусное извлечение** — обычные страницы читает собственный HTTP-движок (миллисекунды, без браузера), JS-оболочки — headless-Chromium; дальше дистилляция под запрос с жёсткими бюджетами символов.
- **Кэш сырца до дистилляции** — SQLite хранит сырой текст, поэтому перечитать страницу под другим углом можно бесплатно и без сети.
- **Ноль облачных квот** — `deep_research` заменяет цепочку «поиск + N чтений», то есть N+1 списаний квоты, одним локальным вызовом.

Методика и пороги — в [docs/operations/metrics.md](docs/operations/metrics.md).

## 📚 Документация

| Раздел | Что внутри | Кому |
|---|---|---|
| [docs/index.md](docs/index.md) | Хаб: дерево документации и три маршрута чтения | всем — точка входа |
| [getting-started](docs/getting-started/install.md) | [Установка](docs/getting-started/install.md) · [конфигурация (20 env)](docs/getting-started/configure.md) · [подключение](docs/getting-started/integrate.md) · [живые кейсы](docs/getting-started/cases.md) | новичку |
| [integrations](docs/integrations/overview.md) | [Обзор подключения](docs/integrations/overview.md) · [zcode](docs/integrations/zcode.md) · [Claude Code](docs/integrations/claude-code.md) · [Cursor](docs/integrations/cursor.md) · [любой MCP-клиент](docs/integrations/generic-mcp.md) | при подключении харнесса |
| [architecture](docs/architecture/overview.md) | [Компоненты](docs/architecture/overview.md) · [конвейер очистки](docs/architecture/pipeline.md) · [потоки данных](docs/architecture/data-flow.md) | контрибьютору |
| [contracts](docs/contracts/mcp-tools.md) | [Инструменты](docs/contracts/mcp-tools.md) · [форматы вывода](docs/contracts/output-format.md) · [модули](docs/contracts/module-contracts.md) · [конфигурация](docs/contracts/config.md) | интегратору |
| [operations](docs/operations/runbook.md) | [Runbook](docs/operations/runbook.md) · [метрики токен-экономии](docs/operations/metrics.md) | эксплуатация |
| [product](docs/product/charter.md) | [Хартия](docs/product/charter.md) · [функции](docs/product/features.md) · [роадмап](docs/product/roadmap.md) · [конкуренты](docs/product/competitive.md) | владельцу продукта |
| [adr](docs/adr/0001-python-crawl4ai.md) | Шесть принятых архитектурных решений | контрибьютору |
| [meta](docs/meta/style-guide.md) | [Стайлгайд доков](docs/meta/style-guide.md) · [глоссарий](docs/meta/glossary.md) | авторам доков |

Вне `docs/`: [agents/](agents/) — субагент, скиллы, дроп-ин · [integrations/](integrations/) — кастомные интеграции (hermes, pi, zcode) · [install.sh](install.sh) — установочный скрипт · [npm/bathys-mcp/](npm/bathys-mcp/) — NPM-обёртка · [tests/](tests/) — юнит-тесты · [CHANGELOG.md](CHANGELOG.md) — история выпусков.

## 📍 Статус

**0.7.2.** Выпускная история: v0.2 «Качество выдачи» (ретраи, здоровье движков), v0.3 «Паритет с Tavily» (`read_urls`, JSON-режим), v0.4 «Эксплуатация» (robots-этика, метрики, `bathys-doctor`), v0.5 «Identity & Harness» (репозиционирование, промпты, субагент), v0.6 «Native Install» (`bathys install`), v0.7 «Ship & Setup» (двухъярусное извлечение, `bathys setup`, однострочник, uninstall) — итоги в [CHANGELOG.md](CHANGELOG.md).

Репозиторий: `github.com/Korrnals/bathys`. Пакет опубликован: [PyPI `bathys`](https://pypi.org/project/bathys/) (pip install), однострочник установки — выше. До 1.0: публикация npm-обёртки `bathys-mcp` и первый прогон Docker-образа; CI (matrix 3.10–3.12 + shellcheck) уже в репозитории.

## ⚖️ Лицензия

[MIT](LICENSE) — см. поле `license` в `pyproject.toml`.