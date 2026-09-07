"""Tests for bathys.batch.read_many (read_urls core): mixed success/failure
sections, shared character budget, utm-dedup, the 10-url limit, MIX metrics.

No network, no browser: engine._read is replaced with a per-URL fake that
dispatches on the URL itself (dive scheduling order must not matter).
"""

import asyncio
import os
import tempfile
import unittest
from unittest import mock

from bathys.batch import read_many
from bathys.config import Config
from bathys.core import Engine, ReadResult
from bathys.crawler import Page


def _mk_page(url, text, title="t"):
    return Page(url=url, status=200, title=title, text=text, raw_chars=len(text))


def _make_engine():
    tmp = tempfile.TemporaryDirectory()
    env = {k: v for k, v in os.environ.items() if not k.startswith("BATHYS_")}
    env["BATHYS_DATA_DIR"] = tmp.name
    env["BATHYS_CACHE_DIR"] = tmp.name
    patcher = mock.patch.dict(os.environ, env, clear=True)
    patcher.start()
    eng = Engine(Config.load())
    eng.http = None  # never started: no client, no network
    return tmp, patcher, eng


class ReadManyTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp, self.patcher, self.eng = _make_engine()
        self.addCleanup(self.tmp.cleanup)
        self.addCleanup(self.patcher.stop)

    def _run(self, *args, **kwargs):
        return asyncio.run(read_many(self.eng, *args, **kwargs))


class MixedResultsTest(ReadManyTestCase):
    def test_footer_counts_and_failed_section(self):
        urls = ["https://one.example/a", "https://two.example/b", "https://three.example/c"]

        async def fake_read(u, *, query, max_chars, refresh=False):
            if "two" in u:
                raise RuntimeError("X: y")
            text = "A" * 4000 if "one" in u else "C" * 4000
            hit = "one" in u
            return ReadResult(page=_mk_page(u, text, title="t"), distilled="", cache_hit=hit)

        self.eng._read = fake_read
        out = self._run(urls, query=None, total_chars=600)

        self.assertIn("batch 3 urls · 2/3 ok", out)
        self.assertIn("(not fetched — X: y)", out)
        self.assertIn("https://two.example/b", out)
        self.assertIn("8000 ch fetched", out)

    def test_successful_sections_share_the_budget(self):
        urls = ["https://one.example/a", "https://two.example/b", "https://three.example/c"]

        async def fake_read(u, *, query, max_chars, refresh=False):
            if "two" in u:
                raise RuntimeError("X: y")
            text = "A" * 4000 if "one" in u else "C" * 4000
            return ReadResult(page=_mk_page(u, text), distilled="", cache_hit=False)

        self.eng._read = fake_read
        out = self._run(urls, query=None, total_chars=600)

        # 'A'/'C' appear only inside the re-distilled page bodies (titles/urls
        # are lowercase), so their counts are exact distilled-section sizes.
        self.assertGreater(out.count("A"), 0)
        self.assertGreater(out.count("C"), 0)
        self.assertLessEqual(out.count("A") + out.count("C"), 600)

    def test_metrics_logged_with_cache_mix(self):
        urls = ["https://one.example/a", "https://two.example/b", "https://three.example/c"]

        async def fake_read(u, *, query, max_chars, refresh=False):
            if "two" in u:
                raise RuntimeError("X: y")
            hit = "one" in u
            return ReadResult(page=_mk_page(u, "A" * 400), distilled="", cache_hit=hit)

        self.eng._read = fake_read
        with mock.patch.object(self.eng, "_log_metrics") as m:
            self._run(urls, query=None, total_chars=600)
        m.assert_called_once()
        self.assertEqual(m.call_args.args, ("read_urls",))  # tool, passed positionally
        self.assertEqual(m.call_args.kwargs.get("cache"), "MIX")
        self.assertIs(m.call_args.kwargs.get("ok"), True)


class DedupTest(ReadManyTestCase):
    def test_utm_source_duplicate_processed_once(self):
        urls = ["https://dup.example/page", "https://dup.example/page?utm_source=nl"]
        calls = []

        async def fake_read(u, *, query, max_chars, refresh=False):
            calls.append(u)
            return ReadResult(page=_mk_page(u, "E" * 50), distilled="", cache_hit=False)

        self.eng._read = fake_read
        out = self._run(urls, query=None, total_chars=300)

        self.assertIn("batch 1 urls · 1/1 ok", out)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0], "https://dup.example/page")  # first spelling kept


class OverLimitTest(ReadManyTestCase):
    def test_more_than_ten_urls_skips_the_rest(self):
        urls = [f"https://skip.example/{i}" for i in range(12)]
        calls = []

        async def fake_read(u, *, query, max_chars, refresh=False):
            calls.append(u)
            return ReadResult(page=_mk_page(u, "D" * 40), distilled="", cache_hit=False)

        self.eng._read = fake_read
        out = self._run(urls, query=None, total_chars=300)

        self.assertIn("Skipped (over the 10-url limit): https://skip.example/10, "
                      "https://skip.example/11", out)
        self.assertIn("batch 10 urls · 10/10 ok", out)
        self.assertEqual(len(calls), 10)


if __name__ == "__main__":
    unittest.main()
