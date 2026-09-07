"""Unit tests for bathys.distill: slim_markdown and passages (pure functions)."""

import unittest

from bathys.distill import passages, slim_markdown

# --- deterministic long document -------------------------------------------
# Three paragraphs, each < 500 chars -> each becomes exactly one chunk.
# Only the lead paragraph and the hit paragraph mention the query term; the
# hit paragraph (later in the document) has a far higher term frequency, so
# score order != document order.
P_LEAD = (
    "The physics paper opens with a broad overview of the subject and mentions "
    "quantum exactly once before drifting into historical context and older citations "
    + " ".join(f"lead{i:03d}" for i in range(24))
)
P_HIT = " ".join(f"quantum effect {i:03d}" for i in range(20))
P_FILL = " ".join(f"fill{i:03d}" for i in range(30))
LONG_TEXT = f"{P_LEAD}\n\n{P_HIT}\n\n{P_FILL}"


class SlimMarkdownTest(unittest.TestCase):
    def test_inline_link_keeps_label_only(self):
        md = 'See [Python](https://python.org "Official site") for docs.'
        self.assertEqual(slim_markdown(md), "See Python for docs.")

    def test_image_keeps_alt_text(self):
        self.assertEqual(slim_markdown("![Logo](https://x.test/logo.png)"), "Logo")

    def test_footnote_definitions_removed(self):
        md = "Intro line.\n[^1]: first footnote.\n[^2]: second footnote.\n\nBody text."
        out = slim_markdown(md)
        self.assertNotIn("footnote", out)
        self.assertNotIn("[^1]", out)
        self.assertIn("Intro line.", out)
        self.assertIn("Body text.", out)

    def test_three_plus_newlines_collapse_to_two(self):
        self.assertEqual(slim_markdown("a\n\n\n\n\nb"), "a\n\nb")


class PassagesTest(unittest.TestCase):
    def test_short_text_returned_whole(self):
        self.assertEqual(passages("hello world", "hello", 100), "hello world")

    def test_empty_text_returns_empty(self):
        self.assertEqual(passages("", None, 100), "")

    def test_no_query_returns_first_chunk_within_budget(self):
        # The lead paragraph alone fits the budget -> exact head-trim.
        self.assertEqual(passages(LONG_TEXT, None, 400), P_LEAD)

    def test_no_query_trims_to_budget_on_word_boundary(self):
        out = passages(LONG_TEXT, None, 120)
        self.assertLessEqual(len(out), 120)
        self.assertTrue(out.endswith("…"))
        self.assertTrue(LONG_TEXT.startswith(out[:-1]))
        self.assertNotEqual(out[-2], " ")

    def test_query_selects_matching_chunks_in_document_order(self):
        # "+4" = two "\n\n" separators counted by the assembler's budget.
        budget = len(P_LEAD) + len(P_HIT) + 4
        self.assertGreater(len(LONG_TEXT), budget)  # short-circuit path not taken
        out = passages(LONG_TEXT, "quantum", budget)
        # Both matching chunks fit; filler excluded; lead (lower score) still first.
        self.assertEqual(out, f"{P_LEAD}\n\n{P_HIT}")

    def test_stopword_only_query_falls_back_to_head(self):
        expected = passages(LONG_TEXT, None, 300)
        self.assertEqual(passages(LONG_TEXT, "the and of what", 300), expected)
        self.assertEqual(passages(LONG_TEXT, "и в на как", 300), expected)

    def test_budget_never_exceeded(self):
        budgets = (150, 300, 700, len(LONG_TEXT) + 50)
        for query in ("quantum", None):
            for max_chars in budgets:
                with self.subTest(query=query, max_chars=max_chars):
                    out = passages(LONG_TEXT, query, max_chars)
                    self.assertLessEqual(len(out), max_chars)


if __name__ == "__main__":
    unittest.main()
