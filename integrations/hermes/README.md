# Bathys × Hermes Agent

[Hermes Agent](https://github.com/NousResearch/hermes-agent) читает MCP из
`~/.hermes/config.yaml` под ключом `mcp_servers` (snake_case; формат
подтверждён [доками Hermes](https://hermes-agent.nousresearch.com/docs/user-guide/features/mcp),
проверено 2026-09-08). Стандартный `bathys install` уже пишет этот файл, если
он существует. Эта интеграция добавляет остальное:

- **создаёт** `~/.hermes/config.yaml`, если его ещё нет (Hermes после первого
  запуска имеет), — по канону его доков;
- ставит **субагента** `bathys-researcher` в `~/.hermes/agents/`.

## Установка

```bash
python integrations/hermes/install.py            # что изменится — вначале план
python integrations/hermes/install.py --apply   # записать (бэкап создастся сам)
```

Скрипту нужен только Python ≥3.10 (stdlib); он не импортирует bathys и
работает с любой установки (`pip install bathys` или из клона). Идемпотентен:
повторный запуск ничего не меняет.

## Что именно пишется

`~/.hermes/config.yaml`:

```yaml
mcp_servers:
  bathys:
    command: "<путь к bathys>"
    args: []
    env: {}
```

`~/.hermes/agents/bathys-researcher.md` — профиль субагента глубокого ресёрча
(копия `agents/bathys-researcher.md` из корня репозитория).