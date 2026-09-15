"""source_check — детерминированная проверка утверждения по источникам.

Идея заимствована у pi-web-access source-check.ts (полярные маркеры,
термин-фильтр, confidence-статусы), перевод на архитектуру Bathys:
источники — web_search по claim либо список URL от вызывающего; чтение —
engine._read(query=claim) параллельно через engine._dive_sem (мок-паттерн
batch.read_many: нам нужны res-объекты, не строковый batch-ответ); пассажи —
top-3 предложения каждого дистиллята; вердикт — SUPPORTED / CONTRADICTED /
UNCLEAR / MISSING-EVIDENCE.

БЕЗ LLM: скоринг лексический (пересечение токенов claim), полярность —
фразовые маркеры с проверкой негации слева от маркера. Выход — строка
(строковый контракт ADR-0006), не JSON.

Наше усиление против Pi: для supported/contradicted считается число
НЕЗАВИСИМЫХ доменов (dedup по netloc); один домен — пониженный confidence
и явная пометка в rationale (правило двух независимых источников из
канона харнеса).
"""

from __future__ import annotations

import asyncio
import hashlib
import math
import re
import time
from urllib.parse import urlsplit

from . import distill
from .searx import normalize_url

_SENT_SPLIT = re.compile(r"(?<=[.!?…])\s+")
_WS = re.compile(r"\s+")

# Полярные маркеры (Pi-web-access, дополненные RU-формами).
_SUPPORT_MARKERS = (
    "yes", "true", "correct", "confirmed", "according to", "shows that",
    "demonstrates", "reported", "verified", "established",
    "подтверждает", "верно", "согласно",
    # definitional copulas (QA-audit finding: "X is a Y" — the most common
    # shape of a direct factual confirmation — scored no marker at all)
    " is a ", " is an ", " is the ", " are a ", " are the ", " was a ",
    " was the ", " были ", " является ", " являются ",
)
_CONTRA_MARKERS = (
    "not true", "false", "incorrect", "debunked", "retracted", "no longer",
    "never", "denied", "contrary", "misleading",
    "неверно", "ложно", "опровергнуто", "больше не",
)
# Негация в пределах двух слов слева от маркера переворачивает полярность.
_NEGATION_RE = re.compile(r"\b(not|no|never|без)\s+(?:\w+\s+){0,2}$", re.I)

# Качество источника — переработка эвристик Pi на python.
_FORUM_HOSTS = ("stackoverflow.com", "superuser.com", "serverfault.com",
                "stackexchange.com", "quora.com", "reddit.com",
                "habr.com", "vc.ru", "dtf.ru")


def classify(url: str) -> str:
    """Класс источника: official_docs | repo_issue | forum | news | blog | unknown.

    Порядок проверки значим: /issues и /pull точнее forum-хостов, а path-признаки
    docs точнее generic-домена — идём от специфичного к общему.
    """
    try:
        parts = urlsplit(url or "")
    except ValueError:
        return "unknown"
    host = (parts.netloc or "").lower().removeprefix("www.")
    path = (parts.path or "").lower()
    if host.startswith(("docs.", "developers.", "learn.", "reference.")) \
            or re.search(r"/docs?(/|$)|/reference", path):
        return "official_docs"
    if "/issues" in path or "/pull" in path:
        return "repo_issue"
    if any(host == h or host.endswith("." + h) for h in _FORUM_HOSTS):
        return "forum"
    if "news" in host or re.search(r"/news(/|$)", path):
        return "news"
    if host.startswith(("blog.", "blogs.")) or re.search(r"/blog(/|$)|/posts?/", path):
        return "blog"
    return "unknown"


def claim_terms(claim: str) -> list[str]:
    """Термины claim: токены >3 символов, lowercased, без стоп-слов distill._STOP."""
    return [t for t in re.findall(r"[a-zа-яё0-9]+", (claim or "").lower())
            if len(t) > 3 and t not in distill._STOP]


def _overlap(text: str, terms: list[str]) -> int:
    """Число уникальных терминов claim, встреченных в text (substring-матч).

    Substring, не пересечение токенов: «source» матчит «sources», «источник» —
    «источников»; стемминга в конвейере нет, точный токенный матч терял бы
    морфологию RU/EN и выкидывал ценные пассажи (в т.ч. contra-цитаты).
    """
    if not terms:
        return 0
    low = text.lower()
    return sum(1 for t in set(terms) if t in low)


def _relevant_sentences(distilled: str, claim: str, top: int = 3) -> list[str]:
    """Top-3 предложения дистиллята по числу терминов claim (20 < len < 400, >=1 термин)."""
    terms = claim_terms(claim)
    scored: list[tuple[int, int, str]] = []  # (score, doc_order, sentence)
    for i, sent in enumerate(_SENT_SPLIT.split(_WS.sub(" ", distilled or ""))):
        s = sent.strip()
        if not 20 < len(s) < 400:
            continue
        score = _overlap(s, terms)
        if score >= 1:
            scored.append((score, i, s))
    scored.sort(key=lambda p: (-p[0], p[1]))
    return [s for _, _, s in scored[:top]]


