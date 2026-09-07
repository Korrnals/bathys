"""Unit tests for bathys.core Engine internals: honest counts, empty-body
footer, F-101 retry rotation, F-301 polite pacing, F-102 healthy fallback.

No network, no processes: searx.search / _backend / _polite_pace / asyncio.sleep
are mocked; the Engine gets a temp-dir cache and http=None.
"""

import asyncio
import os
import tempfile
import time
import unittest
from unittest import mock

from bathys import searx
from bathys.cache import Cache
from bathys.config import Config
from bathys.core import Engine, _ch


def _outcome(hits=None, unresponsive=None):
    return searx.SearchOutcome(
        query="q",
        hits=hits or [],
        answers=[],
        suggestions=[],
        seconds=0.01,
        raw_chars=42,
        unresponsive=unresponsive or [],
    )


def _hit():
    return searx.SearchHit(
        title="Example", url="https://example.com/page", snippet="snip",
        engines=["bing"], score=1.5,
    )


class EngineTestCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        env = {k: v for k, v in os.environ.items() if not k.startswith("BATHYS_")}
        env["BATHYS_DATA_DIR"] = tmp.name
        env["BATHYS_CACHE_DIR"] = tmp.name
        patcher = mock.patch.dict(os.environ, env, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.cfg = Config.load()
        self.eng = Engine(self.cfg)
        self.assertIsNone(self.eng.http)  # never started: no client, no network

    def _cache_key(self):
        return Cache.key("search", "q", 5, None, None, None, None)


class HonestCountTest(unittest.TestCase):
    def test_ch_is_plain_digits_without_suffix(self):
        for n in (0, 7, 999, 123456):
            self.assertEqual(_ch(n), str(n))  # e.g. 2048 -> "2048", never "2k"


class EmptyBodyTest(unittest.TestCase):
    def test_plain_prefix_without_notes(self):
        stored = {"retries": 0, "unresponsive": []}
        self.assertEqual(Engine._empty_body("python mcp", stored), "No results for: python mcp")

    def test_plain_body_has_no_suffixes(self):
        stored = {"retries": 0, "unresponsive": []}
        body = Engine._empty_body("q", stored)
        self.assertNotIn("tried", body)
        self.assertNotIn("unresponsive", body)

    def test_retries_note_counts_engine_sets(self):
        stored = {"retries": 2, "unresponsive": []}
        self.assertIn("tried 3 engine sets", Engine._empty_body("q", stored))

    def test_unresponsive_note_lists_engines(self):
        stored = {"retries": 0, "unresponsive": ["a", "b"]}
        self.assertIn("unresponsive: a, b", Engine._empty_body("q", stored))


class SearchRetriesTest(EngineTestCase):
    def test_rotates_engine_sets_until_hit(self):
        # First two attempts come back empty with a dead engine; the third
        # (rotated set) delivers one hit while google is still unresponsive.
        outcomes = [
            _outcome(unresponsive=["google:captcha"]),
            _outcome(unresponsive=["google:captcha"]),
            _outcome(hits=[_hit()], unresponsive=["google:captcha"]),
        ]
        search_stub = mock.AsyncMock(side_effect=outcomes)
        sleep_stub = mock.AsyncMock()
        with mock.patch.object(Engine, "_backend", new=mock.AsyncMock(return_value=None)), \
                mock.patch.object(Engine, "_polite_pace", new=mock.AsyncMock()), \
                mock.patch("bathys.core.searx.search", new=search_stub), \
                mock.patch("bathys.core.asyncio.sleep", new=sleep_stub):
            stored, cached = asyncio.run(self.eng._search_outcome(
                "q", max_results=5, category=None, engines=None,
                language=None, time_range=None, refresh=True,
            ))
        # Three attempts: the original set plus two rotated sets.
        self.assertEqual(search_stub.await_count, 3)
        self.assertFalse(cached)
        self.assertEqual(stored["retries"], 2)
        self.assertEqual(stored["unresponsive"], ["google:captcha"])
        self.assertEqual(len(stored["hits"]), 1)
        self.assertEqual(stored["hits"][0]["url"], "https://example.com/page")
        # Rotation always happens with a growing positive pause (F-101).
        self.assertEqual(sleep_stub.await_count, 2)
        for call in sleep_stub.await_args_list:
            self.assertGreater(call.args[0], 0)
        # The non-empty outcome is cached for later reads.
        got, cached_value = self.eng.cache.get(self._cache_key())
        self.assertTrue(got)
        self.assertEqual(len(cached_value["hits"]), 1)
        self.assertEqual(cached_value["retries"], 2)
        # F-102 side effect: google reached a 3-streak, bing delivered the hit.
        self.assertEqual(self.eng.bad_engines(), ["google"])

    def test_exhausts_default_budget_and_caches_empty_outcome(self):
        self.assertEqual(self.cfg.search_retries, 2)  # default under test

        async def always_empty(*args, **kwargs):
            return _outcome(unresponsive=["google:captcha"])

        search_stub = mock.AsyncMock(side_effect=always_empty)
        sleep_stub = mock.AsyncMock()
        with mock.patch.object(Engine, "_backend", new=mock.AsyncMock(return_value=None)), \
                mock.patch.object(Engine, "_polite_pace", new=mock.AsyncMock()), \
                mock.patch("bathys.core.searx.search", new=search_stub), \
                mock.patch("bathys.core.asyncio.sleep", new=sleep_stub):
            stored, cached = asyncio.run(self.eng._search_outcome(
                "q", max_results=5, category=None, engines=None,
                language=None, time_range=None, refresh=True,
            ))
        # Default attempt + 2 retries = 3 calls, then the budget is spent.
        self.assertEqual(search_stub.await_count, 3)
        self.assertFalse(cached)
        self.assertEqual(stored["hits"], [])
        self.assertEqual(stored["retries"], 2)
        # Empty outcomes are cached too (with a short TTL).
        got, cached_value = self.eng.cache.get(self._cache_key())
        self.assertTrue(got)
        self.assertEqual(cached_value["hits"], [])


class PolitePaceTest(EngineTestCase):
    def test_sleeps_when_min_interval_not_elapsed(self):
        self.assertEqual(self.cfg.search_min_interval, 1.0)
        sleep_stub = mock.AsyncMock()
        self.eng._search_ts = time.monotonic()  # a search just happened
        with mock.patch("bathys.core.asyncio.sleep", new=sleep_stub):
            asyncio.run(self.eng._polite_pace())
        sleep_stub.assert_awaited_once()
        waited = sleep_stub.await_args.args[0]
        self.assertGreater(waited, 0)
        self.assertLessEqual(waited, 1.0)

    def test_no_sleep_when_last_search_long_ago(self):
        sleep_stub = mock.AsyncMock()
        stale = time.monotonic() - 60
        self.eng._search_ts = stale
        with mock.patch("bathys.core.asyncio.sleep", new=sleep_stub):
            asyncio.run(self.eng._polite_pace())
        sleep_stub.assert_not_awaited()
        self.assertGreater(self.eng._search_ts, stale)  # timestamp refreshed


class HealthyFallbackTest(EngineTestCase):
    def test_drops_engines_with_failure_streak(self):
        self.eng._engine_fails = {"google": 3}
        self.assertEqual(self.eng._healthy_fallback("google,bing"), "bing")

    def test_keeps_set_when_no_engine_is_bad_enough(self):
        self.eng._engine_fails = {"google": 1, "bing": 2}
        self.assertEqual(self.eng._healthy_fallback("google,bing"), "google,bing")

    def test_keeps_set_when_all_engines_are_bad(self):
        self.eng._engine_fails = {"google": 3, "bing": 3}
        self.assertEqual(self.eng._healthy_fallback("google,bing"), "google,bing")


if __name__ == "__main__":
    unittest.main()
