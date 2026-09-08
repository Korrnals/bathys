"""`bathys install` — native, idempotent one-command harness integration.

Detects installed harnesses by their standard config paths and registers the
MCP server there. Two config contours are supported:

  * JSON — zcode, Claude Code/Desktop, Cursor, VS Code, Gemini CLI,
    Cline/Roo/Kilo Code, Windsurf, opencode (each with its own schema);
  * YAML — goose (`extensions` block) and hermes (`mcp_servers` block),
    handled with a minimal built-in emitter/parser that preserves the rest
    of the document as opaque text (no yaml dependency in core).

Pi (badlogic pi-mono) has no MCP config file: integrations are TypeScript
extensions. Bathys ships the harness drop-in for that path instead
(agents/HARNESS-DROPIN.md -> AGENTS.md), and `install` never writes to Pi.

Base directories follow platform conventions by default (see config.py):
data ~/.local/share/bathys, cache ~/.cache/bathys — overridable by env.

Manual wiring is always available: `bathys install --print-config` emits
snippets for every supported harness. Every automatic write is preceded by a
timestamped backup and is idempotent — re-running updates in place.

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

# VS Code-family globalStorage lives under different roots per platform.
_VSCODE_GLOBAL = {
    "linux": _HOME / ".config" / "Code" / "User" / "globalStorage",
    "darwin": _HOME / "Library" / "Application Support" / "Code" / "User" / "globalStorage",
}


def _vscode_globalstorage() -> Path | None:
    import platform

    return _VSCODE_GLOBAL.get(platform.system().lower())


# name -> (config path, dotpath to servers/root, entry format)
# Formats:
#   zcode    {type:stdio, command, args, env}
#   openai   {command, env}                      (claude-code, claude-desktop,
#                                               cursor, gemini, windsurf)
#   vscode   {command, args, env} under "servers"
#   cline    {command, args, env, disabled:false} under mcpServers
#   opencode {type:local, command:[...], enabled, environment}
#   goose    YAML extensions.<name> {type:stdio, cmd, args, envs, enabled}
#   hermes   YAML mcp_servers.<name> {command, args, env}
_HARNESS_TARGETS: dict[str, tuple[Path, str, str]] = {
    "zcode": (_HOME / ".zcode" / "cli" / "config.json", "mcp.servers", "zcode"),
    "claude-code": (_HOME / ".claude.json", "mcpServers", "openai"),
    "cursor": (_HOME / ".cursor" / "mcp.json", "mcpServers", "openai"),
    "claude-desktop": (
        _HOME / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json",
        "mcpServers", "openai",
    ),
    "gemini-cli": (_HOME / ".gemini" / "settings.json", "mcpServers", "openai"),
    "windsurf": (_HOME / ".codeium" / "windsurf" / "mcp_config.json", "mcpServers", "openai"),
    "zed": (_HOME / ".config" / "zed" / "settings.json", "context_servers", "openai"),
    "opencode": (_HOME / ".config" / "opencode" / "opencode.json", "mcp", "opencode"),
}


def _cline_targets() -> dict[str, tuple[Path, str, str]]:
    """Cline-family: each variant keeps its own file inside VS Code globalStorage."""
    base = _vscode_globalstorage()
    if base is None:
        return {}
    variants = {
        "cline": "saoudrizwan.claude-dev/settings/cline_mcp_settings.json",
        "roo-code": "rooveterinaryinc.roo-cline/settings/roo_mcp_settings.json",
        "kilo-code": "kilocode.kilo-Code/settings/kilo_mcp_settings.json",
    }
    return {
        name: (base / rel, "mcpServers", "cline")
        for name, rel in variants.items()
    }


def _yaml_targets() -> dict[str, tuple[Path, str, str]]:
    return {
        "goose": (_HOME / ".config" / "goose" / "config.yaml", "extensions", "goose"),
        "hermes": (_HOME / ".hermes" / "config.yaml", "mcp_servers", "hermes"),
    }


def _bathys_command() -> str:
    """Absolute entry-point path: venv bin if editable, else console script."""
    launcher = Path(sys.executable).parent / "bathys"
    if launcher.is_file():
        return str(launcher)
    return str(_PKG_DIR.parent / ".venv" / "bin" / "bathys") if (
        _PKG_DIR.parent / ".venv" / "bin" / "bathys").is_file() else "bathys"


def _server_entry(fmt: str, searxng_home: str | None) -> dict:
    cmd = _bathys_command()
    env: dict[str, str] = {}
    if searxng_home:
        env["BATHYS_SEARXNG_HOME"] = searxng_home
    if fmt == "zcode":
        entry = {"type": "stdio", "command": cmd, "args": []}
    elif fmt == "vscode":
        entry = {"type": "stdio", "command": cmd, "args": []}
    elif fmt == "cline":
        entry = {"command": cmd, "args": [], "disabled": False}
    elif fmt == "opencode":
        entry = {"type": "local", "command": [cmd], "enabled": True}
    else:  # openai, and the JSON-shaped part of yaml formats
        entry = {"command": cmd}
    if fmt == "opencode":
        if env:
            entry["environment"] = env
    elif env:
        entry["env"] = env
    return entry


# ---------------------------------------------------------------- YAML ----
# Minimal, dependency-free contour for goose/hermes: read the target block as
# plain text, replace/append our entry, keep everything else byte-identical.
_YAML_BLOCK_HDR = re.compile(r"^([A-Za-z_][\w-]*):\s*$")


def _yaml_set(text: str, root: str, name: str, entry_lines: list[str],
              fmt: str) -> str:
    """Set root.<name> in a flat-roots YAML document (goose/hermes style)."""
    lines = text.splitlines()
    root_start = None
    for i, ln in enumerate(lines):
        m = _YAML_BLOCK_HDR.match(ln)
        if m and m.group(1) == root:
            root_start = i
            break
    indented = ["    " + l for l in entry_lines]  # 4 spaces: inside <name>:
    block = [f"  {name}:"] + indented
    if root_start is None:
        # append a new root at the end of the document, entry named inside
        sep = [""] if text and not text.endswith("\n\n") else []
        new_block = [f"{root}:"] + block
        return text.rstrip("\n") + "\n" + "\n".join(sep + new_block) + "\n"
    # find the end of the root block (next top-level key)
    root_end = len(lines)
    for j in range(root_start + 1, len(lines)):
        if lines[j] and not lines[0].startswith(" ") and _YAML_BLOCK_HDR.match(lines[j]):
            root_end = j
            break
        if lines[j] and not lines[j].startswith((" ", "\t", "-", "#")) and ":" in lines[j]:
            root_end = j
            break
    # existing entry?
    entry_pat = re.compile(rf"^  {re.escape(name)}:\s*(#.*)?$")
    for j in range(root_start + 1, root_end):
        if entry_pat.match(lines[j]):
            # replace from entry line to the next sibling (2-space indent)
            k = j + 1
            while k < root_end and (lines[k].startswith("    ") or not lines[k].strip()):
                k += 1
            lines[j:k] = block
            return "\n".join(lines) + "\n"
    # insert at the end of the root block
    insert_at = root_end
    lines[insert_at:insert_at] = block
    return "\n".join(lines) + "\n"


def _yaml_entry_lines(fmt: str, searxng_home: str | None) -> list[str]:
    cmd = _bathys_command()
    if fmt == "goose":
        lines = ["type: stdio", "name: bathys", "enabled: true",
                 f'cmd: "{cmd}"', "args: []", "envs: {}"]
        if searxng_home:
            lines[-1] = "envs:"
            lines.append(f'  BATHYS_SEARXNG_HOME: "{searxng_home}"')
        return lines
    # hermes
    lines = [f'command: "{cmd}"', "args: []", "env: {}"]
    if searxng_home:
        lines[-1] = "env:"
        lines.append(f'  BATHYS_SEARXNG_HOME: "{searxng_home}"')
    return lines


def _yaml_current_ok(text: str, root: str, name: str, fmt: str,
                    searxng_home: str | None) -> bool:
    """True when root.<name> equals the desired entry block exactly."""
    desired_lines = _yaml_entry_lines(fmt, searxng_home)
    lines = text.splitlines()
    in_root = False
    i = 0
    while i < len(lines):
        ln = lines[i]
        m = _YAML_BLOCK_HDR.match(ln)
        if m and m.group(1) == root:
            in_root = True
        elif m and in_root:
            in_root = False
        if in_root and re.match(rf"^  {re.escape(name)}:\s*(#.*)?$", ln):
            got = []
            j = i + 1
            while j < len(lines) and (not lines[j].strip() or lines[j].startswith("    ")):
                if lines[j].strip():
                    got.append(lines[j].strip())
                j += 1
            return [g.strip() for g in got] == [d.strip() for d in desired_lines]
        i += 1
    return False


# --------------------------------------------------------------- shared ----

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
    for key in ("command", "type", "cmd"):
        if key in desired and existing.get(key) != desired[key]:
            return True
    old_env = existing.get("env") or existing.get("environment") or existing.get("envs") or {}
    new_env = desired.get("env") or desired.get("environment") or desired.get("envs") or {}
    return any(new_env[k] != old_env.get(k) for k in new_env)


def _all_targets() -> dict[str, tuple[Path, str, str]]:
    t = dict(_HARNESS_TARGETS)
    t.update(_cline_targets())
    t.update(_yaml_targets())
    return t


def _agent_src() -> Path | None:
    """Locate agents/bathys-researcher.md: repo root (editable install),
    packaged copy (wheel force-include), or CWD (running from a clone)."""
    name = Path("agents") / "bathys-researcher.md"
    pkg_dir = _PKG_DIR  # .../src/bathys or site-packages/bathys
    for base in (pkg_dir.parent.parent, pkg_dir, Path.cwd()):
        cand = base / name
        if cand.is_file():
            return cand
    return None


def install(dry_run: bool, print_config: bool, with_agent: bool,
            searxng_home: str | None, only: list[str] | None = None, list_targets: bool = False,
            _targets: dict[str, tuple[Path, str, str]] | None = None) -> int:
    """Register Bathys in harness configs.

    only: target harness names for a focused install (`bathys install hermes`);
    when a named target's config file is absent, it is CREATED (the user asked
    for it explicitly). None = auto-detect all installed harnesses.
    _targets exists for tests: a full harness registry to substitute
    (detection paths are machine-specific). Production callers omit it.
    """
    all_targets = dict(_targets) if _targets is not None else _all_targets()
    if list_targets:
        found = [n for n, (path, _, _) in all_targets.items() if path.is_file()]
        print("Bathys умеет подключать (bathys install <имя>):")
        for n, (path, _, _) in all_targets.items():
            mark = "[установлен]" if n in found else "[нет конфига]"
            print(f"  {n:15} {mark}  {path}")
        print("  pi             [дроп-ин]     AGENTS.md (у Pi нет MCP-конфига)")
        return 0
    unknown = [n for n in (only or []) if n not in all_targets and n != "pi"]
    if unknown:
        print(f"Неизвестные таргеты: {', '.join(unknown)}; список — `bathys install --list`")
        return 1
    if print_config:
        print("# Bathys — блоки для ручного подключения\n")
        for name, (path, dotpath, fmt) in _all_targets().items():
            print(f"## {name} — {path}")
            if fmt in ("goose", "hermes"):
                lines = _yaml_entry_lines(fmt, searxng_home)
                print(f"{dotpath}:")
                print("  bathys:")
                print("\n".join("    " + l for l in lines))
            else:
                # nest the snippet under the full dotpath (e.g. mcp.servers)
                snippet: dict = {"bathys": _server_entry(fmt, searxng_home)}
                for part in reversed(dotpath.split(".")):
                    snippet = {part: snippet}
                print(json.dumps(snippet, indent=2, ensure_ascii=False))
            print()
        print("# Pi (badlogic pi-mono) не имеет MCP-конфига: вставьте дроп-ин "
              "agents/HARNESS-DROPIN.md в AGENTS.md проекта.")
        return 0

    json_targets = {n: t for n, t in all_targets.items() if t[2] not in ("goose", "hermes")}
    yaml_targets = {n: t for n, t in all_targets.items() if t[2] in ("goose", "hermes")}

    if only:
        # focused install: the named targets only; missing configs are created
        found_json = {n: json_targets[n] for n in only if n in json_targets}
        found_yaml = {n: yaml_targets[n] for n in only if n in yaml_targets}
        created = [n for n in only
                   if n in all_targets and not all_targets[n][0].is_file()]
        if created:
            print(f"[CREATE] создаю отсутствующие конфиги: {', '.join(created)}")
        if "pi" in only:
            print("[i] pi: MCP-конфига нет; вставьте дроп-ин agents/HARNESS-DROPIN.md "
                  "в AGENTS.md проекта (integrations/pi/assets/bathys-rules.md)")
    else:
        found_json = {n: t for n, t in json_targets.items() if t[0].is_file()}
        found_yaml = {n: t for n, t in yaml_targets.items() if t[0].is_file()}
        found_zed_dir = (_HOME / ".config" / "zed").is_dir()
        if found_zed_dir and "zed" not in found_json:
            # Zed commonly has no settings.json yet — creating it is safe: it is
            # user-editable and Zed merges defaults for missing keys.
            found_json["zed"] = json_targets["zed"]

    if not found_json and not found_yaml:
        print("Харнессы не найдены по стандартным путям. Ручное подключение:")
        print("  bathys install --print-config   # готовые блоки для вставки")
        print("  bathys install --list           # все поддерживаемые таргеты")
        return 0

    updated: list[str] = []
    skipped: list[str] = []

    for name, (path, dotpath, fmt) in found_json.items():
        desired = _server_entry(fmt, searxng_home)
        try:
            if path.is_file():
                data = json.loads(path.read_text(encoding="utf-8"))
            else:
                data = {}  # focused install on a fresh config
        except (json.JSONDecodeError, OSError) as e:
            print(f"[SKIP] {name}: {path} не читается ({e.__class__.__name__})")
            continue
        current = (_get_by_path(data, dotpath) or {}).get("bathys")
        if current == desired or not _entry_needs_update(current or {}, desired):
            skipped.append(name)
            continue
        if dry_run:
            updated.append(name)
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        bkp = _backup(path)
        servers = _ensure_path(data, dotpath)
        servers["bathys"] = desired
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n",
                        encoding="utf-8")
        note = f" (бэкап: {bkp.name})" if bkp else ""
        print(f"[OK] {name}: bathys прописан в {path}{note}")
        updated.append(name)

    for name, (path, dotpath, fmt) in found_yaml.items():
        try:
            text = path.read_text(encoding="utf-8") if path.is_file() else ""
        except OSError as e:
            print(f"[SKIP] {name}: {path} не читается ({e.__class__.__name__})")
            continue
        if _yaml_current_ok(text, dotpath, "bathys", fmt, searxng_home):
            skipped.append(name)
            continue
        if dry_run:
            updated.append(name)
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        bkp = _backup(path)
        new_text = _yaml_set(text, dotpath, "bathys", _yaml_entry_lines(fmt, searxng_home), fmt)
        path.write_text(new_text, encoding="utf-8")
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
                "claude-code": _HOME / ".claude" / "agents",
                "goose": _HOME / ".config" / "goose" / "agents",
                "hermes": _HOME / ".hermes" / "agents",
            }
            copied = False
            for harness, dst in dst_dirs.items():
                if harness in ("zcode",) or dst.parent.exists():
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


def setup(searxng_home: str | None = None, skip_browser: bool = False) -> int:
    """`bathys setup` — full post-install in one command.

    Steps: 1) headless chromium (only needed for JS pages; two-tier extraction
    works HTTP-first without it), 2) harness auto-integration (all detected,
    `--with-agent` semantics), 3) researcher subagent where harness dirs exist,
    4) final doctor summary. Idempotent: re-running is a no-op.
    """
    print("bathys setup — полная установка\n")

    # 1) browser engine for JS pages (optional for the HTTP tier)
    if skip_browser:
        print("[=] браузер: пропущен (--skip-browser)")
    else:
        import shutil as _sh
        import subprocess

        try:
            r = subprocess.run(
                [sys.executable, "-m", "playwright", "install", "chromium"],
                capture_output=True, text=True, timeout=600)
            if r.returncode == 0:
                print("[OK] браузер: headless-chromium готов (нужен только для JS-страниц)")
            else:
                print("[i] браузер: не установлен — HTTP-ярус работает без него; "
                      "для JS-страниц выполните: python -m playwright install chromium")
        except (OSError, subprocess.TimeoutExpired):
            print("[i] браузер: playwright недоступен — HTTP-ярус работает без него")

    # 2) harness integration (auto-detect all)
    print()
    rc = install(dry_run=False, print_config=False, with_agent=True,
                 searxng_home=searxng_home)

    # 3) summary + doctor hint
    print()
    print("Следующие шаги:")
    print("  bathys doctor          # диагностика стека")
    print("  bathys install --list  # точечная установка конкретного харнесса")
    print("Готово. MCP-сервер и бэкенд поднимутся автоматически при первом вызове.")
    return rc


def main() -> None:
    ap = argparse.ArgumentParser(
        prog="bathys install",
        description="Интеграция Bathys в харнессы. Без аргументов — автодетект "
                    "установленных; с именами — точечная установка (отсутствующие "
                    "конфиги создаются). Поддержаны: zcode, claude-code, "
                    "claude-desktop, cursor, cline, roo-code, kilo-code, "
                    "gemini-cli, windsurf, zed, opencode, goose, hermes, pi.")
    ap.add_argument("targets", nargs="*", metavar="HARNESS",
                    help="точечная установка: имена харнессов (см. --list)")
    ap.add_argument("--list", action="store_true",
                    help="показать все поддерживаемые таргеты и выйти")
    ap.add_argument("--dry-run", action="store_true", help="показать план без записи")
    ap.add_argument("--print-config", action="store_true",
                    help="напечатать блоки для ручного подключения и выйти")
    ap.add_argument("--with-agent", action="store_true",
                    help="также скопировать субагента bathys-researcher")
    ap.add_argument("--searxng-home", default=None,
                    help="путь BATHYS_SEARXNG_HOME (по умолчанию не писать)")
    args = ap.parse_args()
    raise SystemExit(install(args.dry_run, args.print_config, args.with_agent,
                             args.searxng_home, only=args.targets or None,
                             list_targets=args.list))


if __name__ == "__main__":
    main()