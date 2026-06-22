# Stage 1 — Evidence-to-Decision Experiment Log

진행: 2026-06-22. 본 문서는 Stage 1 life-event 탐지의 "증거→판정" 실험 전 과정을
정리한다. 산출물(예측/분석/HTML)은 `results/`에 생성되며 `.gitignore` 처리되어
저장소에는 포함되지 않는다(재생성 가능). 데이터셋과 하버스(scripts) 변경만 추적된다.

## 실험 목적

대화를 점진적으로 공개하며 3개 모델이 (a) 라이프 이벤트를 언제 식별하는지,
(b) 이벤트가 없을 때 얼마나 견고하게 보류(abstain)하는지 측정한다.

- 모델: `openai:gpt-5.5`, `anthropic:claude-opus-4-8`, `google:gemini-3.5-flash`
- 데이터: 전체 284 레코드 (single 222 + mixed 62). occurred 80개 포함.

## 하버스 (scripts)

| 스크립트 | 역할 |
|---|---|
| `scripts/lib/llm_clients.py` | 통합 멀티프로바이더 `complete(provider, model, …)` |
| `scripts/make_experiment_sample.py` | 균형 샘플. `--multi-session-only --all`로 세션 실험용 샘플 |
| `scripts/run_stage1_progressive.py` | 점진 공개 러너. `--disclose session\|turn` |
| `scripts/analyze_progressive.py` | 지표/리포트. must_detect/abstain_ok/no_event 3분류 |
| `scripts/make_experiment_artifact.py` | HTML 대시보드 |
| `scripts/audit_occurred.py` | occurred 데이터 품질 감사 |

---

## 1. 채점 기준 재정의 (must_detect / abstain_ok / no_event)

초기 채점은 event_related 전체에 "full disclosure에서 gold 라벨 정확 일치"를 요구해
정확도 0.25로 나왔으나 이는 **채점 artifact**였다 (weak_signal/cancelled은 프롬프트상
보류가 정답이고, 출력 스키마 enum에 `cancelled`가 없음).

→ gold `event_status` 기준 3분류로 수정:
- **must_detect** (`occurred`): 모델이 반드시 감지
- **abstain_ok** (`upcoming`/`weak_signal`/`cancelled`): 보류가 프롬프트 준수.
  `lenient_accuracy` = 정답감지 OR 보류
- **no_event**: 이벤트 없음

## 2. 공개 단위 수정 (턴 → 세션)

원래 의도는 **세션 단위** 공개였다 (각 이벤트가 `life_events[].session_id`로 세션에
매핑, decoy는 `no_event_sessions`). 턴 단위 구현은 단일 세션 레코드를 한 발화씩 푸는
것이라 곡선이 평평했고 "너무 쉽다"는 인상을 줬다 — 이는 **잘못된 공개 단위의 artifact**.

→ 러너에 `--disclose session` 추가 (세션 누적 공개). 분석은 `n_steps`/`disclose_unit`로
일반화. 곡선 실험 본체 = multi-session 레코드 (mixed 62 + cancelled_reversed 24 = 86).

**세션 단위 효과**: 평평하던 곡선이 계단식 상승으로 바뀌고, 모델이 이벤트 세션 등장
시점에 정확히 탐지 (`first_correct_k − event_session_pos` ≈ 0). median 2세션 필요.

## 3. occurred 데이터 품질 감사 → 49% 불량

`audit_occurred.py`: occurred 80개에 full-disclosure 탐지를 돌려, 프런티어 3개가
gold를 못 맞히면 결함으로 판정. **bad 39, suspect 4, ok 37 (49% 불량).**

근본 원인 = 생성 프롬프트 결함: "사건 직접 명칭 금지 + 은행 행동만 노출"이라 많은
라벨이 형제 이벤트로 붕괴하거나(이사 블랙홀: 주택구매·전세·결혼·독립 → 이사) 무신호로
사라짐(휴직·연금·은퇴 → no_event). 생성 모델도 **gpt-4o-mini**로 단서가 빈약.

## 4. Hybrid 재생성 (Sonnet + 암묵적 단서)

전략: 붕괴형은 라벨별 식별 단서로 재생성, 무신호형은 라벨 적합성 재검토.

- **생성 모델 교체**: `openai_client.py`를 provider-aware로 (`GEN_PROVIDER`/`GEN_MODEL`
  env, claude면 anthropic 경로). → `claude-sonnet-4-6`로 생성.
- **암묵적 식별 단서**: `generate_stage1_data.py`에 `DISAMBIG_CUES`(24라벨×2) +
  `{DISAMBIG_CUE}` 프롬프트 주입(occurred_positive 한정). 핵심 원칙은 **사건을 선언하지
  않고**(예: "결혼했다" 금지) 호칭 변화(여친→와이프)·고유 금융 흔적(취득세·연금입금·
  퇴직금)·거래 패턴 변화로 **암묵적으로** 드러내 추론을 강제하는 것.
  - 1차 시도는 너무 노골적("혼인신고 마쳤어요")이라 폐기, 암묵 방식으로 재설계.
