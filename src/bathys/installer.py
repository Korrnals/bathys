"""`bathys install` — native, idempotent one-command harness integration.

Detects installed harnesses by their standard config paths, registers the
MCP server there, and (optionally) copies the researcher subagent profile.
Base directories follow platform conventions by default (see config.py):
data ~/.local/share/bathys, cache ~/.cache/bathys — overridable by env.

Manual wiring is always available: `bathys install --print-config` emits the
snippet to paste by hand. Every automatic write is preceded by a timestamped
backup and is idempotent — re-running updates in place.

Exit codes: 0 = at least one target updated (or nothing to do), 1 = failure.
"""

from __future__ import annotations

import argparse
import datetime
import json
import re
import shutil
import sys
from pathlib import Path

_HOME = Path.home()
_PKG_DIR = Path(__file__).resolve().parent

# Harness id -> (config path, dotpath to the servers dict, per-entry format).
# format: "zcode" uses {type, command, args, env}; others use {command, env}.
_HARNESS_TARGETS: dict[str, tuple[Path, str, str]] = {
    "zcode": (_HOME / ".zcode" / "cli" / "config.json", "mcp.servers", "zcode"),
    "claude-code": (_HOME / ".claude.json", "mcpServers", "openai"),
    "cursor": (_HOME / ".cursor" / "mcp.json", "mcpServers", "openai"),
    "claude-desktop": (
        _HOME / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json",
        "mcpServers", "openai",
    ),
}


def _bathys_command() -> str:
    """Absolute entry-point path: venv bin if editable, else console script."""
    launcher = Path(sys.executable).parent / "bathys"
    if launcher.is_file():
        return str(launcher)
    return str(_PKG_DIR.parent / ".venv" / "bin" / "bathys") if (
        _PKG_DIR.parent / ".venv" / "bin" / "bathys").is_file() else "bathys"


def _server_entry(fmt: str, searxng_home: str | None) -> dict:
    entry: dict = {}
    if fmt == "zcode":
        entry = {"type": "stdio", "command": _bathys_command(), "args": []}
    else:
        entry = {"command": _bathys_command()}
    env: dict[str, str] = {}
    if searxng_home:
        env["BATHYS_SEARXNG_HOME"] = searxng_home
    if env:
        entry["env"] = env
    return entry


def _get_by_path(obj: object, dotpath: str) -> dict | None:
    cur: object = obj
    for part in dotpath.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur if isinstance(cur, dict) else None


def _ensure_path(obj: dict, dotpath: str) -> dict:
    cur = obj
    for part in dotpath.split("."):
        cur = cur.setdefault(part, {})
    return cur


def _backup(path: Path) -> Path | None:
    if not path.is_file():
        return None
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    bkp = path.with_name(f"{path.name}.bathys-backup-{stamp}")
    shutil.copy2(path, bkp)
    return bkp


def _entry_needs_update(existing: dict, desired: dict) -> bool:
    if not isinstance(existing, dict):
        return True
    for key in ("command", "type"):
        if key in desired and existing.get(key) != desired[key]:
            return True
    old_env = existing.get("env") or {}
    new_env = desired.get("env") or {}
    return any(new_env[k] != old_env.get(k) for k in new_env)


def _agent_src() -> Path | None:
    """Locate agents/bathys-researcher.md: repo root (editable install),
    packaged copy (wheel force-include), or CWD (running from a clone)."""
    name = Path("agents") / "bathys-researcher.md"
    # repo layout: <repo>/src/bathys/installer.py -> agents sits at <repo>/agents;
    # wheel layout: agents is force-included INTO the package -> <pkg>/agents.
    pkg_dir = _PKG_DIR  # .../src/bathys or site-packages/bathys
    for base in (pkg_dir.parent.parent, pkg_dir, Path.cwd()):
        cand = base / name
        if cand.is_file():
            return cand
    return None


