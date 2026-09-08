# Установка Bathys

Bathys ставится из PyPI без sudo — всё живёт в `$HOME`, ничего не пишет в систему и не портит окружение. Требуется Python ≥ 3.10 (инсталлер сам находит 3.10–3.14) и `git` (нужен нативному режиму SearXNG).

Один и тот же пакет — четыре пути установки:

| Путь | Команда | Кому |
|---|---|---|
| 1. Однострочник | `curl -fsSL …/install.sh \| bash` | обычная машина: всё само |
| 2. pip | `pip install bathys` | кто держит своё окружение |
| 3. npm | `npm i -g bathys-mcp` | Node-first |
| 4. Исходники | `pip install -e .` из клона | контрибьютор |

Все пути заканчиваются одинаково: команда `bathys` в `PATH`, прописанные харнессы и проверенный `bathys-doctor`.

## Путь 1. Однострочник (рекомендуется)

```bash
curl -fsSL https://raw.githubusercontent.com/Korrnals/bathys/main/install.sh | bash
```

Скрипт идемпотентен — повторный запуск обновляет пакет, не ломая существующую установку. Без sudo, ничего вне `$HOME`.

Что делает по шагам:

1. находит Python ≥ 3.10 (`python3.12` → `python3.11` → `python3.10` → `python3`);
2. ставит пакет `bathys` с PyPI в **приватный venv** `~/.local/share/bathys/venv` — изолированно от системного Python, без сюрпризов PEP 668;
3. дописывает PATH-строку `export PATH="$HOME/.local/share/bathys/venv/bin:$PATH"` в `~/.profile` и `~/.bashrc` (по одной строке с комментарием `# bathys (one-line installer)`; повторно не дублируется);
4. запускает `bathys setup` (см. ниже);
5. запускает `bathys-doctor` — финальную диагностику; её exit-код становится exit-кодом скрипта.

Минимальный контейнерный образ без `ensurepip` — не проблема: если в venv нет pip, скрипт бутстрапит его через `get-pip.py` сам. Тот же фолбэк встроен и в автостарт нативного SearXNG (`src/bathys/services.py`).

Пин или откат версии — одной env-переменной (это переменная установщика, не сервера):

```bash
BATHYS_INSTALL_VERSION=0.7.0 bash install.sh   # поставить конкретную версию
```

## Путь 2. pip

```bash
pip install bathys
bathys setup
bathys doctor
```

`bathys setup` — полная пост-установка одним вызовом (идемпотентна, повтор — no-op):

1. ставит headless-Chromium через playwright — он нужен **только для JS-страниц**; HTTP-движок работает и без него (двухъярусное извлечение — [configure.md](configure.md), `BATHYS_BROWSER`);
2. автоподключает все найденные харнессы (`bathys install` с `--with-agent`);
3. копирует субагента `bathys-researcher` туда, где есть каталоги харнессов;
4. печатает следующие шаги (`bathys doctor`, `bathys install --list`).

## Путь 3. npm

```bash
npm i -g bathys-mcp
bathys-mcp setup    # делегирует в bathys setup
```

`bathys-mcp` — тонкая обёртка: postinstall ставит Python-пакет (`pip install bathys`), CLI-команды `install`/`doctor`/`print-config` делегируются в `bathys`, а без аргументов `bathys-mcp` запускает stdio-сервер. Нет Python ≥ 3.10 — обёртка честно скажет и подскажет команды.

## Путь 4. Исходники (ручной контроль)

```bash
git clone https://github.com/Korrnals/bathys.git
cd bathys            # далее — ~/bathys, каталог вашего клона
python3 -m venv .venv
.venv/bin/pip install -e .
.venv/bin/bathys setup
```

Ветка для минимального образа без `ensurepip` — `python3 -m venv --without-pip .venv` и бутстрап `curl -sS https://bootstrap.pypa.io/get-pip.py | .venv/bin/python`; в `setup` этот фолбэк тоже зашит.

Юнит-тесты без сети: `.venv/bin/python -m unittest discover -s tests` (102 теста, ~0.07 c). Живые прогоны конвейера — `scripts/smoke.py` (search → read → research без MCP) и `scripts/stdio_check.py` (полный MCP-диалог).

## Бэкенд SearXNG

Ничего поднимать руками не нужно: сервер и бэкенд стартуют автоматически при первом вызове инструмента. Первый запуск в нативном режиме долог (клон + зависимости SearXNG — минуты), повторные мгновенны. Проверить стек заранее: `bathys doctor --start-backend` — поднимет бэкенд и тут же проверит его.

## Подключение к харнессу

`bathys setup` и `bathys install` без аргументов автодетектят все найденные харнессы и идемпотентно прописывают сервер `bathys` в их конфиги: перед записью создаётся бэкап с таймстампом, повторный запуск не трогает актуальное. Точечно:

```bash
bathys install hermes zcode   # только названные; отсутствующие конфиги создаются
bathys install --list         # карта всех таргетов с путями и статусом
bathys install --print-config # готовые блоки для ручной вставки
bathys install --dry-run      # сначала посмотреть план без записи
```

Таргеты (14): zcode, claude-code, claude-desktop, cursor, cline, roo-code, kilo-code, gemini-cli, windsurf, zed, opencode, goose, hermes + pi. У Pi нет MCP-конфига — для него работает дроп-ин [`agents/HARNESS-DROPIN.md`](../../agents/HARNESS-DROPIN.md) в `AGENTS.md` проекта. Кастомные интеграции (hermes-установщик, pi, zcode-комплект) — в [`integrations/`](../../integrations/README.md).

После установки перезапустите харнесс — сервер поднимется при первом вызове вместе с бэкендом. Ручное подключение всегда доступно: `--print-config` печатает блоки под схему каждого клиента; какие файлы за что отвечают — в [integrate.md](integrate.md) и гайдах [docs/integrations/](../integrations/overview.md).

## Снятие Bathys

```bash
bathys uninstall               # снять записи bathys со всех харнессов
bathys uninstall hermes zcode  # точечно
bathys uninstall --purge       # плюс venv/кэш/данные
```

Семантика:

- `uninstall` удаляет **только записи `bathys`** из конфигов — чужие серверы и остальной документ не трогаются; перед записью создаётся бэкап (`config.json.bathys-backup-<таймстамп>`);
- кэш и данные при снятии не тронуты;
- `--purge` дополнительно удаляет venv инсталлера (`~/.local/share/bathys/venv`), кэш (`~/.cache/bathys`) и данные (`~/.local/share/bathys`);
- PATH-строку в `~/.profile` / `~/.bashrc` (одна строка с `bathys/venv/bin`) удалите руками — скрипт не редактирует rc-файлы в обе стороны;
- субагент `bathys-researcher`, если ставился, тоже копией: `rm ~/.zcode/agents/bathys-researcher.md` и т.п.

Восстановление после ручной правки конфига — из свежайшего `*.bathys-backup-*` рядом с ним.

## Базовые директории

По умолчанию Bathys следует платформенным конвенциям (все переопределяются env — [configure.md](configure.md)):

| Назначение | Путь по умолчанию |
|---|---|
| venv инсталлера (однострочник) | `~/.local/share/bathys/venv` |
| Данные (нативный SearXNG, журнал метрик) | `~/.local/share/bathys` |
| Кэш (SQLite) | `~/.cache/bathys` |

Дальше: конфигурация — [configure.md](configure.md), подключение клиента — [integrate.md](integrate.md), эксплуатация — [runbook.md](../operations/runbook.md).