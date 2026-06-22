PY ?= python3
PLAN ?= configs/stage1_generation_plan.yaml
SINGLE_DIR ?= data/generated/single
GEN_TYPES ?= neutral_no_event,hard_negative,existing_state_negative,pre_event_weak_signal,pre_event_upcoming,cancelled_reversed

.PHONY: extract validate normalize-positive gen-dry-run gen-smoke gen-stage1 \
        build-stage1 validate-stage1 score-example clean-generated help

help:
	@echo "Stage 1 pilot targets:"
	@echo "  make validate           - lightweight JSONL check of the positive seed"
	@echo "  make normalize-positive - seed -> data/generated/single/occurred_positive.jsonl"
	@echo "  make gen-dry-run        - print planned prompts (NO API calls)"
	@echo "  make gen-smoke          - generate 1 record per type via API (requires OPENAI_API_KEY)"
	@echo "  make gen-stage1         - generate the full pilot set via API (requires OPENAI_API_KEY)"
	@echo "  make build-stage1       - build combined single + mixed eval sets"
	@echo "  make validate-stage1    - quality + leakage report over generated data"
	@echo "  make score-example      - run the scorer on the bundled example files"
	@echo "  make clean-generated    - remove everything under data/generated/"

# --- legacy ---
extract:
	$(PY) scripts/extract_pool.py --input data/raw/life_event_pool_original.md --output data/processed

validate:
	$(PY) scripts/validate_jsonl.py data/pilot/stage1_single_positive_seed_30.jsonl

# --- stage 1 pipeline ---
normalize-positive:
	$(PY) scripts/generate_stage1_data.py normalize-positive \
	  --input data/pilot/stage1_single_positive_seed_30.jsonl \
	  --output $(SINGLE_DIR)/occurred_positive.jsonl --overwrite

gen-dry-run:
	$(PY) scripts/generate_stage1_data.py dry-run --plan $(PLAN) --types $(GEN_TYPES) --max-items 2

# Smoke: 1 record per type. Overwrites so it never blocks on stale files.
gen-smoke:
	$(PY) scripts/generate_stage1_data.py generate --plan $(PLAN) --types $(GEN_TYPES) \
	  --output-dir $(SINGLE_DIR) --max-items 1 --execute --overwrite

# Full pilot. --overwrite is explicit here so re-running replaces smoke output.
gen-stage1:
	$(PY) scripts/generate_stage1_data.py generate --plan $(PLAN) --types $(GEN_TYPES) \
	  --output-dir $(SINGLE_DIR) --execute --overwrite

build-stage1:
	$(PY) scripts/build_stage1_eval_sets.py --plan $(PLAN)

validate-stage1:
	$(PY) scripts/validate_stage1_dataset.py --plan $(PLAN)

score-example:
	$(PY) scripts/score_stage1.py --gold examples/stage1_gold_example.jsonl \
	  --pred examples/stage1_predictions_example.jsonl --out results/stage1_example_metrics.json

clean-generated:
	rm -rf data/generated/single/*.jsonl data/generated/mixed/*.jsonl \
	  data/generated/raw_model_outputs/*.txt data/generated/quality_reports/*
	@echo "cleaned data/generated/"
