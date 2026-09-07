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
