#!/usr/bin/env python3
"""Stage 1 Life Event Detection — data generation CLI.

Subcommands
-----------
normalize-positive
    Convert the human-authored positive seed file into the unified schema.

generate
    Build (and, with --execute, call the API to fill) negative / pre-event /
    cancelled dialogues per the generation plan. One JSONL per generation type.

dry-run
    Print the planned prompts and selected source examples. Never calls the API.

Design notes
------------
- Gold labels are assigned here by the controller, never inferred from a model
  after generation.
- Target labels and FA codes are NEVER written into conversation text; they live
  only in metadata / gold.
- IDs are stable and deterministic (see lib.id_utils).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Optional

# Make `from lib.X import ...` work when run as `python scripts/generate_stage1_data.py`.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lib import dialogue_validation as dv  # noqa: E402
from lib.id_utils import make_turn_ids, single_conversation_id  # noqa: E402
from lib.io_utils import read_json, read_jsonl, read_text, read_yaml, write_jsonl  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
PROMPT_DIR = REPO / "prompts" / "generation"
TAXONOMY_PATH = REPO / "data" / "processed" / "life_event_taxonomy.json"
ACTION_POOL_PATH = REPO / "data" / "processed" / "action_pool.json"
SEED_PATH = REPO / "data" / "pilot" / "stage1_single_positive_seed_30.jsonl"

TASK = "stage1_life_event_detection"
SPLIT = "pilot"

# generation_type -> output filename
OUTPUT_FILENAMES = {
    "occurred_positive": "occurred_positive.jsonl",
    "neutral_no_event": "no_event_neutral.jsonl",
    "hard_negative": "hard_negative.jsonl",
    "existing_state_negative": "existing_state_negative.jsonl",
    "pre_event_weak_signal": "pre_event_weak_signal.jsonl",
    "pre_event_upcoming": "pre_event_upcoming.jsonl",
    "cancelled_reversed": "cancelled_reversed.jsonl",
}

# generation_type -> (prompt file, plan key)
PROMPT_FILES = {
    "occurred_positive": "generate_occurred_positive_ko.md",
    "neutral_no_event": "generate_no_event_neutral_ko.md",
    "hard_negative": "generate_hard_negative_counterfactual_ko.md",
    "existing_state_negative": "generate_existing_state_negative_ko.md",
    "pre_event_weak_signal": "generate_pre_event_weak_signal_ko.md",
    "pre_event_upcoming": "generate_pre_event_upcoming_ko.md",
    "cancelled_reversed": "generate_cancelled_reversed_ko.md",
}

GENERATED_TYPES = list(PROMPT_FILES.keys())

# Neutral business hints (no life-event implication). Cycled for neutral_no_event.
NEUTRAL_HINTS = [
    "카드 결제내역/이용대금 조회",
    "거래내역서 발급 및 내보내기",
    "앱 푸시 알림 설정 변경",
    "예금 이자/금리 조회",
    "여행 자금 모으기 적금 가입",
    "취미 자금 목적 통장 만들기",
    "카드 분실 정지 신청",
    "친구와 밥값 정산 송금",
    "구독료 정기이체 등록",
    "일반 신용대출 이자 시뮬레이션",
]

# Existing-state negatives: curated (label -> list of "modify existing arrangement
# only" hints). Labels without a curated entry fall back to a hint derived from the
# taxonomy's banking_situation_ko (see existing_state_hint).
EXISTING_STATE_HINTS: dict[str, list[str]] = {
    "결혼": [
        "배우자에게 매달 보내던 생활비 정기이체의 날짜만 변경",
        "배우자와 함께 쓰던 기존 모임통장 알림 설정만 변경",
    ],
    "출산/입양": [
        "자녀 학원비 자동이체 금액만 변경",
        "자녀 앞으로 들어둔 기존 적금 납입일만 변경",
    ],
    "부양가족 발생/해소": [
        "부모님 병원비를 이번 달만 일회성으로 추가 송금",
        "부모님께 매달 보내던 용돈 정기이체 금액만 조정",
    ],
    "전세·월세 계약/갱신": [
        "기존 월세 정기이체 이체일만 25일로 변경",
        "기존 관리비 자동납부 계좌만 변경",
    ],
    "이직/전근": [
        "같은 회사 급여 수령계좌를 주거래 계좌로 변경",
        "기존 급여계좌에서 빠지는 자동이체 날짜만 조정",
    ],
}

UPDATE_ALLOWED_BY_STATUS = {
    "occurred": True,
    "weak_signal": False,
    "upcoming": "partial",
    "cancelled": False,
}


def plan_counts(plan: dict[str, Any]) -> dict[str, int]:
    """Per-generation-type record counts. Prefers a `single:` block (full plan);
    falls back to `pilot:` for the original pilot plan."""
    return plan.get("single") or plan.get("pilot") or {}


def active_labels(plan: dict[str, Any], taxonomy: dict[str, dict[str, Any]]) -> list[str]:
    """Single source of truth for which life-event labels generation targets.

    Prefers `plan['labels']['active_subset']`; otherwise falls back to every
    `active=true` label in the taxonomy (insertion order preserved).
    """
    subset = (plan.get("labels") or {}).get("active_subset")
    if subset:
        return [lbl for lbl in subset if lbl in taxonomy]
    return [lbl for lbl, row in taxonomy.items() if row.get("active")]


def existing_state_hint(label: str, index: int, taxonomy: dict[str, dict[str, Any]]) -> str:
    """An 'adjust an existing arrangement' hint for the existing-state negative type."""
    curated = EXISTING_STATE_HINTS.get(label)
    if curated:
        return curated[index % len(curated)]
    # Fall back to the first clause of the taxonomy banking situation, reframed as
    # a small adjustment to a long-standing arrangement (not a new event).
    situation = action_hint_for_label(label, taxonomy)
    first = situation.split(",")[0].strip()
    return f"기존에 유지하던 '{first}' 설정의 날짜·금액만 소소하게 변경"


# --------------------------------------------------------------------------- #
# reference data helpers
# --------------------------------------------------------------------------- #

def load_taxonomy() -> dict[str, dict[str, Any]]:
    return {row["event_label_ko"]: row for row in read_json(TAXONOMY_PATH)}


def load_action_pool() -> dict[str, dict[str, Any]]:
    return {row["action_id"]: row for row in read_json(ACTION_POOL_PATH)}


def action_hint_for_label(label: str, taxonomy: dict[str, dict[str, Any]]) -> str:
    row = taxonomy.get(label, {})
    return row.get("banking_situation_ko", "일반 은행 업무")


def representative_action_id(label: str, taxonomy: dict[str, dict[str, Any]]) -> Optional[str]:
    row = taxonomy.get(label, {})
    actions = row.get("matched_actions", [])
    return actions[0] if actions else None


# --------------------------------------------------------------------------- #
# model output parsing
# --------------------------------------------------------------------------- #

def parse_model_json(text: str) -> dict[str, Any]:
    """Parse model output into a dict, tolerating code fences / surrounding prose."""
    text = text.strip()
    # strip ```json ... ``` fences
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            return json.loads(text[start : end + 1])
        raise


def dialogue_to_turns(dialogue: list[dict[str, Any]], session_id: str) -> list[dict[str, str]]:
    speakers = [d.get("speaker", "user") for d in dialogue]
    turn_ids = make_turn_ids(speakers, session_id)
    return [
        {"turn_id": tid, "speaker": d.get("speaker", "user"), "text": (d.get("text") or "").strip()}
        for tid, d in zip(turn_ids, dialogue)
    ]


def indices_to_user_turn_ids(turns: list[dict[str, str]], indices: list[int]) -> list[str]:
    out: list[str] = []
    for idx in indices or []:
        if isinstance(idx, int) and 0 <= idx < len(turns) and turns[idx]["speaker"] == "user":
            out.append(turns[idx]["turn_id"])
    return out


def all_user_turn_ids(turns: list[dict[str, str]]) -> list[str]:
    return [t["turn_id"] for t in turns if t["speaker"] == "user"]


# --------------------------------------------------------------------------- #
# job planning
# --------------------------------------------------------------------------- #

def build_jobs(
    gen_type: str,
    count: int,
    taxonomy: dict[str, dict[str, Any]],
    seeds: list[dict[str, Any]],
    labels: list[str],
) -> list[dict[str, Any]]:
    """Return a list of job dicts describing each record to generate.

    `labels` is the active label set (see active_labels); per-label types cycle
    through it so every active label gets even coverage as `count` grows.
    """
    jobs: list[dict[str, Any]] = []
    prompt_file = PROMPT_FILES[gen_type]
    prompt_template = read_text(PROMPT_DIR / prompt_file)

    for i in range(count):
        job: dict[str, Any] = {
            "generation_type": gen_type,
            "index": i,
            "prompt_file": prompt_file,
            "is_multi": gen_type == "cancelled_reversed",
        }
        if gen_type == "neutral_no_event":
            hint = NEUTRAL_HINTS[i % len(NEUTRAL_HINTS)]
            job.update(target_label="no_event", target_action_id=None, action_hint=hint,
                       near_miss_event=None)
            job["prompt"] = prompt_template.replace("{ACTION_HINT}", hint)

        elif gen_type == "existing_state_negative":
            label = labels[i % len(labels)]
            hint = existing_state_hint(label, i // len(labels), taxonomy)
            action_id = representative_action_id(label, taxonomy)
            job.update(target_label=label, target_action_id=action_id, action_hint=hint,
                       near_miss_event=label, implied_existing_state=True)
            job["prompt"] = (prompt_template
                             .replace("{TARGET_LABEL}", label)
                             .replace("{ACTION_HINT}", hint))

        elif gen_type == "hard_negative":
            # near-miss label drawn from the active set; surface action from taxonomy.
            label = labels[i % len(labels)]
            hint = action_hint_for_label(label, taxonomy)
            action_id = representative_action_id(label, taxonomy)
            job.update(target_label=label, target_action_id=action_id, action_hint=hint,
                       near_miss_event=label)
            job["prompt"] = (prompt_template
                             .replace("{TARGET_LABEL}", label)
                             .replace("{ACTION_HINT}", hint))

        else:  # occurred_positive / pre_event_weak_signal / pre_event_upcoming / cancelled_reversed
            label = labels[i % len(labels)]
            hint = action_hint_for_label(label, taxonomy)
            action_id = representative_action_id(label, taxonomy)
            job.update(target_label=label, target_action_id=action_id, action_hint=hint,
                       near_miss_event=None)
            job["prompt"] = (prompt_template
                             .replace("{TARGET_LABEL}", label)
                             .replace("{ACTION_HINT}", hint))
        jobs.append(job)
    return jobs


# --------------------------------------------------------------------------- #
# record assembly
# --------------------------------------------------------------------------- #

def status_for_type(gen_type: str) -> str:
    return {
        "occurred_positive": "occurred",
        "pre_event_weak_signal": "weak_signal",
        "pre_event_upcoming": "upcoming",
        "cancelled_reversed": "cancelled",
    }[gen_type]


def build_gold_no_event(job: dict[str, Any]) -> dict[str, Any]:
    return {
        "event_relation": "no_event",
        "life_event_detected": False,
        "life_events": [],
        "negative_type": job["generation_type"],
        "near_miss_event": job.get("near_miss_event"),
    }


def build_gold_event_related(
    job: dict[str, Any],
    sessions: list[dict[str, Any]],
    evidence_turns: list[str],
    candidate_user_turns: list[str],
) -> dict[str, Any]:
    status = status_for_type(job["generation_type"])
    session_id = sessions[-1]["session_id"] if status == "cancelled" else sessions[0]["session_id"]
    return {
        "event_relation": "event_related",
        "life_event_detected": True,
        "life_events": [
            {
                "session_id": session_id,
                "life_event_label": job["target_label"],
                "event_status": status,
                "occurred": status == "occurred",
                "update_allowed": UPDATE_ALLOWED_BY_STATUS[status],
                "evidence_turns": evidence_turns,
                "candidate_user_turns": candidate_user_turns,
                "near_miss_labels": [],
            }
        ],
        "negative_type": None,
        "near_miss_event": None,
    }


def assemble_record(
    job: dict[str, Any],
    parsed: dict[str, Any],
    model: str,
    created_at: str,
) -> dict[str, Any]:
    """Turn a parsed model output + job into a unified-schema record."""
    gen_type = job["generation_type"]
    conv_id = single_conversation_id(gen_type, job["index"])

    if job["is_multi"]:
        sessions = []
        all_turns_flat: list[dict[str, str]] = []
        evidence_turns: list[str] = []
        candidate_user_turns: list[str] = []
        cand_map = parsed.get("candidate_evidence_user_turn_indices", {}) or {}
        for s_i, sess in enumerate(parsed.get("sessions", []), 1):
            sid = f"S{s_i}"
            turns = dialogue_to_turns(sess.get("dialogue", []), sid)
            sessions.append({"session_id": sid, "turns": turns})
            all_turns_flat.extend(turns)
            src_sid = sess.get("session_id", sid)
            idxs = cand_map.get(src_sid) or cand_map.get(sid) or []
            evidence_turns.extend(indices_to_user_turn_ids(turns, idxs))
            candidate_user_turns.extend(all_user_turn_ids(turns))
    else:
        turns = dialogue_to_turns(parsed.get("dialogue", []), "S1")
        sessions = [{"session_id": "S1", "turns": turns}]
        idxs = parsed.get("candidate_evidence_user_turn_indices", []) or []
        evidence_turns = indices_to_user_turn_ids(turns, idxs)
        candidate_user_turns = all_user_turn_ids(turns)

    if gen_type in ("neutral_no_event", "hard_negative", "existing_state_negative"):
        gold = build_gold_no_event(job)
    else:
        gold = build_gold_event_related(job, sessions, evidence_turns, candidate_user_turns)

    metadata = {
        "model": model,
        "created_at": created_at,
        "source_conversation_id": job.get("source_conversation_id"),
        "source_action_id": job.get("target_action_id"),
        "prompt_file": job["prompt_file"],
        "repair_attempts": 0,
        "self_check": parsed.get("quality_self_check", {}),
    }
    if job.get("implied_existing_state"):
        metadata["implied_existing_state"] = True

    return {
        "conversation_id": conv_id,
        "task": TASK,
        "split": SPLIT,
        "source_type": "generated",
        "generation_type": gen_type,
        "target_life_event": job["target_label"],
        "target_action_id": job.get("target_action_id"),
        "difficulty": "medium",
        "input": {"sessions": sessions},
        "gold": gold,
        "quality_flags": [],
        "generation_metadata": metadata,
    }


# --------------------------------------------------------------------------- #
# normalize-positive
# --------------------------------------------------------------------------- #

def normalize_positive(input_path: Path, output_path: Path, overwrite: bool) -> None:
    if output_path.exists() and not overwrite:
        print(f"[skip] {output_path} exists (use --overwrite to replace)")
        return
    seeds = read_jsonl(input_path)
    records: list[dict[str, Any]] = []
    for i, seed in enumerate(seeds):
        # re-id turns into the unified S1-U1 / S1-A1 format and remap candidates
        old_sessions = seed["input"]["sessions"]
        new_sessions: list[dict[str, Any]] = []
        old_to_new: dict[str, dict[str, str]] = {}  # session -> {old_turn_id: new_turn_id}
        for s_i, sess in enumerate(old_sessions, 1):
            sid = f"S{s_i}"
            speakers = [t["speaker"] for t in sess["turns"]]
            new_ids = make_turn_ids(speakers, sid)
            mapping = {t["turn_id"]: nid for t, nid in zip(sess["turns"], new_ids)}
            old_to_new[sess.get("session_id", sid)] = mapping
            new_sessions.append({
                "session_id": sid,
                "turns": [
                    {"turn_id": nid, "speaker": t["speaker"], "text": t["text"]}
                    for t, nid in zip(sess["turns"], new_ids)
                ],
            })

        life_events = []
        for ev in seed["gold"]["life_events"]:
            old_sid = ev.get("session_id", "S1")
            mapping = old_to_new.get(old_sid, {})
            ev_turns = [mapping[t] for t in ev.get("evidence_turns", []) if t in mapping]
            cand = ev.get("candidate_user_turns", [])
            cand_new = [mapping[t] for t in cand if t in mapping]
            if not cand_new:
                # fall back to every user turn in the mapped session
                sess = next((s for s in new_sessions if s["session_id"] == "S1"), new_sessions[0])
                cand_new = all_user_turn_ids(sess["turns"])
            life_events.append({
                "session_id": "S1",
                "life_event_label": ev["life_event_label"],
                "event_status": "occurred",
                "occurred": True,
                "update_allowed": True,
                "evidence_turns": ev_turns,  # [] when not manually annotated
                "candidate_user_turns": cand_new,
                "near_miss_labels": [],
            })

        record = {
            "conversation_id": single_conversation_id("occurred_positive", i),
            "task": TASK,
            "split": SPLIT,
            "source_type": "seed_positive",
            "generation_type": "occurred_positive",
            "target_life_event": life_events[0]["life_event_label"] if life_events else "no_event",
            "target_action_id": seed.get("metadata", {}).get("action_id"),
            "difficulty": "medium",
            "input": {"sessions": new_sessions},
            "gold": {
                "event_relation": "event_related",
                "life_event_detected": True,
                "life_events": life_events,
                "negative_type": None,
                "near_miss_event": None,
            },
            "quality_flags": [],
            "generation_metadata": {
                "model": None,
                "created_at": None,
                "source_conversation_id": seed.get("source_conversation_id"),
                "source_action_id": seed.get("metadata", {}).get("action_id"),
                "prompt_file": None,
                "repair_attempts": 0,
            },
        }
        records.append(record)

    # validate (advisory) and attach flags, but never drop seeds
    cfg = {"generation": {}}
    for r in records:
        flags = dv.validate_record(r, cfg)
        if flags:
            r["quality_flags"] = flags
    n = write_jsonl(output_path, records)
    flagged = sum(1 for r in records if r["quality_flags"])
    print(f"[normalize-positive] wrote {n} records -> {output_path} ({flagged} with quality_flags)")


# --------------------------------------------------------------------------- #
# generate
# --------------------------------------------------------------------------- #

def build_repair_prompt(original_instruction: str, issues: list[str], previous_output: str) -> str:
    template = read_text(PROMPT_DIR / "repair_generated_dialogue_ko.md")
    return (template
            .replace("{ORIGINAL_INSTRUCTION}", original_instruction)
            .replace("{ISSUES}", "\n".join(f"- {x}" for x in issues))
            .replace("{PREVIOUS_OUTPUT}", previous_output))


def run_generate(
    types: list[str],
    plan: dict[str, Any],
    output_dir: Path,
    max_items: Optional[int],
    execute: bool,
    overwrite: bool,
    drop_invalid: bool,
) -> None:
    taxonomy = load_taxonomy()
    seeds = read_jsonl(SEED_PATH)
    labels = active_labels(plan, taxonomy)
    counts = plan_counts(plan)
    gen_cfg = plan.get("generation", {})
    max_repair = gen_cfg.get("max_repair_attempts", 2)
    cfg = {"generation": gen_cfg}

    if not execute:
        # planning summary only — no API
        print("[generate] --execute not set: planning summary only (no API calls)\n")
        for gen_type in types:
            count = counts.get(gen_type, 0)
            if max_items is not None:
                count = min(count, max_items)
            jobs = build_jobs(gen_type, count, taxonomy, seeds, labels)
            print(f"  {gen_type}: would generate {len(jobs)} record(s) "
                  f"-> {output_dir / OUTPUT_FILENAMES[gen_type]}")
        print(f"\n[generate] active labels: {len(labels)}")
        print("Re-run with --execute to call the API.")
        return

    # real generation
    from lib.openai_client import generate_text, get_model  # lazy import
    import datetime

    model = get_model()
    created_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
    output_dir.mkdir(parents=True, exist_ok=True)

    for gen_type in types:
        out_path = output_dir / OUTPUT_FILENAMES[gen_type]
        if out_path.exists() and not overwrite:
            print(f"[skip] {out_path} exists (use --overwrite to replace)")
            continue
        count = counts.get(gen_type, 0)
        if max_items is not None:
            count = min(count, max_items)
        jobs = build_jobs(gen_type, count, taxonomy, seeds, labels)
        print(f"[generate] {gen_type}: {len(jobs)} record(s)")

        records: list[dict[str, Any]] = []
        for job in jobs:
            conv_id = single_conversation_id(gen_type, job["index"])
            system_prompt = "너는 한국어 은행 챗봇 대화 데이터를 정확한 JSON으로만 생성하는 도구다."
            raw_tag = f"{conv_id}__attempt0"
            try:
                raw = generate_text(system_prompt, job["prompt"], raw_tag=raw_tag)
                parsed = parse_model_json(raw)
                record = assemble_record(job, parsed, model, created_at)
            except Exception as exc:
                print(f"  [error] {conv_id}: generation failed: {exc}")
                record = _placeholder_record(job, model, created_at, [f"generation_error: {exc}"])
                records.append(record)
                continue

            flags = dv.validate_record(record, cfg)
            attempts = 0
            while flags and attempts < max_repair:
                attempts += 1
                print(f"  [repair] {conv_id} attempt {attempts}: {len(flags)} issue(s)")
                repair_prompt = build_repair_prompt(
                    job["prompt"], flags, json.dumps(parsed, ensure_ascii=False, indent=2)
                )
                try:
                    raw = generate_text(system_prompt, repair_prompt,
                                        raw_tag=f"{conv_id}__attempt{attempts}")
                    parsed = parse_model_json(raw)
                    record = assemble_record(job, parsed, model, created_at)
                    record["generation_metadata"]["repair_attempts"] = attempts
                    flags = dv.validate_record(record, cfg)
                except Exception as exc:
                    print(f"  [error] {conv_id}: repair failed: {exc}")
                    break

            if flags:
                record["quality_flags"] = flags
                if drop_invalid:
                    print(f"  [drop] {conv_id}: invalid after {attempts} repair(s), dropped")
                    continue
                print(f"  [keep] {conv_id}: kept with {len(flags)} quality_flag(s)")
            records.append(record)

        n = write_jsonl(out_path, records)
        flagged = sum(1 for r in records if r.get("quality_flags"))
        print(f"  wrote {n} record(s) -> {out_path} ({flagged} flagged)\n")


def _placeholder_record(job, model, created_at, flags):
    gen_type = job["generation_type"]
    conv_id = single_conversation_id(gen_type, job["index"])
    return {
        "conversation_id": conv_id,
        "task": TASK,
        "split": SPLIT,
        "source_type": "generated",
        "generation_type": gen_type,
        "target_life_event": job["target_label"],
        "target_action_id": job.get("target_action_id"),
        "difficulty": "medium",
        "input": {"sessions": []},
        "gold": (build_gold_no_event(job)
                 if gen_type in ("neutral_no_event", "hard_negative", "existing_state_negative")
                 else {"event_relation": "event_related", "life_event_detected": True,
                       "life_events": [], "negative_type": None, "near_miss_event": None}),
        "quality_flags": flags,
        "generation_metadata": {
            "model": model, "created_at": created_at,
            "source_conversation_id": job.get("source_conversation_id"),
            "source_action_id": job.get("target_action_id"),
            "prompt_file": job["prompt_file"], "repair_attempts": 0,
        },
    }


def run_dry_run(types: list[str], plan: dict[str, Any], max_items: Optional[int]) -> None:
    taxonomy = load_taxonomy()
    seeds = read_jsonl(SEED_PATH)
    labels = active_labels(plan, taxonomy)
    counts = plan_counts(plan)
    for gen_type in types:
        count = counts.get(gen_type, 0)
        if max_items is not None:
            count = min(count, max_items)
        jobs = build_jobs(gen_type, count, taxonomy, seeds, labels)
        print("=" * 70)
        print(f"DRY-RUN: {gen_type}  ({len(jobs)} record(s))")
        print("=" * 70)
        for job in jobs:
            conv_id = single_conversation_id(gen_type, job["index"])
            print(f"\n--- {conv_id} ---")
            print(f"target_label   : {job['target_label']}")
            print(f"target_action  : {job.get('target_action_id')}")
            print(f"near_miss_event: {job.get('near_miss_event')}")
            if job.get("source_conversation_id"):
                print(f"source_conv_id : {job['source_conversation_id']}")
            print(f"prompt_file    : {job['prompt_file']}")
            print("--- prompt (no API call) ---")
            print(job["prompt"])
        print()


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def parse_types(arg: Optional[str]) -> list[str]:
    if not arg:
        return list(GENERATED_TYPES)
    out = []
    for t in arg.split(","):
        t = t.strip()
        if not t:
            continue
        if t not in GENERATED_TYPES:
            raise SystemExit(f"unknown generation type: {t} (valid: {', '.join(GENERATED_TYPES)})")
        out.append(t)
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="Stage 1 data generation CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    p_norm = sub.add_parser("normalize-positive", help="Normalize positive seed into unified schema")
    p_norm.add_argument("--input", type=Path, default=SEED_PATH)
    p_norm.add_argument("--output", type=Path,
                        default=REPO / "data/generated/single/occurred_positive.jsonl")
    p_norm.add_argument("--overwrite", action="store_true")

    p_gen = sub.add_parser("generate", help="Generate dialogues per plan")
    p_gen.add_argument("--plan", type=Path, default=REPO / "configs/stage1_generation_plan.yaml")
    p_gen.add_argument("--types", type=str, default=None)
    p_gen.add_argument("--output-dir", type=Path, default=REPO / "data/generated/single")
    p_gen.add_argument("--max-items", type=int, default=None)
    p_gen.add_argument("--execute", action="store_true", help="Actually call the API")
    p_gen.add_argument("--overwrite", action="store_true")
    p_gen.add_argument("--drop-invalid", action="store_true")

    p_dry = sub.add_parser("dry-run", help="Print planned prompts (never calls API)")
    p_dry.add_argument("--plan", type=Path, default=REPO / "configs/stage1_generation_plan.yaml")
    p_dry.add_argument("--types", type=str, default=None)
    p_dry.add_argument("--max-items", type=int, default=2)

    args = parser.parse_args()

    if args.command == "normalize-positive":
        normalize_positive(args.input, args.output, args.overwrite)
    elif args.command == "generate":
        plan = read_yaml(args.plan)
        run_generate(parse_types(args.types), plan, args.output_dir,
                     args.max_items, args.execute, args.overwrite, args.drop_invalid)
    elif args.command == "dry-run":
        plan = read_yaml(args.plan)
        run_dry_run(parse_types(args.types), plan, args.max_items)


if __name__ == "__main__":
    main()
