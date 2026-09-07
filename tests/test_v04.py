"""Tests for the v0.4 feature slice:

  F-203  services.render_settings — env-keyed engine injection
  F-303  core robots.txt gate — allow/deny, fail-open, parser cache,
         RobotsRefusal caching and the graceful read() answer
  F-304  core metrics journal — schema, off-switch, OSError swallow
  F-204  core search(as_json=True) — pure-JSON payload
  F-305  doctor._cache_stats — alive/expired counting on a real sqlite cache
         scripts/metrics_report.p95 — percentile formula

No network: http clients and crawler.fetch are AsyncMocked.
"""

import asyncio
import dataclasses
import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import httpx

from bathys.cache import Cache
from bathys.config import Config
from bathys.core import Engine, ReadResult, RobotsRefusal
from bathys.crawler import Page
from bathys.doctor import _cache_stats
from bathys.services import render_settings


def _make_engine(**overrides):
    tmp = tempfile.TemporaryDirectory()
    env = {k: v for k, v in os.environ.items() if not k.startswith("BATHYS_")}
    env["BATHYS_DATA_DIR"] = tmp.name
    env["BATHYS_CACHE_DIR"] = tmp.name
    patcher = mock.patch.dict(os.environ, env, clear=True)
    patcher.start()
    cfg = Config.load()
    if overrides:  # Config is a frozen dataclass
        cfg = dataclasses.replace(cfg, **overrides)
    eng = Engine(cfg)
    return tmp, patcher, eng


# ------------------------------------------------------------------ F-203 ---

_BASE = "use_default_proxy: false\nsearch:\n  formats:\n    - html\n    - json\n"


class RenderSettingsTest(unittest.TestCase):
    def test_no_keys_returns_base_text_unchanged(self):
        out = render_settings(_BASE, env={})
        self.assertEqual(out, _BASE)
        self.assertNotIn("engines:", out)

    def test_brave_key_appends_engine_block(self):
        out = render_settings(_BASE, env={"BATHYS_ENGINE_BRAVE_KEY": "key123"})
        for needle in ("engines:", "name: brave", "engine: brave",
                       "api_key: key123", "inactive: false"):
            self.assertIn(needle, out)
        # base lines survive intact, before the injected section
        self.assertLess(out.index("use_default_proxy: false"), out.index("engines:"))
        self.assertLess(out.index("    - json"), out.index("engines:"))
        self.assertTrue(out.startswith("use_default_proxy: false\n"))

    def test_blank_key_is_ignored(self):
        for blank in ("", "   ", "\t "):
            out = render_settings(_BASE, env={"BATHYS_ENGINE_BRAVE_KEY": blank})
            self.assertEqual(out, _BASE)
            self.assertNotIn("engines:", out)


# ------------------------------------------------------------------ F-303 ---

_ROBOTS = "User-agent: *\nDisallow: /private\n"


def _resp(status=200, text=_ROBOTS):
    return mock.Mock(status_code=status, text=text)


class RobotsAllowedTest(unittest.TestCase):
    def _engine(self, **overrides):
        self.tmp, self.patcher, self.eng = _make_engine(**overrides)
        self.addCleanup(self.tmp.cleanup)
        self.addCleanup(self.patcher.stop)

    def test_respect_robots_off_always_allows_without_http(self):
        self._engine(respect_robots=False)
        self.eng.http = mock.Mock(get=mock.AsyncMock())
        for url in ("https://a.example/private/x", "https://b.example/anything"):
            self.assertTrue(asyncio.run(self.eng._robots_allowed(url)))
        self.eng.http.get.assert_not_called()

    def test_no_http_client_fails_open(self):
        self._engine(respect_robots=True)
        self.assertIsNone(self.eng.http)
        self.assertTrue(asyncio.run(self.eng._robots_allowed("https://a.example/private/x")))

    def test_disallow_and_allow_paths(self):
        self._engine(respect_robots=True)
        self.eng.http = mock.Mock(get=mock.AsyncMock(return_value=_resp()))
        self.assertFalse(asyncio.run(self.eng._robots_allowed("https://r.example/private/x")))
        self.assertTrue(asyncio.run(self.eng._robots_allowed("https://r.example/open")))

    def test_404_and_network_error_fail_open(self):
        self._engine(respect_robots=True)
        self.eng.http = mock.Mock(get=mock.AsyncMock(return_value=_resp(status=404)))
        self.assertTrue(asyncio.run(self.eng._robots_allowed("https://four.example/private/x")))

        self.eng.http = mock.Mock(get=mock.AsyncMock(side_effect=httpx.ConnectError("no route")))
        self.assertTrue(asyncio.run(self.eng._robots_allowed("https://dead.example/private/x")))

    def test_parser_is_cached_per_host(self):
        self._engine(respect_robots=True)
        get = mock.AsyncMock(return_value=_resp())
        self.eng.http = mock.Mock(get=get)
        for _ in range(2):
            self.assertFalse(asyncio.run(self.eng._robots_allowed("https://r.example/private/x")))
        self.assertTrue(asyncio.run(self.eng._robots_allowed("https://r.example/open")))
        self.assertEqual(get.call_count, 1)  # same host fetched once


