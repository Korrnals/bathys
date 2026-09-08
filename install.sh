#!/usr/bin/env bash
# Bathys — one-line installer.
#
#   curl -fsSL https://raw.githubusercontent.com/Korrnals/bathys/main/install.sh | bash
#
# What it does (idempotent, safe to re-run):
#   1. finds Python >= 3.10 (python3/python/3.12/3.11/3.10);
#   2. installs the `bathys` package from PyPI into a PRIVATE venv at
#      ~/.local/share/bathys/venv (deterministic, no PEP-668 surprises,
#      no sudo, nothing outside $HOME; --user is deliberately not used —
#      it is fragile across containers/managed environments);
#   3. wires the venv bin into PATH permanently (.profile/.bashrc);
#   4. runs `bathys setup`: browser engine for JS pages -> harness
#      auto-integration (zcode, Claude, Cursor, VS Code family, Gemini CLI,
#      Windsurf, Zed, opencode, goose, Hermes) -> researcher subagent;
#   5. runs `bathys-doctor` for a final health check.
#
# Exit code is the doctor's. Manual alternative (the same result, no script):
#   pip install bathys && bathys setup

set -euo pipefail

BOLD="$(tput bold 2>/dev/null || echo '')"
DIM="$(tput dim 2>/dev/null || echo '')"
RESET="$(tput sgr0 2>/dev/null || echo '')"
say()  { printf "%s\n" "${BOLD}[bathys]${RESET} $*"; }
note() { printf "%s\n" "${DIM}[bathys]${RESET} $*"; }
die()  { printf "%s\n" "${BOLD}[bathys]${RESET} ERROR: $*" >&2; exit 1; }

VENV_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/bathys/venv"

# Pin a specific version when needed (rollback channel):
#   BATHYS_INSTALL_VERSION=0.7.0 bash install.sh
BATHYS_VERSION_SPEC="${BATHYS_INSTALL_VERSION:-bathys}"

# ------------------------------------------------------------------ python --
find_python() {
    for cand in python3.12 python3.11 python3.10 python3 python; do
        if command -v "$cand" >/dev/null 2>&1; then
            if "$cand" - <<'PY' >/dev/null 2>&1
import sys
raise SystemExit(0 if (3, 10) <= sys.version_info[:2] <= (3, 14) else 1)
PY
            then
                echo "$cand"
                return 0
            fi
        fi
    done
    return 1
}

PY="$(find_python)" || die "Python 3.10–3.14 не найден. Установите его и повторите — либо вручную: pip install bathys && bathys setup"
note "python: $($PY --version 2>&1)"

# ------------------------------------------------------------------- venv --
if [ -x "$VENV_DIR/bin/bathys" ] && "$VENV_DIR/bin/bathys" --help >/dev/null 2>&1; then
    note "venv уже живой: $VENV_DIR (обновляю пакет)"
    UPGRADE=yes
else
    note "создаю приватный venv: $VENV_DIR"
    rm -rf "$VENV_DIR"
    "$PY" -m venv "$VENV_DIR" 2>/dev/null \
        || "$PY" -m venv --without-pip "$VENV_DIR" \
        || die "не удалось создать venv в $VENV_DIR"
    UPGRADE=no
fi

# bootstrap pip when the venv lacks it (minimal images without ensurepip)
if [ ! -x "$VENV_DIR/bin/pip" ]; then
    note "pip отсутствует в venv — бутстрап через get-pip.py…"
    TMP_GP="$(mktemp)"; trap 'rm -f "$TMP_GP"' EXIT
    curl -fsSL https://bootstrap.pypa.io/get-pip.py -o "$TMP_GP" \
        || die "не удалось скачать get-pip.py (сеть?)"
    "$VENV_DIR/bin/python" "$TMP_GP" -q >/dev/null 2>&1 \
        || die "get-pip.py не смог подняться в venv"
fi

# ---------------------------------------------------------------- install --
if [ "$UPGRADE" = yes ]; then
    "$VENV_DIR/bin/pip" install --quiet --upgrade "$BATHYS_VERSION_SPEC" >/dev/null 2>&1 \
        || die "pip install --upgrade \"$BATHYS_VERSION_SPEC\" не удался (сеть/PyPI?)"
else
    "$VENV_DIR/bin/pip" install --quiet "$BATHYS_VERSION_SPEC" >/dev/null 2>&1 \
        || die "pip install \"$BATHYS_VERSION_SPEC\" не удался (сеть/PyPI?)"
fi
[ -x "$VENV_DIR/bin/bathys" ] || die "bathys не появился в venv — проверьте вывод pip вручную"

# ------------------------------------------------------------------- PATH --
PATH_LINE='export PATH="$HOME/.local/share/bathys/venv/bin:$PATH"'
if ! case ":$PATH:" in *":$VENV_DIR/bin:"*) false;; esac; then
    export PATH="$VENV_DIR/bin:$PATH"
fi
for rc in "$HOME/.profile" "$HOME/.bashrc"; do
    if [ -f "$rc" ] && ! grep -qF 'bathys/venv/bin' "$rc"; then
        printf '\n# bathys (one-line installer)\n%s\n' "$PATH_LINE" >> "$rc"
        note "PATH дополнен в $rc — перезапустите шелл или: source $rc"
    fi
done

say "установлен: $VENV_DIR/bin/bathys"

# ------------------------------------------------------------------ setup --
say "полная настройка (браузер → харнессы → субагент)…"
"$VENV_DIR/bin/bathys" setup

# ----------------------------------------------------------------- doctor --
say "финальная диагностика:"
exec "$VENV_DIR/bin/bathys" doctor