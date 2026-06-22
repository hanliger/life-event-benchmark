# 생성 지시: Occurred Positive (이미 일어난 사건)

너는 한국어 은행 챗봇 대화 데이터를 만드는 생성기다.
아래 조건을 **모두** 지켜 **단일 세션** 대화 하나를 만든다.

## 핵심 목표
이 대화는 **{TARGET_LABEL}** 사건이 **이미 일어났다**는 것이 자연스럽게 드러나는 positive다.
사건은 확정·완료된 과거/현재 상태다. "할까 말까"가 아니라 "했다 / 됐다 / 시작했다".

- 업무 표면형: {ACTION_HINT}
- 반드시 **사건이 이미 발생했음**을 드러내는 단서를 포함하라
  (지난주에, 어제, 이번에, 이제부터, ~하고 나서, 됐어, 했어 등 완료/기정사실 톤).
- 사건의 결과로 자연스럽게 위 은행 업무를 처리하려는 흐름이어야 한다.

## 사용자 발화 예시 톤 (지정된 업무·사건에 맞춰 변형하라)
- "지난주에 이사 끝나서 자동이체 주소 좀 바꿔야 해"
- "이제 둘이 같이 사니까 생활비 통장 하나 만들래"
- "새 회사 첫 월급 들어왔는데 주거래 계좌로 옮기고 싶어"
- "애기 생겨서 매달 들어가는 돈 자동이체 걸어둘래"

## 사용자 페르소나
- 짧고 캐주얼한 한국어. 한 번에 한 가지만.
- **표적 사건의 직접 명칭을 본문에 쓰지 않는다.** 정황·완료 단서로만 드러낸다.

## 챗봇 페르소나
- 친절하고 간결. 한 번에 실무 질문 하나.
- 사용자의 상황을 인생 사건 명칭으로 요약/단정하지 않는다.

## 형식 규칙 (반드시 지킬 것)
- 총 7~10턴. 사용자 발화 4~6개. user/assistant 교대.
- 이모지 금지. 초성체 금지.
- "FA-08" 같은 코드, "대화 N" 헤더 금지.
- "{TARGET_LABEL}"에 해당하는 직접 단어를 본문에 쓰지 마라.
- 출력은 **JSON만**.

## 출력 JSON 형식
```json
{
  "dialogue": [
    {"speaker": "user", "text": "..."},
    {"speaker": "assistant", "text": "..."}
  ],
  "candidate_evidence_user_turn_indices": [1, 3],
  "quality_self_check": {
    "no_direct_life_event_mention": true,
    "no_chatbot_label_leakage": true,
    "turn_count_ok": true,
    "user_style_ok": true,
    "single_action_focus": true,
    "event_already_occurred": true
  }
}
```
`candidate_evidence_user_turn_indices`에는 사건이 이미 일어났음이 드러난 **사용자 발화 인덱스**(0-based)를 넣는다.
