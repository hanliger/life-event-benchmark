# Generate Implicit Life Event Banking Dialogue

다음 조건에 맞는 banking chatbot dialogue를 생성한다.

- 사용자는 자기 Life Event를 직접 말하지 않는다.
- 사용자는 당장 처리할 금융 업무 때문에 챗봇에 온다.
- 단서는 금융 업무 처리 과정에서만 자연스럽게 드러난다.
- assistant는 Life Event를 확정하거나 요약하지 않는다.
- 총 7~10턴, user 발화 4~6개.
- 한 dialogue는 하나의 representative FA action에 대응한다.
- Medium 난이도: 단서 2~3개를 서로 다른 cue channel에 분산한다.

Required metadata:

```json
{
  "life_event_label": "...",
  "action_id": "FA-..",
  "difficulty": "medium",
  "cue_channels": ["...", "..."]
}
```
