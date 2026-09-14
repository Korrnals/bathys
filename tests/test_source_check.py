"""Tests for bathys.source_check: классификация URL, полярность маркеров
(включая негацию), термин-фильтр, домен-независимость, полный конвейер
(валидация urls, мок _read/_search_outcome, фейл одного URL, парсинг
строки-артефакта, метрики).

No network, no browser: engine._read заменён per-URL фейком (мок-паттерн
test_batch), _search_outcome — AsyncMock со stored-структурой.
"""

import asyncio
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from bathys.core import Engine, ReadResult  # noqa: E402
from bathys.crawler import Page  # noqa: E402
from bathys.config import Config  # noqa: E402
from bathys.source_check import (  # noqa: E402
    _marker_polarity,
    _passage_relevant,
    _relevant_sentences,
    claim_terms,
    classify,
    source_check,
)


def _mk_page(url, text, title="t"):
    return Page(url=url, status=200, title=title, text=text, raw_chars=len(text))


def _mk_res(url, distilled, cache_hit=False, raw=1000):
    return ReadResult(page=_mk_page(url, "x" * raw), distilled=distilled, cache_hit=cache_hit)


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


# ------------------------------------------------------------------- classify ---

class ClassifyTest(unittest.TestCase):
    def test_official_docs(self):
        self.assertEqual(classify("https://docs.python.org/3/library/asyncio"), "official_docs")
        self.assertEqual(classify("https://developers.google.com/youtube"), "official_docs")
        self.assertEqual(classify("https://learn.microsoft.com/dotnet"), "official_docs")
        self.assertEqual(classify("https://example.com/docs/getting-started"), "official_docs")
        self.assertEqual(classify("https://example.com/reference/api"), "official_docs")

    def test_repo_issue(self):
        self.assertEqual(classify("https://github.com/unclecode/crawl4ai/issues/123"), "repo_issue")
        self.assertEqual(classify("https://github.com/crawl4ai/crawl4ai/pull/45"), "repo_issue")

    def test_forum_en(self):
        self.assertEqual(classify("https://stackoverflow.com/questions/12345/py"), "forum")
        self.assertEqual(classify("https://ru.stackoverflow.com/questions/123/py"), "forum")
        self.assertEqual(classify("https://www.reddit.com/r/python/comments/abc"), "forum")

    def test_forum_ru_hosts(self):
        self.assertEqual(classify("https://habr.com/ru/articles/123/"), "forum")
        self.assertEqual(classify("https://vc.ru/tech/123"), "forum")
        self.assertEqual(classify("https://dtf.ru/tech/123"), "forum")

    def test_news_blog_unknown(self):
        self.assertEqual(classify("https://news.ycombinator.com/item?id=1"), "news")
        self.assertEqual(classify("https://blog.python.org/2026/09/release"), "blog")
        self.assertEqual(classify("https://example.com/"), "unknown")

    def test_garbage_is_unknown(self):
        self.assertEqual(classify(""), "unknown")
        self.assertEqual(classify("not a url at all"), "unknown")


# ------------------------------------------------------------------- polarity ---

class PolarityTest(unittest.TestCase):
    def test_support_markers(self):
        for s in ("It is true that asyncio needs an event loop.",
                  "The report confirmed the outage lasted two hours.",
                  "According to the vendor, release ships in October.",
                  "Эксперимент подтверждает гипотезу полных две недели.",
                  "Согласно документации, лимит равен 100 запросов."):
            self.assertEqual(_marker_polarity(s), "SUPPORT", s)

    def test_contra_markers(self):
        for s in ("The rumor is not true, officials said.",
                  "The study was retracted by the journal.",
                  "The claim is false.",
                  "Утверждение опровергнуто независимой проверкой.",
                  "Поддержка этого API больше не доступна."):
            self.assertEqual(_marker_polarity(s), "CONTRA", s)

    def test_negation_flips_support_marker(self):
        self.assertEqual(_marker_polarity("This is not true in any case."), "CONTRA")

    def test_negation_flips_contra_marker_to_support(self):
        self.assertEqual(_marker_polarity("The claim is not false at all."), "SUPPORT")

    def test_contra_outranks_support_in_same_sentence(self):
        # "not true" (contra, длинная фраза) должна победить одиночный "true"
        self.assertEqual(_marker_polarity("It is true... well, actually it is not true."), "CONTRA")

    def test_no_marker_returns_none(self):
        self.assertIsNone(_marker_polarity("Asyncio runs coroutines on an event loop."))


# --------------------------------------------------------------- term filter ---

