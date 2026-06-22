#!/usr/bin/env python3
"""Build a balanced sample for the Stage 1 progressive-disclosure experiment.

Picks `--per-type` records from each generation_type across the single and mixed
eval sets (deterministic, seeded). Writes the full unified records (gold + turns)
to results/experiment/sample.jsonl so the runner and analysis are self-contained.
"""
from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SINGLE = REPO / "data/generated/single/stage1_single_eval_v0.jsonl"
MIXED = REPO / "data/generated/mixed/stage1_mixed_eval_v0.jsonl"
OUT = REPO / "results/experiment/sample.jsonl"


def read_jsonl(p: Path) -> list[dict]:
    return [json.loads(l) for l in p.open(encoding="utf-8") if l.strip()]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-type", type=int, default=4)
    ap.add_argument("--per-type-mixed", type=int, default=3)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--include-mixed", action="store_true", default=True)
    ap.add_argument("--no-mixed", dest="include_mixed", action="store_false")
    ap.add_argument("--multi-session-only", action="store_true", default=False,
                    help="keep only records with >1 session (for session-level disclosure)")
    ap.add_argument("--all", action="store_true", default=False,
                    help="take every matching record instead of --per-type sampling")
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args()

    rng = random.Random(args.seed)
    rows = read_jsonl(SINGLE)
    sources = [("single", args.per_type)]
    if args.include_mixed:
        rows = rows + read_jsonl(MIXED)
        # tag mixed records by their own source via generation_type membership below

    if args.multi_session_only:
        rows = [r for r in rows if len(r["input"]["sessions"]) > 1]

    by_type: dict[str, list[dict]] = {}
    for r in rows:
        by_type.setdefault(r.get("generation_type", "?"), []).append(r)

    mixed_types = {"easy_mixed_positive", "hard_mixed_positive", "pre_event_mixed",
                   "all_negative", "cancelled_sequence"}

    picked: list[dict] = []
    for gtype in sorted(by_type):
        pool = sorted(by_type[gtype], key=lambda r: r["conversation_id"])
        if args.all:
            picked.extend(pool)
            continue
        k = args.per_type_mixed if gtype in mixed_types else args.per_type
        k = min(k, len(pool))
        picked.extend(rng.sample(pool, k))

    picked.sort(key=lambda r: r["conversation_id"])
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as f:
        for r in picked:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    # summary
    counts: dict[str, int] = {}
    for r in picked:
        counts[r["generation_type"]] = counts.get(r["generation_type"], 0) + 1
    print(f"[sample] wrote {len(picked)} records -> {args.out}")
    for t in sorted(counts):
        print(f"  {t}: {counts[t]}")


if __name__ == "__main__":
    main()
