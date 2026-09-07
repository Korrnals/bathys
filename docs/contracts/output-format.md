# Контракт формата вывода — Bathys

Версия: v0.4.0. Источники: `src/bathys/core.py`, `src/bathys/batch.py`, `src/bathys/server.py`. Потребитель грамматик — `docs/operations/metrics.md` (§3.1, регекспы футеров).

## Футеры

Каждый ответ инструмента заканчивается строкой-футером `[bathys: …]` с разделителем `·` (U+00B7).

| Инструмент | Грамматика |
|---|---|
| `web_search`, HIT | `[bathys: {hits} hits · cache HIT · {secs}s · searx json {in} ch → {out} ch]` |
| `web_search`, MISS | `[bathys: {hits} hits · {secs}s · searx json {in} ch → {out} ch]` |
| `read_url` | `[bathys: page {in} ch → {out} ch · {query-distilled\|head-trimmed\|robots-refused} · cache {HIT\|MISS} · {secs}s]` |
| `read_urls` | `[bathys: batch {n} urls · {ok}/{n} ok · {in} ch fetched → {out} ch returned · {secs}s]` |
| `deep_research` | `[bathys: {raw_hits} raw hits, top {n} considered · dove {k} pages · {in} ch fetched → {out} ch returned · {secs}s]` |

Режим `robots-refused` (v0.4): страница не читалась — robots.txt хоста запрещает путь для краулеров; тело при этом `# {url}\n{url}\n\n(not fetched — robots.txt disallows this path: {url})`, поля объёма нулевые, вызов не является ошибкой. Режим `as_json=true` у `web_search` (v0.3): ответ — чистый JSON-объект `{query, count, hits[], answer?}` одной строкой, **без футера** (футер сломал бы строгие json.loads-парсеры; телеметрия такого вызова уходит в `metrics.jsonl`).

Смысл полей: `{hits}` — хитов в ответе; `{raw_hits}` — хитов поиска до усечения `max_results`; `{n}` — рассмотренных (`top`), для `read_urls` — URL после дедупликации и лимита 10; `{k}` — попыток чтения (`dove` — попытки, не успехи); `{ok}` — успешно прочитанных страниц; `{secs}` — секунды вызова (SS.S), для HIT-путей — время подачи из кэша, для MISS — полный сетевой вызов; `{in}`/`{out}` — **символы** до/после сжатия, одна шкала для всех полей (без суффиксов и пересчётов).

## Шкала `ch` (бывшее отклонение K1 — закрыто в v0.2)

До v0.2 `_tok` печатал две шкалы под меткой «tok» (`chars/4` для малых значений, тысячи символов для больших) — сжатие приукрашивалось примерно в 4 раза. С v0.2 каждое поле объёма — честное число символов (`_ch` в `core.py`): например `page 17063 ch → 2325 ch` означает сжатие 7.3×. Пересчёт в токены — забота потребителя (грубая оценка: `tokens ≈ chars / 4`), Bathys шкалу не подменяет.

## Строки `Answer:` / `Refine:`

| Строка | Где | Условие |
|---|---|---|
| `Answer: {текст}` | `web_search`, `deep_research` (вторым блоком после заголовка) | SearXNG вернул direct answers; берётся первый |
| `Refine: {q1, q2, …}` | `web_search`, последняя строка тела (перед футером) | есть suggestions (≤ 6, через `", "`) |

## Грамматика ошибок

Любое исключение в инструменте SDK оборачивает в `isError=true`; текст, видимый клиенту:

```text
Error executing tool {tool}: {сообщение}
```

Сообщения, порождаемые Bathys: `searxng unreachable at {url}: {класс}: {детали}`; `searxng http {код}[- enable JSON in searxng settings: search.formats: [html, json]]`; `searxng at {url} is not answering ({причина}); BATHYS_AUTO_START=0 disables the built-in backend`; `could not start searxng backend — {попытки через "; "}`; `git checkout {ref} failed: {детали}`; `crawl failed: {причина}`; переигранная кэшированная ошибка страницы — `{Класс}: {сообщение}`. Пустая выдача поиска — **не** ошибка: тело `No results for: {query}` при `isError=false`; с v0.2 при срабатывании ретраев тело расширяется суффиксами через ` · `: `No results for: {query} · tried {n} engine sets · unresponsive: {движок:причина, …}` (суффиксы опциональны, префикс неизменен).

## Политика совместимости

- Футер расширяется **только добавлением полей в конец, перед `]`**: существующие регекспы §3.1 обязаны продолжать матчить.
- Запрещено переименовывать, переупорядочивать и удалять существующие поля, менять разделитель `·` и скобочную рамку `[bathys: …]`.
- `Answer:`/`Refine:` добавляются/убираются только вместе с обновлением этого контракта и `metrics.md`.
- Переход на шкалу `ch` и добавление `{secs}s` (v0.2) — единственное состоявшееся ломающее изменение; оно было заранее объявлено (K1) и проведено одним коммитом с регекспами `metrics.md` §3.1. v0.2.1 добавила только новую грамматику для нового инструмента `read_urls` — существующие футеры и регекспы не затронуты. Следующее изменение футера — только через новую ревизию этого контракта.

Связанные документы: параметры инструментов — `mcp-tools.md`; инварианты модулей — `module-contracts.md`; окружение — `config.md`.
