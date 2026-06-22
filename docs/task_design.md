# Task Design

## Goal

Banking chat history에서 사용자가 직접 Life Event를 말하지 않아도, 금융 행동의 이유·수취인 관계·메모 문구·행동 조합·금융 행동 속성을 조합하여 Life Event 발생 여부를 감지한다.

## Stage 1: Life Event Detection

### Input

- one or more chat sessions
- each session has ordered turns
- Life Event candidate label set is provided to the model

### Output

```json
{
  "life_event_detected": true,
  "life_events": [
    {
      "session_id": "S2",
      "life_event_label": "이사",
      "event_status": "occurred",
      "confidence": 0.82,
      "evidence_turns": ["S2:T03", "S2:T05"],
      "brief_reason": "..."
    }
  ]
}
```

### Primary metrics

- binary event detection precision/recall/F1
- event label accuracy
- no-event specificity
- hard-negative false positive rate
- session localization accuracy
- evidence hit rate, after manual evidence annotation

## Stage 2: Update Selection / Memory Update

Stage 2는 다음 단계에서 붙입니다.

```text
Input: chat history + detected/gold Life Event
Output: memory_updates + standing_action_decisions
```

분리된 평가가 필요합니다.

- Oracle Event → Update: event detection 실패와 update 실패를 분리
- Predicted Event → Update: end-to-end 성능 확인

## This week's pilot

이번 주에는 Stage 1만 실행합니다.

- positive life-event-specific dialogues from `data/pilot/stage1_single_positive_seed_30.jsonl`
- general no-event dialogues to be filled in `data/pilot/stage1_no_event_seed.template.jsonl`
- hard negative dialogues to be added manually
- mixed-session bundles to be created from positive + negative sessions
