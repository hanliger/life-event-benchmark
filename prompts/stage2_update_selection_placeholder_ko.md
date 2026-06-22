# Stage 2 Update Selection Placeholder

Stage 2는 다음 주 작업용 placeholder입니다.

Input:
- chat history
- detected or gold Life Event label
- initial financial memory
- standing financial actions

Output:
- memory_updates
- standing_action_decisions

High-risk action은 funds movement가 있는 standing financial action입니다. High-risk action은 실행하지 않고 confirmation/reject/clarify 중 적절한 predefined action을 선택해야 합니다.
