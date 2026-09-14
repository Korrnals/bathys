"""Unit tests for bathys.config: env parsing, bool semantics, clamping."""

import os
import unittest
from unittest import mock

from bathys.config import SEARXNG_REF, Config


def base_env(**overrides):
    """A clean environment: real non-BATHYS vars plus explicit overrides."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("BATHYS_")}
    env.update(overrides)
    return env


class ConfigDefaultsTest(unittest.TestCase):
    def test_defaults_without_bathys_env(self):
        with mock.patch.dict(os.environ, base_env(), clear=True):
            cfg = Config.load()
        self.assertEqual(cfg.searxng_url, "http://127.0.0.1:8888")
        self.assertTrue(cfg.auto_start)
        self.assertEqual(cfg.start_mode, "auto")
        self.assertIsNone(cfg.start_cmd)
        self.assertEqual(cfg.searxng_ref, SEARXNG_REF)
        self.assertEqual(cfg.search_ttl, 3600)
        self.assertEqual(cfg.page_ttl, 86400)
        self.assertEqual(cfg.search_min_interval, 1.0)
        self.assertEqual(cfg.search_retries, 2)
        self.assertEqual(cfg.dive_concurrency, 4)


class AutoStartBoolSemanticsTest(unittest.TestCase):
    def test_falsy_values_mean_false(self):
        for value in ("", " ", "0", "false", "FALSE", "no", "off", " Off "):
            with self.subTest(value=repr(value)):
                env = base_env(BATHYS_AUTO_START=value)
                with mock.patch.dict(os.environ, env, clear=True):
                    self.assertFalse(Config.load().auto_start)

    def test_truthy_values_mean_true(self):
        for value in ("1", "yes", "true", "on", "anything-else"):
            with self.subTest(value=value):
                env = base_env(BATHYS_AUTO_START=value)
                with mock.patch.dict(os.environ, env, clear=True):
                    self.assertTrue(Config.load().auto_start)


class ClampingTest(unittest.TestCase):
    def test_search_retries_clamped_to_0_3(self):
        for value, expected in (("99", 3), ("3", 3), ("1", 1), ("0", 0), ("-5", 0)):
            with self.subTest(value=value):
                env = base_env(BATHYS_SEARCH_RETRIES=value)
                with mock.patch.dict(os.environ, env, clear=True):
                    self.assertEqual(Config.load().search_retries, expected)

    def test_dive_concurrency_clamped_to_1_8(self):
        for value, expected in (("0", 1), ("-3", 1), ("4", 4), ("99", 8)):
            with self.subTest(value=value):
                env = base_env(BATHYS_DIVE_CONCURRENCY=value)
                with mock.patch.dict(os.environ, env, clear=True):
                    self.assertEqual(Config.load().dive_concurrency, expected)


class SearxngRefTest(unittest.TestCase):
    def test_env_ref_overrides_pinned_commit(self):
        env = base_env(BATHYS_SEARXNG_REF="deadbeef0000")
        with mock.patch.dict(os.environ, env, clear=True):
            self.assertEqual(Config.load().searxng_ref, "deadbeef0000")

    def test_empty_ref_falls_back_to_pinned_commit(self):
        env = base_env(BATHYS_SEARXNG_REF="")
        with mock.patch.dict(os.environ, env, clear=True):
            self.assertEqual(Config.load().searxng_ref, SEARXNG_REF)


class SearxngUrlTest(unittest.TestCase):
    def test_trailing_slash_stripped(self):
        env = base_env(BATHYS_SEARXNG_URL="http://x.test:8888/")
        with mock.patch.dict(os.environ, env, clear=True):
            self.assertEqual(Config.load().searxng_url, "http://x.test:8888")


class DocsIndexTest(unittest.TestCase):
    """Phase 3 library_docs: user-grown index location, env-overridable.

    docs_index is a property resolved at access time (not a load-time
    snapshot) so that dataclasses.replace(cfg, data_dir=…) — the tests'
    tmp-dir pattern — keeps pointing at the right place; BATHYS_DOCS_INDEX
    therefore must be asserted INSIDE the patched-env block."""

    def test_default_under_data_dir(self):
        env = base_env(BATHYS_DATA_DIR="/tmp/bathys-data-test")
        with mock.patch.dict(os.environ, env, clear=True):
            cfg = Config.load()
            self.assertEqual(str(cfg.docs_index), "/tmp/bathys-data-test/docs-index.json")

    def test_env_overrides_path(self):
        env = base_env(BATHYS_DOCS_INDEX="/tmp/my-docs-index.json")
        with mock.patch.dict(os.environ, env, clear=True):
            cfg = Config.load()
            self.assertEqual(str(cfg.docs_index), "/tmp/my-docs-index.json")

    def test_survives_dataclasses_replace(self):
        env = base_env()
        with mock.patch.dict(os.environ, env, clear=True):
            cfg = Config.load()
        import dataclasses

        cfg2 = dataclasses.replace(cfg, data_dir=cfg.data_dir / "alt")
        self.assertEqual(cfg2.docs_index, cfg.data_dir / "alt" / "docs-index.json")


if __name__ == "__main__":
    unittest.main()
