"""Bathys — единый локальный поисковый сервис глубокого ресёрча (MCP, stdio).

Owns the whole pipeline (search -> extraction -> query distillation -> cache);
SearXNG and Crawl4AI are swappable internal engines, not the product.

Four tools, deliberately small surface:
  deep_research(query) — search + read top sources + query-distilled digest;
  web_search(query)    — ranked links only;
  read_url(url, query) — distilled text of one page;
  read_urls(urls, …)   — batch read of known URLs under one shared budget.

Plus three prompts (bathys_deep_research, bathys_source_audit,
bathys_fresh_scan) — built-in research strategies the harness can render.
"""

from __future__ import annotations

import contextlib
import sys

from mcp.server.fastmcp import Context, FastMCP
from mcp.types import ToolAnnotations

from . import batch
from .config import Config
from .core import Engine


@contextlib.asynccontextmanager
async def _lifespan(_: FastMCP):
    engine = Engine(Config.load())
    await engine.start()
    try:
        yield engine
    finally:
        await engine.stop()


mcp = FastMCP(
    "bathys",
    instructions=(
        "Bathys — единый локальный поисковый сервис глубокого ресёрча: конвейер "
        "поиск → извлечение → дистилляция → кэш целиком на вашей машине, ноль "
        "облачных квот и API-ключей.\n\n"
        "Матрица выбора инструмента:\n"
        "- исследовательский вопрос («что/как/почему/сравни») → "
        "deep_research(query): ищет, читает топ-источники, возвращает "
        "дистиллят под запрос;\n"
        "- нужны только ссылки → web_search(query); для программы/скрипта — "
        "web_search(…, as_json=true);\n"
        "- один известный URL → read_url(url, query=…);\n"
        "- несколько известных URL (до 10) → read_urls(urls, query=…): один "
        "вызов, общий бюджет, битая страница стоит строку.\n\n"
        "Правила:\n"
        "- запрос — вопрос, а не мешок ключевых слов: дистиллятор отбирает "
        "пассажи по смыслу запроса;\n"
        "- максимум 3 итерации по одной формулировке, дальше — смена угла "
        "(web_search + read_urls по иным доменам), не шестой заход;\n"
        "- подтверждённое утверждение — два независимых источника (разные "
        "домены); один источник — «по данным одного источника»; конфликт "
        "источников фиксируй явно, не выбирай молча сторону;\n"
        "- свежесть — time_range (\"day\"/\"week\"/\"month\"/\"year\"); "
        "refresh=true дорог (ломает кэш): только при протухшем кэше — cache "
        "HIT при устаревших данных в дистилляте — и один раз на главный "
        "источник.\n\n"
        "Семантика сигналов:\n"
        "- \"(not fetched — …)\" — источник не прочитан, причина рядом; это не "
        "провал, используй остальные секции;\n"
        "- robots-refused — сайт запретил краулер: уважай запрет, ищи другой "
        "источник;\n"
        "- \"No results … tried N engine sets\" — поисковики капризничали, "
        "Bathys уже ретраился: смягчи формулировку (синонимы, язык, "
        "category);\n"
        "- \"Answer:\" — мгновенный справочный ответ: годится как факт, "
        "спорное подтверди источником;\n"
        "- футер \"[bathys: …]\" — статистика (cache/secs/ch), не для "
        "цитирования.\n\n"
        "Готовые стратегии — промпты bathys_deep_research, "
        "bathys_source_audit, bathys_fresh_scan. Цитируй URL источников из "
        "секций ответов — это твой след аудита."
    ),
    lifespan=_lifespan,
)


def _engine(ctx: Context) -> Engine:
    return ctx.request_context.lifespan_context


