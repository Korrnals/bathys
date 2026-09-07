# Метрики токен-экономики и эксплуатационные SLO — Bathys

| Поле | Значение |
|---|---|
| Статус | фиксировать как рабочую редакцию archcom (участник-аналитик) |
| Дата редакции | 2026-09-06 |
| Контракт футеров | `docs/contracts/output-format.md` |
| Пересмотр порогов | пересматривать после первой недели реального использования — все пороги раздела 4 являются стартовыми |

## 1. Принципы и допущения

- **A1 — счётчик токенов.** Считать `tokens ≈ chars / 4` (грубая оценка, достаточная для сравнительной динамики; для точного учёта расхода контекста модели мерить реальным токенизатором).
- **A2 — футер как первичный источник.** До v0.4 единственным измеримым источником считать футеры ответов инструментов; формат футера зафиксирован как контракт (раздел 3.1, `docs/contracts/output-format.md`). Любое изменение футера трактовать как ломающее изменение метрик.
- **A3 — облачный бейслайн.** Допущение: облачный web-search MCP списывает ≈ 1% месячной квоты агента за один вызов поиска. Это оценка мейнтейнера проекта, не измерение (зафиксировано 2026-09-06; тарифной ссылки нет). Метрику `quota_saved_baseline` не использовать как внешнее обещание и пересчитывать при смене тарифа.
- **A4 — шкала футеров: единая символьная (закрыто в v0.2).** До v0.2 `_tok` смешивал две шкалы (`chars/4` и тысячи символов) и приукрашивал сжатие ~4×; с v0.2 каждое поле объёма в футере — честное число символов (`ch`), а HIT-пути получили `secs`. Сжатие считается напрямую как `chars_in / chars_out`; пересчёт в токены — опциональная оценка потребителя по A1.

### Иерархия метрик

| Уровень | Метрика | Роль |
|---|---|---|
| North Star | `tokens_saved` накопленно за окно | отражать главную ценность — экономию контекста модели |
| Inputs | `compression_ratio` по типам вызовов; `cache_hit_rate` | объяснять, за счёт чего растёт North Star |
| Guardrails | `crawl_success_rate`; доли ошибок; `latency p95` | ограничивать цену экономии (сбои и ожидание) |
| Diagnostics | счётчики `hits`/`dove`; `startup_time`; размер кэша | диагностировать отклонения без влияния на решения |

## 2. Каталог метрик

| Метрика | Формула | Источник данных сегодня | Ограничение |
|---|---|---|---|
| `compression_ratio(search)` | делить `chars_in / chars_out` | парсить футер `web_search` (`searx json X ch → Y ch`) | — |
| `compression_ratio(read, query-distilled)` | делить `chars_in / chars_out` | парсить футер `read_url` при `mode=query-distilled` | — |
| `compression_ratio(read, head-trimmed)` | делить `chars_in / chars_out` | парсить футер `read_url` при `mode=head-trimmed` | учитывать потолок бюджета `max_chars` (дефолт 8000) |
| `compression_ratio(research)` | делить `Σ chars_fetched / Σ chars_returned` | парсить футер `deep_research` (`X ch fetched → Y ch returned`) | агрегировать только по успешно прочитанным страницам |
| `tokens_saved` (за вызов / накопленно) | вычислять `(chars_in − chars_out) / 4`; накапливать Σ за окно | из тех же футеров (единая шкала, без восстановления); после v0.4 — `metrics.jsonl` | считать по A1 |
| `cache_hit_rate(search)` | делить `HIT / (HIT + MISS)` | считать маркеры `cache HIT` в футерах `web_search` | — |
| `cache_hit_rate(pages)` | делить `HIT / (HIT + MISS)` | считать маркеры `cache HIT/MISS` в футерах `read_url` | — |
| `cache_hit_rate(repeat)` | делить `попадания по повторным ключам / повторные вызовы` | сегодня недоступна — ключ вызова в футере не виден | требует `url_hash`/`q_hash` в JSONL (v0.4); прокси на сегодня — общий HIT-share при стабильном наборе запросов |
| `crawl_success_rate` | делить `успешные fetch / попытки fetch` | считать `dove N pages` (попытки) и строки `(not fetched …)` (неудачи) в телах `deep_research`, плюс MISS-футеры `read_url` | помнить: `dove` считает попытки, а не успехи; без парсинга тела успех не виден |
| `error_share(class)` | делить `ошибки класса / все ошибки` | разбирать тексты `(not fetched — Err: …)` эвристикой по строке | классы `captcha`/`timeout` различимы только эвристикой; надёжно — после `error_class` в JSONL (v0.4) |
| `latency_searx p50/p95` | извлекать секунды из MISS-футеров `web_search` (`· X.Xs ·`) | парсить футеры | холодный старт SearXNG исключать |
| `latency_read p50/p95` | извлекать секунды из футера `read_url` (`· X.Xs]`) | парсить футеры (поле с v0.2) | MISS-вызовы включают полный crawl — мерить отдельно от HIT |
| `latency_research p50/p95` | извлекать секунды из футера `deep_research` (`· X.Xs]`) | парсить футеры | включает параллельный crawl до 4 страниц |
| `startup_time` | замерять от старта сервера до первого успешного вызова | сегодня вручную | считать диагностикой, не SLO (подъём headless-браузера и SearXNG дорог) |
| `quota_saved_baseline` | умножать `N_вызовов × 1%` месячной квоты (A3) | считать счётчики вызовов из футеров | опирается на оценку мейнтейнера от 2026-09-06, не измерение; не цитировать externally без оговорки |

