"""Validation for Stage 1 unified-schema dialogue records.

`validate_record(record, cfg)` returns a list of human-readable issue strings.
An empty list means the record passed all checks. Callers decide what to do
with the issues (attach as `quality_flags`, trigger repair, or drop).

The checks implement section 7 of the task spec:
  - structural (required fields, turn counts, alternation, unique turn ids)
  - leakage (no FA codes, no visible headers, no direct life-event label,
    no chatbot summary leakage, no emoji, no 초성체)
  - gold consistency per generation_type (occurred / weak_signal / upcoming /
    cancelled / no_event)
"""
from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path
from typing import Any

# --- constants ---------------------------------------------------------------

# Chatbot phrases that explicitly acknowledge/summarise the life event and thus
# leak the gold label. Pattern-based so小 variations are caught.
CHATBOT_LEAKAGE_PHRASES = [
    "결혼하셨",
    "결혼 축하",
    "이사하셨",
    "이사 축하",
    "출산하셨",
    "출산 축하",
    "입양하셨",
    "퇴사하셨",
    "이직하셨",
    "전근",
    "별거 중이시",
    "이혼하셨",
    "가족이 사망",
    "상을 당하",
    "독립하셨",
    "분가하셨",
    "실직하셨",
    "취업 축하",
]

# Hangul Compatibility Jamo block (U+3131 ㄱ .. U+3163 ㅣ) — standalone
# consonants/vowels indicate 초성체 (e.g. ㅋㅋ, ㅎㅎ, ㅠㅠ).
_CHOSEONG_RE = re.compile(r"[ㄱ-ㅣ]")

# Emoji / pictographs (covers the common ranges; deliberately broad).
_EMOJI_RE = re.compile(
    "["
    "\U0001F300-\U0001FAFF"
    "\U00002600-\U000027BF"
    "\U0001F000-\U0001F0FF"
    "\U00002190-\U000021FF"
    "\U0000FE00-\U0000FE0F"
    "\U00002B00-\U00002BFF"
    "]"
)

_FA_CODE_RE = re.compile(r"FA-\d{2}")

# Visible section headers we never want inside conversation text, e.g.
# "대화 3 — FA-08" or markdown headers.
_HEADER_RE = re.compile(r"(대화\s*\d+\s*[—\-]|^#{1,6}\s|—\s*FA-)")

TAXONOMY_PATH = Path("data/processed/life_event_taxonomy.json")

# Curated set of words whose verbatim appearance directly *states* a life event.
# We deliberately EXCLUDE banking-product / memo / generic terms (전세, 월세, 대출,
# 계약, 갱신, 발생, 해소, 본인, 가족, 장례비, 이사비) because those are the
# legitimate indirect cues the benchmark relies on — flagging them would defeat
# the implicit-signal design. In particular `장례(비)` and `이사(비)` double as
# transfer-memo cues (and 장례비 is itself a designed hard-negative near-miss),
# so they are NOT treated as direct labels. The list below is limited to abstract
# event-statement words a user would only say when explaining their life.
DIRECT_EVENT_TOKENS = [
    "결혼", "신혼", "이혼", "별거", "출산", "입양", "분가",
    "이직", "전근", "퇴사", "실직", "사망", "부양가족",
    # Extended active-taxonomy labels. Kept to unambiguous words/phrases so plain
    # substring matching does not flag innocuous product talk (e.g. "주택" alone
    # appears in 주택청약/주택담보; "연금" alone in 연금저축). Not exhaustive.
    "취업", "복직", "휴직", "창업", "프리랜서", "폐업",
    "유학", "장기연수", "재교육", "은퇴", "연금 수령",
    "입원", "수술", "질병", "퇴거", "피싱", "보이스피싱",
    "재난 피해", "주택 구매", "주택 매각",
]


@lru_cache(maxsize=1)
def _label_tokens() -> list[str]:
    """Return words whose verbatim appearance counts as direct life-event leakage."""
    return sorted(DIRECT_EVENT_TOKENS, key=len, reverse=True)

