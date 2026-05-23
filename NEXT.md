# NEXT — airdropbot 작업 포인터

**마지막 갱신**: 2026-05-23 KST
**마지막 작업자**: ljk9121 (leejk206 GitHub identity)
**현재 HEAD**: `909c804` (master, origin과 동기화) — v0.9 변경분 미커밋 staged.

다음 세션 시작 시 이 파일 + `docs/specs/`의 최신 spec 노트 + `prompts/*.md`만 보면 컨텍스트 복원 가능.

---

## 1. 현재 상태 (v0.9.0, staged 미커밋)

### 구현 완료 (v0.7 → v0.9 누적)
- **routine prompts**: `prompts/airdrop_digest.md` (v0.9.0), `prompts/airdrop_pin.md` (v0.9.0).
- **routine 데이터**: `sources.yaml` (6 URL), `pinned.yaml` (`pins: []`).
- **봇 디스패치 인프라**: `src/airdropbot/{daily,claude_runner,telegram_post}.py`. cron-driven. `MIN_OUTPUT_LEN=1500` (v0.9.1).
- **테스트**: 46/46 PASS (yaml schema 14 + telegram_post 24 + claude_runner 4 + daily 4). ruff clean.
- **v0.8 (이번 세션 전반)**: HTML parse_mode + `<a>` hyperlink + 2-pass detail enrichment + airdrops.io `/visit/<코드>/` 채택 룰. 활동 URL 추출 4/10 → 8/10.
- **v0.9 (이번 세션 후반)**: 3 카테고리 × Top 10 (종합/딸깍/자본X) + `===CATEGORY_SPLIT===` separator + 양성 태그 + 자본 deploy hard exclude 해제 (-1별 경감 대체) + 라벨 "공식"→"링크". smoke test 4/4 PASS.

### 운영 상태
- **cron 미등록** — 사용자 manual step (`docs/DEPLOY.md` §5) 미진행.
- **현재 `.env`에 smoke test용 토큰**: 본인 DM(`8217902107`). 실 운영 단계에서 새 봇 + 채널 핸들로 교체 검토.
- **routine 평균 시간**: ~7분 (v0.8 ~5분 → v0.9 detail enrichment 대상 union 확대로 증가).

### 직전 commit 흐름 (최근 → 과거)
1. `909c804` docs: NEXT.md 작업 포인터
2. `f8d39f9` v0.7.0: 출력 포맷 compact + 추천도 별점
3. `9790fb7` fix(claude_runner): prompt stdin 전달
4. `b371bd1` polish: _atomic_write docstring + README v0.6 갱신
5. `f96af55` ... (v0.6 시리즈)

### 미커밋 staged (v0.8 + v0.9 묶음)
- `prompts/airdrop_digest.md` (v0.7 → v0.9 대규모 rewrite)
- `prompts/airdrop_pin.md` (v0.7 → v0.9)
- `src/airdropbot/telegram_post.py` (HTML parse_mode + 400 fallback + separator split)
- `src/airdropbot/claude_runner.py` (MIN_OUTPUT_LEN 200 → 1500)
- `tests/test_telegram_post.py` (12 → 24)
- `tests/test_claude_runner.py` (출력 길이 fixture 조정)
- 신규: `docs/specs/2026-05-22-v0.8-html-links.md`, `docs/specs/2026-05-23-v0.9-three-categories.md`, `docs/plans/2026-05-23-v0.9-three-categories.md`

---

## 2. 다음 액션 후보

### 단기
- **사용자가 v0.9 commit 승인** → 통합 commit 1개로 master에 push.
- **태그 boundary 케이스 관찰** — Spicenet/DogeOS/Unicity 같이 "퀘스트 진행" 활동에 [딸깍] 부착이 매일 보수적인지 운영하며 봐야.
- **별점 분포 튜닝** — 현재 보수적(★★★ 이상 1-2개). v0.9 자본 -1별 경감 후에도 ★★★ 위로 잘 안 올라옴. 시그널 가중치 조정 검토.
- **routine 시간 단축** — ~7분이 길면 detail enrichment 대상 unique 셋을 ≤20개로 cap.

### 중기
- **multi-channel broadcast** — 본인 DM → BAY/공개 채널 확장. 토큰·채널 핸들 교체.
- **cron 등록** — `docs/DEPLOY.md` §5 따라.

### 미정 / 명시 결정 대기
- **TGE 자동 감지** — 사용자가 외부 Claude로 별도 리서치. 봇 미관여.
- **수익화 (구독/광고)** — 보류.

---

## 3. 알아둘 결정/제약

### 절대 잊으면 안 되는 정책
- **v0.9: hard exclude 해제** — 자본 deploy 항목도 종합 ranking에 들어옴 (시그널 합산 후 -1별 경감). [자본X] 태그는 자본 0 항목에만 양성 표시.
- **태그 룰**: [딸깍] ≤10분, [자본X] deposit/swap/stake/매수 0원 (gas <$5 OK). 둘 다 만족 → `[딸깍][자본X]`. 정보 부족 시 미부착 (false negative 허용).
- **카테고리별 중복 허용** — 한 프로젝트가 종합/딸깍/자본X 모두 등장 가능.
- **출력 컨트랙트** — prompt §5.9. 응답 본문이 broadcast text 그 자체 (메타 narration 금지). v0.9.0 첫 smoke에서 416자 메타 요약 사고로 추가됨.
- **단방향 채널 broadcast** — 사용자 명령 받지 않음. pin은 Claude CLI 자연어 직접.
- **spec 우선** — 구현 전 spec 고도화. `docs/specs/`.
- **커밋 자율 금지** — 사용자 명시 요청 시만.

### 환경
- **실행 환경**: WSL2 (`/home/ljk9121/projects/airdropbot`).
- **Python**: 3.12.3. **Claude CLI**: v2.1.145.
- **claude subprocess**: prompt를 stdin으로 전달 (deadlock 회피).
- **`CLAUDE_TIMEOUT_SEC=600`** — v0.9에서 routine ~7분이라 마진 좁아짐. 모니터링 필요.
- **`MIN_OUTPUT_LEN=1500`** (v0.9.1) — 메타 요약 회귀 catch.
- **gh CLI active account**: `2021147557` 계정에도 인증. push 직전 `gh auth status`로 `leejk206` active 확인.

### 외부 manual 단계 (사용자가 직접)
1. (smoke test용) BotFather 봇 + 본인 DM 토큰 → 완료.
2. (실 운영 시) 새 BotFather 봇 + Telegram 채널 + 봇 채널 admin → 미완료.
3. (실 운영 시) cron 등록 → 미완료.

---

## 4. 참고 자료 인덱스

- **spec**:
  - `docs/specs/2026-05-20-bot-feedback-v0.5.md` — 태혁 1차 피드백
  - `docs/specs/2026-05-20-bot-dispatch-design.md` — v0.6 봇 디스패치 인프라
  - `docs/specs/2026-05-21-v0.7-compact-format.md` — v0.7 compact + 별점
  - `docs/specs/2026-05-22-v0.8-html-links.md` — v0.8 HTML 링크 + detail enrichment
  - `docs/specs/2026-05-23-v0.9-three-categories.md` — v0.9 3 카테고리 + 태그
- **plan**: `docs/plans/2026-05-23-v0.9-three-categories.md` — v0.9 구현 plan (11 task, 완료)
- **운영 가이드**: `docs/DEPLOY.md` — BotFather/채널/cron/pin
- **GitHub**: https://github.com/leejk206/airdropbot (private)
