# NEXT — airdropbot 작업 포인터

**마지막 갱신**: 2026-05-21 KST
**마지막 작업자**: ljk9121 (leejk206 GitHub identity)
**현재 HEAD**: `f8d39f9` (master, origin과 동기화)

다음 세션 시작 시 이 파일 + `docs/specs/`의 최신 spec 노트 + `prompts/*.md`만 보면 컨텍스트 복원 가능.

---

## 1. 현재 상태 (v0.7.0)

### 구현 완료
- **routine prompts**: `prompts/airdrop_digest.md` (v0.7), `prompts/airdrop_pin.md` (v0.7).
- **routine 데이터**: `sources.yaml` (6 URL), `pinned.yaml` (`pins: []`로 초기화됨).
- **봇 디스패치 인프라**: `src/airdropbot/{daily,claude_runner,telegram_post}.py`. cron-driven, fail-quiet/log-loud.
- **테스트**: 34/34 PASS (yaml schema 14 + telegram_post 12 + claude_runner 4 + daily 4). ruff clean.
- **smoke test 2회 성공 (2026-05-21)**: 사용자 DM(`8217902107`)으로 v0.6 + v0.7 broadcast 도달 확인. 각각 ~3분 소요.

### 운영 상태
- **cron 미등록** — 사용자 manual step (`docs/DEPLOY.md` §5)이 아직 안 됨. 등록 안 하면 자동 daily broadcast 안 일어남.
- **현재 `.env`에 smoke test용 토큰**: `TELEGRAM_BOT_TOKEN=8619378907:AAEypBt5J_G8qqrULXsoJCr5-JHg-bUanpg`, `TELEGRAM_CHANNEL_ID=8217902107` (사용자 본인 DM). 사용자가 "실 프로덕트 단계에서 다시 결정"하기로 함 — 운영 시 토큰 revoke + 새 BotFather 봇 + 채널 핸들로 교체 검토.

### 직전 commit 흐름 (최근 → 과거)
1. `f8d39f9` v0.7.0: 출력 포맷 compact + 추천도 별점 5단계
2. `9790fb7` fix(claude_runner): prompt stdin 전달 (subprocess deadlock 회피)
3. `b371bd1` polish: _atomic_write docstring + README v0.6 본문 갱신
4. `f96af55` ... (v0.6 시리즈 — Task 1~10 + spec/plan)
5. `2678543` v0.5.0: 태혁 1차 피드백 반영

---

## 2. 다음 액션 후보

### 단기 (가장 가까운 다음 작업)
- **태혁에게 v0.7 출력 공유** → 디자인/말투 피드백 수집. v0.7 별점 분포가 보수적(★★/★ 위주)이라 매핑 룰 튜닝 필요할 수 있음.
- **cron 등록** (선택) — `docs/DEPLOY.md` §5 그대로. WSL2 환경에서 동작 확인.
- **별점 분포 튜닝** — `prompts/airdrop_digest.md` §3.2 양수 시그널 개수→별 매핑 룰을 사용자가 받는 분포 보고 조정. 예: 시그널 1개 → ★★★ (현재 ★★)로 올리기.

### 중기 (별도 sprint)
- **routine 실행 시간 단축** — 현재 ~3분. WebFetch 6개 병렬이 bottleneck. 가벼운 소스 추가 또는 페이지 chunk 제한 고려.
- **사용자별 프로필 toggle** — 자본 있는 사용자도 노출하고 싶다면 hard exclude 무효화 옵션. 현재는 글로벌 "자본 0" 고정.
- **multi-channel broadcast** — 본인 DM → BAY 채널 또는 공개 채널로 확장 시 `TELEGRAM_CHANNEL_ID` 교체 + 봇을 새 채널 admin 추가.

### 미정 / 명시 결정 대기
- **TGE 자동 감지** — 사용자가 외부 Claude로 별도 리서치하기로 명시. 봇 미관여.
- **요수익화 (구독/광고)** — 태혁이 5:14에 옵션 언급했으나 사용자가 5:17에 "그냥 봇으로 가죠" 결정. 보류.

---

## 3. 알아둘 결정/제약

### 절대 잊으면 안 되는 정책
- **자본=없음 hard exclude** 유지 (v0.5부터). 사용자 프로필 = 자본 0.
- **단방향 채널 broadcast** — 사용자 명령 받지 않음. pin은 사용자가 Claude CLI 자연어로 직접.
- **PROFILE.md** "spec 우선 원칙" — 구현 전 spec 고도화. 현재 spec 위치 = `docs/specs/`.
- **커밋 자율 금지** — 사용자가 명시적으로 commit 요청할 때만.

### 환경
- **실행 환경**: 본인 PC WSL2 (`/home/ljk9121/projects/airdropbot`).
- **Python**: 3.12.3.
- **Claude CLI**: `/home/ljk9121/.nvm/versions/node/v24.14.1/bin/claude` v2.1.145.
- **claude subprocess 호출 방식**: prompt를 **stdin으로** 전달 (`claude_runner.py:31-46`). args로 prompt 넘기면 큰 prompt + capture_output 조합에서 deadlock — 절대 args로 되돌리지 말 것.
- **CLAUDE_TIMEOUT_SEC**: 600초 (10분) 코드 기본값. smoke test 시 일시 1500초로 올린 적 있으나 stdin fix 후 600초로 충분 (routine 평균 ~3분).
- **gh CLI active account 주의**: `2021147557` 계정에도 인증돼 있음. `git push` 직전 `gh auth status` 확인하고 `leejk206`이 active인지 체크. 이전에 active 잘못돼서 push가 "Repository not found"로 실패한 적 있음.

### 외부 manual 단계 (사용자가 직접)
1. (smoke test용) BotFather 봇 + 본인 DM 토큰 → 이미 완료.
2. (실 운영 시) 새 BotFather 봇 + Telegram 채널 + 봇을 채널 admin → 미완료.
3. (실 운영 시) cron 등록 → 미완료.

---

## 4. 참고 자료 인덱스

- **spec**:
  - `docs/specs/2026-05-20-bot-feedback-v0.5.md` — 태혁 1차 피드백 (마감 임박순, 카테고리 태그, 백킹/리서치)
  - `docs/specs/2026-05-20-bot-dispatch-design.md` — v0.6 봇 디스패치 인프라
  - `docs/specs/2026-05-21-v0.7-compact-format.md` — v0.7 출력 compact + 별점
- **plan**: `docs/plans/2026-05-20-bot-dispatch-v1.md` — v0.6 구현 plan (10 task, 완료)
- **운영 가이드**: `docs/DEPLOY.md` — BotFather/채널/cron/pin 사용법
- **GitHub**: https://github.com/leejk206/airdropbot (private)
