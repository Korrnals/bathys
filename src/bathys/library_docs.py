"""library_docs — up-to-date library documentation for agents, Context7-style
but local and unlimited (initiative: docs/product/library-docs-initiative.md).

Resolution chain (phase 3): seed index (docs_index.json) -> user-grown
index (BATHYS_DOCS_INDEX, auto-filled from live-search finds) -> one live
web_search ("<library> official documentation") -> GitHub slug guess. With
`version` given and a GitHub repo known (owner/repo), docs resolve from
raw.githubusercontent.com at that tag — pinned docs for the exact version
asked. Extraction reuses the two-tier crawler; distillation reuses the
BM25 passage engine; the raw page lands in the existing page cache, so
follow-up questions on the same library are instant, offline and free.

Phase 2 (v0.11.0): doc HOME pages are often navigational. After the home
read, we extract same-site subpage links from the raw text, rank them against
the query (token overlap in the URL path), fetch the best matches in
parallel through the engine dive semaphore, and merge the distilled
passages — one compact digest built from the pages that actually carry
the content.
"""

from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path
from urllib.parse import urlsplit

from . import distill

_INDEX_PATH = Path(__file__).resolve().parent / "docs_index.json"
_LINK_RE = re.compile(r"\((https?://[^\s)]+)\)")


def _seed_index() -> dict[str, str]:
    try:
        data = json.loads(_INDEX_PATH.read_text(encoding="utf-8"))
        # skip non-entry keys (comments live in the same JSON namespace)
        return {k: v for k, v in data.items()
                if not k.startswith("_") and isinstance(v, str)}
    except (OSError, json.JSONDecodeError):
        return {}


def _user_index_path(cfg) -> Path | None:
    """BATHYS_DOCS_INDEX location; None when the engine/config carries no
    data_dir (unit-test fakes may have neither)."""
    path = getattr(cfg, "docs_index", None) if cfg is not None else None
    return path or (cfg.data_dir / "docs-index.json" if cfg is not None else None)


def _load_user_index(path: Path | None) -> dict[str, str]:
    if path is None:
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {k: v for k, v in data.items()
            if isinstance(k, str) and isinstance(v, str) and not k.startswith("_")}


def _save_to_user_index(path: Path | None, library: str, url: str) -> None:
    """Idempotent write-through of a successful search resolve: same key
    rewrites to the same value, corrupt/unwritable index never breaks the
    tool. Lazy: the file appears only when there is something to store."""
    if path is None:
        return
    data = _load_user_index(path)
    if data.get(_normalize(library)) == url:
        return  # idempotent: nothing to rewrite
    data[_normalize(library)] = url
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n",
                       encoding="utf-8")
        tmp.replace(path)
    except OSError:
        try:
            tmp.unlink(missing_ok=True)
        except (OSError, NameError, UnboundLocalError):
            pass


def _normalize(name: str) -> str:
    return (name or "").strip().lower().lstrip("/").rstrip("/")


async def resolve_docs_url(engine, library: str) -> tuple[str, str]:
    """Return (docs_url, source) for a library name.

    source: 'index' | 'user-index' | 'search' | 'github' — provenance for the
    answer header. Resolution priority: seed index -> user-grown index ->
    one live web_search -> GitHub slug guess. Raises RuntimeError when
    nothing plausible is found.
    """
    key = _normalize(library)
    seed = _seed_index()
    hit = _index_lookup(seed, key)
    if hit:
        return hit, "index"

    cfg = getattr(engine, "cfg", None)
    user = _load_user_index(_user_index_path(cfg))
    hit = _index_lookup(user, key)
    if hit:
        return hit, "user-index"

    # live search fallback: one web_search call
    raw = await engine.search(f"{library} official documentation", max_results=5, refresh=False)
    lines = raw.splitlines()
    for ln in lines:
        s = ln.strip()
        if s.startswith("http://") or s.startswith("https://"):
            low = s.lower()
            if any(b in low for b in ("docs.", "/docs", "documentation.", "developer.",
                                      "github.com/")):
                url = s.split()[0]
                # phase 3b: remember search-found docs sites in the user
                # index, so the next call for the same library skips the
                # network entirely. GitHub slug guesses are NOT stored —
                # low quality; only real search finds win.
                _save_to_user_index(_user_index_path(cfg), key, url)
                return url, "search"
    # last resort: github slug
    if " " not in key and "/" not in key:
        return f"https://github.com/{key}", "github"
    raise RuntimeError(f"library_docs: не удалось найти документацию для {library!r}")


