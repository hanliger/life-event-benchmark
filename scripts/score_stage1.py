#!/usr/bin/env python3
"""Score Stage 1 Life Event Detection predictions (expanded labels & statuses).

Gold JSONL: unified Stage 1 records (single or mixed). Each row has an id
(`conversation_id`, falling back to `scenario_id`), a `generation_type`, and a
`gold` object with `event_relation`, `life_event_detected`, and `life_events`.

Prediction JSONL rows:
  {"conversation_id": ..., "life_event_detected": bool,
   "life_events": [{"session_id", "life_event_label", "event_status",
                    "occurred", "confidence", "evidence_turns"}]}
(also accepts a nested {"prediction": {...}} and legacy `scenario_id`.)

Separately measures event-related detection, occurred detection, label and
status classification, localization, and evidence — plus the false-positive /
false-occurred rates for each hard negative / pre-event bucket.
"""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any

OCCURRED_STATUSES = {"occurred"}


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def safe_div(num: float, den: float) -> float:
    return num / den if den else 0.0


def f1(p: float, r: float) -> float:
    return safe_div(2 * p * r, p + r)


def row_id(row: dict[str, Any]) -> str:
    return row.get("conversation_id") or row.get("scenario_id")


def normalize_pred(row: dict[str, Any]) -> dict[str, Any]:
    return row.get("prediction", row)


# --- field extractors (tolerant of old & new schema) ------------------------

def is_event_related(obj: dict[str, Any]) -> bool:
    if obj.get("event_relation") == "event_related":
        return True
    if obj.get("event_relation") == "no_event":
        return False
    return bool(obj.get("life_event_detected"))


def is_occurred(obj: dict[str, Any]) -> bool:
    for ev in obj.get("life_events", []) or []:
        if ev.get("occurred") is True:
            return True
        if "occurred" not in ev and ev.get("event_status") in OCCURRED_STATUSES:
            return True
    return False


def label_set(obj: dict[str, Any]) -> set[str]:
    return {e.get("life_event_label") for e in obj.get("life_events", []) if e.get("life_event_label")}


def primary_label(obj: dict[str, Any]) -> str:
    for e in obj.get("life_events", []) or []:
        if e.get("life_event_label"):
            return e["life_event_label"]
    return "no_event"


def primary_status(obj: dict[str, Any]) -> str:
    for e in obj.get("life_events", []) or []:
        if e.get("event_status"):
            return e["event_status"]
    return "no_event"


def session_set(obj: dict[str, Any]) -> set[str]:
    return {e.get("session_id") for e in obj.get("life_events", []) if e.get("session_id")}


def evidence_set(obj: dict[str, Any]) -> set[str]:
    ids: set[str] = set()
    for e in obj.get("life_events", []) or []:
        ids.update(e.get("evidence_turns", []) or [])
    return ids


# --- scoring -----------------------------------------------------------------