@mcp.tool(annotations=ToolAnnotations(
    title="Глубокое исследование: поиск + чтение + дистиллят",
    readOnlyHint=True,
    openWorldHint=True,
))
async def deep_research(
    query: str,
    max_sources: int = 3,
    max_results: int = 10,
    per_source_chars: int = 3500,
    time_range: str | None = None,
    category: str | None = None,
    language: str | None = None,
    refresh: bool = False,
    ctx: Context = None,
) -> str:
    """Search the web AND read the top sources in one shot.

    Runs SearXNG metasearch, dives into the top max_sources pages with a real
    browser, distills each page down to passages relevant to `query`, and
    returns one merged digest. Best first call for any research question.
    Args:
        query: research question or keywords (RU/EN both fine)
        max_sources: how many top hits to read in full (1-6)
        max_results: how many search hits to consider (1-20)
        per_source_chars: per-source character budget (300-8000)
        time_range: "day" | "week" | "month" | "year"
        category: searxng category, e.g. "general", "news", "science", "it"
        language: result language, e.g. "ru", "en", "ru-RU"
        refresh: ignore cache and re-fetch search results and pages
    """
    return await _engine(ctx).research(
        query, max_sources=max_sources, max_results=max_results,
        per_source_chars=per_source_chars, category=category,
        engines=None, language=language, time_range=time_range, refresh=refresh,
    )


@mcp.tool(annotations=ToolAnnotations(
    title="Веб-поиск: ранжированные ссылки",
    readOnlyHint=True,
    openWorldHint=True,
))
async def web_search(
    query: str,
    max_results: int = 8,
    time_range: str | None = None,
    category: str | None = None,
    engines: str | None = None,
    language: str | None = None,
    refresh: bool = False,
    as_json: bool = False,
    ctx: Context = None,
) -> str:
    """Search the web via SearXNG metasearch; return a compact ranked link list.

    Returns title, URL and a short snippet per hit — no page content. Empty or
    blocked results are retried automatically with other engine sets.
    To actually read pages, call read_url; to do both at once, call deep_research.
    Args:
        query: search query (natural language or keywords)
        max_results: 1-20
        time_range: "day" | "week" | "month" | "year"
        category: e.g. "general", "news", "science", "it", "files"
        engines: comma-separated engine names, e.g. "google,bing,duckduckgo"
        language: e.g. "ru", "en", "ru-RU"
        refresh: ignore cache and re-run the search
        as_json: return pure machine-readable JSON {query, count, hits[], answer?}
            instead of the human-friendly list (no footer line)
    """
    return await _engine(ctx).search(
        query, max_results=max_results, category=category,
        engines=engines, language=language, time_range=time_range,
        refresh=refresh, as_json=as_json,
    )


@mcp.tool(annotations=ToolAnnotations(
    title="Чтение одной страницы",
    readOnlyHint=True,
    openWorldHint=True,
))
async def read_url(
    url: str,
    query: str | None = None,
    max_chars: int = 8000,
    refresh: bool = False,
    ctx: Context = None,
) -> str:
    """Read one web page; return its main content as clean, budgeted markdown.

    JS-rendered pages are handled by a real headless browser. Boilerplate
    (nav, footer, ads) is stripped; if `query` is given, only passages relevant
    to it are returned. Pages are cached — re-reads with a different query are
    instant and cost no network.
    Args:
        url: absolute http(s) URL
        query: optional focus; return only passages relevant to it
        max_chars: output character budget (300-50000)
        refresh: ignore cache and re-fetch the page
    """
    return await _engine(ctx).read(url, query=query, max_chars=max_chars, refresh=refresh)


@mcp.tool(annotations=ToolAnnotations(
    title="Пакетное чтение до 10 страниц",
    readOnlyHint=True,
    openWorldHint=True,
))
async def read_urls(
    urls: list[str],
    query: str | None = None,
    total_chars: int = 12000,
    refresh: bool = False,
    ctx: Context = None,
) -> str:
    """Read several known web pages in one call under one shared character budget.

    Pages are fetched in parallel (JS-rendered, boilerplate-stripped) and the
    combined total_chars budget is split evenly between the pages that came
    back. Prefer this over N read_url calls when you already hold the URLs:
    one round-trip, one budget, and a failed page costs one line instead of
    a failed call.
    Args:
        urls: 1-10 absolute http(s) URLs; duplicates (after utm/fragment
            cleanup) are merged, extras beyond 10 are reported in a Skipped line
        query: optional focus; each page is distilled to passages relevant to it
        total_chars: combined output budget across all sections (300-30000)
        refresh: ignore cache and re-fetch every page
    """
    return await batch.read_many(
        _engine(ctx), urls, query=query, total_chars=total_chars, refresh=refresh,
    )