def _same_site(base: str, cand: str) -> bool:
    try:
        b, c = urlsplit(base), urlsplit(cand)
    except ValueError:
        return False
    return b.netloc.replace("www.", "") == c.netloc.replace("www.", "")


def _index_lookup(idx: dict[str, str], key: str) -> str | None:
    """Exact match, then common alias shapes (js suffix, -python, etc.)."""
    if key in idx:
        return idx[key]
    for suffix in ("js", "-js", ".js", "-python", "py", "-dev"):
        if key + suffix in idx:
            return idx[key + suffix]
    return None


_GH_REPO_RE = re.compile(r"github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)/?$")
_RAW_HOST = "raw.githubusercontent.com"


def _tag_variants(version: str) -> tuple[str, ...]:
    """'2.1' -> ('2.1', 'v2.1'); 'v2.1' -> ('v2.1', '2.1'). Branch names and
    SHAs pass through as-is first (they are legal raw.githubusercontent refs)."""
    v = version.strip()
    if not v:
        return ()
    if v[0] in "vV" and len(v) > 1 and v[1].isdigit():
        return (v, v[1:])
    if v[0].isdigit():
        return (v, "v" + v)
    return (v,)


def _raw_url(owner: str, repo: str, tag: str, path: str) -> str:
    return f"https://{_RAW_HOST}/{owner}/{repo}/{tag}/{path}"


async def _resolve_versioned(engine, repo: tuple[str, str], version: str,
                             max_chars: int, refresh: bool):
    """Phase 3a: docs pinned to a GitHub tag via raw.githubusercontent.

    Entry discovery is deliberately shallow: for each tag variant try
    README.md then docs/index.md in the repo root — one candidate per shot.
    First 200 wins; anything else (404 for a wrong tag, README missing,
    network) gives up honestly and the caller falls back to the latest-docs
    path with a note. No deep guessing: a wrong tag must fail fast."""
    owner, name = repo
    for tag in _tag_variants(version):
        for path in ("README.md", "docs/index.md"):
            url = _raw_url(owner, name, tag, path)
            try:
                res = await engine._read(url, query=None, max_chars=max_chars,
                                         refresh=refresh)
            except Exception:  # noqa: BLE001 — wrong tag/path: try next
                continue
            return res, url, tag
    return None, None, None


def _q_variants(token: str) -> tuple[str, ...]:
    """Light morphology: 'dependency' also matches 'dependencies' (and vice
    versa) — final y/ies is the most common doc-path plural shape."""
    if token.endswith("y"):
        return (token, token[:-1] + "ies")
    if token.endswith("ies"):
        return (token, token[:-3] + "y")
    return (token,)


def _extract_subpages(raw_text: str, base_url: str, query: str, limit: int) -> list[str]:
    """Pick same-site doc links from the raw cached text, ranked by query
    token overlap in the path — navigation URLs carry the page topic in the
    path, a good cheap proxy for content match."""
    q_tokens = {t for t in re.findall(r"[a-z0-9]+", (query or "").lower()) if len(t) > 2}
    scored: list[tuple[float, str]] = []
    seen: set[str] = set()
    for m in _LINK_RE.finditer(raw_text or ""):
        url = m.group(1)
        if url in seen or not _same_site(base_url, url):
            continue
        seen.add(url)
        if any(url.lower().endswith(ext) for ext in
               (".png", ".jpg", ".svg", ".zip", ".css", ".js", ".ico")):
            continue
        path = urlsplit(url).path.lower()
        score = sum(1.0 for t in q_tokens
                    if any(v in path for v in _q_variants(t)))
        if any(k in path for k in ("/guide", "/docs", "/tutorial", "/how-to", "/reference", "/api")):
            score += 0.5
        if score > 0:
            scored.append((score, url))
    scored.sort(key=lambda p: -p[0])
    return [u for _, u in scored[:limit]]