class RobotsRefusalTest(unittest.TestCase):
    def setUp(self):
        self.tmp, self.patcher, self.eng = _make_engine(respect_robots=True)
        self.addCleanup(self.tmp.cleanup)
        self.addCleanup(self.patcher.stop)
        self.url = "https://deny.example/page"

    def test_refusal_is_raised_and_cached_as_error(self):
        fetch = mock.AsyncMock()
        with mock.patch.object(self.eng, "_robots_allowed", new=mock.AsyncMock(return_value=False)), \
                mock.patch.object(self.eng.crawler, "fetch", new=fetch):
            with self.assertRaises(RobotsRefusal) as cm:
                asyncio.run(self.eng._read(self.url, query=None, max_chars=1000))
            err = str(cm.exception)
            self.assertEqual(err, f"robots.txt disallows this path: {self.url}")
            fetch.assert_not_called()

            got, stored = self.eng.cache.get(Cache.key("page", self.url))
            self.assertTrue(got)
            self.assertEqual(stored.get("error"), err)

            # replay from the error cache: plain RuntimeError, same text
            with self.assertRaises(RuntimeError) as cm2:
                asyncio.run(self.eng._read(self.url, query=None, max_chars=1000))
            self.assertEqual(str(cm2.exception), err)

    def test_read_returns_graceful_answer_on_refusal(self):
        refusal = RobotsRefusal("robots.txt disallows this path: X")
        with mock.patch.object(self.eng, "_read", new=mock.AsyncMock(side_effect=refusal)):
            out = asyncio.run(self.eng.read("X"))
        self.assertIn("(not fetched — robots.txt disallows this path: X)", out)
        self.assertIn("robots-refused", out)


# ------------------------------------------------------------------ F-304 ---

class MetricsJournalTest(unittest.TestCase):
    def test_event_schema_and_hash_length(self):
        tmp, patcher, eng = _make_engine(metrics=True)
        with tmp, patcher:
            eng._log_metrics("web_search", cache="MISS", chars_in=100, chars_out=20,
                             secs=1.0, q="x", url="http://y")
            path = eng.cfg.data_dir / "metrics.jsonl"
            self.assertTrue(path.is_file())
            event = json.loads(path.read_text(encoding="utf-8").splitlines()[-1])
            for field in ("ts", "tool", "cache", "chars_in", "chars_out", "secs",
                          "ok", "error_class", "url_hash", "q_hash"):
                self.assertIn(field, event)
            self.assertEqual(event["tool"], "web_search")
            self.assertEqual(event["cache"], "MISS")
            self.assertEqual(event["ok"], True)
            self.assertEqual(len(event["url_hash"]), 12)
            self.assertEqual(len(event["q_hash"]), 12)

    def test_disabled_metrics_write_nothing(self):
        tmp, patcher, eng = _make_engine(metrics=False)
        with tmp, patcher:
            eng._log_metrics("web_search", cache="MISS", q="x")
            self.assertFalse((eng.cfg.data_dir / "metrics.jsonl").exists())

    def test_oserror_on_write_is_swallowed(self):
        tmp, patcher, eng = _make_engine(metrics=True)
        with tmp, patcher:
            with mock.patch("builtins.open", side_effect=OSError("disk full")):
                eng._log_metrics("web_search", cache="MISS", q="x")  # must not raise


# ------------------------------------------------------------------ F-204 ---

class SearchJsonTest(unittest.TestCase):
    def setUp(self):
        self.tmp, self.patcher, self.eng = _make_engine()
        self.addCleanup(self.tmp.cleanup)
        self.addCleanup(self.patcher.stop)
        stored = {
            "hits": [
                {"title": "H1", "url": "https://a.example/1", "snippet": "s1",
                 "engines": ["bing"], "score": 1.0, "published": ""},
                {"title": "H2", "url": "https://b.example/2", "snippet": "s2",
                 "engines": ["google", "brave"], "score": 0.5, "published": "2026-01-02"},
            ],
            "answers": ["The answer"],
            "suggestions": [],
            "raw_chars": 1234,
        }
        self.eng._search_outcome = mock.AsyncMock(return_value=(stored, False))

    def test_payload_is_pure_json_with_contract_keys(self):
        out = asyncio.run(self.eng.search("q", as_json=True))
        payload = json.loads(out)  # whole string must be one JSON document
        self.assertEqual(payload["query"], "q")
        self.assertEqual(payload["count"], 2)
        self.assertEqual(payload["answer"], "The answer")
        self.assertEqual(len(payload["hits"]), 2)
        h1, h2 = payload["hits"]
        for key in ("title", "url", "snippet", "engines", "published"):
            self.assertIn(key, h1)
        self.assertIsNone(h1["published"])  # "" -> None in JSON mode
        self.assertEqual(h2["published"], "2026-01-02")
        self.assertEqual(h1["engines"], ["bing"])


# ------------------------------------------------------------------ F-305 ---

class CacheStatsTest(unittest.TestCase):
    def test_missing_db_is_zero_zero(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(_cache_stats(Path(d) / "cache.db"), (0, 0))

    def test_counts_total_and_alive_rows(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "cache.db"
            cache = Cache(path)
            cache.set("k1", {"v": 1}, ttl=3600)
            cache.set("k2", {"v": 2}, ttl=3600)
            cache.set("k3", {"v": 3}, ttl=-5)  # already expired
            self.assertEqual(_cache_stats(path), (3, 2))


def _load_metrics_report():
    path = Path(__file__).resolve().parents[1] / "scripts" / "metrics_report.py"
    spec = importlib.util.spec_from_file_location("bathys_metrics_report_test", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class P95Test(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = _load_metrics_report()

    def test_uniform_hundred(self):
        value = self.mod.p95([float(i) for i in range(1, 101)])
        self.assertGreaterEqual(value, 93)
        self.assertLessEqual(value, 96)

    def test_edges(self):
        self.assertEqual(self.mod.p95([]), 0.0)
        self.assertEqual(self.mod.p95([7.0]), 7.0)


if __name__ == "__main__":
    unittest.main()
