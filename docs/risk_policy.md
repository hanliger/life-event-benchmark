# Funds Movement Risk Policy

이 benchmark에서 Low/High risk는 action-level에 붙입니다.

## Definition

- **Low-risk:** 돈이 실제로 이동하지 않는 action
- **High-risk:** 현재 또는 미래의 funds movement를 생성/변경/중단하는 action

## Source action pool mapping

| Action ID | Risk | Funds movement? |
|---|---:|---:|
| FA-01 조회·확인·증빙 발급 | low | false |
| FA-02 알림·일정 설정 | low | false |
| FA-03 고객·계좌 정보 등록/변경 | low | false |
| FA-04 금융상품·대출 조건 조회 | low | false |
| FA-05 계좌·목적 자금공간 개설/분리 | low | false |
| FA-06 보안·사고 대응 | low | false |
| FA-07 이체·송금·환전 | high | true |
| FA-08 정기이체·자동납부 관리 | high | true |
| FA-09 저축·연금 납입/해지/전환 | high | true |
| FA-10 대출 실행·상환·상환설정 | high | true |


## Stage 1 note

Stage 1에서는 risk/action decision을 평가하지 않습니다. 다만 `action_id`는 event detection 대화의 metadata로 보존합니다.

## Stage 2 note

Stage 2에서는 Life Event로 인해 영향을 받는 standing financial action을 찾고, funds movement 여부에 따라 predefined action을 선택하게 합니다.