# --- Built-in strategy prompts (rendered via get_prompt, see agents/skills/) ---

@mcp.prompt(description="Глубокое исследование одного вопроса за 1–3 итерации: "
                        "заход, разбор, уточнение терминами источников, верификация, синтез.")
def bathys_deep_research(question: str, time_range: str = "") -> str:
    """Стратегия глубокого исследования одного вопроса за 1–3 итерации.

    Args:
        question: исследовательский вопрос (не мешок ключевых слов)
        time_range: свежесть day|week|month|year; пусто — без фильтра
    """
    tr = f', time_range="{time_range}"' if time_range else ""
    return f"""# Глубокое исследование: {question}

Процедура — максимум 3 итерации, дальше смена угла, не шестой заход.

1. Заход: deep_research(query="{question}"{tr}, max_sources=3) — без
   предварительного web_search: первый вызов уже ищет и читает
   топ-источники.
2. Разбор дистиллята: из секций ответа выпиши (a) что отвечает на вопрос,
   (b) что противоречит, (c) каких данных не хватает.
3. Уточнение: переформулируй запрос терминами из (a)–(c) — терминами
   предметной области, найденными в источниках, не своими синонимами — и
   повтори deep_research. Не хватает конкретики: web_search по узкому
   термину, затем read_urls по 2–4 лучшим URL с query="{question}".
4. Верификация: ключевое утверждение подтверждено при двух независимых
   доменах; конфликт — покажи обе версии с URL, не выбирай молча сторону.
5. Синтез: вывод — первым предложением; затем 3–7 пунктов, у каждого
   нетривиального факта — URL; в конце — «что не удалось проверить».

Сигналы: «(not fetched — …)» — не провал, работай с остальными секциями;
robots-refused — уважай запрет, ищи другой источник; футер [bathys: …] —
статистика, не цитируй. Дистиллят — сырьё: твой результат — синтез, а не
пересказ."""


@mcp.prompt(description="Аудит утверждения по списку URL: чтение под тезис, "
                        "кросс-поиск опровержений, вердикты по каждому пункту.")
def bathys_source_audit(claim: str, urls: str) -> str:
    """Аудит утверждения по списку URL: чтение под тезис, кросс-поиск опровержений, вердикты.

    Args:
        claim: проверяемое утверждение словами
        urls: 1–10 URL через запятую или пробел
    """
    url_list = "\n".join(
        f"- {u}" for u in urls.replace(",", " ").split() if u
    ) or "- (пусто: сначала добери URL через web_search)"
    return f"""# Аудит утверждения: {claim}

Источники на проверку:
{url_list}

Процедура:

1. Пакетное чтение: read_urls(urls, query="{claim}") — дистилляция
   вплотную к проверяемому утверждению, не «вообще о чём статья». Битые
   URL отвалятся строкой «(not fetched — …)» — это не провал.
2. Контекст каждого источника: домен/автор, дата публикации,
   первоисточник или пересказ. Два пересказа одного пресс-релиза —
   один источник, не два.
3. Кросс-поиск опровержений: deep_research("{claim}" + «критика /
   опровержение / альтернативы») — ищи расхождения, а не подтверждения;
   при споре об актуальности добавь time_range.
4. Свежесть: проверяешь «как сейчас» — один refresh=true на главный
   источник, не на весь пакет.
5. Вердикт по каждому тезису: подтверждено (≥2 независимых домена) /
   частично (1 источник) / опровергнуто (опровержение с URL) /
   непроверяемо (404, robots-refused — указать причину).

Выход: таблица «тезис → вердикт → источники (URL)» плюс абзац общего
вывода; каждый вердикт обязан содержать хотя бы один URL либо явную
причину его отсутствия."""


