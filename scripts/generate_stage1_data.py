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

# Implicit disambiguating cues for occurred_positive ONLY. The benchmark tests
# INFERENCE: the model must deduce the life event from how the user incidentally
# refers to people/things and from the unique financial footprint the event leaves
# — NEVER from an announcement. The audit (occurred_audit.json) showed that with no
# cue at all, labels collapse to a generic sibling ("이사 black hole") or vanish
# (휴직/연금 → no_event). So each label gets a REQUIRED *implicit* tell that
# distinguishes it from its nearest sibling, surfaced naturally while the user does
# ordinary banking. Forbidden: stating the event or its defining act ("결혼했다",
# "집 샀다", "퇴사했다"). Required: the tell leaks through reference/footprint.
# Two variants per label. NOT applied to weak_signal/upcoming (ambiguity intended).
DISAMBIG_CUES: dict[str, list[str]] = {
    "결혼": ["배우자를 '와이프/남편/배우자'로 자연스럽게 지칭(예전 호칭 아님)하고 신혼집 살림을 합치는 맥락 — '결혼했다'는 말은 금지",
           "양가·신혼집·부부 공동생활 관련 지출이 처음 등장 — 혼인 사실은 호칭과 정황으로만"],
    "이혼/별거": ["배우자를 '전남편/전처' 또는 '이제 따로 산다'는 식으로 지칭하고 공동계좌·위자료를 정리 — '이혼했다' 직접 진술 금지",
              "함께 쓰던 공동 자금을 둘로 가르고 각자 계좌로 분리하는 맥락 — 헤어짐은 정황으로만"],
    "출산/입양": ["'우리 아기/갓난쟁이'가 처음 등장하고 분유·기저귀·산후조리 등 육아 지출이 시작 — '출산했다' 진술 금지",
              "아이 앞으로 통장·보험을 새로 드는 맥락에서 신생아 존재가 자연스럽게 묻어남"],
    "부양가족 발생/해소": ["'이제 부모님이랑 같이 산다/부모님을 모신다'는 맥락과 부모 생활비·병원비를 새로 떠안음(신생아 아님) — '부양가족 생겼다' 진술 금지",
                  "같이 살던 가족이 빠져 부양 부담이 줄어든 맥락이 지출 변화로 드러남"],
    "가족 사망": ["'돌아가신 아버지/어머니' 등 고인을 지칭하며 상속·고인 계좌·장례비를 정리 — 호칭과 정황으로만",
              "상속받은 자금이나 고인 명의 계좌 해지를 처리하는 맥락"],
    "독립/분가": ["'부모님 집에서 나와 이제 혼자 산다'는 맥락과 생애 처음 본인 명의로 공과금·관리비를 내는 정황(가족 동반 이사 아님)",
              "본가에서 나와 처음 혼자 살림을 꾸리는 1인 가구 전환이 지출로 드러남"],
    "이사": ["주거 형태나 가족 구성 변화 없이 사는 곳만 옮긴 단순 이전 — 매매/전세/독립/결혼 등 다른 사건 신호는 일절 없음",
           "주소만 바뀌었을 뿐 다른 인생 변화 신호가 전혀 없는 평범한 이전"],
    "전세·월세 계약/갱신": ["전세자금대출 이자, 보증금, 집주인·임대차 갱신처럼 '남의 집을 빌려 산다'는 흔적(소유 아님) — 매매 신호 금지",
                  "보증금·월세·전세대출 관련 흔적으로 임차 상태가 드러남"],
    "주택 구매": ["취득세·재산세 고지서, 주택담보대출 원리금, 등기 비용처럼 '내 소유 집'에서만 나오는 흔적 — '집 샀다' 진술 금지, 전세 신호 아님",
              "주담대 원리금 상환과 재산세 자동납부 설정 등 자가 소유 footprint로 드러남"],
    "주택 매각/퇴거": ["큰 매도대금 입금, 중개수수료, 양도세처럼 '집을 팔아 처분했다'는 흔적 — 단순 이사 신호 아님",
                "보유 부동산을 처분하고 목돈이 들어와 자금을 굴리는 맥락"],
    "취업/복직": ["생애 첫(혹은 경력단절 후) 급여가 처음 들어오기 시작하고 4대보험이 잡히는 맥락 — 다른 회사로 옮긴 게 아님(이직 아님)",
              "그동안 소득이 없다가 첫 월급 입금이 시작된 사회 진입/복귀 정황"],
    "이직/전근": ["급여 입금처(회사명)가 다른 곳으로 바뀌고 전 직장 퇴직정산 뒤 새 급여가 들어오는 맥락 — 첫 취업이 아님",
              "근무지·급여 지급처가 다른 회사로 바뀐 흔적(경력 연속, 첫 취업 아님)"],
    "휴직": ["출산·육아·병가로 일정 기간만 일을 쉬어 급여가 육아휴직급여 등으로 바뀌었고 '복직 예정'이 분명한 맥락 — '무기한'·퇴직금·실업급여 같은 영구 중단 신호는 절대 금지(퇴사 아님)",
           "복직 시점을 염두에 두고 휴직 기간 동안만 고정지출을 잠시 줄이는 정황 — 다시 출근/복귀할 것이 전제됨"],
    "퇴사/실직": ["퇴직금 입금, 실업급여, 4대보험 상실처럼 '일을 영구히 그만뒀다'는 흔적 — 복직 전제는 없음(휴직 아님)",
              "급여가 끊기고 퇴직금·실업급여로 버티며 복귀 계획이 없는 정황"],
    "창업/프리랜서 전환": ["사업자 통장 개설, 부가세, 불규칙한 사업 입금처럼 '직접 벌이를 시작했다'는 흔적 — 월급쟁이 아님",
                  "고정 월급 대신 사업/프리랜서 수입이 불규칙하게 들어오는 정황"],
    "폐업/사업 중단": ["사업자 정리, 사업 대출 상환, 사업 계좌 해지처럼 '벌이던 사업을 접었다'는 흔적",
                "매출 입금이 끊기고 사업 관련 대출·계좌를 닫는 정황"],
    "본인 장기 교육/재교육 시작": ["본인 대학원·장기과정 등록금/학자금대출 흔적으로 '내가 다시 공부를 시작했다'가 드러남(자녀 아님)",
                      "본인 학업 등록금·학자금 관련 지출이 새로 생긴 정황"],
    "자녀 교육 단계 진입": ["자녀가 상급 학교(초/중/고/대학)에 입학·진학해 입학금·새 학기 등록금이 처음 발생하는 맥락 — 단순 학원 변경이 아니라 교육 '단계'가 바뀜",
                  "아이가 새 과정에 들어가 입학 관련 목돈·교복·등록금이 처음 나가는 정황(기존 지출 조정 아님)"],
    "유학/장기연수": ["반복되는 해외 송금, 현지 통화 카드 사용, 해외 학비처럼 '한동안 외국에 나가 있다'는 흔적",
              "장기 해외 체류에 따른 송금·현지 비용 흔적으로 드러남"],
    "은퇴 준비 시작": ["정년을 앞두고 노후자금·퇴직연금을 새로 굴리기 시작하는 맥락 — 아직 연금을 '받는' 단계는 아님",
              "퇴직을 앞두고 노후 대비 저축·연금 가입을 시작한 정황(수령 전)"],
    "연금 수령 시작": ["정년 퇴직·은퇴로 더는 근로소득이 없는 사람에게 이번 달부터 매달 들어오기 시작한 연금성 입금 — 나이 들어 일을 그만둔 맥락이 함께 드러나야 함(신규 급여·임대수입과 구별)",
              "오랜 직장생활을 마치고 근로소득이 끊긴 뒤, 노후에 매달 지급되기 시작한 정기 입금 정황(수령 개시, 가입/준비 아님)"],
    "본인/가족 질병·입원·수술": ["큰 병원비·수술비 지출과 실손보험 청구처럼 입원·치료가 있었음이 드러남",
                    "갑작스런 의료비를 분할·대출로 처리하고 보험금을 청구하는 맥락"],
    "사고/재난 피해": ["사고·재해 보험금 수령과 복구비 지출처럼 피해를 입었음이 드러남",
               "재해 복구 비용을 보험금·대출로 충당하는 맥락"],
    "금융사기/피싱 피해": ["지급정지, 피해 신고, 사기 이체처럼 사기를 당했음이 드러남",
                  "사기 피해로 계좌를 막고 피해금을 신고·복구하는 맥락"],
}


