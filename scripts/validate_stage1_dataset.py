#!/usr/bin/env python3
"""Quality + leakage report over generated Stage 1 data.

Scans the per-type single files (and the mixed eval set) and writes a report to:
  data/generated/quality_reports/stage1_quality_report.json
  data/generated/quality_reports/stage1_quality_report.md
"""
from __future__ import annotations

import argparse
import os
import sys
from collections import Counter
from pathlib import Path
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lib import dialogue_validation as dv  # noqa: E402
from lib.io_utils import read_jsonl, read_yaml, write_json  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
SINGLE_DIR = REPO / "data" / "generated" / "single"
MIXED_DIR = REPO / "data" / "generated" / "mixed"
REPORT_DIR = REPO / "data" / "generated" / "quality_reports"

PER_TYPE_FILES = [
    "occurred_positive.jsonl",
    "no_event_neutral.jsonl",
    "hard_negative.jsonl",
    "existing_state_negative.jsonl",
    "pre_event_weak_signal.jsonl",
    "pre_event_upcoming.jsonl",
    "cancelled_reversed.jsonl",
]

NO_EVENT_TYPES = {"neutral_no_event", "hard_negative", "existing_state_negative"}


def default_inputs() -> list[Path]:
    paths = [SINGLE_DIR / f for f in PER_TYPE_FILES if (SINGLE_DIR / f).exists()]
    mixed = MIXED_DIR / "stage1_mixed_eval_v0.jsonl"
    if mixed.exists():
        paths.append(mixed)
    return paths


def count_turns(record: dict[str, Any]) -> tuple[int, int]:
    total = user = 0
    for _, t in dv.iter_turns(record):
        total += 1
        if t.get("speaker") == "user":
            user += 1
    return total, user


def analyze(records: list[dict[str, Any]], cfg: dict[str, Any]) -> dict[str, Any]:
    by_type: Counter = Counter()
    by_label: Counter = Counter()
    by_action: Counter = Counter()
    turn_totals: list[int] = []
    user_totals: list[int] = []

    invalid = 0
    direct_label_leaks = 0
    chatbot_leaks = 0
    evidence_invalid = 0
    no_event_with_events = 0
    event_related_empty = 0
    pre_event_bad_occurred = 0
    cancelled_bad_occurred = 0
    flagged_examples: list[dict[str, Any]] = []

    for r in records:
        gtype = r.get("generation_type", "unknown")
        by_type[gtype] += 1
        by_label[r.get("target_life_event", "n/a")] += 1
        by_action[r.get("target_action_id") or "null"] += 1

        total, user = count_turns(r)
        turn_totals.append(total)
        user_totals.append(user)

        issues = dv.validate_record(r, cfg)
        if issues:
            invalid += 1
            flagged_examples.append({"conversation_id": r.get("conversation_id"),
                                     "generation_type": gtype, "issues": issues})

        # leakage counts (text-level)
        for _, t in dv.iter_turns(r):
            text = t.get("text", "")
            if dv.direct_label_hits(text):
                direct_label_leaks += 1
            if t.get("speaker") == "assistant" and dv.chatbot_leakage_hits(text):
                chatbot_leaks += 1

        gold = r.get("gold", {})
        life_events = gold.get("life_events", [])
        u_ids = dv.user_turn_ids(r)
        for ev in life_events:
            for tid in ev.get("evidence_turns", []) or []:
                if tid not in u_ids:
                    evidence_invalid += 1

        relation = gold.get("event_relation")
        if relation == "no_event" and life_events:
            no_event_with_events += 1
        if relation == "event_related" and not life_events:
            event_related_empty += 1

        if gtype in ("pre_event_weak_signal", "pre_event_upcoming"):
            if any(ev.get("occurred") is True for ev in life_events):
                pre_event_bad_occurred += 1
        if gtype == "cancelled_reversed":
            if any(ev.get("occurred") is True for ev in life_events):
                cancelled_bad_occurred += 1

    n = len(records)
    return {
        "total_records": n,
        "records_by_generation_type": dict(by_type),
        "records_by_event_label": dict(by_label),
        "records_by_action_id": dict(by_action),
        "avg_turns": round(sum(turn_totals) / n, 2) if n else 0,
        "avg_user_turns": round(sum(user_totals) / n, 2) if n else 0,
        "invalid_records": invalid,
        "direct_label_leakage_count": direct_label_leaks,
        "chatbot_leakage_count": chatbot_leaks,
        "invalid_evidence_turns": evidence_invalid,
        "no_event_records_with_life_events": no_event_with_events,
        "event_related_records_with_empty_life_events": event_related_empty,
        "pre_event_incorrectly_marked_occurred": pre_event_bad_occurred,
        "cancelled_incorrectly_marked_occurred": cancelled_bad_occurred,
        "flagged_examples": flagged_examples,
    }