Классы ошибок (таксономия для `error_share`): `captcha`, `timeout`, `http_4xx`, `http_5xx`, `conn` (DNS/сеть), `searx` (недоступен/не-200), `other`. Сегодня все классы, кроме грубой эвристики по строке ошибки, сваливаются в `other`.

## 3. Источники данных

### 3.1 Сегодня: футеры (контракт — `docs/contracts/output-format.md`)

Зафиксировать три шаблона футеров как контракт:

```
[bathys: {hits} hits · cache HIT · {secs}s · searx json {in} ch → {out} ch]                        # web_search, HIT
[bathys: {hits} hits · {secs}s · searx json {in} ch → {out} ch]                                    # web_search, MISS
[bathys: page {in} ch → {out} ch · {query-distilled|head-trimmed} · cache {HIT|MISS} · {secs}s]    # read_url
[bathys: batch {n} urls · {ok}/{n} ok · {in} ch fetched → {out} ch returned · {secs}s]             # read_urls
[bathys: {raw_hits} raw hits, top {n} considered · dove {k} pages · {in} ch fetched → {out} ch returned · {secs}s]  # deep_research
```

Опорные regex'ы для парсинга:

```text
web_search:    \[bathys: ([0-9]+) hits · (?:cache HIT · )?([0-9.]+)s · searx json ([0-9]+) ch → ([0-9]+) ch\]
read_url:      \[bathys: page ([0-9]+) ch → ([0-9]+) ch · (query-distilled|head-trimmed) · cache (HIT|MISS) · ([0-9.]+)s\]
read_urls:     \[bathys: batch ([0-9]+) urls · ([0-9]+)/([0-9]+) ok · ([0-9]+) ch fetched → ([0-9]+) ch returned · ([0-9.]+)s\]
deep_research: \[bathys: ([0-9]+) raw hits, top ([0-9]+) considered · dove ([0-9]+) pages · ([0-9]+) ch fetched → ([0-9]+) ch returned · ([0-9.]+)s\]
```

Извлекается сегодня: счётчики вызовов, HIT/MISS, значения `chars_in/chars_out` в одной шкале, latency `web_search` (HIT и MISS), latency `read_url`, секунды research и batch, число попыток dive, доля успешных чтений пакета (`{ok}/{n}`). Не извлекается: классы ошибок (кроме эвристики по `(not fetched — …)`), ключи повторов, per-page cache-состояния внутри `deep_research`.

### 3.2 Реализовано в v0.4: `BATHYS_DATA_DIR/metrics.jsonl`

Пишется по одному событию на вызов инструмента (`Engine._log_metrics`; `BATHYS_METRICS=0` отключает). Фактическая схема (v0.4.0; `mode` из брифа замещён полем `tool`+`cache`, токены-дубли удалены — шкала единая символьная по A4):

```json
{"ts": "2026-09-06T12:00:00+00:00", "tool": "read_url", "cache": "MISS",
 "chars_in": 17000, "chars_out": 2324, "secs": 6.1, "ok": true,
 "error_class": null, "url_hash": "a1b2c3d4e5f6", "q_hash": "0f9e8d7c6b5a"}
```

| Поле | Смысл | Зачем |
|---|---|---|
| `ts, tool, cache, secs, ok, error_class` | фиксировать событие вызова | закрывают SLO по latency и error-долям; `error_class` — имя класса (`SearxError`, `RuntimeError`, спец-значение `robots`) |
| `chars_in / chars_out` | сырые целые символы, одна шкала | сжатие и `tokens_saved` считаются напрямую (A4 закрыт) |
| `url_hash / q_hash` | sha256-префикс 12 hex | repeat-анализ без хранения адресов |
| `cache` | `HIT`/`MISS`/`MIX` (пакет) | hit-rate по типам вызовов |

Агрегация одной командой: `.venv/bin/python scripts/metrics_report.py` — счётчики по инструментам, hit-rate, медианное сжатие, p50/p95 секунд, ошибки по классам, накопленный `tokens_saved` (chars/4). Объём: строка JSON на вызов, append в конец; при одиночном использовании ротация не требуется.

## 4. SLO и стартовые пороги

Все пороги — стартовые значения; пересмотреть после недели реального использования. Отношения сжатия зафиксированы в символьной шкале (A4); брифовое «≥ 15×» для `read` соответствует футерной арифметике — в символьной шкале типичное наблюдение ≈ 7×.