@mcp.prompt(description="Свежий срез по теме за окно времени: отбор значимых "
                        "событий, пакетное чтение, сводка с датами и URL.")
def bathys_fresh_scan(topic: str, window: str = "week") -> str:
    """Свежий срез по теме: поиск в окне, отбор значимого, пакетное чтение, сводка с датами.

    Args:
        topic: тема среза
        window: окно свежести day|week|month|year
    """
    return f"""# Свежий срез: {topic}

Процедура:

1. web_search(query="{topic}", time_range="{window}", max_results=8) —
   только свежая выдача; не расширяй окно без необходимости.
2. Отбери 3–5 значимых событий/изменений; отсей дубли — пересказы одного
   релиза в разных изданиях считаются одним событием.
3. read_urls(выбранные URL, query="{topic}") — один вызов, общий бюджет;
   читай только то, что реально поясняет срез.
4. Сводка: события и изменения по убыванию значимости; каждый пункт —
   с датой и URL. Конфликт дат или версий между источниками — покажи обе
   версии, не выбирай молча сторону.
5. Подозрение протухшего кэша — cache HIT при устаревшей дате в
   дистилляте — единственный refresh=true на главный источник, не на
   весь пакет.

Выход: плотная сводка «что произошло / что изменилось» с датами и URL,
без пересказа дистиллятов целиком; спорный пункт на одном источнике
помечай «по данным одного источника»."""


def _describe_prompt_args(*names: str) -> None:
    """Fill PromptArgument.description from each prompt docstring's Args section.

    mcp 1.29 func_metadata does not carry docstring Args into the argument
    schema, so @prompt() alone yields description=None on the wire; FastMCP
    has no public accessor for a registered Prompt, hence _prompt_manager.
    Fails loudly if the internals ever move.
    """
    for name in names:
        prompt = mcp._prompt_manager.get_prompt(name)
        docs: dict[str, str] = {}
        in_args = False
        for line in (prompt.fn.__doc__ or "").splitlines():
            stripped = line.strip()
            if stripped == "Args:":
                in_args = True
            elif in_args and stripped:
                key, sep, value = stripped.partition(":")
                if sep and value:
                    docs[key.strip()] = value.strip()
        prompt.arguments = [
            a.model_copy(update={"description": docs.get(a.name)})
            for a in prompt.arguments or []
        ]


_describe_prompt_args(
    "bathys_deep_research", "bathys_source_audit", "bathys_fresh_scan",
)


def _hush_stdout_logs() -> None:
    """MCP stdio owns stdout; any library handler pointed at it moves to stderr."""
    import logging
    import sys

    for name in ("", "crawl4ai", "playwright"):
        for h in logging.getLogger(name).handlers:
            if getattr(h, "stream", None) is sys.stdout:
                h.stream = sys.stderr


def main() -> None:
    argv = sys.argv[1:]
    if argv and argv[0] in ("install", "doctor", "setup"):
        # Console-style subcommands: one entry point covers the MCP server
        # and the setup tooling, so `pip install bathys` is all a user needs.
        from . import doctor, installer

        if argv[0] == "install":
            sys.argv = ["bathys install", *argv[1:]]
            raise SystemExit(installer.main())
        if argv[0] == "setup":
            sys.argv = ["bathys setup", *argv[1:]]
            raise SystemExit(installer.setup())
        sys.argv = ["bathys doctor", *argv[1:]]
        raise SystemExit(doctor.main())
    if argv and argv[0] in ("-h", "--help", "help"):
        print("bathys — единый локальный поисковый сервис глубокого ресёрча (MCP, stdio)\n"
              "\n"
              "Использование:\n"
              "  bathys                        запустить MCP-сервер (stdio; для харнесса)\n"
              "  bathys setup                  полная установка: браузер → все найденные\n"
              "                                харнессы → субагент → самодиагностика\n"
              "  bathys install [HARNESS…]     автоподключение всех харнессов или точечное\n"
              "                                (bathys install hermes; --list, --print-config)\n"
              "  bathys doctor [--full]        диагностика стека\n")
        return
    _hush_stdout_logs()
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