def _is_navigational(distilled: str) -> bool:
    """A home distills thin BY MEANING when it is a table of contents:
    concatenated entry titles have low word diversity for their length
    (most words occur exactly once because each is a different page name).
    Raw-link counting is blind here — slim collapses links to labels and
    the HTTP tier may strip nav markup entirely (no URLs survive)."""
    if not distilled:
        return True
    words = re.findall(r"[A-Za-z]{3,}", distilled)
    if len(words) < 40:
        return False  # too short to judge; thin-length branch covers it
    uniq = len(set(w.lower() for w in words))
    # empirical (fastapi/pytorch homes): concatenated TOC titles sit at
    # ~0.73–0.77 unique-ratio; prose runs ≥0.83 (function words repeat).
    return uniq / len(words) >= 0.78


async def _search_subpages(engine, library: str, base_url: str, query: str,
                           limit: int) -> list[str]:
    """Site-scoped web search as the subpage-discovery fallback for homes
    that carry no extractable links."""
    host = urlsplit(base_url).netloc.replace("www.", "")
    raw = await engine.search(f"{library} {query} site:{host}", max_results=limit + 2,
                              refresh=False)
    out: list[str] = []
    for ln in raw.splitlines():
        s = ln.strip()
        if s.startswith(("http://", "https://")) and host in s:
            u = s.split()[0]
            if u != base_url and u not in out:
                out.append(u)
            if len(out) >= limit:
                break
    return out


async def _fetch_subpages(engine, pages: list[str], query: str, per_page: int,
                          refresh: bool) -> tuple[list[tuple[str, str]], list[str]]:
    """Dive `pages` in parallel under the engine semaphore; return
    ([(url, distilled)], failed_notes). A dead subpage costs one note,
    never the call."""
    texts: list[tuple[str, str]] = []
    failed: list[str] = []
    if not pages:
        return texts, failed
    sem = engine._dive_sem

    async def dive(u: str):
        async with sem:
            try:
                r = await engine._read(u, query=query, max_chars=per_page,
                                       refresh=refresh)
                return r, u, None
            except Exception as e:  # noqa: BLE001 — one dead subpage is fine
                return None, u, f"{e.__class__.__name__}"

    outs = await asyncio.gather(*(dive(u) for u in pages))
    for r, u, err in outs:
        if r is None:
            failed.append(f"{u} ({err})")
            continue
        slim = distill.slim_markdown(r.page.text)
        d = distill.passages(slim, query, per_page)
        if d:
            texts.append((u, d))
    return texts, failed


def _assemble_digest(library: str, base_url: str, source: str, res, *,
                     home_distilled: str, sub_texts: list[str], sub_urls: list[str],
                     sub_failed: list[str], version_note: str) -> str:
    """One answer shape for every resolution path (versioned raw, doc site):
    header with provenance, home digest, subpage sections, honest notes,
    stats footer — footer stays the last line (output-format contract)."""
    from .core import _ch

    total_out = len(home_distilled) + sum(len(t) for _, t in sub_texts)
    head = f"# Документация: {library}\n{base_url}\n(источник: {source})"
    parts = [head]
    if home_distilled:
        parts.append(home_distilled)
    parts += [f"### {u}\n\n{t}" for u, t in sub_texts]
    tail = ""
    if sub_urls or sub_failed:
        tail = "\n\nПодстраницы: " + ", ".join(sub_urls)
        if sub_failed:
            tail += " | не прочитаны: " + ", ".join(sub_failed)
    if version_note:
        tail += f"\n\n{version_note}"
    footer = (f"[bathys: docs {_ch(res.page.raw_chars)} ch → {_ch(total_out)} ch"
              f"{' · +' + str(len(sub_urls)) + ' подстр.' if sub_urls else ''} · "
              f"cache {'HIT' if res.cache_hit else 'MISS'}] — повторы бесплатны: уточняй запросом")
    return "\n\n".join(p for p in parts if p) + tail + "\n\n" + footer


def _gh_repo_from(base_url: str, library: str) -> tuple[str, str] | None:
    """(owner, repo) when the docs resolve maps to a GitHub repo — the only
    shape phase-3a version pinning applies to. No guessing beyond what the
    resolver already established: github.com/{owner}/{repo} URLs, or a
    {owner}/{repo} given AS the library name itself."""
    m = _GH_REPO_RE.search(base_url or "")
    if m:
        return m.group(1), m.group(2)
    key = _normalize(library)
    if "/" in key and " " not in key:
        owner, _, repo = key.partition("/")
        if owner and repo:
            return owner, repo
    return None