def _marker_polarity(sentence: str) -> str | None:
    """SUPPORT | CONTRA | None для предложения.

    Фразовый матч: contra-маркеры проверяются раньше support (любой contra-сигнал
    информативнее поддержки); внутри — раньше длинные фразы ("not true" перед
    "true"). Негация (not|no|never|без) в пределах двух слов слева от маркера
    переворачивает полярность.
    """
    low = sentence.lower()
    for marker in (*_CONTRA_MARKERS, *_SUPPORT_MARKERS):
        pos = low.find(marker)
        if pos == -1:
            continue
        polarity = "CONTRA" if marker in _CONTRA_MARKERS else "SUPPORT"
        if _NEGATION_RE.search(low[:pos]):
            polarity = "CONTRA" if polarity == "SUPPORT" else "SUPPORT"
        return polarity
    return None


def _passage_relevant(sentence: str, terms: list[str]) -> bool:
    """Пассаж релевантен при >= max(2, ceil(len(terms)/4)) уникальных терминах claim."""
    if not terms:
        return False
    return _overlap(sentence, terms) >= max(2, math.ceil(len(set(terms)) / 4))


def _netloc(url: str) -> str:
    try:
        return (urlsplit(url).netloc or "").lower().removeprefix("www.")
    except ValueError:
        return url


def _fmt_confidence(c: float) -> str:
    return f"{c:.2g}"


