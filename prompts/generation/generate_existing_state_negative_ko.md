# 생성 지시: Existing-state Negative (기존 상태, 새 사건 아님)

너는 한국어 은행 챗봇 대화 데이터를 만드는 생성기다.
아래 조건을 **모두** 지켜 **단일 세션** 대화 하나를 만든다.

## 핵심 목표
이 대화는 배우자/자녀/부모/월세/급여일/지원금 등을 **언급하지만**,
그것은 **이미 오래 전부터 존재하던 상태**다. **새로운 Life Event가 아니다.**

- 관련 near-miss 사건: **{TARGET_LABEL}** (실제로는 새 사건이 아님)
- **이번 대화에서 다룰 업무는 오직 이것 하나다: {ACTION_HINT}**
- 사용자는 기존에 하던 것을 **소소하게 조정**할 뿐이다 (날짜/금액 변경, 일회성 추가 등).

## 절대 규칙: 단일 업무
- 위에 지정된 **하나의 업무만** 다뤄라. 다른 업무(다른 이체/적금/계좌 등)를 섞지 마라.
- 예: 월세 이체일 변경이 주제면 학원비·병원비 같은 다른 항목을 추가하지 마라.
- 대화 전체가 그 하나의 조정을 자연스럽게 처리하는 흐름이어야 한다.

## 톤 (아래는 형식 참고용 — 지정된 업무에 맞춰 한 가지만 골라 변형하라)
- "와이프한테 매달 보내던 생활비 날짜만 바꿔줘"
- "기존 월세 이체일만 25일로 바꿔"
- "회사 급여계좌를 주거래로 바꾸고 싶어"

핵심: "매달 보내던", "기존", "원래", "늘 하던", "이번 달만" 같이
**이미 진행 중이던 상태**임을 드러내라. 새로 시작/변화한 사건이 아니어야 한다.

## 사용자 페르소나
- 짧고 캐주얼한 한국어. 한 번에 한 가지만.

## 챗봇 페르소나
- 친절하고 간결. 한 번에 실무 질문 하나.
- 상황을 인생 사건으로 요약/추측하지 않는다.

## 형식 규칙 (반드시 지킬 것)
- 총 7~10턴. 사용자 발화 4~6개. user/assistant 교대.
- 이모지 금지. 초성체 금지.
- "FA-08" 코드, "대화 N" 헤더 금지.
- "{TARGET_LABEL}"에 해당하는 직접 단어를 본문에 쓰지 마라.
- 출력은 **JSON만**.

## 출력 JSON 형식
```json
{
  "dialogue": [
    {"speaker": "user", "text": "..."},
    {"speaker": "assistant", "text": "..."}
  ],
  "candidate_evidence_user_turn_indices": [],
  "quality_self_check": {
    "no_direct_life_event_mention": true,
    "no_chatbot_label_leakage": true,
    "turn_count_ok": true,
    "user_style_ok": true,
    "single_action_focus": true,
    "is_existing_state_not_new_event": true
  }
}
```
existing-state negative이므로 `candidate_evidence_user_turn_indices`는 빈 배열로 둔다.
