#!/usr/bin/env python3
"""Stage 1 progressive-disclosure experiment runner.

For each (model, record), reveal the conversation one USER turn at a time. At
disclosure step k the model sees every turn up to and including the k-th user
turn and must predict {life_event_detected, life_events:[{label,status,...}]}
using the Stage 1 detection prompt. Abstention (no_event) is the correct answer
until enough evidence is visible.

Writes one JSONL row per (provider, model, conversation_id, k). Resumable: rows
already present in the output are skipped. Concurrent across calls.

  python scripts/run_stage1_progressive.py \
    --sample results/experiment/sample.jsonl \
    --out results/experiment/predictions.jsonl \
    --models openai,anthropic,google [--max-records N] [--concurrency 8]
"""
from __future__ import annotations

import argparse
import json
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib.llm_clients import DEFAULT_MODELS, complete, parse_json_loose  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
PROMPT = REPO / "prompts/stage1_life_event_detection_ko.md"

USER_TMPL = (
    "다음은 사용자와 은행 챗봇의 대화입니다. 지금까지 공개된 부분이며, "
    "마지막 사용자 발화 이후의 내용은 아직 알 수 없습니다.\n"
    "지금까지 공개된 내용만 근거로 Life Event를 판정하세요. "
    "근거가 부족하면 반드시 no_event로 두세요(섣불리 단정하지 말 것).\n\n"
    "{conv}\n\n"
    "지정된 JSON 형식으로만 답하세요."
)


def read_jsonl(p: Path) -> list[dict]:
    return [json.loads(l) for l in p.open(encoding="utf-8") if l.strip()]


def flatten_turns(record: dict) -> list[tuple[str, dict]]:
    out = []
    for s in record["input"]["sessions"]:
        for t in s["turns"]:
            out.append((s["session_id"], t))
    return out


def user_step_indices(turns: list[tuple[str, dict]]) -> list[int]:
    return [i for i, (_, t) in enumerate(turns) if t.get("speaker") == "user"]


def session_slices(record: dict) -> list[tuple[str, list[tuple[str, dict]]]]:
    """Cumulative session disclosure: step k reveals sessions[:k] in full.
    Returns [(last_session_id, turns_up_to_and_including_session_k), ...]."""
    sessions = record["input"]["sessions"]
    out = []
    acc: list[tuple[str, dict]] = []
    for s in sessions:
        for t in s["turns"]:
            acc.append((s["session_id"], t))
        out.append((s["session_id"], list(acc)))
    return out


def render(turns_slice: list[tuple[str, dict]], multi_session: bool) -> str:
    lines, cur = [], None
    for sid, t in turns_slice:
        if multi_session and sid != cur:
            lines.append(f"== 세션 {sid} ==")
            cur = sid
        who = "사용자" if t.get("speaker") == "user" else "챗봇"
        lines.append(f"[{t['turn_id']}] {who}: {t.get('text','')}")
    return "\n".join(lines)


def normalize_pred(obj: dict) -> dict:
    events = obj.get("life_events") or []
    primary = events[0] if events else {}
    detected = obj.get("life_event_detected")
    if detected is None:
        detected = bool(events)
    return {
        "life_event_detected": bool(detected),
        "life_events": events,
        "pred_label": primary.get("life_event_label") or "no_event",
        "pred_status": primary.get("event_status") or "no_event",
        "confidence": primary.get("confidence"),
    }


