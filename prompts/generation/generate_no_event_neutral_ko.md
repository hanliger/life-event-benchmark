# 생성 지시: 중립(no-event) 은행 챗봇 대화

너는 한국어 은행 챗봇 대화 데이터를 만드는 생성기다.
아래 조건을 **모두** 지켜 **단일 세션** 대화 하나를 만든다.

## 상황
- 사용자는 평범한 은행 업무를 처리하러 왔다. **새로운 Life Event는 전혀 없다.**
- 이 대화는 결혼/이사/이직/출산/사망 등 어떤 인생 사건도 암시하면 안 된다.
- 일상적이고 사무적인 은행 업무여야 한다.

## 이번 대화의 은행 업무 (하나만 집중)
{ACTION_HINT}

예시 업무 유형(참고용, 하나만 사용):
- 카드 결제내역/이용대금 조회
- 거래내역서 발급/내보내기
- 앱 푸시 알림 설정 변경
- 예금 이자/금리 조회
- 여행 자금 모으기 적금
- 취미 자금 통장 만들기
- 카드 분실 정지
- 친구와 밥값 정산 송금
- 구독료 정기이체 등록
- 일반 신용대출 이자 시뮬레이션

## 사용자 페르소나
- 짧고 캐주얼한 한국어 반말 혹은 가벼운 존댓말.
- 한 번에 한 가지만 말한다.
- 군더더기 없이 실무적으로.

## 챗봇 페르소나
- 친절하고 간결한 은행 상담 챗봇.
- 한 번에 **실무적인 질문 하나만** 한다.
- 사용자의 상황을 인생 사건으로 요약하지 않는다.

## 형식 규칙 (반드시 지킬 것)
- 총 7~10턴. 사용자 발화 4~6개.
- user와 assistant가 번갈아 말한다.
- 이모지 금지. 초성체(ㅋㅋ, ㅎㅎ, ㅠㅠ 등) 금지.
- "FA-08" 같은 코드, "대화 N" 같은 헤더를 본문에 절대 쓰지 마라.
- 출력은 **JSON만**. 설명 문장 금지.

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
    "single_action_focus": true
  }
}
```
no-event 대화이므로 `candidate_evidence_user_turn_indices`는 빈 배열로 둔다.
`dialogue` 배열은 user로 시작해 user/assistant가 번갈아 나오도록 한다.
