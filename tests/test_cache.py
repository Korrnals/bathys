"""Unit tests for bathys.cache: SQLite TTL cache in a temporary directory."""

import tempfile
import unittest
from pathlib import Path

from bathys.cache import Cache


class CacheTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.cache = Cache(Path(tmp.name) / "cache.db")

    def test_set_get_roundtrip_various_json_values(self):
        values = [
            {"a": [1, 2, 3], "b": "c"},
            "plain string",
            42,
            [1, "two", None],
            {"nested": {"deep": True}},
        ]
        for i, value in enumerate(values):
            self.cache.set(f"k{i}", value, ttl=60)
        for i, value in enumerate(values):
            got, stored = self.cache.get(f"k{i}")
            self.assertTrue(got)
            self.assertEqual(stored, value)

    def test_get_missing_key_is_miss(self):
        self.assertEqual(self.cache.get("no-such-key"), (False, None))

    def test_expired_entry_is_miss(self):
        self.cache.set("k", "value", ttl=-1)  # already in the past
        self.assertEqual(self.cache.get("k"), (False, None))

    def test_same_key_is_overwritten(self):
        self.cache.set("k", "first", ttl=60)
        self.cache.set("k", "second", ttl=60)
        got, stored = self.cache.get("k")
        self.assertTrue(got)
        self.assertEqual(stored, "second")

    def test_key_deterministic_and_sensitive_to_parts(self):
        self.assertEqual(Cache.key("search", "q", 5, None), Cache.key("search", "q", 5, None))
        self.assertNotEqual(Cache.key("search", "q", 5, None), Cache.key("search", "q", 5, "bing"))
        self.assertNotEqual(Cache.key("search", "q", 5), Cache.key("search", "q", 8))
        self.assertNotEqual(Cache.key("a", "b"), Cache.key("b", "a"))


if __name__ == "__main__":
    unittest.main()
