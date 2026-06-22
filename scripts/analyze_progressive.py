#!/usr/bin/env python3
"""Analyze the Stage 1 progressive-disclosure experiment.

Joins sample.jsonl (gold) with predictions.jsonl and computes, per model:
  Event-related records ("how many evidences to identify"):
    - first_correct_k   : first disclosure step whose primary label is correct
    - stable_correct_k   : step after which the label stays correct to the end
    - evidence_fraction  : stable_correct_k / n_user_turns
    - final_correct      : correct at full disclosure
  No-event records ("abstention robustness"):
    - ever_false_committed / first_false_commit_k
    - final_correct (abstained at the end) / recovered (committed then abstained)

Also a normalized detection curve (accuracy vs fraction of turns disclosed) and
breakdowns by generation_type. Writes analysis.json, per_record.csv, report.md.
"""
from __future__ import annotations

import argparse
import csv
import json
import statistics as st
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
GRID = [round(0.1 * i, 1) for i in range(1, 11)]  # 0.1 .. 1.0


def read_jsonl(p: Path) -> list[dict]:
    return [json.loads(l) for l in p.open(encoding="utf-8") if l.strip()]


def med(xs):
    xs = [x for x in xs if x is not None]
    return round(st.median(xs), 2) if xs else None


def gold_labels(rec: dict) -> set[str]:
    return {e["life_event_label"] for e in rec["gold"].get("life_events", []) if e.get("life_event_label")}


def gold_statuses(rec: dict) -> set[str]:
    return {e.get("event_status") for e in rec["gold"].get("life_events", []) if e.get("event_status")}


# An event is "must-detect" only when it has actually occurred. upcoming /
# weak_signal / cancelled events are gold event_related, but the detection
# prompt instructs the model to abstain (or mark weak_signal) on weak evidence
# and cannot even emit "cancelled" — so abstaining there is prompt-compliant.
ABSTAIN_OK_STATUSES = {"upcoming", "weak_signal", "cancelled", "implicit_candidate"}


def detect_kind(rec: dict) -> str:
    """One of: 'must_detect' (occurred event), 'abstain_ok' (event_related but
    only upcoming/weak/cancelled), 'no_event'."""
    g = rec["gold"]
    related = g.get("event_relation") == "event_related" or (
        g.get("event_relation") != "no_event" and bool(g.get("life_event_detected"))
    )
    if not related:
        return "no_event"
    return "must_detect" if "occurred" in gold_statuses(rec) else "abstain_ok"


def pred_label(row: dict) -> str:
    p = row.get("pred")
    if not p:
        return "no_event"  # errors / non-answers count as abstention
    return p.get("pred_label") or "no_event"


def pred_detected(row: dict) -> bool:
    p = row.get("pred")
    if not p:
        return False
    return bool(p.get("life_event_detected"))


