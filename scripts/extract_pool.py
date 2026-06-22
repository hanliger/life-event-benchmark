#!/usr/bin/env python3
"""Extract action pool, life event taxonomy, and dialogue examples from Life Event Pool markdown.

This script is intentionally conservative and mirrors the extraction used to build the skeleton.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from collections import Counter

CATEGORY_MAP = {
    "가족·관계 변화": "family_relationship",
    "주거 변화": "housing",
    "직업·소득·사업 변화": "career_income_business",
    "교육·역량 투자": "education_capability",
    "은퇴·노후 전환": "retirement_aging",
    "비정기·위기 사건": "irregular_crisis",
}


def clean_md(text: str) -> str:
    return re.sub(r"\*\*|~~|`", "", text).strip()


def write_json(path: Path, obj) -> None:
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)

    lines = args.input.read_text(encoding="utf-8").splitlines()

    start = next(i for i, line in enumerate(lines) if line.strip().startswith("# 1. 금융 Action Pool"))
    end = next(i for i, line in enumerate(lines[start + 1 :], start + 1) if line.strip().startswith("# 2. Life Event"))
    actions = []
    for line in lines[start:end]:
        s = line.strip()
        if s.startswith("|") and not re.match(r"\|\s*---", s) and "Action ID" not in s:
            cells = [clean_md(c) for c in s.strip("|").split("|")]
            if len(cells) >= 4 and cells[0].startswith("FA-"):
                actions.append({
                    "action_id": cells[0],
                    "name_ko": cells[1],
                    "risk": cells[2].lower(),
                    "funds_movement": cells[2].lower() == "high",
                    "description_ko": cells[3],
                    "source": "uploaded_life_event_pool",
                })

    current_category = None
    events = []
    for line in lines:
        s = line.strip()
        for ko, code in CATEGORY_MAP.items():
            if re.match(r"#+\s*(\d+[)-]?\s*)?" + re.escape(ko) + r"\s*$", s):
                current_category = (code, ko)
        if s.startswith("|") and "Life event" not in s and not re.match(r"\|\s*---", s):
            cells = [clean_md(c) for c in s.strip("|").split("|")]
            if len(cells) >= 3 and cells[1].startswith("FA-"):
                disabled = "~~" in s.split("|")[1] if "|" in s else False
                action_ids = [a.strip() for a in re.split(r",\s*", cells[1]) if a.strip().startswith("FA-")]
                events.append({
                    "event_label_ko": cells[0],
                    "event_id": None,
                    "category": current_category[0] if current_category else None,
                    "category_ko": current_category[1] if current_category else None,
                    "matched_actions": action_ids,
                    "banking_situation_ko": cells[2],
                    "active": not disabled,
                    "source": "uploaded_life_event_pool",
                })

    cat_counts = Counter()
    for event in events:
        cat_counts[event["category"]] += 1
        event["event_id"] = f"LE-{event['category'].upper()[:3]}-{cat_counts[event['category']]:02d}"

    event_labels = {e["event_label_ko"] for e in events}
    event_id_by_label = {e["event_label_ko"]: e["event_id"] for e in events}
    event_active_by_label = {e["event_label_ko"]: e["active"] for e in events}

    current_category = None
    current_event = None
    current_source = "unknown"
    conversations = []
    cur = None
    for idx, line in enumerate(lines, 1):
        s = line.strip()
        if not s:
            continue
        if "대화 예시(재용)" in s:
            current_source = "jaeyong"
        elif "대화 예시(재익)" in s:
            current_source = "jaeik"
        elif (re.match(r"-\s*대화\s*예시", s) or re.match(r"-\s*대화예시", s)) and idx > 980:
            current_source = "generic"
        for ko, code in CATEGORY_MAP.items():
            if re.match(r"#+\s*(\d+[)-]?\s*)?" + re.escape(ko) + r"\s*$", s):
                current_category = (code, ko)
                current_event = None
        if s.startswith("#") and "대화" not in s:
            head = clean_md(re.sub(r"^#+\s*", "", s))
            label = re.sub(r"^\d+(?:-\d+)?[\)\.]\s*", "", head).strip()
            label = re.sub(r"\s*\(FA-[^)]+\)\s*$", "", label).strip()
            if label in event_labels:
                current_event = label
        m = re.match(r"#+\s*(~~)?(?:대화\s*\d+|대화\s*\d+).*?FA-(\d{2})\s*\((.*?)\)", s)
        if m:
            if cur:
                conversations.append(cur)
            action_id = "FA-" + m.group(2)
            cur = {
                "conversation_id": None,
                "source": current_source,
                "category": current_category[0] if current_category else None,
                "category_ko": current_category[1] if current_category else None,
                "life_event_label": current_event,
                "event_id": event_id_by_label.get(current_event),
                "is_event_positive": True,
                "event_status": "implicit_candidate",
                "action_id": action_id,
                "action_name_ko": clean_md(m.group(3)),
                "title_ko": clean_md(re.sub(r"^#+\s*", "", s)),
                "active_conversation": not (bool(m.group(1)) or "~~" in s),
                "active_event_in_taxonomy": event_active_by_label.get(current_event, True),
                "turns": [],
                "source_line": idx,
            }
            continue
        if cur:
            mt = re.match(r"(?:~~)?\*\*(나|챗봇):\*\*\s*(.*?)(?:~~)?\s*$", s)
            if mt:
                speaker = "user" if mt.group(1) == "나" else "assistant"
                content = clean_md(mt.group(2))
                if content:
                    cur["turns"].append({"turn_id": f"T{len(cur['turns']) + 1:02d}", "speaker": speaker, "text": content})
    if cur:
        conversations.append(cur)

    active = [c for c in conversations if c["active_conversation"] and c["active_event_in_taxonomy"] and c["life_event_label"]]
    for i, conv in enumerate(active, 1):
        conv["conversation_id"] = f"POS-{i:04d}"
    for i, conv in enumerate(conversations, 1):
        if conv["conversation_id"] is None:
            conv["conversation_id"] = f"RAW-{i:04d}"

    write_json(args.output / "action_pool.json", actions)
    write_json(args.output / "life_event_taxonomy.json", events)
    write_json(args.output / "event_action_matching.json", [
        {k: e[k] for k in ["event_id", "event_label_ko", "category", "category_ko", "matched_actions", "banking_situation_ko", "active"]}
        for e in events
    ])
    with (args.output / "conversation_examples.jsonl").open("w", encoding="utf-8") as f:
        for conv in active:
            f.write(json.dumps(conv, ensure_ascii=False) + "\n")
    print(f"actions={len(actions)} events={len(events)} active_conversations={len(active)}")


if __name__ == "__main__":
    main()
