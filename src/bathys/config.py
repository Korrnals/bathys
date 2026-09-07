"""Runtime configuration, read once from the environment with sane defaults."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _env_bool(name: str, default: bool) -> bool:
    v = os.environ.get(name)
    if v is None:
        return default
    return v.strip().lower() not in {"", "0", "false", "no", "off"}


# Pinned SearXNG source commit (F-302, supply-chain). The upstream repo has no
# git tags; this full SHA is reviewable on github.com/searxng/searxng and matches
# the docker image tag pinned in compose.yaml (2026.9.5-c7f3080aa). Re-pin
# deliberately (quarterly), never silently track master.
SEARXNG_REF = "c7f3080aac5de13b619c4a5ab36590a2c5165e1c"


@dataclass(frozen=True)
class Config:
    searxng_url: str
    auto_start: bool
    start_mode: str  # "auto" | "docker" | "native"
    start_cmd: str | None
    searxng_ref: str
    data_dir: Path
    cache_dir: Path
    searxng_home: Path
    search_ttl: int
    page_ttl: int
    search_timeout: float
    crawl_timeout: float
    startup_timeout: float
    search_min_interval: float
    search_retries: int
    dive_concurrency: int
    respect_robots: bool
    metrics: bool

    @classmethod
    def load(cls) -> "Config":
        data_dir = Path(
            os.environ.get("BATHYS_DATA_DIR", str(Path.home() / ".local" / "share" / "bathys"))
        ).expanduser()
        return cls(
            searxng_url=os.environ.get("BATHYS_SEARXNG_URL", "http://127.0.0.1:8888").rstrip("/"),
            auto_start=_env_bool("BATHYS_AUTO_START", True),
            start_mode=(os.environ.get("BATHYS_START_MODE") or "auto").strip().lower(),
            start_cmd=os.environ.get("BATHYS_START_CMD") or None,
            searxng_ref=(os.environ.get("BATHYS_SEARXNG_REF") or SEARXNG_REF).strip(),
            data_dir=data_dir,
            cache_dir=Path(os.environ.get("BATHYS_CACHE_DIR", str(Path.home() / ".cache" / "bathys"))).expanduser(),
            searxng_home=Path(
                os.environ.get("BATHYS_SEARXNG_HOME", str(data_dir / "searxng-home"))
            ).expanduser(),
            search_ttl=int(os.environ.get("BATHYS_SEARCH_TTL", "3600")),
            page_ttl=int(os.environ.get("BATHYS_PAGE_TTL", "86400")),
            search_timeout=float(os.environ.get("BATHYS_SEARCH_TIMEOUT", "15")),
            crawl_timeout=float(os.environ.get("BATHYS_CRAWL_TIMEOUT", "40")),
            startup_timeout=float(os.environ.get("BATHYS_STARTUP_TIMEOUT", "90")),
            search_min_interval=float(os.environ.get("BATHYS_SEARCH_MIN_INTERVAL", "1.0")),
            search_retries=max(0, min(3, int(os.environ.get("BATHYS_SEARCH_RETRIES", "2")))),
            dive_concurrency=max(1, min(8, int(os.environ.get("BATHYS_DIVE_CONCURRENCY", "4")))),
            respect_robots=_env_bool("BATHYS_ROBOTS", True),
            metrics=_env_bool("BATHYS_METRICS", True),
        )