def install(dry_run: bool, print_config: bool, with_agent: bool,
            searxng_home: str | None) -> int:
    desired_env = {"BATHYS_SEARXNG_HOME": searxng_home} if searxng_home else None
    if print_config:
        print(json.dumps({"mcpServers": {"bathys": _server_entry("openai", searxng_home)}},
                         indent=2, ensure_ascii=False))
        print("# zcode (~/.zcode/cli/config.json → mcp.servers):")
        print(json.dumps({"bathys": _server_entry("zcode", searxng_home)},
                         indent=2, ensure_ascii=False))
        return 0

    targets: list[tuple[str, Path, dict]] = []
    for name, (path, dotpath, fmt) in _HARNESS_TARGETS.items():
        if path.is_file():
            targets.append((name, path, _server_entry(fmt, searxng_home)))
    if not targets:
        print("Харнессы не найдены по стандартным путям. Ручное подключение:")
        print("  bathys install --print-config   # готовые блоки для вставки")
        return 0

    updated, skipped = [], []
    for name, path, desired in targets:
        _, dotpath, _ = _HARNESS_TARGETS[name]
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            print(f"[SKIP] {name}: {path} не читается ({e.__class__.__name__})")
            continue
        servers = _get_by_path(data, dotpath)
        current = (servers or {}).get("bathys")
        if current == desired or not _entry_needs_update(current or {}, desired):
            skipped.append(name)
            continue
        if dry_run:
            updated.append(name)
            continue
        bkp = _backup(path)
        servers = _ensure_path(data, dotpath)
        servers["bathys"] = desired
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n",
                        encoding="utf-8")
        note = f" (бэкап: {bkp.name})" if bkp else ""
        print(f"[OK] {name}: bathys прописан в {path}{note}")
        updated.append(name)

    for name in skipped:
        print(f"[=] {name}: уже актуален, не тронут")

    if with_agent:
        src = _agent_src()
        if src is None:
            print("[i] субагент не найден в установке; скопируйте agents/bathys-researcher.md вручную")
        else:
            dst_dirs = {
                "zcode": _HOME / ".zcode" / "agents",
                "claude-code": Path.cwd() / ".claude" / "agents",
            }
            copied = False
            for harness, dst in dst_dirs.items():
                parent = dst.parent
                wants = harness == "zcode" or parent.exists() or (
                    harness == "claude-code" and (parent.parent / ".claude.json").exists())
                if wants:
                    if dry_run:
                        print(f"[DRY] агент → {dst}")
                        copied = True
                        continue
                    dst.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src, dst / src.name)
                    print(f"[OK] субагент {src.name} → {dst}")
                    copied = True
            if not copied:
                print("[i] подходящих каталогов харнессов не найдено; скопируйте вручную "
                      f"{src}")

    if dry_run:
        print(f"[DRY] изменено бы: {', '.join(updated) or '—'}; актуально: {', '.join(skipped) or '—'}")
    else:
        print(f"Готово: обновлено {len(updated)}, без изменений {len(skipped)}.")
        print("Перезапустите харнесс, чтобы он подхватил конфиг; поведение агента — `bathys install --print-config` и docs/getting-started/cases.md (раздел C).")
    return 1 if not updated and not skipped else 0


def main() -> None:
    ap = argparse.ArgumentParser(
        prog="bathys install",
        description="Нативная интеграция Bathys в харнессы: автодетект конфигов, "
                    "идемпотентная запись с бэкапом, опциональный субагент.")
    ap.add_argument("--dry-run", action="store_true", help="показать план без записи")
    ap.add_argument("--print-config", action="store_true",
                    help="напечатать блоки для ручного подключения и выйти")
    ap.add_argument("--with-agent", action="store_true",
                    help="также скопировать субагента bathys-researcher")
    ap.add_argument("--searxng-home", default=None,
                    help="путь BATHYS_SEARXNG_HOME (по умолчанию не писать)")
    args = ap.parse_args()
    raise SystemExit(install(args.dry_run, args.print_config, args.with_agent,
                             args.searxng_home))


if __name__ == "__main__":
    main()