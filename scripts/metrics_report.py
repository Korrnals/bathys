"""Aggregate metrics.jsonl into the dashboard of docs/operations/metrics.md §2.

Run:  .venv/bin/python scripts/metrics_report.py [path-to-metrics.jsonl]
"""

import json
import statistics
import sys
from collections import Counter
from pathlib import Path


def p95(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(round(0.95 * len(ordered))) - (1 if len(ordered) > 1 else 0))]


def main() -> None:
    path = Path(sys.argv[1] if len(sys.argv) > 1 else
                Path.home() / ".local/share/bathys/metrics.jsonl")
    if not path.is_file():
        print(f"no metrics yet: {path}")
        return
    events = [json.loads(l) for l in path.open(encoding="utf-8") if l.strip()]

    by_tool: Counter = Counter(e["tool"] for e in events)
    print(f"events: {len(events)} ({path})")
    print("calls per tool:", dict(by_tool))

    for tool in sorted(by_tool):
        rows = [e for e in events if e["tool"] == tool]
        hits = [e for e in rows if e.get("cache") == "HIT"]
        misses = [e for e in rows if e.get("cache") == "MISS"]
        comp = [e["chars_in"] / e["chars_out"] for e in rows
                if e.get("chars_out") and e.get("chars_in")]
        secs = [e["secs"] for e in rows]
        errs = Counter(e["error_class"] for e in rows if not e.get("ok", True))
        hit_rate = len(hits) / (len(hits) + len(misses)) if (hits or misses) else None
        print(f"\n{tool}: n={len(rows)}"
              + (f" · cache HIT {hit_rate:.0%}" if hit_rate is not None else "")
              + (f" · compression median {statistics.median(comp):.1f}x" if comp else "")
              + f" · secs p50 {statistics.median(secs):.1f} p95 {p95(secs):.1f}"
              + (f" · errors {dict(errs)}" if errs else ""))

    total_saved = sum(e["chars_in"] - e["chars_out"] for e in events
                      if e.get("chars_in") and e.get("chars_out"))
    print(f"\ntokens saved (rough, chars/4): ~{max(total_saved, 0) // 4:,}")


if __name__ == "__main__":
    main()