def to_markdown(report: dict[str, Any]) -> str:
    lines = ["# Stage 1 Dataset Quality Report", ""]
    lines.append(f"- Total records: **{report['total_records']}**")
    lines.append(f"- Avg turns / record: {report['avg_turns']}")
    lines.append(f"- Avg user turns / record: {report['avg_user_turns']}")
    lines.append("")
    lines.append("## Records by generation type")
    for k, v in sorted(report["records_by_generation_type"].items()):
        lines.append(f"- {k}: {v}")
    lines.append("")
    lines.append("## Records by target life event")
    for k, v in sorted(report["records_by_event_label"].items()):
        lines.append(f"- {k}: {v}")
    lines.append("")
    lines.append("## Records by target action id")
    for k, v in sorted(report["records_by_action_id"].items()):
        lines.append(f"- {k}: {v}")
    lines.append("")
    lines.append("## Integrity checks")
    checks = [
        ("Invalid records (validation flags)", report["invalid_records"]),
        ("Direct life-event label leakage (turns)", report["direct_label_leakage_count"]),
        ("Chatbot leakage phrases (turns)", report["chatbot_leakage_count"]),
        ("Invalid evidence turns (non-user)", report["invalid_evidence_turns"]),
        ("no_event records with life_events", report["no_event_records_with_life_events"]),
        ("event-related records with empty life_events", report["event_related_records_with_empty_life_events"]),
        ("pre_event incorrectly marked occurred", report["pre_event_incorrectly_marked_occurred"]),
        ("cancelled incorrectly marked occurred", report["cancelled_incorrectly_marked_occurred"]),
    ]
    for name, val in checks:
        mark = "✅" if val == 0 else "⚠️"
        lines.append(f"- {mark} {name}: {val}")
    lines.append("")
    if report["flagged_examples"]:
        lines.append("## Flagged examples")
        for ex in report["flagged_examples"]:
            lines.append(f"- `{ex['conversation_id']}` ({ex['generation_type']}):")
            for issue in ex["issues"]:
                lines.append(f"    - {issue}")
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Stage 1 dataset quality report")
    parser.add_argument("--inputs", nargs="*", type=Path, default=None)
    parser.add_argument("--plan", type=Path, default=REPO / "configs/stage1_generation_plan.yaml")
    args = parser.parse_args()

    inputs = args.inputs if args.inputs else default_inputs()
    if not inputs:
        raise SystemExit("No generated files found. Run normalize-positive / generate first.")

    plan = read_yaml(args.plan) if args.plan.exists() else {}
    cfg = {"generation": plan.get("generation", {})}

    records: list[dict[str, Any]] = []
    for path in inputs:
        records.extend(read_jsonl(path))

    report = analyze(records, cfg)
    report["inputs"] = [str(p) for p in inputs]

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    write_json(REPORT_DIR / "stage1_quality_report.json", report)
    (REPORT_DIR / "stage1_quality_report.md").write_text(to_markdown(report), encoding="utf-8")

    print(to_markdown(report))
    print(f"[report] wrote {REPORT_DIR}/stage1_quality_report.json and .md")


if __name__ == "__main__":
    main()