def build_tasks(records: list[dict], models: list[tuple[str, str]], done: set,
                disclose: str = "session") -> list[dict]:
    tasks = []
    for rec in records:
        multi = len(rec["input"]["sessions"]) > 1
        steps_meta: list[dict] = []  # one entry per disclosure step
        if disclose == "session":
            for sid, turns_slice in session_slices(rec):
                steps_meta.append({"conv": render(turns_slice, multi),
                                   "revealed_session_id": sid})
        else:  # turn
            turns = flatten_turns(rec)
            for end_idx in user_step_indices(turns):
                steps_meta.append({"conv": render(turns[: end_idx + 1], multi),
                                   "revealed_user_turn_id": turns[end_idx][1]["turn_id"]})
        n = len(steps_meta)
        for k, sm in enumerate(steps_meta, start=1):
            for provider, model in models:
                key = (provider, model, rec["conversation_id"], k)
                if key in done:
                    continue
                tasks.append({
                    "provider": provider, "model": model,
                    "conversation_id": rec["conversation_id"],
                    "generation_type": rec.get("generation_type", "?"),
                    "k": k, "n_steps": n, "disclose_unit": disclose,
                    "revealed_session_id": sm.get("revealed_session_id"),
                    "revealed_user_turn_id": sm.get("revealed_user_turn_id"),
                    "conv": sm["conv"],
                })
    return tasks


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", type=Path, default=REPO / "results/experiment/sample.jsonl")
    ap.add_argument("--out", type=Path, default=REPO / "results/experiment/predictions.jsonl")
    ap.add_argument("--models", type=str, default="openai,anthropic,google",
                    help="comma list of providers; or provider=modelid pairs")
    ap.add_argument("--max-records", type=int, default=None)
    ap.add_argument("--concurrency", type=int, default=8)
    ap.add_argument("--max-tokens", type=int, default=2048)
    ap.add_argument("--disclose", choices=["session", "turn"], default="session",
                    help="progressive disclosure unit (default: session)")
    args = ap.parse_args()

    models: list[tuple[str, str]] = []
    for spec in args.models.split(","):
        spec = spec.strip()
        if not spec:
            continue
        if "=" in spec:
            prov, mid = spec.split("=", 1)
            models.append((prov.strip(), mid.strip()))
        else:
            models.append((spec, DEFAULT_MODELS[spec]))

    system = PROMPT.read_text(encoding="utf-8")
    records = read_jsonl(args.sample)
    if args.max_records:
        records = records[: args.max_records]

    args.out.parent.mkdir(parents=True, exist_ok=True)
    done = set()
    if args.out.exists():
        for r in read_jsonl(args.out):
            done.add((r["provider"], r["model"], r["conversation_id"], r["k"]))

    tasks = build_tasks(records, models, done, disclose=args.disclose)
    print(f"[run] disclose={args.disclose} · {len(records)} records x {len(models)} models "
          f"-> {len(tasks)} new calls ({len(done)} already done)")
    if not tasks:
        print("[run] nothing to do.")
        return

    lock = threading.Lock()
    fout = args.out.open("a", encoding="utf-8")
    counters = {"ok": 0, "err": 0}

    def work(task: dict) -> dict:
        t0 = time.time()
        user = USER_TMPL.format(conv=task["conv"])
        row = {k: task[k] for k in ("provider", "model", "conversation_id",
                                    "generation_type", "k", "n_steps", "disclose_unit",
                                    "revealed_session_id", "revealed_user_turn_id")}
        try:
            raw = complete(task["provider"], task["model"], system=system,
                           user=user, max_tokens=args.max_tokens)
            try:
                pred = normalize_pred(parse_json_loose(raw))
                row["pred"] = pred
            except Exception as pe:  # noqa: BLE001
                row["error"] = f"parse_error: {pe}"
                row["raw"] = raw[:1000]
        except Exception as ce:  # noqa: BLE001
            row["error"] = f"call_error: {ce}"
        row["latency_s"] = round(time.time() - t0, 2)
        return row

    with ThreadPoolExecutor(max_workers=args.concurrency) as ex:
        futures = [ex.submit(work, t) for t in tasks]
        for i, fut in enumerate(as_completed(futures), 1):
            row = fut.result()
            with lock:
                fout.write(json.dumps(row, ensure_ascii=False) + "\n")
                fout.flush()
                counters["err" if row.get("error") else "ok"] += 1
            if i % 25 == 0 or i == len(futures):
                print(f"  {i}/{len(futures)}  ok={counters['ok']} err={counters['err']}")

    fout.close()
    print(f"[run] done. ok={counters['ok']} err={counters['err']} -> {args.out}")


if __name__ == "__main__":
    main()
