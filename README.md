# Life Event Detection Benchmark Skeleton

Banking chat history에서 implicit life event를 감지하고, 이후 memory/action update로 연결하기 위한 benchmark skeleton입니다.

이번 skeleton은 업로드된 `Life Event Pool`에서 다음 항목을 분리했습니다.

- 사용자/챗봇 대화 생성 가이드
- 금융 Action Pool `FA-01` ~ `FA-10`
- Life Event taxonomy 및 action matching
- positive life-event 대화 예시
- Stage 1 life event detection용 prompt, schema, scorer

## Current scope

이 benchmark은 **Stage 1: Life Event Detection**을 대상으로 합니다.

```text
Input: 일반 banking 대화 + life-event-specific 대화
Output: life_event_detected, life_event_label, session_id, evidence_turns
```

> **현재 데이터셋 상태 (2026-06-22):** 초기 10개 label pilot을 넘어, **active taxonomy 전체(24개 label)** 에 대한
> 전량 생성을 완료했습니다. 총 **284 records** (single 222 + mixed 62), label당 8 records로 균형을 맞췄으며,
> quality/leakage 검사를 전부 통과했습니다 (invalid 0, leakage 0).
> 전체 생성은 `configs/stage1_generation_plan_full.yaml` 기준이며, 기존 10-label pilot 산출물은
> `data/generated_pilot_backup/`에 백업되어 있습니다.

Stage 2인 update selection / memory update는 `prompts/stage2_update_selection_placeholder_ko.md`와 `schemas/stage2_update_output.schema.json`에 placeholder만 둡니다.

## Repository layout

```text
.
├── data/
│   ├── raw/                              # 원문 보존
│   ├── processed/                        # action/event/dialogue 추출 결과
│   └── pilot/                            # 이번 주 pilot용 seed/template
├── docs/                                 # task, annotation, generation guideline
├── prompts/                              # model prompts
├── schemas/                              # JSON schemas
├── scripts/                              # extraction/scoring scripts
├── examples/                             # prediction/gold example
└── results/                              # run output placeholder
```

## Quick start

```bash
python scripts/extract_pool.py --input data/raw/life_event_pool_original.md --output data/processed
python scripts/score_stage1.py --gold data/pilot/stage1_single_positive_seed_30.jsonl --pred examples/stage1_predictions_example.jsonl
```

## Important pilot notes

1. `stage1_single_positive_seed_30.jsonl`은 10-label pilot용 positive seed(사람이 작성)입니다. 전체 생성에서는 `occurred_positive`를 24개 label에 대해 API로 생성합니다(`source_type: generated`).
2. 생성 대상 label은 `configs/stage1_generation_plan_full.yaml`의 `labels.active_subset`이 단일 기준입니다(taxonomy의 `active=true`와 일치). 코드의 하드코딩 목록이 아니라 이 설정을 따릅니다.
3. `evidence_turns`는 아직 수동 annotation 대상입니다. 현재는 `candidate_user_turns`만 제공합니다.
4. 모델에게는 Life Event label set만 주고, event-action matching table은 주지 않는 것을 기본 설정으로 둡니다.

---

# Stage 1 Life Event Detection — executable generation pipeline

## What Stage 1 evaluates
Given one or more banking chat sessions, detect:
1. whether the conversation is **Life-Event related** (`event_related` vs `no_event`),
2. whether the event has **occurred** (`occurred`),
3. **which** Life Event it is (label) and its **status**
   (`occurred | upcoming | weak_signal | existing_state | cancelled | no_event`),
4. **which user turns** provide the evidence.

This week's pilot evaluates *detection of implicit Life Events*, not update selection.
The user never states the event directly — cues leak through the banking action,
recipient relationship, memo text, amount, urgency, recurrence, action sequence, or timing.

## event_related vs occurred (the key distinction)
- `life_event_detected` / `event_related` = the conversation is **about** a life event.
- `occurred` = the event **actually happened**.
- So pre-event (`weak_signal`, `upcoming`) and `cancelled` records are
  `event_related: true` but `occurred: false`.

See [docs/event_status_labeling.md](docs/event_status_labeling.md).

## Generation types
| type | relation | occurred | purpose |
|------|----------|----------|---------|
| `occurred_positive` | event_related | true | event has happened; API-generated across all active labels (10-label pilot used the 30-record human seed) |
| `neutral_no_event` | no_event | false | clean negative baseline |
| `hard_negative` | no_event | false | action-matched counterfactual (anti-shortcut) |
| `existing_state_negative` | no_event | false | already-existing state, not a new event |
| `pre_event_weak_signal` | event_related | false | unconfirmed / exploring |
| `pre_event_upcoming` | event_related | false | confirmed but future-dated |
| `cancelled_reversed` | event_related | false | earlier signal later cancelled (multi-session) |

