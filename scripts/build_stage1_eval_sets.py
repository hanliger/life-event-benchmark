#!/usr/bin/env python3
"""Build combined Stage 1 eval sets.

Outputs
-------
data/generated/single/stage1_single_eval_v0.jsonl
    All per-type single-dialogue files concatenated (deterministic order).

data/generated/mixed/stage1_mixed_eval_v0.jsonl
    Mixed-session bundles per the plan's `mixed:` counts. Session and turn IDs
    are reassigned; a mapping back to source IDs is kept in metadata.
"""
from __future__ import annotations

import argparse
import os
import random
import sys
from pathlib import Path
from typing import Any, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lib.id_utils import make_turn_ids, mixed_conversation_id  # noqa: E402
from lib.io_utils import read_jsonl, read_yaml, write_jsonl  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
SINGLE_DIR = REPO / "data" / "generated" / "single"
MIXED_DIR = REPO / "data" / "generated" / "mixed"

TASK = "stage1_life_event_detection"
SPLIT = "pilot"

# generation_type -> single file. Order defines the combined-file order.
SINGLE_FILES = [
    ("occurred_positive", "occurred_positive.jsonl"),
    ("neutral_no_event", "no_event_neutral.jsonl"),
    ("hard_negative", "hard_negative.jsonl"),
    ("existing_state_negative", "existing_state_negative.jsonl"),
    ("pre_event_weak_signal", "pre_event_weak_signal.jsonl"),
    ("pre_event_upcoming", "pre_event_upcoming.jsonl"),
    ("cancelled_reversed", "cancelled_reversed.jsonl"),
]

EVENT_RELATED_TYPES = {
    "occurred_positive", "pre_event_weak_signal", "pre_event_upcoming", "cancelled_reversed",
}


def load_pools() -> dict[str, list[dict[str, Any]]]:
    pools: dict[str, list[dict[str, Any]]] = {}
    for gen_type, fname in SINGLE_FILES:
        path = SINGLE_DIR / fname
        pools[gen_type] = read_jsonl(path) if path.exists() else []
    return pools


def combine_single(pools: dict[str, list[dict[str, Any]]], out_path: Path) -> int:
    rows: list[dict[str, Any]] = []
    for gen_type, _ in SINGLE_FILES:
        rows.extend(pools.get(gen_type, []))
    return write_jsonl(out_path, rows)


def pick(pool: list[dict[str, Any]], k: int, rng: random.Random) -> list[dict[str, Any]]:
    """Pick k records. Samples without replacement when possible, else with."""
    if not pool:
        return []
    if len(pool) >= k:
        return rng.sample(pool, k)
    return rng.choices(pool, k=k)


def remap_into_bundle(
    sources: list[dict[str, Any]],
    rng: random.Random,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str], dict[str, Any]]:
    """Combine source records' sessions into one bundle with fresh S/turn IDs.

    Returns (sessions, life_events, no_event_sessions, id_mapping).
    """
    order = list(range(len(sources)))
    rng.shuffle(order)

    sessions: list[dict[str, Any]] = []
    life_events: list[dict[str, Any]] = []
    no_event_sessions: list[str] = []
    id_mapping: dict[str, Any] = {}
    next_s = 1

    for src_idx in order:
        src = sources[src_idx]
        gen_type = src.get("generation_type")
        # map this source's own session_id -> new session_id, plus turn id remap
        local_session_map: dict[str, str] = {}
        local_turn_map: dict[str, str] = {}
        for sess in src["input"]["sessions"]:
            new_sid = f"S{next_s}"
            next_s += 1
            old_sid = sess["session_id"]
            local_session_map[old_sid] = new_sid
            speakers = [t["speaker"] for t in sess["turns"]]
            new_ids = make_turn_ids(speakers, new_sid)
            new_turns = []
            for t, nid in zip(sess["turns"], new_ids):
                local_turn_map[t["turn_id"]] = nid
                new_turns.append({"turn_id": nid, "speaker": t["speaker"], "text": t["text"]})
            sessions.append({"session_id": new_sid, "turns": new_turns})

        id_mapping[src["conversation_id"]] = {
            "sessions": local_session_map,
            "generation_type": gen_type,
        }

        if gen_type in EVENT_RELATED_TYPES:
            for ev in src["gold"].get("life_events", []):
                new_ev = dict(ev)
                old_sid = ev.get("session_id", src["input"]["sessions"][0]["session_id"])
                new_ev["session_id"] = local_session_map.get(old_sid, f"S{next_s-1}")
                new_ev["evidence_turns"] = [
                    local_turn_map[t] for t in ev.get("evidence_turns", []) if t in local_turn_map
                ]
                if ev.get("candidate_user_turns"):
                    new_ev["candidate_user_turns"] = [
                        local_turn_map[t] for t in ev["candidate_user_turns"] if t in local_turn_map
                    ]
                life_events.append(new_ev)
        else:
            no_event_sessions.extend(local_session_map.values())

    return sessions, life_events, no_event_sessions, id_mapping