class TermFilterTest(unittest.TestCase):
    def test_claim_terms_length_and_stopwords(self):
        terms = claim_terms("Will this async library really cache every page?")
        self.assertNotIn("will", terms)      # стоп-слово distill._STOP
        self.assertNotIn("this", terms)      # стоп-слово distill._STOP
        self.assertNotIn("the", terms)       # len <= 3
        self.assertIn("async", terms)
        self.assertIn("library", terms)
        self.assertIn("cache", terms)        # len == 4 — остаётся

    def test_passage_without_term_overlap_is_ignored(self):
        terms = claim_terms("postgresql supports jsonb GIN indexes")
        self.assertFalse(_passage_relevant("The chef cooked pasta with olive oil today.", terms))

    def test_passage_with_enough_overlap_passes(self):
        terms = claim_terms("postgresql supports jsonb GIN indexes")
        self.assertTrue(_passage_relevant(
            "PostgreSQL supports jsonb columns with GIN indexes.", terms))

    def test_relevant_sentences_top3_scored(self):
        distilled = ("Bathys supports source checks. "
                      "Bathys supports source checks, verdicts and citations. "
                      "Bathys supports source checks and verdicts for claims. "
                      "Unrelated filler sentence about nothing at all here now!")
        got = _relevant_sentences(distilled, "bathys supports source checks verdicts")
        self.assertEqual(len(got), 3)          # filler отсеян, топ-3 взяты
        for s in got:
            self.assertIn("supports", s.lower())

    def test_relevant_sentences_length_bounds(self):
        self.assertEqual(_relevant_sentences("Too short. " * 50, "short supports checks"), [])
        long_sent = "word " * 120 + "supports checks."
        self.assertEqual(_relevant_sentences(long_sent, "supports checks"), [])


# ------------------------------------------------------------------- pipeline ---

class SourceCheckTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp, self.patcher, self.eng = _make_engine()
        self.addCleanup(self.tmp.cleanup)
        self.addCleanup(self.patcher.stop)

    def _run(self, *args, **kwargs):
        return asyncio.run(source_check(self.eng, *args, **kwargs))

    def _set_read(self, dispatch):
        """dispatch: url -> distilled (str) | Exception instance to raise."""
        async def fake_read(u, *, query, max_chars, refresh=False):
            v = dispatch[u]
            if isinstance(v, Exception):
                raise v
            return _mk_res(u, v)
        self.eng._read = fake_read

    @staticmethod
    def _stored(*urls):
        return {
            "hits": [
                {"title": f"H{i}", "url": u, "snippet": "s", "engines": ["bing"],
                 "score": 1.0, "published": ""}
                for i, u in enumerate(urls, 1)
            ],
            "answers": [], "suggestions": [], "raw_chars": 100,
        }


class PipelineVerdictsTest(SourceCheckTestCase):
    SUP = ("According to the docs, bathys supports source checks with real citations. "
           "The benchmark confirmed the pipeline handles four sources.")
    CON = ("This is not true: the pipeline handles no sources. The claim is false.")

    def test_supported_two_domains_full_confidence(self):
        self._set_read({
            "https://a.example/docs/x": self.SUP,
            "https://b.example/y": self.SUP,
        })
        out = self._run("bathys supports source checks", urls=[
            "https://a.example/docs/x", "https://b.example/y"])
        self.assertIn("Вердикт: SUPPORTED", out)
        self.assertIn("2 домен(ов)", out)
        self.assertNotIn("домен-независимость не подтверждена", out)
        self.assertIn("[bathys: check 2 urls · 2 fetched · verdict supported · 2 domains", out)

    def test_supported_one_domain_capped_confidence_and_note(self):
        self._set_read({
            "https://a.example/docs/x": self.SUP,
            "https://a.example/docs/y": self.SUP,
        })
        out = self._run("bathys supports source checks", urls=[
            "https://a.example/docs/x", "https://a.example/docs/y"])
        self.assertIn("Вердикт: SUPPORTED", out)
        self.assertIn("источник один — домен-независимость не подтверждена", out)
        self.assertIn("(confidence 0.65", out)              # cap 0.65
        self.assertIn("1 домен(ов)", out)

    def test_contradicted(self):
        self._set_read({
            "https://a.example/x": self.CON,
            "https://b.example/y": self.CON,
        })
        out = self._run("pipeline handles sources", urls=[
            "https://a.example/x", "https://b.example/y"])
        self.assertIn("Вердикт: CONTRADICTED", out)
        self.assertIn("verdict contradicted", out)

    def test_mixed_marks_unclear(self):
        self._set_read({
            "https://a.example/x": self.SUP,
            "https://b.example/y": ("This is not true: bathys supports source checks "
                                    "poorly, the claim is false."),
        })
        out = self._run("bathys supports source checks", urls=[
            "https://a.example/x", "https://b.example/y"])
        self.assertIn("Вердикт: UNCLEAR", out)
        self.assertIn("mixed: маркеры за и против", out)
        self.assertIn("confidence 0.4", out)


