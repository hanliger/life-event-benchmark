# Stage 1 Annotation Guideline

## Label set

아래 active Life Event label 또는 `no_event` 중 하나 이상을 사용합니다.

- 결혼
- 이혼/별거
- 출산/입양
- 부양가족 발생/해소
- 가족 사망
- 독립/분가
- 이사
- 전세·월세 계약/갱신
- 주택 구매
- 주택 매각/퇴거
- 취업/복직
- 이직/전근
- 휴직
- 퇴사/실직
- 창업/프리랜서 전환
- 폐업/사업 중단
- 본인 장기 교육/재교육 시작
- 자녀 교육 단계 진입
- 유학/장기연수
- 은퇴 준비 시작
- 연금 수령 시작
- 본인/가족 질병·입원·수술
- 사고/재난 피해
- 금융사기/피싱 피해
- no_event

## Event status

| Status | Meaning |
|---|---|
| `occurred` | 이미 발생한 Life Event |
| `upcoming` | 예정되어 있으나 아직 발생 전인 Life Event |
| `weak_signal` | 가능성은 있으나 확정하기 어려운 신호 |
| `implicit_candidate` | source dialogue에서 implicit cue로 생성된 positive seed |
| `no_event` | Life Event 근거 없음 |

## Positive label rule

Life Event를 직접 말하지 않아도 user utterance의 단서를 조합해 label을 붙일 수 있습니다. 단, 금융 action 자체만으로 확정하면 안 됩니다.

예: `월세 정기이체`만으로는 전세·월세 계약/갱신을 확정하지 않습니다. `처음 시작`, `계약`, `잔금`, `새 집`, `집주인` 등 추가 단서가 필요합니다.

## No-event rule

근거가 약하면 `no_event` 또는 `weak_signal`로 둡니다. 이번 Stage 1 binary scoring에서는 `weak_signal` 처리 정책을 별도 실험 옵션으로 둘 수 있습니다.

## Evidence turns

- evidence는 user turn만 기본으로 annotation합니다.
- assistant가 사용자의 단서를 요약한 경우, assistant turn만 evidence로 잡지 않습니다.
- evidence turn id format은 mixed setting에서 `S2:T05`처럼 session id를 붙입니다.

## Hard negative examples to add

| Near-miss event | Hard negative idea |
|---|---|
| 결혼 | 룸메이트 생활비 모임통장 |
| 출산/입양 | 조카 선물용 적금 또는 청년지원금 조회 |
| 이사 | 카드 명세서 수령지만 변경 |
| 전세·월세 계약/갱신 | 기존 월세 이체일만 변경 |
| 가족 사망 | 회사 조의금 정산용 송금 |
| 이직/전근 | 같은 회사 내 급여계좌만 변경 |
| 퇴사/실직 | 단순 소비 증가로 저축액 조정 |
