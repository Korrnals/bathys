"""Single-system bootstrap for the SearXNG backend.

Order of attempts on a cold start:
  1. already-running instance at BATHYS_SEARXNG_URL (someone else manages it);
  2. container engine (docker compose / podman compose / docker-compose /
     podman-compose) with the bundled compose.yaml — the standard way on a host;
  3. native mode: a private searxng checkout + venv under BATHYS_SEARXNG_HOME,
     cloned and installed on first run, started as a child subprocess — for
     environments without any container engine (plain VPS, CI, containers
     without docker-in-docker).

The mode can be forced with BATHYS_START_MODE=docker|native.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import sys
from pathlib import Path

import httpx

from .config import Config

_REPO_URL = "https://github.com/searxng/searxng"
_ENGINES = (
    ("docker", "compose"),
    ("podman", "compose"),
    ("docker-compose",),
    ("podman-compose",),
)
_GET_PIP_URL = "https://bootstrap.pypa.io/get-pip.py"

_running_native: "_Native | None" = None


async def _ping(cfg: Config, http: httpx.AsyncClient, timeout: float = 2.0) -> str | None:
    try:
        r = await http.get(cfg.searxng_url + "/search", params={"q": "ping", "format": "json"}, timeout=timeout)
        if r.status_code == 200:
            return None
        return f"http {r.status_code}"
    except (httpx.HTTPError, ValueError) as e:
        return e.__class__.__name__


async def _wait_ready(cfg: Config, http: httpx.AsyncClient, timeout: float) -> str | None:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while True:
        err = await _ping(cfg, http)
        if err is None:
            return None
        if loop.time() > deadline:
            return err
        await asyncio.sleep(1.5)


async def _run(argv: list[str], cwd: Path | None = None, timeout: float = 120.0) -> tuple[int, str]:
    proc = await asyncio.create_subprocess_exec(
        *argv, cwd=cwd,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
    )
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        return 124, "timeout"
    return proc.returncode or 0, out.decode(errors="replace")[-800:]


def _settings_file() -> Path:
    return Path(__file__).resolve().parent / "searxng-settings.yml"


def render_settings(base_text: str, env: dict[str, str] | None = None) -> str:
    """F-203: optional API-engines injected from env keys — one key enables an
    engine in the generated searxng settings. Native mode writes the rendered
    text; keep the mapping deliberately tiny and explicit."""
    env = env if env is not None else dict(os.environ)
    blocks: list[str] = []
    engine_lines: list[str] = []
    brave = env.get("BATHYS_ENGINE_BRAVE_KEY", "").strip()
    if brave:
        # braveapi (official API module) — NOT `brave` (the scraper ignores api_key)
        engine_lines += [
            "  - name: braveapi", "    engine: braveapi", "    shortcut: brapi",
            f"    api_key: {brave}", "    inactive: false",
        ]
    exa = env.get("BATHYS_ENGINE_EXA_KEY", "").strip()
    if exa:
        engine_lines += [
            "  - name: exaapi", "    engine: exaapi", "    shortcut: exa",
            f"    api_key: {exa}", "    inactive: false",
        ]
    yandex = env.get("BATHYS_ENGINE_YANDEX_KEY", "").strip()
    if yandex:
        folder = env.get("BATHYS_ENGINE_YANDEX_FOLDER", "").strip()
        engine_lines += [
            "  - name: yandex_api", "    engine: yandex_api", "    shortcut: ydxapi",
            f"    api_key: {yandex}",
        ]
        if folder:
            engine_lines.append(f"    yandex_folder_id: {folder}")
        engine_lines.append("    inactive: false")
    if engine_lines:
        blocks.append("\nengines:\n" + "\n".join(engine_lines) + "\n")
    text = base_text
    if blocks:
        text = text.rstrip("\n") + "\n" + "".join(blocks)
    return text


def _compose_file() -> Path:
    return Path(__file__).resolve().parent / "compose.yaml"


async def _start_containers(cfg: Config) -> None:
    if cfg.start_cmd:
        argv = cfg.start_cmd.split()
    else:
        engine = None
        for cmd in _ENGINES:
            if all(shutil.which(c) for c in cmd):
                engine = cmd
                break
        if engine is None:
            raise FileNotFoundError("no container engine (docker/podman) found")
        argv = [*engine, "-f", str(_compose_file()), "up", "-d"]
    rc, out = await _run(argv, timeout=600)
    if rc != 0:
        raise RuntimeError(out.strip() or f"exit {rc}")


class _Native:
    """searxng checkout + venv under one home dir, run as a child process."""

    def __init__(self, home: Path, ref: str) -> None:
        self.home = home
        self.repo = home / "repo"
        self.venv = home / "venv"
        self._ref = ref
        self.proc: asyncio.subprocess.Process | None = None
        self.log_path = home / "searxng.log"

    async def prepare(self) -> None:
        self.home.mkdir(parents=True, exist_ok=True)
        if not (self.repo / "searx" / "webapp.py").is_file():
            rc, out = await _run(
                ["git", "clone", "--depth", "1", _REPO_URL, str(self.repo)],
                timeout=300,
            )
            if rc != 0:
                raise RuntimeError(f"git clone searxng failed: {out.strip()}")
        await self._ensure_ref()
        await self._ensure_venv()
        marker = self.venv / ".searxng-reqs-done"
        if not marker.is_file():
            rc, out = await _run(
                [str(self.venv / "bin" / "pip"), "install", "-q", "-r", str(self.repo / "requirements.txt")],
                timeout=900,
            )
            if rc != 0:
                raise RuntimeError(f"searxng requirements install failed: {out.strip()}")
            marker.write_text("ok")

    async def _ensure_ref(self) -> None:
        """Pin the checkout to the configured ref (SHA by default); upstream has
        no tags, so a full-SHA pin replaces the old `master` clone (F-302).
        Skips the network when the marker already matches the ref."""
        ref = self._ref
        marker = self.repo / ".bathys-ref"
        if marker.is_file() and marker.read_text().strip() == ref:
            return
        rc, out = await _run(["git", "-C", str(self.repo), "fetch", "-q", "origin"], timeout=300)
        if rc != 0:
            raise RuntimeError(f"git fetch searxng failed: {out.strip()}")
        rc, out = await _run(["git", "-C", str(self.repo), "checkout", "-q", ref], timeout=120)
        if rc != 0:
            raise RuntimeError(f"git checkout {ref} failed: {out.strip()}")
        marker.write_text(ref)

    async def _ensure_venv(self) -> None:
        """`python -m venv` needs ensurepip, which minimal debian images lack;
        fall back to venv --without-pip + get-pip.py bootstrap."""
        pip = self.venv / "bin" / "pip"
        if pip.is_file():
            return
        rc, out = await _run([sys.executable, "-m", "venv", str(self.venv)], timeout=120)
        if rc != 0 or not pip.is_file():
            shutil.rmtree(self.venv, ignore_errors=True)
            rc, out = await _run([sys.executable, "-m", "venv", "--without-pip", str(self.venv)], timeout=120)
            if rc != 0:
                raise RuntimeError(f"venv creation failed: {out.strip()}")
            getter = self.home / "get-pip.py"
            rc, out = await _run(["curl", "-sS", _GET_PIP_URL, "-o", str(getter)], timeout=120)
            if rc != 0 or not getter.is_file():
                raise RuntimeError(f"cannot download get-pip.py: {out.strip()}")
            rc, out = await _run([str(self.venv / "bin" / "python"), str(getter), "-q"], timeout=300)
            if rc != 0 or not pip.is_file():
                raise RuntimeError(f"pip bootstrap failed: {out.strip()}")
        await _run([str(pip), "install", "-q", "-U", "pip"], timeout=300)

    async def start(self, cfg: Config) -> None:
        await self.prepare()
        settings = self.home / "settings.yml"
        settings.write_text(render_settings(_settings_file().read_text()))
        log = open(self.log_path, "ab")
        env = dict(os.environ, SEARXNG_SETTINGS_PATH=str(settings))
        self.proc = await asyncio.create_subprocess_exec(
            str(self.venv / "bin" / "python"), "-m", "searx.webapp",
            cwd=str(self.repo), env=env,
            stdout=log, stderr=asyncio.subprocess.STDOUT,
        )

    async def stop(self) -> None:
        if self.proc is not None and self.proc.returncode is None:
            try:
                self.proc.terminate()
                await asyncio.wait_for(self.proc.wait(), timeout=5)
            except asyncio.TimeoutError:
                self.proc.kill()
            except Exception:
                pass
        self.proc = None


def _native(cfg: Config) -> _Native:
    global _running_native
    if _running_native is None:
        _running_native = _Native(cfg.searxng_home, cfg.searxng_ref)
    return _running_native


async def stop_native() -> None:
    global _running_native
    if _running_native is not None:
        await _running_native.stop()
        _running_native = None


async def ensure_running(cfg: Config, http: httpx.AsyncClient) -> str:
    """Make sure /search answers at cfg.searxng_url; start a backend if allowed.
    Returns the mode that served the request: external | docker | native."""
    err = await _ping(cfg, http)
    if err is None:
        return "external"
    if not cfg.auto_start:
        raise RuntimeError(
            f"searxng at {cfg.searxng_url} is not answering ({err}); "
            "BATHYS_AUTO_START=0 disables the built-in backend"
        )
    attempts: list[str] = []
    mode = cfg.start_mode
    if mode in ("auto", "docker"):
        try:
            await _start_containers(cfg)
        except Exception as e:
            attempts.append(f"docker: {e}")
        else:
            err2 = await _wait_ready(cfg, http, cfg.startup_timeout)
            if err2 is None:
                return "docker"
            attempts.append(f"docker: not ready ({err2})")
    if mode in ("auto", "native"):
        nat = _native(cfg)
        try:
            if nat.proc is None or nat.proc.returncode is not None:
                await nat.start(cfg)
        except Exception as e:
            attempts.append(f"native: {e}")
        else:
            err3 = await _wait_ready(cfg, http, cfg.startup_timeout)
            if err3 is None:
                return "native"
            attempts.append(f"native: not ready ({err3}; log: {nat.log_path})")
    raise RuntimeError("could not start searxng backend — " + "; ".join(attempts))
