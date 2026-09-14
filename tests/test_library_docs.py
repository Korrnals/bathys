"""Unit tests for library_docs: seed index, resolver, subpage extraction."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from bathys.library_docs import (  # noqa: E402
    _extract_subpages,
    _seed_index,
    _same_site,
    _normalize,
)


class SeedIndexTest(unittest.TestCase):
    def test_index_loads_with_entries(self):
        idx = _seed_index()
        self.assertGreater(len(idx), 20)
        self.assertIn("fastapi", idx)
        self.assertIn("pytorch", idx)
        self.assertTrue(all(v.startswith("https://") for v in idx.values()))

    def test_normalize_strips_slashes_and_case(self):
        self.assertEqual(_normalize("/FastAPI/"), "fastapi")


class SameSiteTest(unittest.TestCase):
    def test_same_host_variants(self):
        self.assertTrue(_same_site("https://a.com/x", "https://a.com/y"))
        self.assertTrue(_same_site("https://www.a.com/x", "https://a.com/y"))
        self.assertFalse(_same_site("https://a.com/x", "https://b.com/y"))


class ExtractSubpagesTest(unittest.TestCase):
    """Subpage ranking: same-site only, query-token overlap, asset filter."""

    BASE = "https://fastapi.tiangolo.com/"

    def test_ranks_by_query_tokens_and_filters_assets(self):
        raw = ("Guide [deps](https://fastapi.tiangolo.com/tutorial/dependencies/) "
               "[img](https://fastapi.tiangolo.com/logo.png) "
               "[advanced](https://fastapi.tiangolo.com/advanced/advanced-dependencies/) "
               "[alien](https://example.com/tutorial/dependencies/)")
        got = _extract_subpages(raw, self.BASE, "dependency injection", limit=2)
        self.assertEqual(set(got), {"https://fastapi.tiangolo.com/tutorial/dependencies/",
                                     "https://fastapi.tiangolo.com/advanced/advanced-dependencies/"})
        self.assertEqual(len(got), 2)

    def test_content_path_bonus(self):
        raw = ("[a](https://x.org/guide/setup) [b](https://x.org/random) "
               "[c](https://x.org/docs/tutorial)")
        got = _extract_subpages(raw, "https://x.org/", "guide", limit=2)
        self.assertEqual(got[0], "https://x.org/guide/setup")

    def test_no_links_returns_empty(self):
        self.assertEqual(_extract_subpages("no urls here", self.BASE, "q", limit=3), [])

    def test_limit_respected(self):
        raw = " ".join(f"(https://fastapi.tiangolo.com/guide/part{i}/)" for i in range(10))
        got = _extract_subpages(raw, self.BASE, "guide", limit=3)
        self.assertEqual(len(got), 3)


class ResolverAliasTest(unittest.TestCase):
    def test_alias_suffixes_hit_index(self):
        import asyncio

        from bathys.library_docs import resolve_docs_url

        class _NoSearchEngine:
            async def search(self, *a, **k):  # pragma: no cover — must not be reached
                raise AssertionError("search must not run for an index hit")

        url, source = asyncio.run(resolve_docs_url(_NoSearchEngine(), "nodejs"))
        self.assertEqual(source, "index")
        self.assertIn("nodejs.org", url)


if __name__ == "__main__":
    unittest.main()