#!/usr/bin/env python3
"""Prototype: CROSS-SESSION drift records for Stage 1.

Hypothesis: if a life event is revealed only by a *shift across sessions*
(여자친구 → 와이프), then no single session is sufficient to infer the EVENT —
only comparing sessions reveals it. This is the genuine multi-session implicit
inference the benchmark aspires to, unlike the current composed-mixed records
where the whole signal sits inside one session.

This script (1) generates one coherent persona's multi-session history with
claude-sonnet-4-6, where the event leaks ONLY through a cross-session referential
shift, and (2) probes detection with all 3 models on each single session vs. the
full sequence. If single-session detection abstains/misses but full-sequence
detection recovers the event, the design works.

  GEN_MODEL=claude-sonnet-4-6 GEN_PROVIDER=anthropic python3 scripts/prototype_cross_session.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib.llm_clients import complete, parse_json_loose  # noqa: E402
from run_stage1_progressive import USER_TMPL, normalize_pred  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
DET_PROMPT = (REPO / "prompts/stage1_life_event_detection_ko.md").read_text(encoding="utf-8")
MODELS = [("anthropic", "claude-opus-4-8"), ("openai", "gpt-5.5"), ("google", "gemini-3.5-flash")]

GEN_SYSTEM = "너는 한국어 은행 챗봇 대화 데이터를 정확한 JSON으로만 생성하는 도구다."

# Each scenario: the event is inferable ONLY from the shift between sessions.
SCENARIOS = [
    {
        "label": "결혼",
        "instruction": (
            "한 사람(동일 인물)의 은행 챗봇 대화를 시간 순서로 3개 세션으로 만든다. "
            "세션들은 수개월 간격이다. 이 사람은 S1과 S3 사이에 결혼했다. 파트너는 "
            "세션 내내 '민지'라는 같은 이름으로만 지칭한다.\n"
            "- S1(과거): '여자친구 민지'라고 한 번 자연스럽게 밝히고, 연애 단계의 평범한 업무"
            "(데이트 비용 반반 정산, 민지에게 가끔 이체 등).\n"
            "- S2(중간): 결혼과 무관한 평범한 은행 업무. 민지·결혼 신호 없음.\n"
            "- S3(현재): '민지'를 이름으로만 지칭하며, 둘이 살림을 합쳐 공동 생활비 통장을 만들고 "
            "민지를 가족/피보험자로 등록하는 평범한 업무. **단, 민지가 누구인지(여자친구/와이프/배우자) "
            "관계 단어는 일절 쓰지 않는다.**\n"
            "절대 규칙: '결혼/혼인/예식/청첩장/와이프/배우자/남편/부부' 단어 전부 금지. 어느 한 세션도 "
            "단독으론 결혼을 알 수 없어야 한다 — S3만 보면 '민지라는 사람과 공동통장·가족등록' 정도로만 "
            "보여서 가족/지인일 수도 있게. 결혼이라는 사건은 오직 S1(민지=여자친구) → S3(민지와 살림 합치고 "
            "가족 등록)의 대조로만 추론되게 하라. 각 세션은 평범한 은행 상담으로 읽혀야 한다."
        ),
    },
    {
        "label": "이직/전근",
        "instruction": (
            "한 사람(동일 인물)의 은행 챗봇 대화를 시간 순서로 3개 세션으로 만든다. "
            "세션들은 수개월 간격이다. 이 사람은 S1과 S3 사이에 다니던 회사를 옮겼다.\n"
            "- S1(과거): 매달 '한빛전자'에서 급여가 들어오는 직장인의 평범한 업무"
            "(급여통장 관리, 급여일 자동이체 등). 회사명 '한빛전자'를 자연스럽게 한 번 언급.\n"
            "- S2(중간): 회사와 무관한 평범한 업무(카드·적금 등).\n"
            "- S3(현재): 이제 매달 '대성물산'에서 급여가 들어온다. 새 급여 입금처에 맞춰 자동이체를 "
            "재정렬하는 평범한 업무. 회사명 '대성물산'을 자연스럽게 한 번 언급.\n"
            "절대 규칙: '이직/전직/퇴사/입사/회사를 옮겼다' 같은 직접 표현 전부 금지. 어느 한 세션도 "
            "단독으론 직장 변화를 알 수 없어야 한다 — S1만 보면 '한빛전자 다니는 직장인', S3만 보면 "
            "'대성물산 다니는 직장인'으로만 보여서 사건이 없게. 이직이라는 사건은 오직 S1(급여=한빛전자) → "
            "S3(급여=대성물산)라는 급여 입금처 변화의 대조로만 추론되게 하라."
        ),
    },
]

OUT_SCHEMA_HINT = (
    '출력은 JSON만: {"sessions": [{"session_id":"S1","turns":[{"speaker":"user","text":"..."},'
    '{"speaker":"assistant","text":"..."}]}, {"session_id":"S2",...}, {"session_id":"S3",...}]}. '
    "각 세션 user 발화 3~5개, user/assistant 교대. 이모지·초성체 금지."
)


def gen_record(scn: dict) -> dict:
    raw = complete("anthropic", "claude-sonnet-4-6",
                   system=GEN_SYSTEM, user=scn["instruction"] + "\n\n" + OUT_SCHEMA_HINT,
                   max_tokens=4096)
    try:
        return parse_json_loose(raw)
    except Exception:
        # one retry with an explicit "JSON만, 짧게" nudge
        raw = complete("anthropic", "claude-sonnet-4-6",
                       system=GEN_SYSTEM,
                       user=scn["instruction"] + "\n\n" + OUT_SCHEMA_HINT
                       + "\n반드시 완결된 JSON 하나만 출력하라. 각 세션 user 발화는 3개로 짧게.",
                       max_tokens=4096)
        return parse_json_loose(raw)


def render(sessions: list[dict], multi: bool) -> str:
    lines = []
    for s in sessions:
        if multi:
            lines.append(f"== 세션 {s['session_id']} ==")
        for i, t in enumerate(s["turns"], 1):
            who = "사용자" if t["speaker"] == "user" else "챗봇"
            lines.append(f"[{s['session_id']}-{'U' if t['speaker']=='user' else 'A'}{i}] {who}: {t.get('text','')}")
    return "\n".join(lines)


def detect(conv: str) -> dict:
    out = {}
    for prov, model in MODELS:
        try:
            raw = complete(prov, model, system=DET_PROMPT, user=USER_TMPL.format(conv=conv), max_tokens=2048)
            p = normalize_pred(parse_json_loose(raw))
            out[prov] = (p.get("pred_label"), p.get("pred_status"))
        except Exception as e:  # noqa: BLE001
            out[prov] = ("ERR", str(e)[:40])
    return out


def main() -> None:
    for scn in SCENARIOS:
        print("#" * 70)
        print(f"# SCENARIO: {scn['label']}  (event hidden in cross-session drift)")
        print("#" * 70)
        rec = gen_record(scn)
        sessions = rec["sessions"]
        for s in sessions:
            print(f"\n── {s['session_id']} ──")
            for t in s["turns"]:
                if t["speaker"] == "user":
                    print("  U:", t.get("text", ""))

        # probes
        probes = {
            "S1 only": [sessions[0]],
            "S3 only": [sessions[-1]],
            "S1+S2+S3 (full)": sessions,
        }
        print("\n=== DETECTION (label, status) per probe ===")
        for name, subset in probes.items():
            conv = render(subset, multi=len(subset) > 1)
            res = detect(conv)
            cells = "  ".join(f"{k}={v[0]}" for k, v in res.items())
            print(f"  [{name:16s}] {cells}")
        # persist for inspection
        outp = REPO / "results/experiment/prototype_cross_session.json"
        outp.parent.mkdir(parents=True, exist_ok=True)
        outp.write_text(json.dumps(rec, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n[saved record] {outp}")


if __name__ == "__main__":
    main()
