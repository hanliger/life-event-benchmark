# Negative & Pre-event Generation Strategy (Stage 1)

The pilot is built to defeat **shortcut learning** — detecting a Life Event from a
surface banking signal alone (공동 계좌 → 결혼, 월세 정기이체 → 독립, 장례비 → 가족 사망).
Each negative / pre-event type targets a specific shortcut.

## 1. neutral_no_event
- Ordinary banking business with no life-event implication.
- Uses FA-01..FA-10 surface forms (card inquiry, statement export, alerts, …).
- Purpose: establish a clean negative baseline and measure `no_event_specificity`.
- Shortcut prevented: "any banking chat that mentions money implies a life event".

## 2. hard_negative (action-matched counterfactual)
- Same/similar banking action and surface form as a real positive, but the life
  event **did not occur**. The cue is replaced with a mundane reason
  (roommate, friend settlement, existing relationship, work reimbursement,
  one-time payment, payment-date change, mailing preference, ordinary savings).
- Purpose: the core anti-shortcut set. Measures `hard_negative_false_positive_rate`.
- Shortcuts prevented:
  - 공동 계좌 ≠ 결혼 (룸메이트 생활비)
  - 월세 정기이체 ≠ 독립/계약 (기존 이체일 변경)
  - 병원비 송금 ≠ 부양가족 발생 (일회성 도움)
  - 장례비 ≠ 가족 사망 (회사 조의금 모금)
  - 급여계좌 변경 ≠ 이직 (같은 회사 수령계좌 변경)
  - 자동저축 중단 ≠ 실직 (일시적 과소비)

## 3. existing_state_negative
- Mentions spouse/child/parent/rent/salary day, but as an **already-existing**
  state being lightly adjusted (date/amount change, one-off top-up).
- `metadata.implied_existing_state = true`.
- Purpose: measure `existing_state_false_positive_rate`.
- Shortcut prevented: "any mention of family/rent/salary is a *new* event".

## 4. pre_event_weak_signal
- Life-event-related but unconfirmed (exploration, comparison, planning).
- `event_status = weak_signal`, `occurred = false`, `update_allowed = false`.
- Purpose: the conversation IS event-related, but the model must not assert the
  event occurred. Contributes to `pre_event_false_occurred_rate`.
- Shortcut prevented: "event-related ⇒ event occurred".

## 5. pre_event_upcoming
- Confirmed but future-dated event (effective date / future timing required).
- `event_status = upcoming`, `occurred = false`, `update_allowed = partial`.
- Purpose: distinguish "scheduled" from "happened".
- Shortcut prevented: "confirmed plan ⇒ already happened".

## 6. cancelled_reversed
- Multi-session record: an early signal (weak/upcoming) is later cancelled.
- `event_status = cancelled`, `occurred = false`, `update_allowed = false`.
- Evidence spans the original cue and the cancellation cue.
- Purpose: measure `cancelled_false_occurred_rate` and test temporal reasoning.
- Shortcut prevented: "saw the signal earlier ⇒ event stands".

## Mixed-session bundles
Single records are recombined into multi-session bundles (see
`scripts/build_stage1_eval_sets.py`) so the model must localize *which* session
carries the event among distractor sessions:
- `easy_mixed_positive`  : 2 neutral + 1 occurred positive
- `hard_mixed_positive`  : 2 hard negative + 1 occurred positive
- `pre_event_mixed`      : 2 neutral + 1 weak/upcoming
- `all_negative`         : 3 mixed negatives (no event anywhere)
- `cancelled_sequence`   : a cancelled record (optionally bracketed by a neutral)

Session and turn IDs are reassigned; a mapping back to the source records is kept
in `generation_metadata.id_mapping`. No source label ever leaks into the text.