Plus mixed-session bundles: `easy_mixed_positive`, `hard_mixed_positive`,
`pre_event_mixed`, `all_negative`, `cancelled_sequence`.
See [docs/negative_generation_strategy.md](docs/negative_generation_strategy.md)
and [docs/stage1_generation_pipeline.md](docs/stage1_generation_pipeline.md).

## Setup (`.env`)
```bash
cp .env.example .env      # then put your OPENAI_API_KEY in .env
pip install -r requirements.txt
```
Supported env vars: `OPENAI_API_KEY`, `OPENAI_MODEL` (default `gpt-4o-mini`),
`OPENAI_TEMPERATURE`, `OPENAI_MAX_OUTPUT_TOKENS`, `OPENAI_CONCURRENCY`.
Secrets are loaded via python-dotenv and never printed or committed.

## Workflow
```bash
make normalize-positive   # seed -> data/generated/single/occurred_positive.jsonl (no API)
make gen-dry-run          # print planned prompts, NO API calls
make gen-smoke            # 1 record per type via API (requires OPENAI_API_KEY)
make build-stage1         # combined single + mixed eval sets
make validate-stage1      # quality + leakage report
```
For the 10-label pilot (~120 single records + ~30 mixed):
```bash
make gen-stage1           # pilot generation via API (cost warning below)
make build-stage1
make validate-stage1
```

For the **full active taxonomy** (24 labels → 222 single + 62 mixed) drive everything
off `stage1_generation_plan_full.yaml` and pass `occurred_positive` explicitly
(it is API-generated here rather than normalized from the seed):
```bash
PLAN=configs/stage1_generation_plan_full.yaml
python scripts/generate_stage1_data.py generate --plan $PLAN \
  --types occurred_positive,neutral_no_event,hard_negative,existing_state_negative,pre_event_weak_signal,pre_event_upcoming,cancelled_reversed \
  --output-dir data/generated/single --execute --overwrite
python scripts/build_stage1_eval_sets.py     --plan $PLAN
python scripts/validate_stage1_dataset.py    --plan $PLAN
```
The label set comes from `labels.active_subset`; per-type counts from the `single:`
block. Run `--types ...` without `--execute` first for a free planning summary.

Score predictions:
```bash
python scripts/score_stage1.py \
  --gold data/generated/single/stage1_single_eval_v0.jsonl \
  --pred results/predictions/stage1_predictions.jsonl \
  --out results/stage1_pilot_metrics.json
```
Headline metrics: `event_related_f1`, `occurred_detection_f1`,
`hard_negative_false_positive_rate`, `pre_event_false_occurred_rate`, `evidence_hit_rate`.

## ⚠️ Label-leakage warnings
- The user must **never** state the Life Event directly; the chatbot must **never**
  summarize it (e.g. "결혼하셨군요"). Validation flags these.
- Conversation text (`input.sessions[].turns[].text`) must not contain labels
  (`결혼`, `이사`, …), `FA-XX` codes, or `대화 N` headers. Labels live in metadata/gold only.
- Note: banking memo cues such as `장례비`, `이사비`, `전세대출` are intentionally
  allowed — they are the indirect signals the benchmark relies on.

## ⚠️ API cost warning
`make gen-stage1` (pilot) issues roughly 90+ generation calls; the **full taxonomy run**
issues ~222 generation calls plus repairs. Use `make gen-dry-run` (free) and
`make gen-smoke` (≈6 small calls) first. Default model is the inexpensive `gpt-4o-mini`;
override with `OPENAI_MODEL`.

## Stage 1 files
```text
configs/stage1_generation_plan.yaml          # 10-label pilot plan (counts, labels, turn bounds, seed)
configs/stage1_generation_plan_full.yaml     # full 24-label taxonomy plan (single: counts + active_subset)
prompts/generation/*.md                       # per-type generation + repair prompts (incl. occurred_positive)
scripts/lib/                                   # io / openai / validation / id helpers
scripts/generate_stage1_data.py               # normalize-positive | generate | dry-run
scripts/build_stage1_eval_sets.py             # combined single + mixed bundles
scripts/validate_stage1_dataset.py            # quality + leakage report
scripts/score_stage1.py                        # expanded scorer
data/generated/{single,mixed,raw_model_outputs,quality_reports}/
data/generated_pilot_backup/                  # 10-label pilot output, preserved
```