async def source_check(engine, claim: str, urls: list[str] | None = None,
                       max_sources: int = 4, per_source_chars: int = 2500,
                       refresh: bool = False) -> str:
    """Проверка утверждения: источники -> пассажи -> вердикт. Детерминированная, без LLM.

    urls=None (или пустой список) -> web_search(claim) -> top URL; иначе валидация
    (http/https, дедуп по normalize_url, cap max_sources). Фейл URL — строка в
    артефакте, вызов не срывает. Выход — строка-артефакт: вердикт, цитаты
    (passage_id + content_hash), rationale, футер [bathys: …].
    """
    started = time.monotonic()
    claim = (claim or "").strip()
    max_sources = max(1, min(10, max_sources))
    per_source_chars = max(300, min(50_000, per_source_chars))

    # -- 1. Источники ---------------------------------------------------------
    invalid_urls: list[tuple[str, str]] = []
    failed_urls: list[tuple[str, str]] = []
    skipped_urls: list[str] = []
    if urls:
        kept: list[str] = []
        seen: set[str] = set()
        for u in urls:
            u = (u or "").strip()
            if not u:
                continue
            try:
                parts = urlsplit(u)
            except ValueError:
                parts = None
            if parts is None or parts.scheme not in ("http", "https") or not parts.netloc:
                invalid_urls.append((u, "не http(s) URL"))
                continue
            key = normalize_url(u)
            if not key or key in seen:
                continue
            seen.add(key)
            kept.append(u)
        sources = kept[:max_sources]
        skipped_urls = kept[max_sources:]
        if not sources:
            reason = ("все переданные urls невалидны: "
                      + "; ".join(f"{u} — {e}" for u, e in invalid_urls)
                      if invalid_urls
                      else "утверждение без источников — передайте urls или оставьте "
                           "urls=None для автопоиска")
            return _missing_evidence(engine, claim, reason, started)
    else:
        stored, _ = await engine._search_outcome(
            claim, max_results=8, category=None, engines=None,
            language=None, time_range=None, refresh=refresh,
        )
        sources = [h["url"] for h in stored["hits"][:max_sources] if h.get("url")]
        skipped_urls = [h["url"] for h in stored["hits"][max_sources:max_sources + 5]]
        if not sources:
            return _missing_evidence(engine, claim, "источники не найдены", started,
                                    searched_empty=True)

    # -- 2. Пассажи из каждого источника (параллельно через _dive_sem) ----------
    sem = engine._dive_sem

    async def dive(u: str):
        async with sem:
            try:
                return await engine._read(u, query=claim,
                                          max_chars=per_source_chars,
                                          refresh=refresh), None
            except Exception as e:
                # _read raises "{Class}: {msg}" both fresh and from the error cache.
                return None, str(e) or e.__class__.__name__

    results = await asyncio.gather(*(dive(u) for u in sources))

    passages: list[dict] = []
    source_classes: list[tuple[str, str]] = []
    fetched = 0
    raw_total = 0
    for src_idx, (u, (res, err)) in enumerate(zip(sources, results), 1):
        source_classes.append((u, classify(u)))
        if res is None:
            failed_urls.append((u, err))
            continue
        fetched += 1
        raw_total += res.page.raw_chars
        for sent_idx, sent in enumerate(_relevant_sentences(res.distilled, claim), 1):
            passages.append({
                "url": u,
                "id": f"p{src_idx}-{sent_idx}",
                "text": sent,
                "hash": hashlib.sha256(sent.encode()).hexdigest()[:16],
            })

    # -- 3. Вердикт ------------------------------------------------------------
    terms = claim_terms(claim)
    relevant = [p for p in passages if _passage_relevant(p["text"], terms)]
    sup = [p for p in relevant if _marker_polarity(p["text"]) == "SUPPORT"]
    con = [p for p in relevant if _marker_polarity(p["text"]) == "CONTRA"]

    if not relevant:
        verdict, label, confidence = "MISSING-EVIDENCE", "missing-evidence", 0.2
        domains = 0
        reason = "нет релевантных пассажей — источники не отвечают на утверждение" \
            if fetched else "ни один источник не прочитан"
    elif sup and con:
        verdict, label, confidence = "UNCLEAR", "unclear", 0.4
        domains = len({_netloc(p["url"]) for p in (*sup, *con)})
        reason = "mixed: маркеры за и против"
    elif not con and sup:
        verdict, label, confidence = "SUPPORTED", "supported", \
            min(0.85, 0.5 + len(sup) * 0.1)
        domains = len({_netloc(p["url"]) for p in sup})
        reason = ""
        if domains < 2:
            confidence = min(confidence, 0.65)
            reason = "источник один — домен-независимость не подтверждена"
    elif not sup and con:
        verdict, label, confidence = "CONTRADICTED", "contradicted", \
            min(0.85, 0.5 + len(con) * 0.1)
        domains = len({_netloc(p["url"]) for p in con})
        reason = ""
        if domains < 2:
            confidence = min(confidence, 0.65)
            reason = "источник один — домен-независимость не подтверждена"
    else:
        verdict, label, confidence = "UNCLEAR", "unclear", 0.3
        domains = 0
        reason = "полярные маркеры не найдены"

    # -- 4. Артефакт ------------------------------------------------------------
    sections: list[str] = [f"# source_check: «{claim}»"]
    sections.append(
        f"Вердикт: {verdict} (confidence {_fmt_confidence(confidence)}, "
        f"{domains} домен(ов))" + (f"\n{reason}" if reason else "")
    )

    def _cite(p: dict) -> str:
        return (f"- [{p['id']}] {_netloc(p['url'])} — «{p['text']}» "
                f"(sha256:{p['hash']}…)")

    if sup:
        sections.append(f"## Подтверждающие ({len(sup)})\n" + "\n".join(_cite(p) for p in sup))
    if con:
        sections.append(f"## Противоречащие ({len(con)})\n" + "\n".join(_cite(p) for p in con))
    if relevant and not sup and not con:
        sections.append(f"## Релевантные пассажи ({len(relevant)})\n"
                        + "\n".join(_cite(p) for p in relevant))
    if not relevant and passages:
        shown = passages[:5]
        sections.append(
            f"## Нерелевантные пассажи ({len(passages)}, показано {len(shown)})\n"
            + "\n".join(_cite(p) for p in shown))

    notes: list[str] = []
    if source_classes:
        notes.append("Источники: " + ", ".join(f"{u} ({c})" for u, c in source_classes))
    if invalid_urls:
        notes.append("Ошибки: " + "; ".join(f"{u} — {e}" for u, e in invalid_urls))
    if failed_urls:
        notes.append("Ошибки: " + "; ".join(f"{u} — {e}" for u, e in failed_urls))
    if skipped_urls:
        notes.append("Пропущены (сверх лимита): " + ", ".join(skipped_urls))
    if notes:
        sections.append("\n".join(notes))

    secs = round(time.monotonic() - started, 1)
    sections.append(
        f"[bathys: check {len(sources)} urls · {fetched} fetched · "
        f"verdict {label} · {domains} domains · {secs}s]"
    )
    out = "\n\n".join(sections)
    engine._log_metrics("source_check", chars_in=raw_total, chars_out=len(out),
                        secs=secs, q=claim, ok=True)
    return out


def _missing_evidence(engine, claim: str, reason: str, started: float,
                      *, searched_empty: bool = False) -> str:
    """Ранний MISSING-EVIDENCE: источники не найдены/невалидны — честный артефакт, не ошибка."""
    secs = round(time.monotonic() - started, 1)
    sections = [
        f"# source_check: «{claim}»",
        f"Вердикт: MISSING-EVIDENCE (confidence 0.2, 0 домен(ов))\n{reason}",
        f"[bathys: check 0 urls · 0 fetched · verdict missing-evidence · "
        f"0 domains · {secs}s]" + (" · search empty" if searched_empty else ""),
    ]
    out = "\n\n".join(sections)
    engine._log_metrics("source_check", chars_in=0, chars_out=len(out),
                        secs=secs, q=claim, ok=True)
    return out