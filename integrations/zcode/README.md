# Bathys × zcode — комплект установки

zcode покрывается стандартным `bathys install` (автодетект
`~/.zcode/cli/config.json` → `mcp.servers`). Этот комплект — для ручной
установки всех.agent-активов разом и для случаев, когда ставят из клона.

## Установка

```bash
bathys install                    # конфиг MCP (авто; бэкап создаётся сам)
cp agents/bathys-researcher.md ~/.zcode/agents/          # субагент
cp -r agents/skills/* ~/.zcode/skills/ 2>/dev/null || true # скиллы (если каталог скиллов используется)
```

## Что ставится

| Артефакт | Куда | Зачем |
|---|---|---|
| MCP-сервер `bathys` | `~/.zcode/cli/config.json` → `mcp.servers` | 4 инструмента + 3 промпта + annotations (видны харнессу на рукопожатии) |
| Субагент `bathys-researcher` | `~/.zcode/agents/` | профиль глубокого ресёрча; делегируй ему исследования целиком |
| Скиллы `bathys-deep-dive`, `bathys-source-audit` | каталог скиллов харнесса | процедуры глубокого исследования и аудита источников |
| Дроп-ин (опционально) | `~/.zcode/AGENTS.md` или проектный `AGENTS.md` | если instructions MCP не показываются — блок из `agents/HARNESS-DROPIN.md` |

## Проверка

```bash
bathys-doctor          # конфиг + бэкенд + кэш + браузерный стек
bathys install --dry-run   # конфиг виден и актуален
```

После установки перезапустите zcode; сервер поднимется при первом вызове
вместе с бэкендом (external → docker → native).