def score(gold_rows: list[dict[str, Any]], pred_rows: list[dict[str, Any]]) -> dict[str, Any]:
    gold = {row_id(r): r for r in gold_rows}
    preds = {row_id(r): normalize_pred(r) for r in pred_rows}

    er_tp = er_fp = er_fn = er_tn = 0
    oc_tp = oc_fp = oc_fn = 0
    label_hit = label_total = 0
    status_correct = status_total = 0
    sess_correct = sess_total = 0
    ev_correct = ev_total = 0

    # bucket counters for specialized rates
    buckets: dict[str, dict[str, int]] = {}

    def bump(name: str, key: str) -> None:
        buckets.setdefault(name, {"total": 0, "hit": 0})
        buckets[name][key] += 1

    conf_label: dict[str, dict[str, int]] = {}
    conf_status: dict[str, dict[str, int]] = {}
    per_label: dict[str, dict[str, int]] = {}
    missing: list[str] = []
    per_case: list[dict[str, Any]] = []

    for cid, grow in gold.items():
        g = grow["gold"]
        gen_type = grow.get("generation_type", "")
        prow = preds.get(cid)
        if prow is None:
            missing.append(cid)
            prow = {"life_event_detected": False, "life_events": []}

        g_er = is_event_related(g)
        p_er = is_event_related(prow)
        g_oc = is_occurred(g)
        p_oc = is_occurred(prow)

        # event-related confusion
        if g_er and p_er:
            er_tp += 1
        elif (not g_er) and p_er:
            er_fp += 1
        elif g_er and (not p_er):
            er_fn += 1
        else:
            er_tn += 1

        # occurred confusion
        if g_oc and p_oc:
            oc_tp += 1
        elif (not g_oc) and p_oc:
            oc_fp += 1
        elif g_oc and (not p_oc):
            oc_fn += 1

        # label / status / localization / evidence — only over event-related gold
        if g_er:
            label_total += 1
            label_hit += int(bool(label_set(g) & label_set(prow)))

            status_total += 1
            status_correct += int(primary_status(g) == primary_status(prow))

            if session_set(g):
                sess_total += 1
                sess_correct += int(bool(session_set(g) & session_set(prow)))

            if evidence_set(g):
                ev_total += 1
                ev_correct += int(bool(evidence_set(g) & evidence_set(prow)))

        # specialized buckets
        if gen_type == "hard_negative":
            bump("hard_negative_fp", "total")
            if p_er:
                bump("hard_negative_fp", "hit")
        if gen_type == "existing_state_negative":
            bump("existing_state_fp", "total")
            if p_er:
                bump("existing_state_fp", "hit")
        if gen_type in ("pre_event_weak_signal", "pre_event_upcoming"):
            bump("pre_event_false_occurred", "total")
            if p_oc:
                bump("pre_event_false_occurred", "hit")
        if gen_type == "cancelled_reversed":
            bump("cancelled_false_occurred", "total")
            if p_oc:
                bump("cancelled_false_occurred", "hit")

        # confusion matrices
        gl, pl = primary_label(g), primary_label(prow)
        conf_label.setdefault(gl, {}).setdefault(pl, 0)
        conf_label[gl][pl] += 1
        gs, ps = primary_status(g), primary_status(prow)
        conf_status.setdefault(gs, {}).setdefault(ps, 0)
        conf_status[gs][ps] += 1

        # per-label one-vs-rest (using primary labels, excluding no_event)
        for lbl in {gl, pl} - {"no_event"}:
            per_label.setdefault(lbl, {"tp": 0, "fp": 0, "fn": 0})
        if gl != "no_event":
            if gl == pl:
                per_label[gl]["tp"] += 1
            else:
                per_label[gl]["fn"] += 1
                if pl != "no_event":
                    per_label[pl]["fp"] += 1
        elif pl != "no_event":
            per_label[pl]["fp"] += 1

        per_case.append({
            "conversation_id": cid,
            "generation_type": gen_type,
            "gold_event_related": g_er, "pred_event_related": p_er,
            "gold_occurred": g_oc, "pred_occurred": p_oc,
            "gold_label": gl, "pred_label": pl,
            "gold_status": gs, "pred_status": ps,
        })

    # macro F1 by label
    label_f1s = {}
    for lbl, c in per_label.items():
        p = safe_div(c["tp"], c["tp"] + c["fp"])
        r = safe_div(c["tp"], c["tp"] + c["fn"])
        label_f1s[lbl] = f1(p, r)
    macro_f1 = safe_div(sum(label_f1s.values()), len(label_f1s)) if label_f1s else 0.0

    er_p = safe_div(er_tp, er_tp + er_fp)
    er_r = safe_div(er_tp, er_tp + er_fn)
    oc_p = safe_div(oc_tp, oc_tp + oc_fp)
    oc_r = safe_div(oc_tp, oc_tp + oc_fn)

    def rate(name: str) -> float:
        b = buckets.get(name, {"total": 0, "hit": 0})
        return safe_div(b["hit"], b["total"])

    metrics = {
        "n_gold": len(gold),
        "n_pred": len(preds),
        "missing_predictions": missing,
        "event_related_precision": er_p,
        "event_related_recall": er_r,
        "event_related_f1": f1(er_p, er_r),
        "occurred_detection_precision": oc_p,
        "occurred_detection_recall": oc_r,
        "occurred_detection_f1": f1(oc_p, oc_r),
        "no_event_specificity": safe_div(er_tn, er_tn + er_fp),
        "hard_negative_false_positive_rate": rate("hard_negative_fp"),
        "existing_state_false_positive_rate": rate("existing_state_fp"),
        "pre_event_false_occurred_rate": rate("pre_event_false_occurred"),
        "cancelled_false_occurred_rate": rate("cancelled_false_occurred"),
        "event_label_accuracy_on_event_related": safe_div(label_hit, label_total),
        "event_status_accuracy": safe_div(status_correct, status_total),
        "session_localization_accuracy": safe_div(sess_correct, sess_total),
        "evidence_hit_rate": safe_div(ev_correct, ev_total),
        "evidence_metric_skipped_cases": label_total - ev_total,
        "macro_f1_by_life_event_label": macro_f1,
        "per_label_f1": label_f1s,
        "binary_event_related": {"tp": er_tp, "fp": er_fp, "fn": er_fn, "tn": er_tn},
        "binary_occurred": {"tp": oc_tp, "fp": oc_fp, "fn": oc_fn},
    }
    return {
        "metrics": metrics,
        "confusion_matrix_life_event_label": conf_label,
        "confusion_matrix_event_status": conf_status,
        "per_case": per_case,
    }


# --- output ------------------------------------------------------------------

def write_metrics_csv(path: Path, metrics: dict[str, Any]) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["metric", "value"])
        for k, v in metrics.items():
            if isinstance(v, (int, float, str)):
                w.writerow([k, v])
        for lbl, val in metrics.get("per_label_f1", {}).items():
            w.writerow([f"per_label_f1::{lbl}", val])


def write_confusion_csv(path: Path, matrix: dict[str, dict[str, int]]) -> None:
    cols = sorted({c for row in matrix.values() for c in row} | set(matrix.keys()))
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["gold\\pred"] + cols)
        for g in sorted(matrix.keys()):
            w.writerow([g] + [matrix[g].get(c, 0) for c in cols])


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--gold", required=True, type=Path)
    parser.add_argument("--pred", required=True, type=Path)
    parser.add_argument("--out", type=Path, default=Path("results/stage1_pilot_metrics.json"))
    args = parser.parse_args()

    result = score(read_jsonl(args.gold), read_jsonl(args.pred))

    out = args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_metrics_csv(out.with_suffix(".csv"), result["metrics"])
    write_confusion_csv(out.parent / "stage1_confusion_life_event.csv",
                        result["confusion_matrix_life_event_label"])
    write_confusion_csv(out.parent / "stage1_confusion_status.csv",
                        result["confusion_matrix_event_status"])

    print(json.dumps(result["metrics"], ensure_ascii=False, indent=2))
    print(f"\n[score] wrote {out}, {out.with_suffix('.csv')}, and confusion CSVs to {out.parent}/")


if __name__ == "__main__":
    main()
