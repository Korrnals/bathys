#!/usr/bin/env python3
"""Bathys integration installer for Hermes Agent.

Creates ~/.hermes/config.yaml (mcp_servers.bathys) when absent and installs
the researcher subagent into ~/.hermes/agents/. Idempotent; backs up any
existing config before writing. Stdlib-only, works from any Bathys install.

Usage:
  python integrations/hermes/install.py            # plan only
  python integrations/hermes/install.py --apply   # write changes
"""

from __future__ import annotations

import argparse
import datetime
import re
import shutil
import sys
from pathlib import Path

HOME = Path.home()
CONFIG = HOME / ".hermes" / "config.yaml"
AGENTS = HOME / ".hermes" / "agents"


def _bathys_command() -> str:
    launcher = Path(sys.executable).parent / "bathys"
    if launcher.is_file():
        return str(launcher)
    here = Path(__file__).resolve()
    for base in (here.parents[2], here.parents[3]):
        cand = base / ".venv" / "bin" / "bathys"
        if cand.is_file():
            return str(cand)
    return "bathys"


ENTRY = """mcp_servers:
  bathys:
    command: "{cmd}"
    args: []
    env: {{}}
"""


def _entry_block(cmd: str) -> str:
    return ENTRY.format(cmd=cmd)


def _has_bathys(text: str) -> bool:
    return re.search(r"^  bathys:", text, re.M) is not None


def _set_bathys(text: str, cmd: str) -> str:
    block = _entry_block(cmd).rstrip("\n").splitlines()
    lines = text.splitlines()
    # replace existing entry if present
    for i, ln in enumerate(lines):
        if re.match(r"^  bathys:\s*$", ln):
            j = i + 1
            while j < len(lines) and (not lines[j].strip() or lines[j].startswith("    ")):
                j += 1
            lines[i:j] = block[1:]
            return "\n".join(lines) + "\n"
    # root mcp_servers present? insert at its end
    for i, ln in enumerate(lines):
        if re.match(r"^mcp_servers:\s*$", ln):
            j = i + 1
            while j < len(lines) and (not lines[j].strip() or lines[j].startswith("  ")):
                j += 1
            lines[j:j] = block[1:]
            return "\n".join(lines) + "\n"
    # append a fresh root
    sep = [""] if lines else []
    return "\n".join(lines + sep + block) + "\n"


def _agent_src() -> Path | None:
    here = Path(__file__).resolve()
    for base in (here.parents[2], here.parents[3]):
        cand = base / "agents" / "bathys-researcher.md"
        if cand.is_file():
            return cand
    # site-packages layout (pip install): bathys/agents/ inside the package
    for parent in here.parents:
        cand = parent / "bathys" / "agents" / "bathys-researcher.md"
        if cand.is_file():
            return cand
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true", help="write changes (default: plan)")
    args = ap.parse_args()

    cmd = _bathys_command()
    changes: list[str] = []

    if CONFIG.is_file():
        text = CONFIG.read_text(encoding="utf-8")
        if _has_bathys(text) and f'command: "{cmd}"' in text:
            print(f"[=] {CONFIG}: bathys уже актуален")
        else:
            changes.append(f"обновить {CONFIG} (бэкап создастся)")
    else:
        changes.append(f"создать {CONFIG} (mcp_servers.bathys)")

    src = _agent_src()
    dst = AGENTS / "bathys-researcher.md" if src else None
    if src and dst:
        if dst.is_file() and dst.read_text(encoding="utf-8") == src.read_text(encoding="utf-8"):
            print("[=] субагент уже актуален")
        else:
            changes.append(f"субагент {src.name} -> {dst}")

    if not changes:
        print("Готово: изменений нет.")
        return 0
    print("План изменений:")
    for c in changes:
        print("  -", c)
    if not args.apply:
        print("Запустите с --apply, чтобы записать.")
        return 0

    if not args.apply:
        return 0
    if CONFIG.is_file():
        stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        shutil.copy2(CONFIG, CONFIG.with_name(f"{CONFIG.name}.bathys-backup-{stamp}"))
        CONFIG.write_text(_set_bathys(CONFIG.read_text(encoding="utf-8"), cmd), encoding="utf-8")
    else:
        CONFIG.parent.mkdir(parents=True, exist_ok=True)
        CONFIG.write_text(_entry_block(cmd), encoding="utf-8")
    print(f"[OK] конфиг: {CONFIG}")
    if src and dst:
        if dst.is_dir():
            shutil.rmtree(dst)  # recover from the pre-0.6.2 dir-instead-of-file bug
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        print(f"[OK] субагент: {dst}")
    print("Перезапустите Hermes, чтобы он подхватил mcp_servers.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())