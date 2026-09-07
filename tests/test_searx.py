"""Unit tests for bathys.searx pure helpers: normalize_url, clean_text,
SearchHit.dedupe_key. No network, no httpx calls."""

import unittest

from bathys.searx import SearchHit, clean_text, normalize_url


class NormalizeUrlTest(unittest.TestCase):
    def test_drops_tracking_params_keeps_rest_and_order(self):
        url = ("https://example.com/p?a=1&utm_source=x&utm_medium=y&gclid=G"
               "&b=2&fbclid=F&ref=R&utm_campaign=c")
        self.assertEqual(normalize_url(url), "https://example.com/p?a=1&b=2")

    def test_keeps_path_when_all_params_dropped(self):
        self.assertEqual(
            normalize_url("https://example.com/a/b/c?utm_term=t"),
            "https://example.com/a/b/c",
        )

    def test_tracking_param_match_is_case_insensitive(self):
        self.assertEqual(
            normalize_url("https://e.test/p?UTM_Source=x&ok=1"),
            "https://e.test/p?ok=1",
        )

    def test_mailto_scheme_untouched(self):
        self.assertEqual(normalize_url("mailto:user@example.com"), "mailto:user@example.com")

    def test_url_without_scheme_untouched(self):
        url = "example.com/page?utm_source=x&keep=1"
        self.assertEqual(normalize_url(url), url)


class CleanTextTest(unittest.TestCase):
    def test_strips_tags_and_unescapes_entities(self):
        self.assertEqual(clean_text("<b>Hello</b> &amp; <i>world</i>", 100), "Hello & world")

    def test_collapses_all_whitespace_to_single_spaces(self):
        self.assertEqual(clean_text("a \n\t b   c", 100), "a b c")

    def test_text_within_limit_unchanged(self):
        self.assertEqual(clean_text("short text", 100), "short text")
        self.assertEqual(clean_text("exact len", len("exact len")), "exact len")

    def test_truncates_on_word_boundary_with_ellipsis_within_limit(self):
        out = clean_text("alpha bravo charlie delta echo", 11)
        self.assertLessEqual(len(out), 11)
        self.assertTrue(out.endswith("…"))
        self.assertEqual(out, "alpha…")  # cut at the last full word boundary
        self.assertTrue("alpha bravo charlie delta echo".startswith(out[:-1]))

    def test_truncation_does_not_leave_trailing_punctuation(self):
        out = clean_text("alpha, bravo charlie delta", 8)
        self.assertLessEqual(len(out), 8)
        self.assertTrue(out.endswith("…"))
        self.assertFalse(out[:-1].rstrip().endswith(","))


class DedupeKeyTest(unittest.TestCase):
    def test_ignores_www_trailing_slash_and_case(self):
        a = SearchHit(title="", url="https://www.Example.com/Docs/", snippet="")
        b = SearchHit(title="", url="https://example.com/Docs", snippet="")
        self.assertEqual(a.dedupe_key, b.dedupe_key)

    def test_differs_for_different_paths(self):
        a = SearchHit(title="", url="https://example.com/one", snippet="")
        b = SearchHit(title="", url="https://example.com/two", snippet="")
        self.assertNotEqual(a.dedupe_key, b.dedupe_key)

    def test_differs_for_different_hosts(self):
        a = SearchHit(title="", url="https://a.test/x", snippet="")
        b = SearchHit(title="", url="https://b.test/x", snippet="")
        self.assertNotEqual(a.dedupe_key, b.dedupe_key)


if __name__ == "__main__":
    unittest.main()