async def library_docs(engine, library: str, query: str, max_chars: int = 6000,
                       refresh: bool = False, subpages: int = 3,
                       version: str | None = None) -> str:
    """Fetch and distill official docs for `library` under `query`.

    Phase 2: the docs home is usually navigational, so up to `subpages`
    same-site pages ranked by query relevance are fetched in parallel and
    merged into one digest. Subpage follow-loading is UNCONDITIONAL (the
    tool's profile): lexical navigational heuristics proved unreliable at
    the TOC/prose boundary; one extra search when a home has no
    extractable links is a fair price for depth.

    Phase 3a: with `version` given and a GitHub repo behind the resolve,
    the docs come from raw.githubusercontent.com/{owner}/{repo}/{tag}/
    (entry found shallowly: README.md, then docs/index.md — one candidate
    per shot; a wrong tag fails fast and the latest docs are shown with an
    honest note). Doc sites are NOT version-pinned (not every docs site
    versions by URL) — there `version` only sharpens the site-search
    ranking for subpages. Versioned raw pages carry no same-site links,
    so their subpages come from one site-scoped live search over the
    project's docs domain; the raw entry page alone is already an honest
    partial answer when that search finds nothing.
    """
    base_url, source = await resolve_docs_url(engine, library)
    version = (version or "").strip() or None

    # ---- phase 3a: version pinning (GitHub repos only) --------------------
    if version:
        repo = _gh_repo_from(base_url, library)
        if repo:
            vres, v_url, tag = await _resolve_versioned(
                engine, repo, version, max_chars, refresh)
            if vres is not None:
                raw_text = vres.page.text or ""
                home_slim = distill.slim_markdown(raw_text)
                home_distilled = distill.passages(home_slim, query, max_chars)
                sub_texts: list[tuple[str, str]] = []
                sub_urls: list[str] = []
                sub_failed: list[str] = []
                # raw pages are linkless markdown: discover query-relevant
                # pages with one site-scoped search over the project docs
                # domain, not raw.githubusercontent.com.
                host = (repo[1] if "." in repo[1] else repo[1] + ".github.io")
                if subpages > 0:
                    found = await _search_subpages(engine, repo[1],
                                                   f"https://{host}/", query,
                                                   limit=subpages)
                    per = max(max_chars // (len(found) + 1), 300) if found else 0
                    sub_texts, sub_failed = await _fetch_subpages(
                        engine, found, query, per, refresh)
                    sub_urls = [u for u, _ in sub_texts]
                return _assemble_digest(
                    library, v_url, f"{source}+raw@{tag}", vres,
                    home_distilled=home_distilled, sub_texts=sub_texts,
                    sub_urls=sub_urls, sub_failed=sub_failed, version_note="")
            note = (f"Версия {version}: источник на GitHub не найден, "
                    f"показана последняя документация")
        else:
            note = (f"Версия {version}: пиннинг версий поддержан только для "
                    f"GitHub-репозиториев, показана последняя документация")
    else:
        note = ""

    # ---- latest-docs path (seed / user-index / search / plain github) -----
    res = await engine._read(base_url, query=query, max_chars=max_chars, refresh=refresh)
    home_slim = distill.slim_markdown(res.page.text)
    home_distilled = distill.passages(home_slim, query, max_chars)

    sub_texts, sub_urls, sub_failed = [], [], []
    if subpages > 0:
        raw = res.page.text or ""
        pages = _extract_subpages(raw, base_url, query, limit=subpages)
        if not pages:
            # linkless home: one targeted site-search. With `version` given
            # on a doc-site path (no repo behind it) the version rides along
            # in the query — better ranking on sites that keep old versions
            # indexable.
            if version:
                pages = await _search_subpages(engine, library, base_url,
                                               f"{query} {version}", limit=subpages)
            else:
                pages = await _search_subpages(engine, library, base_url, query, limit=subpages)
        per = max(max_chars // (len(pages) + 1), 300)
        sub_texts, sub_failed = await _fetch_subpages(engine, pages, query, per, refresh)
        sub_urls = [u for u, _ in sub_texts]

    return _assemble_digest(
        library, base_url, source, res,
        home_distilled=home_distilled, sub_texts=sub_texts,
        sub_urls=sub_urls, sub_failed=sub_failed, version_note=note)
