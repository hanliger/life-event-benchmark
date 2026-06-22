# 생성 지시: Cancelled / Reversed (취소·번복)

너는 한국어 은행 챗봇 대화 데이터를 만드는 생성기다.
아래 조건을 **모두** 지켜 **여러 세션**(최소 2개) 대화 하나를 만든다.

## 핵심 목표
**{TARGET_LABEL}** 사건의 신호가 먼저 나왔다가, 나중에 **취소/번복**되는 대화다.
사건은 결국 일어나지 않았다(occurred=false). 하지만 대화는 사건과 관련이 있다.

- S1: 약한 신호 또는 확정 예정 신호가 나온다. (예: "이직할 수도 있어서…", "집 계약할 것 같아서…")
- S2(또는 그 이후): 그 신호를 명확히 취소/번복한다. (예: "그냥 안 옮기기로 했어", "그 집은 안 하기로 했어")
- 업무 표면형: {ACTION_HINT}

## 사용자 발화 예시 톤
- S1: "이직할 수도 있어서 급여일 알림 바꿔야 하나"
  S2: "그냥 안 옮기기로 했어 지금 회사 그대로야"
- S1: "집 계약할 것 같아서 전세대출 한도만 봐줘"
  S2: "그 집은 안 하기로 했어"

## 사용자 페르소나
- 짧고 캐주얼한 한국어. 한 번에 한 가지만.
- **표적 사건을 직접 말하지 않는다.**

## 챗봇 페르소나
- 친절하고 간결. 한 번에 실무 질문 하나.
- 사건을 단정/요약하지 않는다.

## 형식 규칙 (반드시 지킬 것)
- 세션은 2개. 각 세션 3~6턴 정도. 전체적으로 자연스럽게.
- 각 세션은 user/assistant 교대. user 발화로 시작.
- 이모지 금지. 초성체 금지.
- "FA-08" 코드, "대화 N" 헤더 금지.
- "{TARGET_LABEL}"에 해당하는 직접 단어를 본문에 쓰지 마라.
- 출력은 **JSON만**.

## 출력 JSON 형식
```json
{
  "sessions": [
    {
      "session_id": "S1",
      "dialogue": [
        {"speaker": "user", "text": "..."},
        {"speaker": "assistant", "text": "..."}
      ]
    },
    {
      "session_id": "S2",
      "dialogue": [
        {"speaker": "user", "text": "..."},
        {"speaker": "assistant", "text": "..."}
      ]
    }
  ],
  "candidate_evidence_user_turn_indices": {
    "S1": [0],
    "S2": [0]
  },
  "quality_self_check": {
    "no_direct_life_event_mention": true,
    "no_chatbot_label_leakage": true,
    "turn_count_ok": true,
    "user_style_ok": true,
    "single_action_focus": true,
    "later_session_cancels_earlier": true
  }
}
```
`candidate_evidence_user_turn_indices`는 세션별로 신호/취소가 드러난 **사용자 발화 인덱스**(0-based, 각 세션 dialogue 기준)를 넣는다.
S1에는 원래 신호, S2에는 취소 단서가 모두 포함되도록 한다.