- **부분 재생성**: `--only-labels`(필터+병합, 타 레코드 보존) 추가. 잔여 어려운 라벨
  (연금→정년/은퇴 앵커, 휴직→복귀 전제, 자녀교육→입학/진학)만 단서 보정 후 재생성.

**재감사 결과**: bad **39 → 5 → 3**, ok **37 → 70 → 75**. 49% → ~4% 불량.
남은 비-ok 5개 중 4개는 최강 모델(Opus)이 추론 성공(1/3) — 암묵 벤치마크에선 결함이
아니라 적정 난이도. 진짜 0/3 결함은 1개(MIXED-001006)뿐.

데이터 백업: `data/generated_backup_20260622_2106/` (gitignore, 로컬 보존).

## 5. 클린 데이터로 세션 단위 재실험

| must-detect 탐지 정확도 | 구 데이터 | 클린 데이터 |
|---|---|---|
| Opus 4.8 | 0.34 | **0.875** |
| GPT-5.5 | 0.38 | **0.844** |
| Gemini 3.5 Flash | 0.44 | **0.719** |

- 탐지 곡선(Opus): 10–30% **0.28** → 40–60% **0.56** → 70–100% **0.875** (세션 2·3
  경계에서 도약).
- 정렬: 정답 80건 중 76건이 이벤트 세션 등장 즉시 탐지.
- abstain_ok: lenient 0.83 (재생성 안 한 영역, 동일).
- no-event 보류: false-commit 0.5, 최종 보류 Opus/Gemini 0.58 — decoy 세션 누적 시
  섣부른 commit. **미포화 축.**

## 6. 포화(saturation) 분석 — 핵심 발견

탐지 정확도 0.72~0.875는 literal 포화는 아니나(모델 변별 존재), 두 가지 한계가 있다:

1. **cross-session 추론이 사실상 0건**: 이벤트 세션 등장 *전에* 맞힌 경우 1건뿐.
   모델은 **이벤트가 담긴 단일 세션만 읽고** 탐지하며, 앞 세션은 탐지에 기여 안 함.
   "progressive 곡선"은 증거 누적이 아니라 **결정적 세션이 뒤에 배치된 위치 artifact**.
2. **현재 설계는 단일 세션 탐지로 풀린다**: 의도한 cross-session 암묵 추론
   ("여자친구 선물 → 와이프 선물", 세션 비교로만 추론 가능)이 아니라, 신호가 한 세션에
   다 들어있어 단일 세션 탐지로 승리.

→ 결론: 탐지 축은 frontier에 사실상 쉬움 + 의도(다중 세션 추론)와 어긋남. 진짜 어려운
미포화 축은 **보류/시간적 정밀도**(false-commit 0.5).

## 7. Cross-session 드리프트 프로토타입 (검증됨)

`scripts/prototype_cross_session.py`: 한 인물의 3세션 히스토리를 Sonnet으로 생성하되
사건을 세션 간 변화로만 드러내고, S1만/S3만/전체에 대해 3개 모델 탐지를 비교.

| 시나리오 | S1만 | S3만 | 전체 |
|---|---|---|---|
| **이직** (급여 입금처 한빛전자→대성물산) | no_event ×3 | **no_event ×3** | 이직 ×3 |
| **결혼** (여친→와이프, 또는 이름+가족등록) | no_event ×3 | **결혼 2/3 누설** | 결혼 |

- **이직**은 깨끗한 cross-session: 단일 세션은 그냥 "직장인의 일상 업무", 사건(고용주
  변화)은 세션 비교로만 드러남 → 단일 세션 탐지 무력화 성공.
- **결혼**은 종결 상태(가족등록·공동통장)가 단일 세션에서 진단적이라 S3만으로 2/3 누설.

**설계 원칙 (검증):** 진짜 cross-session·미포화 레코드는 **"반복 신호의 변화"로 정의되는
사건**이어야 한다 (고용주·소득·주소·정기 수취인 등 — 어느 스냅샷도 정상이고 세션 간
델타만이 사건). 종결 상태 자체가 진단적인 사건(결혼·출산)은 단일 세션 누설로 cross-session
전용 구성이 어렵다. 샘플: `results/experiment/prototype_cross_session.json`.

### 다음 설계 방향

새 generation_type **`persona_drift`**: 조합형(composed) mixed → 인물 일관 드리프트형.
변화 정의형 사건(이직·소득변화·이사·부양변화 등)을 대상으로, gold는 사건을 표시하되
**각 세션 단독 탐지가 no_event여야** 통과하는 검증 게이트를 둔다. 이로써 (a) 단일 세션
탐지 무력화, (b) 다중 세션 통합 강제, (c) 포화 해제, (d) 진짜 누적 곡선 형성.

---

## 산출물 위치 (gitignore, 재생성 가능)

- 분석/리포트: `results/experiment/{analysis.json, per_record.csv, report.md, report.html}`
- 세션 실험(클린): `results/experiment/session_v2/`
- 감사: `results/experiment/occurred_audit{,_v2,_v3}.json`
- 진행 스냅샷: `results/experiment/PROGRESS_2026-06-22.md`
