#!/usr/bin/env python3
"""Standalone helper: build mixed-session Stage 1 records from a positive and a
negative unified-schema JSONL file.

This is a thin convenience wrapper around the same remapping logic used by
scripts/build_stage1_eval_sets.py. For the full pilot mixed set prefer:

    python scripts/build_stage1_eval_sets.py

This script remains for ad-hoc "positive + 2 negatives" bundles.
"""
from __future__ import annotations

import argparse
import os
import random
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from build_stage1_eval_sets import build_bundle  # noqa: E402
from lib.io_utils import read_jsonl, write_jsonl  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--positive", required=True, type=Path)
    parser.add_argument("--negative", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--n", type=int, default=10)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    rng = random.Random(args.seed)
    positives = read_jsonl(args.positive)
    negatives = read_jsonl(args.negative)
    if not positives or not negatives:
        raise SystemExit("Both positive and negative files must be non-empty.")
    if any(not r.get("input", {}).get("sessions", [{}])[0].get("turns") for r in negatives):
        raise SystemExit("Negative scenarios must be filled before building mixed sessions.")

    rows = []
    for i in range(args.n):
        pos = rng.choice(positives)
        negs = rng.sample(negatives, k=min(2, len(negatives)))
        sources = [negs[0], pos] + ([negs[-1]] if len(negs) > 1 else [])
        rows.append(build_bundle("hard_mixed_positive", i, sources, rng))

    n = write_jsonl(args.out, rows)
    print(f"[make-mixed] wrote {n} mixed records -> {args.out}")


if __name__ == "__main__":
    main()
