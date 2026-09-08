# Установка Bathys

Bathys ставится в изолированный venv внутри каталога проекта. Требуется Python ≥ 3.10 (в примерах — `python3.12`) и `git` (нужен нативному режиму SearXNG).

## Шаг 1. Создать venv

Выберите ветку по своей среде.

**Обычная машина** (есть `ensurepip`):

```bash
git clone https://github.com/Korrnals/bathys.git
cd bathys            # далее — ~/bathys, каталог вашего клона
python3.12 -m venv .venv
```

**Контейнер/минимальный образ без `ensurepip`** — venv создаётся без pip, pip накатывается скриптом bootstrap:

```bash
cd ~/bathys
python3.12 -m venv --without-pip .venv
curl -sS https://bootstrap.pypa.io/get-pip.py | .venv/bin/python
```

Тот же фолбэк встроен в автостарт нативного SearXNG — если `python3-venv` урезан (минимальный образ без ensurepip), venv бэкенда поднимется через `get-pip.py` сам (см. `src/bathys/services.py`).

## Шаг 2. Поставить пакет

```bash
.venv/bin/pip install -e .
```

Устанавливает зависимости `mcp`, `httpx`, `crawl4ai` и создаёт точку входа `.venv/bin/bathys`.

## Шаг 3. Браузер для извлечения

```bash
.venv/bin/python -m playwright install chromium
```

На голой системе без библиотек GUI Chromium не стартует — системные зависимости ставятся отдельно (см. «Chromium не стартует» в [runbook.md](../operations/runbook.md)).

## Шаг 4. Проверка

```bash
.venv/bin/python scripts/smoke.py        # конвейер: search → read → research без MCP
.venv/bin/python scripts/stdio_check.py  # полный MCP-диалог по stdio
```

`smoke.py` показывает живые футеры `web_search`, `read_url` и `deep_research` — по ним видно сжатие «было → стало». Первый запуск долгий: нативный режим клонирует SearXNG и ставит его зависимости в `BATHYS_SEARXNG_HOME`; повторные — мгновенные.

Если оба скрипта отработали — сервер готов. Дальше: конфигурация в [configure.md](configure.md), подключение клиента в [integrate.md](integrate.md).

## Шаг 5. Подключение к харнессу: автоматически

Вместо ручной правки конфигов харнессов — одна команда:

```bash
.venv/bin/bathys install              # автодетект + прописывание
.venv/bin/bathys install --dry-run    # сначала посмотреть план без записи
.venv/bin/bathys install --with-agent # плюс субагент-ресёрчер
```

Что делает команда:

- ищет харнессы по стандартным путям: zcode (`~/.zcode/cli/config.json`), Claude Code (`~/.claude.json`), Claude Desktop, Cursor (`~/.cursor/mcp.json`), VS Code-семейство — Cline / Roo Code / Kilo Code (globalStorage `mcp_settings.json`), Gemini CLI (`~/.gemini/settings.json`), Windsurf (`~/.codeium/windsurf/mcp_config.json`), Zed (`~/.config/zed/settings.json`, `context_servers`), opencode (`~/.config/opencode/opencode.json`), goose (`~/.config/goose/config.yaml`, секция `extensions`), Hermes (`~/.hermes/config.yaml`, секция `mcp_servers`);
- идемпотентно прописывает сервер `bathys` в найденный конфиг: перед записью создаёт бэкап с таймстампом, повторный запуск не трогает актуальное;
- `--searxng-home <путь>` дополнительно пишет `BATHYS_SEARXNG_HOME` в env сервера;
- `--with-agent` копирует субагента `bathys-researcher` в каталог харнесса;
- ничего не находит — печатает подсказку про ручной путь;
- форматы различаются автоматически: JSON-схемы (openai/zcode/vscode/cline/opencode) и YAML-контуры goose/hermes — правки точечные, остальной документ конфига не трогается;
- Pi (badlogic pi-mono) MCP-конфига не имеет — для него работает дроп-ин [`agents/HARNESS-DROPIN.md`](../../agents/HARNESS-DROPIN.md) в `AGENTS.md` проекта.

После установки перезапустите харнесс — сервер поднимется при первом вызове вместе с бэкендом.

### Ручное подключение (всегда доступно)

`bathys install --print-config` печатает готовые блоки для вставки в конфиг каждого клиента; какие файлы за что отвечают — в [integrate.md](integrate.md) и гайдах [docs/integrations/](../integrations/overview.md).

## Базовые директории

По умолчанию Bathys следует платформенным конвенциям (все переопределяются env — [configure.md](configure.md)):

| Назначение | Путь по умолчанию |
|---|---|
| Данные (нативный SearXNG, журнал метрик) | `~/.local/share/bathys` |
| Кэш (SQLite) | `~/.cache/bathys` |