| SLO | Порог | Как измерять сегодня | Статус |
|---|---|---|---|
| `compression_ratio(read, query-distilled)` | ≥ 5× chars | парсить футеры `read_url` | активен; наблюдение 2026-09-06 ≈ 7× |
| `compression_ratio(read, head-trimmed)` | ≥ 1.5× chars | парсить футеры `read_url` | активен; потолок задаёт `max_chars` |
| `compression_ratio(search)` | ≥ 8× chars | парсить футеры `web_search` | активен; наблюдение ≈ 18× |
| `compression_ratio(research)` | ≥ 4× chars | парсить футеры `deep_research` | активен; наблюдение ≈ 5× |
| `cache_hit_rate(repeat)` | ≥ 80% | прокси: HIT-share за окно | строгая версия — с v0.4 (`url_hash`/`q_hash`) |
| `crawl_success_rate` | ≥ 90% | считать `dove` и `(not fetched` в `deep_research` + MISS-футеры `read_url` | активен |
| `error_share(timeout + captcha)` | ≤ 10% попыток | разбирать строки ошибок эвристикой | активен грубо; точно — с v0.4 |
| `latency_searx` p95 (MISS) | ≤ 5s | парсить MISS-футеры `web_search` | активен |
| `latency_read` p95 | ≤ 8s | отсутствует в футерах | вводится с v0.4 |
| `latency_research` p95 | ≤ 40s | парсить футеры `deep_research` | активен; холодный старт исключён (`startup_time` отдельно) |

## 5. Как считать за неделю

Команды выполнять по дампу сессии/логу, содержащему ответы инструментов (`$LOG`).

1. Инвентарь футеров и счётчики вызовов:

```bash
grep -hoE '\[bathys: [^]]+\]' "$LOG" | sort | uniq -c | sort -rn | head -15
```

2. HIT-share по кэшу (поиск + страницы совместно):

```bash
grep -oE 'cache (HIT|MISS)' "$LOG" | awk '{n[$2]++} END {printf "hit=%.0f%% HIT=%d MISS=%d\n", 100*n["HIT"]/(n["HIT"]+n["MISS"]), n["HIT"], n["MISS"]}'
```

3. Агрегированное символьное сжатие research (обе величины в k-ветке — корректно; смешанные ветки дают смещение по A4):

```bash
grep -oE '[0-9]+k? tok fetched → [0-9]+k? tok returned' "$LOG" | awk '{gsub(/k/,"",$1); gsub(/k/,"",$5); i+=$1; o+=$5; n++} END {if(o)printf "research ≈ %.1fx chars over %d calls\n", i/o, n}'
```

4. p50/p95 searx-latency (только MISS-вызовы):

```bash
grep -oE '[0-9.]+s · searx json' "$LOG" | grep -oE '^[0-9.]+' | sort -n | awk '{a[NR]=$1} END {if(!NR)exit; i50=int(NR*0.5+0.5); i95=int(NR*0.95+0.5); if(i95>NR)i95=NR; printf "searx n=%d p50=%.2fs p95=%.2fs\n", NR, a[i50], a[i95]}'
```

5. crawl_success_rate по research (попытки = Σ `dove`, неудачи = строки `not fetched`):

```bash
awk '/raw hits, top .*dove /{s=$0; sub(/.*dove /,"",s); sub(/ pages.*/,"",s); d+=s} /\(not fetched/{f++} END {if(d)printf "attempts=%d fail=%d success=%.0f%%\n", d, f, 100*(d-f)/d}' "$LOG"
```

6. После v0.4 — p50/p95 `read_url` из `metrics.jsonl` (будущий формат):

```bash
jq -s '[.[].secs | numbers] | sort | {n: length, p50: .[(length/2|floor)], p95: .[(length*0.95|floor)]}' <(grep '"tool":"read_url"' "$BATHYS_DATA_DIR/metrics.jsonl")
```

## 6. Слепые зоны и что добавить в v0.4

Слепые зоны, не закрываемые футерами:

- качество дистилляции: compression измеряет экономию, но не полезность; отсутствует guardrail «агент получил ответ с первого вызова» — прокси (повторные `read_url` того же URL) требует `url_hash`;
- latency `read_url` и latency cache-HIT вызовов `web_search` не фиксируются вовсе — два SLO раздела 4 без этого мертвы или проксируются;
- классы ошибок эвристичны: `captcha` от `timeout` отличает только текст сообщения crawl4ai;
- `dove N pages` в футере `deep_research` считает попытки, успехи видны только по телу ответа;
- нет корреляции с сессией — накопленный `tokens_saved` нельзя отнести к задаче пользователя.

В v0.4 добавить (приоритет по убыванию):

1. `metrics.jsonl` по схеме раздела 3.2 — закрывает latency, `error_class` и repeat-анализ.
2. Добавить `secs` в футеры `read_url` и cache-HIT `web_search` — дешёвое расширение контракта, оживляющее два SLO до появления JSONL.
3. Ввести структурный `error_class` в точках raise (`src/bathys/crawler.py`, `src/bathys/searx.py`).
4. Унифицировать `_tok`: либо метка «k chars», либо единая ветка `chars/4` — устраняет допущение A4.
5. (Опционально) недельный саммари одной командой: печатать таблицу раздела 4 из `metrics.jsonl`.
