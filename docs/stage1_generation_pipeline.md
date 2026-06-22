# Stage 1 Generation Pipeline

End-to-end, reproducible pipeline for the Stage 1 Life Event Detection pilot.

```
seed positives ─► normalize-positive ─┐
                                       ├─► build-stage1 ─► single + mixed eval sets ─► score
plan + prompts ─► generate (API) ─────┘
                         │
                         └─► validate + repair (per record)
```

## 1. Data sources
- `data/pilot/stage1_single_positive_seed_30.jsonl` — 30 human-authored positives
  (10 active labels × 3). Normalized into the unified schema by `normalize-positive`.
- `data/processed/life_event_taxonomy.json` — labels, categories, matched actions,
  `banking_situation_ko` (used as natural-language action hints; no FA codes leak).
- `data/processed/action_pool.json` — FA-01..FA-10 action definitions.
- `configs/stage1_generation_plan.yaml` — pilot/mixed counts, active label subset,
  turn bounds, repair attempts, seed, default model.

## 2. Generation plan
`configs/stage1_generation_plan.yaml` drives counts. CLI flags override
(`--types`, `--max-items`). Stable IDs come from `scripts/lib/id_utils.py`
(per-type numeric offset → `STAGE1-SINGLE-NNNNNN` / `STAGE1-MIXED-NNNNNN`).

Gold labels are assigned by the **controller** (`generate_stage1_data.py`),
never inferred by a model after generation.

## 3. Prompts
`prompts/generation/*.md`, one per generation type plus a repair prompt. Each:
- defines Korean user + chatbot personas,
- forbids direct life-event mention, chatbot summary leakage, emoji, 초성체, FA codes,
- enforces 7–10 turns / 4–6 user turns (single session),
- requires **JSON-only** output (`dialogue` + `candidate_evidence_user_turn_indices`
  + `quality_self_check`; cancelled uses `sessions`).

`{TARGET_LABEL}` and `{ACTION_HINT}` are substituted by the controller.

## 4. Validation (`scripts/lib/dialogue_validation.py`)
Per record: JSON/required fields, turn & user-turn counts (single session),
speaker alternation, unique turn ids, no FA codes / headers / emoji / 초성체,
no direct life-event label, no chatbot leakage phrase, evidence turns must be
user turns, and gold consistency (no_event ⇒ empty life_events; occurred flags
per type; upcoming needs a future cue; cancelled needs ≥2 sessions or a cancel cue).

## 5. Repair
On failure the controller calls `repair_generated_dialogue_ko.md` with the issue
list and previous output, up to `generation.max_repair_attempts` (default 2).
Raw outputs (each attempt) are saved under `data/generated/raw_model_outputs/`.
If still invalid: the record is **kept** with `quality_flags` (never silently
dropped) unless `--drop-invalid` is passed.

## 6. Output files
```
data/generated/single/occurred_positive.jsonl        (normalize-positive)
data/generated/single/no_event_neutral.jsonl
data/generated/single/hard_negative.jsonl
data/generated/single/existing_state_negative.jsonl
data/generated/single/pre_event_weak_signal.jsonl
data/generated/single/pre_event_upcoming.jsonl
data/generated/single/cancelled_reversed.jsonl
data/generated/single/stage1_single_eval_v0.jsonl   (build-stage1: combined)
data/generated/mixed/stage1_mixed_eval_v0.jsonl     (build-stage1: bundles)
data/generated/raw_model_outputs/*.txt              (raw responses, per attempt)
data/generated/quality_reports/stage1_quality_report.{json,md}
```

## 7. Scoring (`scripts/score_stage1.py`)
Measures event-related detection, occurred detection, label/status classification,
session localization, evidence hit-rate, and the per-bucket false-positive /
false-occurred rates. Writes `results/stage1_pilot_metrics.{json,csv}` and
`results/stage1_confusion_{life_event,status}.csv`.

Headline pilot metrics: `event_related_f1`, `occurred_detection_f1`,
`hard_negative_false_positive_rate`, `pre_event_false_occurred_rate`,
`evidence_hit_rate`.

## Reproducibility notes
- Deterministic IDs and a fixed mixing seed (`generation.seed`, default 42).
- `dry-run` and `generate` without `--execute` never call the API.
- No secrets in code; `.env` is loaded via python-dotenv.
