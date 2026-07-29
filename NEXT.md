# NEXT — airdropbot 작업 포인터

> **2026-07-29 갱신**: v1.0 Playwright 파이프라인 **커밋·push 완료** (`d27f87c`). 아래 §0 참조.
> 그 아래 §1~§4는 v0.11 시점 기록으로, 기존 broadcast 경로는 그대로 살아있다.

---

## 0. v1.0 — Playwright 수집 + 행동 포인팅 (커밋 `d27f87c`, 2026-07-29 push)

- **spec**: `docs/specs/2026-07-28-playwright-collect-and-act.md`
- **plan**: `docs/plans/2026-07-28-playwright-collect-and-act.md`
- **참조 아키텍처**: `~/projects/autoinsta` 파이프라인 이식 (사용자 지정)

### 구조

```
collectors(Playwright 렌더 + LLM 추출 + 2-pass enrichment)
  → kb(팩트 저장/만료 + 교차소스 official_url 합의)
  → selection → recon(액션 레시피) → execute 게이트(guard → council) [v1 dry-run]
```

신규 모듈: `models.py`, `llm.py`, `kb/store.py`, `collectors/{browser,extract,enrich}.py`,
`selection.py`, `recon/{scout,store}.py`, `verify/{council,cache}.py`,
`execute/{guard,session,runner}.py`, `orchestrator.py`. 기존 `daily.py`/`claude_runner.py`/
`telegram_post.py`와 프롬프트 자산은 **손대지 않았다**.

### 확정된 정책

- **지갑**: 전용 버너 지갑. 코드가 키를 만지지 않는다 — persistent context 프로필에
  확장을 두고 사람이 1회 headful 셋업 (`execute/session.py`, autoinsta 이식).
- **council 위치**: 수집이 아니라 **서명 게이트**. 후보마다 돌리면 ~11분/일이라 타임아웃.
  Defender 없이 Refuter+Judge 2콜, fail-closed.
- **앵커링**: `official_url`은 2개 이상 소스 도메인 합의분만. 단일 소스는 실행 불가.
- **정찰은 앵커 불요** (읽기 전용, 데이터 축적 목적). 실행만 guard가 막는다.
- **v1은 서명 미실행** — `runner._drive`가 지갑 스텝에서 중단.

### 상태

- 테스트 **147 passed**, ruff clean. `playwright>=1.49` 의존성 추가, version 0.7.0 → 1.0.0.
- 라이브 검증 완료: 6개 소스 렌더 6/6, 177 팩트, 앵커 후보 12개, 레시피 생성·guard 거부 확인.
- **커밋 완료** — `d27f87c` (36 files, +4425). spec/plan/구현 단일 번들로 master push.
- **KB 영속 데이터 아직 없음** — `facts.yaml`/`actions.yaml` 미생성. 라이브 검증은 일회성이라
  누적 데이터가 안 남았다. 아래 다음 액션 1번이 첫 실데이터 적재가 된다.

### 다음 액션

1. **6개 소스 전량 파이프라인 1회 실행** — 2소스만으로는 앵커가 0개. 6소스에서 실제
   `anchored > 0`이 나오는지, 레시피가 몇 건 쌓이는지 확인.
2. 며칠 운영해 `actions.yaml` 누적 → 체인·`signature_kind`·`automatable` 분포 집계.
3. 그 데이터로 v2 allowlist 작성 → 게이트 개방 (spec §12).
4. 기존 broadcast(`prompts/airdrop_digest.md`) 입력을 KB로 갈아끼우는 배선은 **아직 안 함**.

---

**마지막 갱신**: 2026-07-29 KST (v1.0 커밋·push). 아래 §1~§4 본문은 2026-05-25 v0.11 시점 기록.
**마지막 작업자**: ljk9121 (leejk206 GitHub identity)
**현재 HEAD**: `d27f87c` (master, pushed) — v1.0 Playwright 파이프라인 커밋 완료. working tree clean.

다음 세션 시작 시 **§0 → `docs/specs/2026-07-28-*` → `docs/plans/2026-07-28-*`** 순으로 읽으면 v1.0 컨텍스트 복원 가능.
기존 broadcast 경로(v0.11)는 §1~§4 + `prompts/*.md` 참조.
브레인스토밍 전체 흐름은 `~/.claude/plans/2026-07-28-playwright-collect-and-act.md`.

---

## 1. 현재 상태 (v0.11.x — 커밋 완료, `39e9808`)

