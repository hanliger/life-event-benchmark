#!/usr/bin/env bash
set -euo pipefail
python scripts/score_stage1.py --gold examples/stage1_gold_example.jsonl --pred examples/stage1_predictions_example.jsonl > /tmp/stage1_score_test.json
python scripts/validate_jsonl.py data/pilot/stage1_single_positive_seed_30.jsonl
