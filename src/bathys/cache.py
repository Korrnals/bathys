"""Tiny SQLite TTL cache.

Pages are cached raw (clean markdown); distillation happens after a cache hit,
so re-reading the same URL with a different query never re-downloads anything.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import time
from pathlib import Path


def key(*parts: object) -> str:
    return hashlib.sha256("\x1f".join(str(p) for p in parts).encode()).hexdigest()


class Cache:
    key = staticmethod(key)

    def __init__(self, path: Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._db = sqlite3.connect(path, check_same_thread=False)
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS cache (k TEXT PRIMARY KEY, exp REAL NOT NULL, v TEXT NOT NULL)"
        )
        self._db.execute("CREATE INDEX IF NOT EXISTS cache_exp ON cache (exp)")

    def get(self, k: str) -> tuple[bool, object]:
        with self._lock:
            row = self._db.execute("SELECT exp, v FROM cache WHERE k = ?", (k,)).fetchone()
        if row is None or row[0] <= time.time():
            return False, None
        return True, json.loads(row[1])

    def set(self, k: str, value: object, ttl: int) -> None:
        with self._lock, self._db:
            self._db.execute(
                "INSERT INTO cache (k, exp, v) VALUES (?, ?, ?) "
                "ON CONFLICT(k) DO UPDATE SET exp = excluded.exp, v = excluded.v",
                (k, time.time() + ttl, json.dumps(value, ensure_ascii=False)),
            )