# Future-timing cues used to validate `upcoming` examples.
FUTURE_TIMING_CUES = [
    "다음달", "다음 달", "담달", "내달", "다음주", "다음 주", "내주",
    "예정", "예약", "부터", "이후", "잔금일", "입주", "곧", "조만간",
    "내년", "다음달부터", "다음 달부터", "말일", "초에", "월부터",
]

# Cancellation cues used to validate `cancelled` examples.
CANCEL_CUES = [
    "안 하기로", "안하기로", "취소", "없던 일", "그대로", "안 옮기", "안옮기",
    "안 가기로", "안가기로", "무산", "철회", "안 하게", "안하게", "포기",
    "그냥 안", "안 하기", "안하기",
]

NO_EVENT_TYPES = {"neutral_no_event", "hard_negative", "existing_state_negative"}
OCCURRED_FALSE_TYPES = {"pre_event_weak_signal", "pre_event_upcoming", "cancelled_reversed"}
EVENT_RELATED_TYPES = {"occurred_positive"} | OCCURRED_FALSE_TYPES


def is_event_related_type(gen_type: str) -> bool:
    """True for single-record generation types that are life-event related."""
    return gen_type in EVENT_RELATED_TYPES


# --- atomic text checks ------------------------------------------------------

def has_emoji(text: str) -> bool:
    return bool(_EMOJI_RE.search(text))


def has_choseong(text: str) -> bool:
    return bool(_CHOSEONG_RE.search(text))


def has_fa_code(text: str) -> bool:
    return bool(_FA_CODE_RE.search(text))


def has_header(text: str) -> bool:
    return bool(_HEADER_RE.search(text))


def chatbot_leakage_hits(text: str) -> list[str]:
    return [p for p in CHATBOT_LEAKAGE_PHRASES if p in text]


def direct_label_hits(text: str) -> list[str]:
    return [tok for tok in _label_tokens() if tok in text]


def has_any(text: str, cues: list[str]) -> bool:
    return any(c in text for c in cues)


# --- record helpers ----------------------------------------------------------

def iter_turns(record: dict[str, Any]):
    for session in record.get("input", {}).get("sessions", []):
        sid = session.get("session_id")
        for turn in session.get("turns", []):
            yield sid, turn


def user_turn_ids(record: dict[str, Any]) -> set[str]:
    return {t["turn_id"] for _, t in iter_turns(record) if t.get("speaker") == "user"}


def all_turn_ids(record: dict[str, Any]) -> list[str]:
    return [t["turn_id"] for _, t in iter_turns(record)]


# --- main validator ----------------------------------------------------------

