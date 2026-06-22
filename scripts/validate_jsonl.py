#!/usr/bin/env python3
"""Lightweight JSONL validator for pilot files."""
from __future__ import annotations
import argparse, json
from pathlib import Path


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("path", type=Path)
    args = p.parse_args()
    n = 0
    for i, line in enumerate(args.path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        obj = json.loads(line)
        assert "scenario_id" in obj, f"line {i}: missing scenario_id"
        assert "input" in obj, f"line {i}: missing input"
        assert "gold" in obj, f"line {i}: missing gold"
        n += 1
    print(f"ok: {n} records")

if __name__ == "__main__":
    main()
