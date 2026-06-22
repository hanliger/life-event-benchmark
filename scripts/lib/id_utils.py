"""Stable, deterministic ID helpers for Stage 1 records.

Conversation IDs are derived from a per-type numeric offset so that IDs stay
stable across re-runs and never collide between generation-type files, while
remaining easy to read.
"""
from __future__ import annotations

# Each generation type gets a 1000-wide numeric block. The pilot never produces
# more than a few dozen records per type, so the blocks have plenty of room and
# the IDs stay stable as long as the ordering of source items is stable.
SINGLE_TYPE_OFFSETS: dict[str, int] = {
    "occurred_positive": 0,
    "neutral_no_event": 1000,
    "hard_negative": 2000,
    "existing_state_negative": 3000,
    "pre_event_weak_signal": 4000,
    "pre_event_upcoming": 5000,
    "cancelled_reversed": 6000,
}

MIXED_TYPE_OFFSETS: dict[str, int] = {
    "easy_mixed_positive": 0,
    "hard_mixed_positive": 1000,
    "pre_event_mixed": 2000,
    "all_negative": 3000,
    "cancelled_sequence": 4000,
}


def single_conversation_id(generation_type: str, index: int) -> str:
    """Return a stable conversation_id for a single-dialogue record.

    `index` is 0-based within the generation type.
    """
    if generation_type not in SINGLE_TYPE_OFFSETS:
        raise ValueError(f"unknown single generation_type: {generation_type}")
    n = SINGLE_TYPE_OFFSETS[generation_type] + index + 1
    return f"STAGE1-SINGLE-{n:06d}"


def mixed_conversation_id(generation_type: str, index: int) -> str:
    """Return a stable conversation_id for a mixed-session bundle."""
    if generation_type not in MIXED_TYPE_OFFSETS:
        raise ValueError(f"unknown mixed generation_type: {generation_type}")
    n = MIXED_TYPE_OFFSETS[generation_type] + index + 1
    return f"STAGE1-MIXED-{n:06d}"


def make_turn_ids(speakers: list[str], session_id: str) -> list[str]:
    """Assign turn IDs of the form `<session_id>-U<k>` / `<session_id>-A<k>`.

    User and assistant turns are numbered independently within the session,
    e.g. S1-U1, S1-A1, S1-U2, S1-A2, ...
    """
    turn_ids: list[str] = []
    u = a = 0
    for sp in speakers:
        if sp == "user":
            u += 1
            turn_ids.append(f"{session_id}-U{u}")
        else:
            a += 1
            turn_ids.append(f"{session_id}-A{a}")
    return turn_ids
