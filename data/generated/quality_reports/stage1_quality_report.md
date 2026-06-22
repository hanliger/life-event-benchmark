# Stage 1 Dataset Quality Report

- Total records: **284**
- Avg turns / record: 11.03
- Avg user turns / record: 5.71

## Records by generation type
- all_negative: 12
- cancelled_reversed: 24
- cancelled_sequence: 6
- easy_mixed_positive: 16
- existing_state_negative: 24
- hard_mixed_positive: 16
- hard_negative: 48
- neutral_no_event: 30
- occurred_positive: 48
- pre_event_mixed: 12
- pre_event_upcoming: 24
- pre_event_weak_signal: 24

## Records by target life event
- n/a: 62
- no_event: 30
- 가족 사망: 8
- 결혼: 8
- 금융사기/피싱 피해: 8
- 독립/분가: 8
- 본인 장기 교육/재교육 시작: 8
- 본인/가족 질병·입원·수술: 8
- 부양가족 발생/해소: 8
- 사고/재난 피해: 8
- 연금 수령 시작: 8
- 유학/장기연수: 8
- 은퇴 준비 시작: 8
- 이사: 8
- 이직/전근: 8
- 이혼/별거: 8
- 자녀 교육 단계 진입: 8
- 전세·월세 계약/갱신: 8
- 주택 구매: 8
- 주택 매각/퇴거: 8
- 창업/프리랜서 전환: 8
- 출산/입양: 8
- 취업/복직: 8
- 퇴사/실직: 8
- 폐업/사업 중단: 8
- 휴직: 8

## Records by target action id
- FA-01: 88
- FA-02: 16
- FA-03: 32
- FA-04: 24
- FA-05: 24
- FA-07: 8
- null: 92

## Integrity checks
- ✅ Invalid records (validation flags): 0
- ✅ Direct life-event label leakage (turns): 0
- ✅ Chatbot leakage phrases (turns): 0
- ✅ Invalid evidence turns (non-user): 0
- ✅ no_event records with life_events: 0
- ✅ event-related records with empty life_events: 0
- ✅ pre_event incorrectly marked occurred: 0
- ✅ cancelled incorrectly marked occurred: 0

