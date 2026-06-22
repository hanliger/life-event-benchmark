# Event Status Labeling (Stage 1)

Stage 1 separates two orthogonal questions:

1. **Is the conversation Life-Event related?** (`event_relation` / `life_event_detected`)
2. **Has the event actually occurred?** (`occurred`)

A conversation can be event-related but not occurred (pre-event, cancelled).
`event_status` captures the finer-grained state.

| status          | event_relation | occurred | update_allowed | meaning |
|-----------------|----------------|----------|----------------|---------|
| `occurred`      | event_related  | true     | true           | The event has happened / is completed or activated. |
| `upcoming`      | event_related  | false    | "partial"      | Confirmed & scheduled, but not yet happened. |
| `weak_signal`   | event_related  | false    | false          | Possible / being explored. Not confirmed. |
| `existing_state`| no_event       | false    | n/a            | References an already-existing state, not a new event. |
| `cancelled`     | event_related  | false    | false          | An earlier signal was later cancelled / reversed. |
| `no_event`      | no_event       | false    | n/a            | No life-event relation at all. |

## occurred
- The Life Event has happened or is clearly completed/activated.
- Example: the address was already changed because the user moved this week.
- Memory/state update is fully allowed.

## upcoming
- The Life Event is scheduled/confirmed but has not happened yet.
- Example: user starts a new job next month; the salary day is already known.
- The dialogue MUST contain an effective date or future-timing cue
  (다음달, 잔금일, 입주 예정, 다음주부터, 25일부터, …).
- Update is only partially allowed (e.g. schedule it, but do not assert it as fact).

## weak_signal
- The Life Event is merely possible or being explored ("한도만", "미리", "할 수도").
- No confirmed event. **No committed memory update.**
- Example: "집 알아보는 중인데 전세대출 한도만 보고싶어".

## existing_state
- The conversation references spouse / child / parent / rent / salary day / support
  payments, but as an **already-existing** state — not a new event.
- Treated as **no_event** for occurrence detection (life_events stays empty), with
  `negative_type = existing_state_negative` and `near_miss_event` set.
- Example: "와이프한테 매달 보내던 생활비 날짜만 바꿔줘".

## cancelled
- An earlier weak/upcoming signal is later cancelled or reversed in a subsequent session.
- Event-related (the topic came up) but **occurred = false**. Do NOT treat as occurred.
- Evidence should include both the original cue and the cancellation cue.
- Example: S1 "이직할 수도 있어서…" → S2 "그냥 안 옮기기로 했어".

## no_event
- No Life Event relation. Ordinary banking business.
- `life_events = []`, `negative_type = neutral_no_event`, `near_miss_event = null`.

## Why this matters for scoring
The scorer measures `event_related` detection and `occurred` detection **separately**,
plus `pre_event_false_occurred_rate` and `cancelled_false_occurred_rate`. A model that
treats every life-event mention as "occurred" will score well on event-related recall
but badly on the false-occurred rates — which is exactly the failure mode the pilot
is built to expose.