### 구현 완료 (v0.7 → v0.11 누적)
- **routine prompts**: `prompts/airdrop_digest.md` (v0.11.0), `prompts/airdrop_pin.md` (v0.11.0).
- **routine 데이터**: `sources.yaml` (6 URL), `pinned.yaml` (`pins: []`).
- **봇 디스패치 인프라**: `src/airdropbot/{daily,claude_runner,telegram_post}.py`. cron-driven. `MIN_OUTPUT_LEN=1500` (v0.9.1).
- **테스트**: 46/46 PASS (yaml schema 14 + telegram_post 24 + claude_runner 4 + daily 4). ruff clean.
- **v0.8**: HTML parse_mode + `<a>` hyperlink + 2-pass detail enrichment + airdrops.io `/visit/<코드>/` 채택 룰. 활동 URL 추출 4/10 → 8/10.
- **v0.9**: 3 카테고리 × Top 10 (종합/딸깍/자본X) + `===CATEGORY_SPLIT===` separator + 양성 태그 + 자본 deploy hard exclude 해제 (-1별 경감 대체) + 라벨 "공식"→"링크". smoke test 4/4 PASS.
- **v0.10**: 프로젝트명에 **공식 링크 hyperlink** 추가 (홈 > X fallback, Discord 제외). §4.5 detail enrichment를 `activity_url` + `official_url` 두 갈래 추출로 확장. row 포맷 4종 케이스. smoke test PASS (cache 6067자, `<a>` 짝 82=82, 케이스 A 22 + 케이스 C 8).
- **v0.11 (이번 세션 후반)**: **별점 룰 ROI 기반 전면 rewrite** (분자/분모 가중치 합산 → 점수 매핑) + **자동 pin 시스템 신설** (별점 ★★★ 이상 항목 broadcast 직후 pinned.yaml에 upsert, 만료 TGE 또는 60일 default, cap 없음). 종합 prefix에 📌 수동 + 👀 자동 통합 노출. pinned.yaml 스키마에 `auto_pinned`, `tge_date` 필드 추가. -1별 경감 폐기. invisible drop 방지 목적.

### 운영 상태
- **cron 미등록** — 사용자 manual step (`docs/DEPLOY.md` §5) 미진행.
- **현재 `.env`에 smoke test용 토큰**: 본인 DM(`8217902107`). 실 운영 단계에서 새 봇 + 채널 핸들로 교체 검토.
- **routine 평균 시간**: ~7분 (v0.8 ~5분 → v0.9 detail enrichment 대상 union 확대로 증가).

### 직전 commit 흐름 (최근 → 과거)
1. `f7fa79b` v0.8 + v0.9: HTML 링크 + 3 카테고리 × Top 10 + 자본 deploy ranking
2. `909c804` docs: NEXT.md 작업 포인터
3. `f8d39f9` v0.7.0: 출력 포맷 compact + 추천도 별점
4. `9790fb7` fix(claude_runner): prompt stdin 전달
5. `b371bd1` polish: _atomic_write docstring + README v0.6 갱신

### v0.10 + v0.11 묶음 내역 (`7d0db01`·`39e9808`로 커밋됨)
- `prompts/airdrop_digest.md` (v0.9.0 → v0.11.0): v0.10 변경(§4.5/§5.4/§5.5/§5.8 + 헤더) + v0.11 변경 (§3.2 ROI 별점 룰 전면 rewrite, §3.3 raw 점수 tie-breaker, §4 -1별 폐기, §0 자동 pin 만료 인지, §5.3 prefix 📌+👀 통합, §5.7 dedupe 룰 확장, §5.9 첫 글자 룰 갱신, §7 자동 pin upsert 신설, 헤더 v0.11).
- `prompts/airdrop_pin.md` (v0.9.0 → v0.11.0): v0.10 변경(§6 snapshot 4종 케이스 + activity_url/official_url 메타) + v0.11 변경(§4 자동 → 수동 승격 룰, §6 yaml 형식에 auto_pinned/tge_date 추가, §remove에 자동 pin 명시 제거 룰, 헤더 v0.11).
- `tests/test_pinned_schema.py`: OPTIONAL에 `activity_url`, `official_url`, `auto_pinned`, `tge_date` 추가.
- 신규: `~/.claude/plans/2026-05-25-airdropbot-v0.10-project-name-link.md`, `~/.claude/plans/2026-05-25-v0.11-roi-autopin.md` (작업 계획서, 워크스페이스 외부).

---

## 2. 다음 액션 후보

### 단기
- **사용자가 v0.10 + v0.11 commit 승인** → 통합 commit 1-2개로 master에 push.
- **v0.11 smoke test 1회** — 실 broadcast 1회 돌려 (a) ROI 별점 분포 (b) 자동 pin upsert 동작 (pinned.yaml에 처음으로 데이터 들어감) (c) 만료 분기 (TGE 명시 vs TBA) (d) 종합 prefix `👀 Watchlist` 노출 확인.
- **자동 pin cumulative growth 관찰** — 매일 1-3개씩 추가되어 60일까지 누적 가능. 운영 며칠 후 활성 자동 pin 수 모니터링, 너무 많으면 v0.11.1로 cap 도입 검토.
- **태그 boundary 케이스 관찰** — Spicenet/DogeOS/Unicity 같이 "퀘스트 진행" 활동에 [딸깍] 부착이 매일 보수적인지 운영하며 봐야.
- **routine 시간 단축** — ~7-8분 (v0.10 smoke 기준)이 길면 detail enrichment 대상 unique 셋을 ≤20개로 cap.
- **load_dotenv 도입 검토** — daily.py가 .env 자동 로드 안 함. cron 운영 시 entry에 `set -a; source .env` 넣거나, python-dotenv 추가 (PROFILE.md 정책상 추가 결정은 사용자 명시 후).

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