def curve_value(series: list[tuple[int, bool]], n: int, frac: float) -> bool:
    """Step value at a normalized disclosure fraction: the correctness at the
    smallest k with k/n >= frac (carry the latest available if none)."""
    target_k = max(1, min(n, -(-int(round(frac * n * 100)) // 100) or 1))
    # pick the smallest k whose position k/n >= frac
    chosen = None
    for k, v in series:
        if k / n >= frac - 1e-9:
            chosen = v
            break
    if chosen is None and series:
        chosen = series[-1][1]
    return bool(chosen)


def analyze(sample_path: Path, pred_path: Path) -> dict:
    gold = {r["conversation_id"]: r for r in read_jsonl(sample_path)}
    preds = read_jsonl(pred_path)

    # group predictions by (provider/model, conversation_id)
    grouped: dict[tuple, dict[int, dict]] = {}
    models: set[str] = set()
    n_err = 0
    for row in preds:
        if row.get("error"):
            n_err += 1
        mkey = f"{row['provider']}:{row['model']}"
        models.add(mkey)
        grouped.setdefault((mkey, row["conversation_id"]), {})[row["k"]] = row

    per_record: list[dict] = []
    for (mkey, cid), byk in grouped.items():
        rec = gold.get(cid)
        if not rec:
            continue
        ks = sorted(byk)
        last = byk[ks[-1]]
        n = last.get("n_steps") or last.get("n_user_turns")
        disclose_unit = last.get("disclose_unit", "turn")
        kind = detect_kind(rec)
        glabels = gold_labels(rec)
        gtype = rec.get("generation_type", "?")
        gstatus = sorted(gold_statuses(rec))

        if kind in ("must_detect", "abstain_ok"):
            correct = [(k, pred_detected(byk[k]) and pred_label(byk[k]) in glabels) for k in ks]
            first_correct = next((k for k, c in correct if c), None)
            stable = None
            for k, _ in correct:
                if all(c for kk, c in correct if kk >= k):
                    stable = k
                    break
            final_correct = correct[-1][1] if correct else False
            # final disposition (used for abstain_ok lenient scoring)
            final_detected = pred_detected(byk[ks[-1]]) if ks else False
            if not final_detected:
                final_disp = "abstain"
            elif pred_label(byk[ks[-1]]) in glabels:
                final_disp = "detect_correct"
            else:
                final_disp = "detect_other"
            rowm = {
                "model": mkey, "conversation_id": cid, "generation_type": gtype,
                "kind": kind, "gold_label": sorted(glabels), "gold_status": gstatus,
                "n_steps": n, "disclose_unit": disclose_unit,"first_correct_k": first_correct,
                "stable_correct_k": stable,
                "evidence_fraction": round(stable / n, 3) if stable else None,
                "final_correct": final_correct, "final_disposition": final_disp,
                "_curve": [(k, c) for k, c in correct],
            }
        else:
            committed = [(k, pred_detected(byk[k])) for k in ks]
            ever = any(c for _, c in committed)
            first_commit = next((k for k, c in committed if c), None)
            final_abstain = not committed[-1][1] if committed else True
            rowm = {
                "model": mkey, "conversation_id": cid, "generation_type": gtype,
                "kind": "no_event", "gold_label": ["no_event"],
                "n_steps": n, "disclose_unit": disclose_unit,"ever_false_committed": ever,
                "first_false_commit_k": first_commit,
                "final_correct": final_abstain,
                "recovered": ever and final_abstain,
                # curve: correctness = abstaining
                "_curve": [(k, not c) for k, c in committed],
            }
        per_record.append(rowm)

    # aggregate per model
    agg = {}
    for mkey in sorted(models):
        recs = [r for r in per_record if r["model"] == mkey]
        must = [r for r in recs if r["kind"] == "must_detect"]
        soft = [r for r in recs if r["kind"] == "abstain_ok"]
        nos = [r for r in recs if r["kind"] == "no_event"]

        def curve(records):
            out = {}
            for f in GRID:
                vals = [curve_value(r["_curve"], r["n_steps"], f) for r in records if r["_curve"]]
                out[f] = round(sum(vals) / len(vals), 3) if vals else None
            return out

        def disp_rate(records, disp):
            return round(sum(r["final_disposition"] == disp for r in records) / len(records), 3) if records else None

        agg[mkey] = {
            "must_detect": {
                "n": len(must),
                "final_detection_accuracy": round(sum(r["final_correct"] for r in must) / len(must), 3) if must else None,
                "ever_correct_rate": round(sum(r["first_correct_k"] is not None for r in must) / len(must), 3) if must else None,
                "median_first_correct_k": med([r["first_correct_k"] for r in must]),
                "median_stable_correct_k": med([r["stable_correct_k"] for r in must]),
                "median_evidence_fraction": med([r["evidence_fraction"] for r in must]),
                "detection_curve": curve(must),
            },
            "abstain_ok": {
                "n": len(soft),
                "detect_correct_rate": disp_rate(soft, "detect_correct"),
                "abstain_rate": disp_rate(soft, "abstain"),
                "detect_other_rate": disp_rate(soft, "detect_other"),
                # lenient: detecting with the right label OR abstaining are both acceptable
                "lenient_accuracy": round(sum(r["final_disposition"] in ("detect_correct", "abstain") for r in soft) / len(soft), 3) if soft else None,
                "by_status": {
                    s: {
                        "n": sum(s in r["gold_status"] for r in soft),
                        "detect_correct": round(sum(r["final_disposition"] == "detect_correct" for r in soft if s in r["gold_status"]) / max(1, sum(s in r["gold_status"] for r in soft)), 3),
                        "abstain": round(sum(r["final_disposition"] == "abstain" for r in soft if s in r["gold_status"]) / max(1, sum(s in r["gold_status"] for r in soft)), 3),
                    }
                    for s in sorted({s for r in soft for s in r["gold_status"]})
                },
            },
            "no_event": {
                "n": len(nos),
                "final_abstention_accuracy": round(sum(r["final_correct"] for r in nos) / len(nos), 3) if nos else None,
                "false_commit_rate_any_step": round(sum(r["ever_false_committed"] for r in nos) / len(nos), 3) if nos else None,
                "median_first_false_commit_k": med([r["first_false_commit_k"] for r in nos]),
                "recovery_rate": round(sum(r["recovered"] for r in nos) / max(1, sum(r["ever_false_committed"] for r in nos)), 3) if nos else None,
                "abstention_curve": curve(nos),
            },
        }

        # by generation_type (false-commit for negatives, detection for positives)
        bytype = {}
        for r in recs:
            t = bytype.setdefault(r["generation_type"], {"n": 0, "final_correct": 0})
            t["n"] += 1
            t["final_correct"] += int(r["final_correct"])
        agg[mkey]["by_generation_type"] = {
            t: {"n": v["n"], "final_accuracy": round(v["final_correct"] / v["n"], 3)}
            for t, v in sorted(bytype.items())
        }

    disclose_unit = per_record[0].get("disclose_unit", "turn") if per_record else "turn"
    return {"models": sorted(models), "n_errors": n_err, "disclose_unit": disclose_unit,
            "aggregate": agg, "per_record": per_record, "grid": GRID}


def write_outputs(result: dict, outdir: Path) -> None:
    outdir.mkdir(parents=True, exist_ok=True)
    # strip private curve series from per_record for json/csv
    pr = []
    for r in result["per_record"]:
        rr = {k: v for k, v in r.items() if k != "_curve"}
        pr.append(rr)
    (outdir / "analysis.json").write_text(
        json.dumps({"models": result["models"], "n_errors": result["n_errors"],
                    "disclose_unit": result.get("disclose_unit", "turn"),
                    "grid": result["grid"], "aggregate": result["aggregate"]},
                   ensure_ascii=False, indent=2), encoding="utf-8")
    # per-record csv
    cols = ["model", "conversation_id", "generation_type", "kind", "gold_status",
            "n_steps", "disclose_unit", "first_correct_k", "stable_correct_k", "evidence_fraction",
            "final_disposition", "ever_false_committed", "first_false_commit_k",
            "recovered", "final_correct"]
    with (outdir / "per_record.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for r in pr:
            w.writerow(r)
    # markdown report
    write_report(result, outdir / "report.md")


def write_report(result: dict, path: Path) -> None:
    L = ["# Stage 1 — Evidence-to-Decision experiment\n",
         f"Models: {', '.join(result['models'])}  ·  parse/call errors: {result['n_errors']}\n",
         "\nScoring splits event-related records by gold `event_status`: **must-detect** "
         "(`occurred` — model should detect) vs **abstain-acceptable** "
         "(`upcoming`/`weak_signal`/`cancelled` — prompt allows / requires abstention).\n",
         "\n## A. Must-detect events (occurred) — how many evidences to identify\n",
         "| model | n | final detect acc | ever correct | median first-correct k | median stable k | median evidence fraction |",
         "|---|---|---|---|---|---|---|"]
    for m in result["models"]:
        e = result["aggregate"][m]["must_detect"]
        L.append(f"| {m} | {e['n']} | {e['final_detection_accuracy']} | {e['ever_correct_rate']} | "
                 f"{e['median_first_correct_k']} | {e['median_stable_correct_k']} | {e['median_evidence_fraction']} |")
    L += ["\n## B. Abstain-acceptable events (upcoming / weak_signal / cancelled)\n",
          "Both detecting with the correct label and abstaining are defensible; `lenient acc` counts either.\n",
          "| model | n | detect-correct | abstain | detect-other | lenient acc |",
          "|---|---|---|---|---|---|"]
    for m in result["models"]:
        s = result["aggregate"][m]["abstain_ok"]
        L.append(f"| {m} | {s['n']} | {s['detect_correct_rate']} | {s['abstain_rate']} | "
                 f"{s['detect_other_rate']} | {s['lenient_accuracy']} |")
    L += ["\n## C. Abstention robustness (no-event records)\n",
          "| model | n | final abstain acc | false-commit rate (any step) | median first false-commit k | recovery rate |",
          "|---|---|---|---|---|---|"]
    for m in result["models"]:
        ne = result["aggregate"][m]["no_event"]
        L.append(f"| {m} | {ne['n']} | {ne['final_abstention_accuracy']} | {ne['false_commit_rate_any_step']} | "
                 f"{ne['median_first_false_commit_k']} | {ne['recovery_rate']} |")
    unit = result.get("disclose_unit", "step")
    L += [f"\n## D. Detection curve — % correct vs fraction of {unit}s disclosed (must-detect only)\n",
          "| model | " + " | ".join(f"{int(f*100)}%" for f in result["grid"]) + " |",
          "|---|" + "---|" * len(result["grid"])]
    for m in result["models"]:
        c = result["aggregate"][m]["must_detect"]["detection_curve"]
        L.append(f"| {m} | " + " | ".join(str(c[f]) for f in result["grid"]) + " |")
    path.write_text("\n".join(L) + "\n", encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", type=Path, default=REPO / "results/experiment/sample.jsonl")
    ap.add_argument("--pred", type=Path, default=REPO / "results/experiment/predictions.jsonl")
    ap.add_argument("--outdir", type=Path, default=REPO / "results/experiment")
    args = ap.parse_args()
    result = analyze(args.sample, args.pred)
    write_outputs(result, args.outdir)
    print(f"[analyze] {len(result['per_record'])} (model,record) pairs, "
          f"{result['n_errors']} errors -> {args.outdir}/analysis.json, per_record.csv, report.md")


if __name__ == "__main__":
    main()