def validate_record(record: dict[str, Any], cfg: dict[str, Any] | None = None) -> list[str]:
    """Validate a unified Stage 1 record. Returns a list of issue strings."""
    cfg = cfg or {}
    gen = cfg.get("generation", {}) if isinstance(cfg.get("generation"), dict) else {}
    min_turns = gen.get("min_turns", 7)
    max_turns = gen.get("max_turns", 10)
    min_user = gen.get("min_user_turns", 4)
    max_user = gen.get("max_user_turns", 6)

    issues: list[str] = []
    gtype = record.get("generation_type", "")

    # --- required top-level fields ---
    for field in ("conversation_id", "task", "generation_type", "input", "gold"):
        if field not in record:
            issues.append(f"missing required field: {field}")
    sessions = record.get("input", {}).get("sessions", [])
    if not sessions:
        issues.append("input.sessions is empty")
        return issues  # nothing more to check

    is_multi = len(sessions) > 1

    # --- per-session structural checks ---
    seen_turn_ids: set[str] = set()
    total_turns = 0
    total_user_turns = 0
    for session in sessions:
        turns = session.get("turns", [])
        total_turns += len(turns)
        prev_speaker = None
        consecutive = 0
        for turn in turns:
            tid = turn.get("turn_id")
            if tid in seen_turn_ids:
                issues.append(f"duplicate turn_id: {tid}")
            seen_turn_ids.add(tid)
            if turn.get("speaker") == "user":
                total_user_turns += 1
            # speaker alternation (allow occasional repeats but flag runs >=3)
            if turn.get("speaker") == prev_speaker:
                consecutive += 1
                if consecutive >= 2:
                    issues.append(
                        f"{session.get('session_id')}: 3+ consecutive {turn.get('speaker')} turns"
                    )
            else:
                consecutive = 0
            prev_speaker = turn.get("speaker")

    # --- turn-count bounds (single-session only; cancelled multi-session exempt) ---
    if not is_multi:
        if not (min_turns <= total_turns <= max_turns):
            issues.append(f"turn count {total_turns} out of [{min_turns},{max_turns}]")
        if not (min_user <= total_user_turns <= max_user):
            issues.append(f"user turn count {total_user_turns} out of [{min_user},{max_user}]")
    else:
        if total_turns < 4:
            issues.append(f"multi-session total turn count too small: {total_turns}")

    # --- text leakage checks ---
    check_direct_label = gtype not in ("",) and gtype != "neutral_no_event"
    for sid, turn in iter_turns(record):
        text = turn.get("text", "")
        if has_emoji(text):
            issues.append(f"{turn.get('turn_id')}: contains emoji")
        if has_choseong(text):
            issues.append(f"{turn.get('turn_id')}: contains 초성체")
        if has_fa_code(text):
            issues.append(f"{turn.get('turn_id')}: contains FA code")
        if has_header(text):
            issues.append(f"{turn.get('turn_id')}: contains visible header")
        if turn.get("speaker") == "assistant":
            for hit in chatbot_leakage_hits(text):
                issues.append(f"{turn.get('turn_id')}: chatbot leakage phrase '{hit}'")
        # direct label mention applies to both speakers for non-neutral types
        if check_direct_label:
            for hit in direct_label_hits(text):
                issues.append(f"{turn.get('turn_id')}: direct life-event label '{hit}'")

    # --- gold consistency ---
    gold = record.get("gold", {})
    life_events = gold.get("life_events", [])
    relation = gold.get("event_relation")

    # Use gold.event_relation as the source of truth (works for both single and
    # mixed records); fall back to generation_type when relation is absent.
    if relation == "no_event":
        if life_events:
            issues.append("no_event but life_events is non-empty")
    elif relation == "event_related":
        if not life_events:
            issues.append("event_related but life_events is empty")
    elif gtype in NO_EVENT_TYPES:
        if life_events:
            issues.append("no_event type but life_events is non-empty")
    elif gtype and is_event_related_type(gtype):
        if not life_events:
            issues.append("event-related type but life_events is empty")

    # evidence turns must refer to user turns
    u_ids = user_turn_ids(record)
    for ev in life_events:
        for tid in ev.get("evidence_turns", []) or []:
            if tid not in u_ids:
                issues.append(f"evidence turn {tid} is not a user turn")
        # occurred flag consistency
        if gtype == "occurred_positive" and ev.get("occurred") is not True:
            issues.append("occurred_positive but occurred != true")
        if gtype in OCCURRED_FALSE_TYPES and ev.get("occurred") is not False:
            issues.append(f"{gtype} but occurred != false")

    # upcoming requires a future timing cue somewhere in user text
    if gtype == "pre_event_upcoming":
        user_text = " ".join(
            t.get("text", "") for _, t in iter_turns(record) if t.get("speaker") == "user"
        )
        if not has_any(user_text, FUTURE_TIMING_CUES):
            issues.append("pre_event_upcoming but no future timing cue found")

    # cancelled requires >=2 sessions or an explicit cancellation cue
    if gtype == "cancelled_reversed":
        user_text = " ".join(
            t.get("text", "") for _, t in iter_turns(record) if t.get("speaker") == "user"
        )
        if not is_multi and not has_any(user_text, CANCEL_CUES):
            issues.append("cancelled_reversed but neither multi-session nor cancellation cue")

    return issues
