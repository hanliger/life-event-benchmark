# Source Mapping

이 문서는 업로드된 Life Event Pool에서 skeleton으로 분리한 항목을 정리합니다.

## Extracted artifacts

| Source content | Repo file |
|---|---|
| 금융 Action Pool | `data/processed/action_pool.json` |
| Life Event별 금융 Action Matching | `data/processed/life_event_taxonomy.json`, `data/processed/event_action_matching.json` |
| 대화 예시 | `data/processed/conversation_examples.jsonl` |
| 이번 주 positive pilot subset | `data/pilot/stage1_single_positive_seed_30.jsonl` |
| 생성 가이드 | `docs/generation_guidelines.md`, `prompts/generate_life_event_dialogue_ko.md` |

## Parsed counts

| Item | Count |
|---|---:|
| Financial actions | 10 |
| Life event labels, including inactive labels | 25 |
| Active life event labels | 24 |
| Active positive dialogue examples | 87 |
| Stage 1 positive seed scenarios | 30 |

## Notes

- `퇴직/은퇴`는 원문 taxonomy에서 취소선으로 표시되어 `active: false`로 추출했습니다.
- 전세·월세 계약/갱신의 FA-07 계약금·잔금 이체 대화는 취소선 처리된 예시이므로 active positive seed에서 제외했습니다.
- No-event 및 hard-negative 대화는 원문에 별도 pool이 없으므로 template만 제공합니다.
