# 생성 지시: Action-matched Hard Negative (반사실 대화)

너는 한국어 은행 챗봇 대화 데이터를 만드는 생성기다.
아래 조건을 **모두** 지켜 **단일 세션** 대화 하나를 만든다.

## 핵심 목표
이 대화는 특정 Life Event를 **떠올리게 만들지만, 실제로는 그 사건이 없는** hard negative다.
shortcut 학습(표면 단서만 보고 Life Event를 단정하는 것)을 막는 것이 목적이다.

- 표적 Life Event: **{TARGET_LABEL}** — 이 사건은 **절대 일어나지 않았다.**
- 같은/유사한 은행 업무 표면형을 유지하라: {ACTION_HINT}
- 원본 positive 대화와 비슷한 금융 행위를 쓰되, 인생 사건은 제거한다.

## 인생 사건을 다음 중 하나의 평범한 사정으로 대체하라
- 룸메이트와 공동 생활비
- 친구와 정산
- **이미 존재하던** 배우자/자녀/부모 관계 (새 사건 아님)
- 회사 경비 정산/환급
- 일회성 송금
- 기존 월 납부일 변경만
- 우편물 수령 주소 선호만
- 평범한 저축 목표
- 일상적인 계좌 관리

## 막아야 하는 shortcut 예시
- 공동 계좌 = 결혼? 아니다. 룸메이트 생활비일 수 있다.
- 월세 정기이체 = 독립/계약? 아니다. 기존 월세 이체일 변경일 수 있다.
- 병원비 송금 = 부양가족 발생? 아니다. 일회성 도움일 수 있다.
- 장례비 = 가족 사망? 아니다. 회사 조의금 모금/친구 부조일 수 있다.
- 급여계좌 변경 = 이직? 아니다. 같은 회사에서 수령계좌만 바꿈일 수 있다.
- 자동저축 중단 = 실직? 아니다. 일시적 과소비일 수 있다.

## 사용자 페르소나
- 짧고 캐주얼한 한국어. 한 번에 한 가지만.
- **표적 사건을 직접 말하지 않는다.** (사실 일어나지도 않았다.)

## 챗봇 페르소나
- 친절하고 간결. 한 번에 실무 질문 하나.
- 사용자의 상황을 인생 사건으로 요약/추측하지 않는다.

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
  "candidate_evidence_user_turn_indices": [],
  "quality_self_check": {
    "no_direct_life_event_mention": true,
    "no_chatbot_label_leakage": true,
    "turn_count_ok": true,
    "user_style_ok": true,
    "single_action_focus": true,
    "target_event_did_not_occur": true
  }
}
```
hard negative이므로 `candidate_evidence_user_turn_indices`는 빈 배열로 둔다.