def build_bundle(
    gen_type: str,
    index: int,
    sources: list[dict[str, Any]],
    rng: random.Random,
) -> dict[str, Any]:
    sessions, life_events, no_event_sessions, id_mapping = remap_into_bundle(sources, rng)
    has_event = bool(life_events)
    gold = {
        "event_relation": "event_related" if has_event else "no_event",
        "life_event_detected": has_event,
        "life_events": life_events,
        "no_event_sessions": no_event_sessions,
    }
    return {
        "conversation_id": mixed_conversation_id(gen_type, index),
        "task": TASK,
        "split": SPLIT,
        "source_type": "generated_mixed",
        "generation_type": gen_type,
        "difficulty": "medium",
        "input": {"sessions": sessions},
        "gold": gold,
        "quality_flags": [],
        "generation_metadata": {
            "source_conversation_ids": [s["conversation_id"] for s in sources],
            "id_mapping": id_mapping,
        },
    }


def build_mixed(
    pools: dict[str, list[dict[str, Any]]],
    plan: dict[str, Any],
    rng: random.Random,
) -> list[dict[str, Any]]:
    mixed_cfg = plan.get("mixed", {})
    rows: list[dict[str, Any]] = []

    negatives_all = (
        pools.get("neutral_no_event", [])
        + pools.get("hard_negative", [])
        + pools.get("existing_state_negative", [])
    )
    pre_event_all = pools.get("pre_event_weak_signal", []) + pools.get("pre_event_upcoming", [])

    def emit(gen_type: str, source_fn) -> None:
        n = mixed_cfg.get(gen_type, 0)
        made = 0
        for i in range(n):
            sources = source_fn()
            if not sources or all(not s.get("input", {}).get("sessions") for s in sources):
                continue
            rows.append(build_bundle(gen_type, made, sources, rng))
            made += 1
        if made < n:
            print(f"  [warn] {gen_type}: requested {n}, built {made} (source pool too small)")

    # easy_mixed_positive: 2 neutral + 1 occurred positive
    emit("easy_mixed_positive", lambda: (
        pick(pools.get("neutral_no_event", []), 2, rng) + pick(pools.get("occurred_positive", []), 1, rng)
    ))
    # hard_mixed_positive: 2 hard negative + 1 occurred positive
    emit("hard_mixed_positive", lambda: (
        pick(pools.get("hard_negative", []), 2, rng) + pick(pools.get("occurred_positive", []), 1, rng)
    ))
    # pre_event_mixed: 2 neutral + 1 weak/upcoming
    emit("pre_event_mixed", lambda: (
        pick(pools.get("neutral_no_event", []), 2, rng) + pick(pre_event_all, 1, rng)
    ))
    # all_negative: 3 mixed negatives
    emit("all_negative", lambda: pick(negatives_all, 3, rng))
    # cancelled_sequence: 1 cancelled, optionally bracketed by a no-event session
    emit("cancelled_sequence", lambda: (
        pick(pools.get("neutral_no_event", []), 1, rng) + pick(pools.get("cancelled_reversed", []), 1, rng)
    ))
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description="Build Stage 1 combined + mixed eval sets")
    parser.add_argument("--plan", type=Path, default=REPO / "configs/stage1_generation_plan.yaml")
    parser.add_argument("--single-out", type=Path, default=SINGLE_DIR / "stage1_single_eval_v0.jsonl")
    parser.add_argument("--mixed-out", type=Path, default=MIXED_DIR / "stage1_mixed_eval_v0.jsonl")
    parser.add_argument("--seed", type=int, default=None)
    args = parser.parse_args()

    plan = read_yaml(args.plan)
    seed = args.seed if args.seed is not None else plan.get("generation", {}).get("seed", 42)
    rng = random.Random(seed)

    pools = load_pools()
    n_single = combine_single(pools, args.single_out)
    print(f"[build] combined single eval -> {args.single_out} ({n_single} records)")

    mixed_rows = build_mixed(pools, plan, rng)
    n_mixed = write_jsonl(args.mixed_out, mixed_rows)
    print(f"[build] mixed eval -> {args.mixed_out} ({n_mixed} records)")


if __name__ == "__main__":
    main()