class PipelineInputsTest(SourceCheckTestCase):
    def test_failed_url_is_a_note_not_a_crash(self):
        self._set_read({
            "https://a.example/x": "According to the docs, bathys supports source checks.",
            "https://b.example/y": RuntimeError("X: boom"),
        })
        out = self._run("bathys supports source checks", urls=[
            "https://a.example/x", "https://b.example/y"])
        self.assertIn("Ошибки: https://b.example/y — X: boom", out)
        self.assertIn("check 2 urls · 1 fetched", out)
        self.assertIn("Вердикт:", out)  # вызов завершился вердиктом, не падением

    def test_invalid_urls_reported_and_missing_evidence(self):
        self._set_read({})
        out = self._run("some claim", urls=["ftp://a.example/x", "not-a-url"])
        self.assertIn("Вердикт: MISSING-EVIDENCE", out)
        self.assertIn("не http(s) URL", out)
        self.assertIn("[bathys: check 0 urls · 0 fetched · verdict missing-evidence", out)

    def test_dedup_and_cap_by_normalize_url(self):
        calls = []
        text = "According to the docs, bathys supports source checks with citations."
        dispatch = {f"https://a.example/p{i}": text for i in range(6)}

        async def fake_read(u, *, query, max_chars, refresh=False):
            calls.append(u)
            return _mk_res(u, dispatch[u])
        self.eng._read = fake_read
        out = self._run("bathys supports source checks", urls=[
            "https://a.example/p0", "https://a.example/p0?utm_source=nl",
            "https://a.example/p1", "https://a.example/p2",
            "https://a.example/p3", "https://a.example/p4"],
            max_sources=4)
        self.assertEqual(len(calls), 4)                      # дедуп + cap 4
        self.assertEqual(calls[0], "https://a.example/p0")  # первая орфография
        self.assertIn("Пропущены (сверх лимита): https://a.example/p4", out)

    def test_search_fallback_when_no_urls(self):
        self._set_read({
            "https://a.example/docs/x": "According to the docs, bathys supports source checks.",
            "https://b.example/y": "The benchmark confirmed bathys supports source checks.",
        })
        stored = self._stored("https://a.example/docs/x", "https://b.example/y",
                              "https://c.example/z")
        self.eng._search_outcome = mock.AsyncMock(return_value=(stored, False))
        out = self._run("bathys supports source checks")
        q = self.eng._search_outcome.call_args.args[0]
        self.assertEqual(q, "bathys supports source checks")
        self.assertEqual(self.eng._search_outcome.call_args.kwargs.get("max_results"), 8)
        self.assertIn("Вердикт: SUPPORTED", out)
        self.assertIn("(official_docs)", out)

    def test_search_empty_is_missing_evidence(self):
        self.eng._search_outcome = mock.AsyncMock(return_value=(self._stored(), False))
        out = self._run("nonexistent claim xyzzy")
        self.assertIn("Вердикт: MISSING-EVIDENCE", out)
        self.assertIn("источники не найдены", out)
        self.assertIn("search empty", out)

    def test_no_relevant_passages_is_missing_evidence(self):
        self._set_read({
            "https://a.example/x": "Completely unrelated cooking recipe with pasta and sauce.",
        })
        out = self._run("postgresql supports jsonb indexes", urls=["https://a.example/x"])
        self.assertIn("Вердикт: MISSING-EVIDENCE", out)
        self.assertIn("нет релевантных пассажей", out)
        self.assertIn("confidence 0.2", out)

    def test_artifact_markers_and_metrics(self):
        self._set_read({
            "https://a.example/docs/x": "According to the docs, bathys supports source checks.",
            "https://b.example/y": "The benchmark confirmed bathys supports source checks.",
        })
        with mock.patch.object(self.eng, "_log_metrics") as m:
            out = self._run("bathys supports source checks", urls=[
                "https://a.example/docs/x", "https://b.example/y"])
        self.assertIn("# source_check: «bathys supports source checks»", out)
        self.assertIn("## Подтверждающие (2)", out)
        self.assertIn("[p1-1]", out)                      # passage_id
        self.assertIn("(sha256:", out)                    # content_hash
        self.assertIn("Источники: https://a.example/docs/x (official_docs)", out)
        self.assertTrue(out.rstrip().endswith("]"))       # футер — последняя строка
        m.assert_called_once()
        self.assertEqual(m.call_args.args, ("source_check",))
        self.assertIs(m.call_args.kwargs.get("ok"), True)


if __name__ == "__main__":
    unittest.main()