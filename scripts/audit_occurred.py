#!/usr/bin/env python3
"""Audit occurred-positive records for label quality.

By design, occurred records present the event as a completed/established fact
with decisive evidence in the user turns. If frontier detection models — given
the FULL conversation — cannot recover the gold label, the evidence is absent or
misleading: a data defect, not a model failure.

For every record whose gold contains an `occurred` event, this runs the Stage 1
detection prompt at full disclosure across all configured models and tiers them:
  - bad      : 0 of N models recovered a gold occurred label (unanimous miss)
  - suspect  : minority recovered it (majority miss)
  - ok       : majority/all recovered it

Writes results/experiment/occurred_audit.json and prints a summary. No data is
mutated here; regeneration is a separate step driven by the `bad`/`suspect` ids.

  python scripts/audit_occurred.py [--models openai,anthropic,google] [--concurrency 8]
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
from run_stage1_progressive import (  # noqa: E402
    USER_TMPL, flatten_turns, normalize_pred, render,
)

REPO = Path(__file__).resolve().parent.parent
PROMPT = REPO / "prompts/stage1_life_event_detection_ko.md"
SOURCES = [
    REPO / "data/generated/single/stage1_single_eval_v0.jsonl",
    REPO / "data/generated/mixed/stage1_mixed_eval_v0.jsonl",
]


def read_jsonl(p: Path) -> list[dict]:
    return [json.loads(l) for l in p.open(encoding="utf-8") if l.strip()]


def occurred_labels(rec: dict) -> set[str]:
    return {e.get("life_event_label") for e in rec["gold"].get("life_events", [])
            if e.get("event_status") == "occurred" and e.get("life_event_label")}


def pred_labels(pred: dict) -> set[str]:
    out = set()
    for e in pred.get("life_events", []) or []:
        if e.get("life_event_label"):
            out.add(e["life_event_label"])
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", type=str, default="openai,anthropic,google")
    ap.add_argument("--concurrency", type=int, default=8)
    ap.add_argument("--max-tokens", type=int, default=2048)
    ap.add_argument("--out", type=Path, default=REPO / "results/experiment/occurred_audit.json")
    args = ap.parse_args()

    models: list[tuple[str, str]] = []
    for spec in args.models.split(","):
        spec = spec.strip()
        if not spec:
            continue
        prov, mid = (spec.split("=", 1) if "=" in spec else (spec, DEFAULT_MODELS[spec]))
        models.append((prov.strip(), mid.strip()))

    system = PROMPT.read_text(encoding="utf-8")
    records = []
    for src in SOURCES:
        records += read_jsonl(src)
    occ = [r for r in records if occurred_labels(r)]
    print(f"[audit] {len(occ)} occurred records x {len(models)} models = {len(occ)*len(models)} calls")

    tasks = []
    for rec in occ:
        turns = flatten_turns(rec)
        multi = len(rec["input"]["sessions"]) > 1
        conv = render(turns, multi)  # full disclosure
        for provider, model in models:
            tasks.append({"provider": provider, "model": model,
                          "cid": rec["conversation_id"], "conv": conv})

    results: dict = {}
    lock = threading.Lock()

    def work(t: dict) -> dict:
        t0 = time.time()
        out = {"provider": t["provider"], "model": t["model"], "cid": t["cid"]}
        try:
            raw = complete(t["provider"], t["model"], system=system,
                           user=USER_TMPL.format(conv=t["conv"]), max_tokens=args.max_tokens)
            out["pred"] = normalize_pred(parse_json_loose(raw))
        except Exception as e:  # noqa: BLE001
            out["error"] = str(e)[:200]
        out["latency_s"] = round(time.time() - t0, 2)
        return out

    with ThreadPoolExecutor(max_workers=args.concurrency) as ex:
        futs = [ex.submit(work, t) for t in tasks]
        for i, f in enumerate(as_completed(futs), 1):
            r = f.result()
            results.setdefault(r["cid"], []).append(r)
            if i % 30 == 0 or i == len(futs):
                print(f"  {i}/{len(futs)}")

    # score per record
    by_cid = {r["conversation_id"]: r for r in occ}
    audit = []
    for cid, rows in results.items():
        rec = by_cid[cid]
        gold = occurred_labels(rec)
        hits, says = 0, {}
        for row in rows:
            p = row.get("pred")
            got = bool(p and p.get("life_event_detected") and (pred_labels(p) & gold))
            hits += int(got)
            mk = f"{row['provider'].split(':')[0]}"
            if p:
                says[mk] = "✓" if got else (",".join(sorted(pred_labels(p))) or "no_event")
            else:
                says[mk] = f"ERR"
        n = len(rows)
        # majority recovered -> ok; none recovered -> bad; minority -> suspect
        tier = "ok" if hits > n / 2 else ("bad" if hits == 0 else "suspect")
        audit.append({
            "conversation_id": cid,
            "generation_type": rec.get("generation_type"),
            "gold_occurred": sorted(gold),
            "n_models": n, "n_recovered": hits, "tier": tier,
            "model_says": says,
        })

    audit.sort(key=lambda a: (a["tier"] != "bad", a["tier"] != "suspect", a["conversation_id"]))
    summary = {"bad": 0, "suspect": 0, "ok": 0}
    for a in audit:
        summary[a["tier"]] += 1
    out = {"models": [f"{p}:{m}" for p, m in models], "n_records": len(audit),
           "summary": summary, "records": audit}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n[audit] summary: {summary}  -> {args.out}\n")
    for a in audit:
        if a["tier"] == "ok":
            continue
        says = "  ".join(f"{k}={v}" for k, v in sorted(a["model_says"].items()))
        print(f"  [{a['tier']:7s}] {a['conversation_id']}  gold={a['gold_occurred']}  ({a['generation_type']})")
        print(f"             {says}")


if __name__ == "__main__":
    main()
