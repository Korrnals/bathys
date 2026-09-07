"""Query-focused distillation.

Score text chunks against the query (BM25-flavoured), keep the best ones in
document order, trim to a hard character budget. This is where most of the
token savings happen: a crawled page is often 50-300k chars, we return a few
thousand.
"""

from __future__ import annotations

import math
import re

_MD_LINK = re.compile(r"!?\[([^\]\n]*)\]\([^)]*\)")
_MD_REF = re.compile(r"\n\[\^?\d+\]:.*")
_SENT_SPLIT = re.compile(r"(?<=[.!?…])\s+")
_WS = re.compile(r"[ \t]+")

_STOP = frozenset("""
a about an and are as at be been but by for from has have how in into is it its
of on or that the their there this to was were what when where which who will
with you your
и в во не что он на я с со как а то все она так его но да ты к у же вы за бы по
только ее мне было вот от меня еще нет о из ему теперь когда даже ну вдруг ли
если уже или ни быть был него до вас нибудь опять уж вам ведь там потом себя
ничего ей может они тут где есть надо ней для мы тебя их чем была сам чтоб без
будто чего раз тоже себе под будет тогда кто этот того потому этого какой совсем
ним здесь этом один почти мой тем чтобы нее сейчас были куда зачем всех никогда
сегодня можно при наконец два об другой хоть после над больше тот через эти нас
про всего них какая много три эту моя впрочем хорошо свою этой перед иногда
лучше чуть том нельзя такой им более всегда конечно всю между
""".split())


def slim_markdown(text: str) -> str:
    """Token-oriented markdown slimming: inline links/images become their label."""
    text = _MD_REF.sub("", text)
    text = _MD_LINK.sub(lambda m: (m.group(1) or "").strip(), text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _tokens(text: str) -> list[str]:
    return [w for w in re.findall(r"[a-zа-яё0-9]+", text.lower()) if len(w) > 1 and w not in _STOP]


def _split_chunks(text: str, target: int = 320, hard: int = 500) -> list[str]:
    chunks: list[str] = []
    for para in re.split(r"\n\s*\n", text):
        para = para.strip()
        if not para:
            continue
        if len(para) <= hard:
            chunks.append(para)
            continue
        buf: list[str] = []
        size = 0
        for sent in _SENT_SPLIT.split(_WS.sub(" ", para)):
            if not sent:
                continue
            if buf and size + len(sent) > target:
                chunks.append(" ".join(buf))
                buf, size = [sent], len(sent)
            else:
                buf.append(sent)
                size += len(sent) + 1
        if buf:
            chunks.append(" ".join(buf))
    out: list[str] = []
    for c in chunks:
        while len(c) > 900:
            out.append(c[:900])
            c = c[900:]
        out.append(c)
    return out


def passages(text: str, query: str | None, max_chars: int) -> str:
    """Best passages of `text` for `query`, in document order, <= max_chars."""
    text = text.strip()
    if not text:
        return ""
    if len(text) <= max_chars:
        return text
    chunks = _split_chunks(text)
    if not chunks:
        return text[:max_chars]
    keep: set[int] = set()
    q_counts: dict[str, int] = {}
    if query:
        for w in _tokens(query):
            q_counts[w] = q_counts.get(w, 0) + 1
    if q_counts:
        toks = [_tokens(c) for c in chunks]
        n = len(chunks)
        df: dict[str, int] = {}
        for ts in toks:
            for t in set(ts):
                df[t] = df.get(t, 0) + 1
        scored: list[tuple[float, int]] = []
        for i, ts in enumerate(toks):
            counts: dict[str, int] = {}
            for t in ts:
                counts[t] = counts.get(t, 0) + 1
            s = 0.0
            for term, qtf in q_counts.items():
                tf = counts.get(term, 0)
                if tf:
                    s += qtf * (1.0 + math.log(tf)) * math.log(1.0 + n / df.get(term, 1))
            scored.append((s, i))
        scored.sort(key=lambda p: -p[0])
        for s, i in scored:
            if s <= 0:
                break
            if sum(len(chunks[j]) + 2 for j in keep) >= max_chars:
                break
            keep.add(i)
        # query terms absent from the page -> fall back to the lead
        if not keep:
            keep = {0}
    else:
        keep = {0}  # no query: head-trimmed reading, lead paragraph carries it
    picked = sorted(keep)
    parts: list[str] = []
    used = 0
    for i in picked:
        c = chunks[i]
        if used + len(c) + 2 > max_chars:
            remain = max_chars - used - 1
            if remain > 80:
                parts.append(c[:remain].rsplit(" ", 1)[0] + "…")
            break
        parts.append(c)
        used += len(c) + 2
    return "\n\n".join(parts)