def disambig_cue_for_label(label: str, index: int) -> str:
    cues = DISAMBIG_CUES.get(label)
    if not cues:
        return "표적 사건을 가장 가까운 형제 사건과 구별해 주는, 선언이 아닌 암묵적 정황·금융 흔적"
    return cues[index % len(cues)]


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

        elif gen_type == "occurred_positive":
            # occurred positives additionally inject a per-label disambiguating cue
            # so the event does not collapse to a generic sibling (see DISAMBIG_CUES).
            label = labels[i % len(labels)]
            hint = action_hint_for_label(label, taxonomy)
            action_id = representative_action_id(label, taxonomy)
            cue = disambig_cue_for_label(label, i // len(labels))
            job.update(target_label=label, target_action_id=action_id, action_hint=hint,
                       near_miss_event=None, disambig_cue=cue)
            job["prompt"] = (prompt_template
                             .replace("{TARGET_LABEL}", label)
                             .replace("{ACTION_HINT}", hint)
                             .replace("{DISAMBIG_CUE}", cue))

        else:  # pre_event_weak_signal / pre_event_upcoming / cancelled_reversed
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
    only_labels: Optional[set[str]] = None,
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
        if out_path.exists() and not overwrite and not only_labels:
            print(f"[skip] {out_path} exists (use --overwrite to replace)")
            continue
        count = counts.get(gen_type, 0)
        if max_items is not None:
            count = min(count, max_items)
        jobs = build_jobs(gen_type, count, taxonomy, seeds, labels)
        if only_labels:
            jobs = [j for j in jobs if j.get("target_label") in only_labels]
            print(f"[generate] {gen_type}: {len(jobs)} record(s) for labels {sorted(only_labels)} "
                  f"(merging into existing {out_path.name})")
        else:
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

        if only_labels and out_path.exists():
            # merge: replace regenerated conversation_ids in place, keep the rest
            existing = read_jsonl(out_path)
            new_by_id = {r["conversation_id"]: r for r in records}
            merged = [new_by_id.pop(r["conversation_id"], r) for r in existing]
            merged.extend(new_by_id.values())  # any genuinely new ids
            n = write_jsonl(out_path, merged)
            flagged = sum(1 for r in records if r.get("quality_flags"))
            print(f"  merged {len(records)} record(s) into {out_path} (total {n}, {flagged} flagged)\n")
        else:
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
    p_gen.add_argument("--only-labels", type=str, default=None,
                       help="comma-separated target labels; regenerate only these and "
                            "merge into the existing pool file (preserves other records)")

    p_dry = sub.add_parser("dry-run", help="Print planned prompts (never calls API)")
    p_dry.add_argument("--plan", type=Path, default=REPO / "configs/stage1_generation_plan.yaml")
    p_dry.add_argument("--types", type=str, default=None)
    p_dry.add_argument("--max-items", type=int, default=2)

    args = parser.parse_args()

    if args.command == "normalize-positive":
        normalize_positive(args.input, args.output, args.overwrite)
    elif args.command == "generate":
        plan = read_yaml(args.plan)
        only = {s.strip() for s in args.only_labels.split(",") if s.strip()} if args.only_labels else None
        run_generate(parse_types(args.types), plan, args.output_dir,
                     args.max_items, args.execute, args.overwrite, args.drop_invalid,
                     only_labels=only)
    elif args.command == "dry-run":
        plan = read_yaml(args.plan)
        run_dry_run(parse_types(args.types), plan, args.max_items)


if __name__ == "__main__":
    main()
