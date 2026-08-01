# NEXT — airdropbot 작업 포인터

> **2026-08-01 세션 전체 기록**: `docs/sessions/2026-08-01.md`
> (링크 예산 → council → 축적 루프 수리 → `full=0` 두 번 측정 → Track B→A 배선 →
> warm 세션 재정의. 커밋 6건 push 완료. 가설이 네 번 틀리고 측정이 네 번 맞은 날.)

> **2026-07-29 갱신**: v1.0 파이프라인 커밋(`d27f87c`) → 라이브 검증 2회 → 결함 4건 수정
> (`6cfcfef`) → 3차 데이터(`d1cdc52`) 전부 push 완료. 아래 §0 참조.
> 그 아래 §1~§4는 v0.11 시점 기록으로, 기존 broadcast 경로는 그대로 살아있다.

---

## 0. v1.0 — Playwright 수집 + 행동 포인팅 (`d27f87c` → `6cfcfef` → `16e19a4`, push 완료)

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

- 테스트 **166 passed**, ruff clean. `playwright>=1.49` 의존성 추가, version 0.7.0 → 1.0.0.
- **커밋 완료** — `d27f87c` 구현(36 files, +4425) / `6cfcfef` 결함 수정 4건 /
  `16e19a4` enrichment 계측 / `d1cdc52`·`4b276d6` 레시피 데이터.
- **6소스 전량 라이브 검증 완료 (2026-07-29)** — 832.9s, LLM 30콜. 첫 실데이터 적재:
  `cache/kb.yaml` 45KB(114 팩트), `actions.yaml` 16KB(7 레시피). 결과
  `facts=114 anchored=0 targets=10 recipes=7`, 실행 게이트 **rejected 7/7**.
  전체 분해는 plan 문서 "실측 검증 기록 2차" 참조.

### 결함 4건 수정 완료 (2026-07-29, TDD / 166 passed / ruff clean)

라이브 검증에서 드러난 결함을 spec 갱신 후 수정했다. 상세는 plan "실측 검증 기록 3차".

1. **LLM 샌드박싱** (`llm.py`, spec §2.3) — `--dangerously-skip-permissions`가 서브프로세스에
   세션 MCP·툴 전권을 물려줘서, 빈 페이지를 받으면 모델이 **자기 브라우저로 독립 조사**했다
   (AIW3: 0자 페이지 + 123자 프롬프트 → 233.8초 → 33스텝 환각 + 레포에 스크린샷 4장).
   → `--strict-mcp-config` + `--disallowedTools '*'` + 유효 툴명 열거 + `cwd=` 격리.
   `--allowedTools ''`는 실측 결과 **불충분**(WebFetch만 막히고 Bash+curl 우회).
2. **빈 페이지 가드** (`scout.py`, spec §4.3) — 본문 200자 미달 시 LLM 호출 없이 `None`.
3. **렌더 폴링** (`browser.py`, spec §4.3) — 고정 settle 폐기. `aiw3.ai`는 빈 페이지가 아니라
   **10초에 4,292자가 그려지는** 페이지였다 (2s/5s 0자) — 너무 일찍 포기한 쪽이 문제였다.
   하한 도달 시 즉시 중단하는 폴링이라 이미 그려진 페이지는 안 기다린다(`arc.network` 4.8s).
4. **데스크톱 UA + networkidle 대기** — `render`/`resolve_redirect` 양쪽.

`tests/test_browser.py` 신설 (기존 커버리지 0). 1차 실행의 `actions.yaml`·`cache/kb.yaml`은
환각 오염이라 폐기하고 재적재했다.

### 앵커 정족수 룰 — 1차 판정 철회

1차에서 "정족수 룰은 실데이터에서 구조적으로 달성 불가"라고 기록했다. **틀렸다.**
`anchored=0`의 원인은 룰이 아니라 `freeairdrop.io`의 렌더 결함이었다. 그 소스를 살리자
(팩트 0건 → 55건) **첫 앵커가 성립했다** — `polymarket.com`을 `freeairdrop.io`와
`icodrops.com`이 동의. spec §5.1 경고문을 정정했다.

수율은 얇다 (151 프로젝트 중 1건). 실패 지점은 도메인 충돌이 아니라 **한쪽 소스에서 URL을
못 캐는 것**이다. 그 원인을 아래 §계측이 특정했다 — 파싱 실패가 아니라 `detail_url` 누락이다.
**지금 룰을 바꿀 근거는 없다** — 작동하고 있고, 굶고 있는 것이다.

### 3차 실행 결과 (수정 후)

`facts=160 anchored=2 targets=10 recipes=5 runs=6`, 667.4s (1차 832.9s).

| 지표 | 1차 | 3차 |
|---|---|---|
| 팩트를 내는 소스 | 4/6 | **5/6** |
| 앵커 성립 | 0 | **1** |
| 레시피 | 7 (2건 환각) | **5 (전건 접지)** |
| 게이트 거부 사유 | 전부 앵커 부재 | **2건은 `무제한 approve`** ← 2차 방어층 첫 작동 |

### enrichment 계측 완료 — 가설이 반증됐다 (spec §4.4)

`enrich_source_url` → `EnrichResult(fact, outcome, detail)`. `run_pipeline` 요약에
`enrich`(개수) + `enrich_log`(실패만). 177 passed, ruff clean.

**계측 전 추정한 주범("파싱 실패를 조용히 삼킨다")은 0건이었다.** 진짜 병목:

| outcome | 건수 |
|---|---|
| **`skipped_no_detail_url`** | **12** (52%) |
| `filled` | 9 |
| `skipped_already_known` / `no_url_reported` | 1 / 1 |
| `unparseable_output` 및 그 외 전부 | **0** |

`detail_url`이 없으면 enrichment는 렌더도 LLM 호출도 없이 **시작 전에** 건너뛰어진다.
반대로 **detail_url이 있으면 10번 중 9번 성공한다** — 메커니즘은 건강하고, 절반의 후보에
아예 호출되지 않는 것이 문제다. 원인은 enrichment가 아니라 **수집 단의 `detail_url` 누락**.

| 소스 | 팩트 | `detail_url` 있음 | 비율 |
|---|---|---|---|
| freeairdrop.io / icodrops.com / cryptorank.io | 110 / 24 / 20 | 전량 | **100%** |
| **airdropalert.com** | 95 | 51 | **54%** |
| **airdrops.io** | 70 | 34 | **49%** |

세 소스가 100%이므로 추출 프롬프트의 일반적 결함이 아니라 **두 소스의 리스팅 구조** 문제다.
`airdrops.io`는 상세 링크(`airdrops.io/<project>/`)가 분명히 있는데도 49%다.

4차 실행: `facts=160 anchored=4 targets=10 recipes=6 runs=8`, 638.6s. 앵커 2 → 4건
(KB 누적이 교차 일치 기회를 늘린다).

### `detail_url` 커버리지 측정 완료 — 원인은 둘이었다 (2026-08-01, spec §4.5)

측정 스크립트로 절단 **전** 링크 전량을 관찰하고 KB 실데이터와 대조했다.

| 소스 | 전체 링크 | 고유 상세 링크 | 앞 80 내 | **상한** | KB 실측 |
|---|---|---|---|---|---|
| `airdrops.io` | 155 | 38 | 21 | **55%** | **49%** |
| `airdropalert.com/farm` | 87 | **0** | 0 | **0%** | 54%(허위) |
| `freeairdrop.io` | 109 | 53 | 53 | 100% | 100% |
| `icodrops.com` | 110 | 53 | 47 | 89% | 100% |

**A. `airdrops.io` = 프롬프트 링크 절단.** `extract.py`가 앞 80개만 넣는데, 상세 링크는
index 1~147에 분포하고 **중앙값이 73** — 절단선에 정확히 걸쳐 있다. 검증: KB에 채워진 것 중
오늘도 존재하는 13건은 **13/13 전부 idx<80**, 페이지에 있는데 안 채워진 25건 중 17건이
idx≥80. 대조군 두 소스가 100%인 이유도 품질이 아니라 **안 잘렸기 때문**이었다.
→ `MAX_LINKS_IN_PROMPT = MAX_LINKS`로 수정. **실측 49% → 100%** (30/30), 그중 **20건이
이전엔 프롬프트에 들어갈 수조차 없던 idx≥80 구간**에서 나왔다. 180 passed, ruff clean.

**B. `airdropalert.com/farm` = 소스 문제 (코드 아님).** 링크 87개뿐이라 절단을 안 겪는다.
대신 **per-project 상세 페이지가 아예 없다** — 21개가 `browse-airdrops/?category=…`(고유 9개)
카테고리 필터고 나머지는 거래소 제휴 링크다. KB의 51건은 **전부 허위**(리스팅 41 + 제휴 10),
실질 커버리지는 **0%**. 오염 검사: 이 41건에서 승격된 `source_url`은 **0건** — §4.1 도메인
검사가 막았고 대가는 호출 낭비뿐이었다.

`MAX_LINKS=300`·`MAX_TEXT_CHARS=20000`은 어느 소스에서도 바인딩되지 않아 안 건드렸다.

### 5차 라이브 (2026-08-01) — 링크 수정의 효과가 전 구간으로 전파됐다

915.0s, `facts=193 anchored=15 targets=10 recipes=12`.

| 지표 | 4차 | **5차** |
|---|---|---|
| `skipped_no_detail_url` | 12 (52%) | **0** |
| `filled` (source_url 확보) | 9 | **22** |
| 앵커 팩트 / 프로젝트 | 4 / 2 | **15 / 7** |
| 레시피 누적 | 6 | **12** |
| detail_url 100% 소스 | 3/5 | **5/5** |

앵커: AIW3, Abstract, GRVT, KOR Protocol, MoonPay, Polymarket, Renaiss Protocol.
**7개 중 6개가 `cryptorank.io` 다리** (`airdrops.io`×`cryptorank.io` 5건).

**게이트 거동이 처음 바뀌었다** — 규칙 1(앵커 부재)이 더 이상 지배적 거부 사유가 아니고,
**규칙 6(`pointing_only`)이 처음 도달**(5건). 나머지 5건은 규칙 3(자본 상한 $0).

**council 예측은 빗나갔다** (`anchored ≤ 4` 예상 / 실측 15). 원인: "multi-source 9개 중 8개가
airdropalert 다리"를 **누적 KB**에서 계산했는데 앵커링은 **런 단위**로 돈다. 게다가 겹침 집합을
고정으로 취급한 게 오류였다 — 링크 수정이 각 소스가 *무엇을 뽑는지*를 바꿨다. 전문은
`docs/council/2026-08-01-v1-pipeline-improvements.md` (status: miss).

**살아남은 진단**: `airdropalert.com`은 detail_url 49/49(100%)인데 `source_url` **0/49**.
그리고 `automatable: full`은 **레시피 12건에서도 0건**이다.

### 축적 루프 수리 (2026-08-01, spec §5.1.1 + §5.4)

council이 지목한 세 결함 중 둘을 고쳤다. 193 passed (180 + 신규 13), ruff clean.

1. **`_fact_id`가 LLM 요약을 해싱**해서 KB가 매 실행 자기를 복제했다 (507 팩트 = 227의 중복).
   → `(source, project)`만의 함수로. **`put()` 병합이 필수 짝** — 없이 id만 고치면 재추출본이
   enrichment 결과를 매일 null로 덮어써서 회귀한다. 마이그레이션 **507 → 227**, 정보 손실 0건.
2. **정찰 대상 선정이 알파벳순으로 붕괴**했다 (`expires_at`이 전건 null이라 2차 키가 상수).
   → 프로젝트 dedupe + URL 보유 대표 선택 + 기정찰 후순위 로테이션 + 소스 수 tie-break.
   **고유 정찰 대상 4 → 10.**

**미수정 (council 지적)**: 앵커링이 누적 KB를 안 본다(`orchestrator.py`가 `resolve_official_urls`를
`FactStore.load`보다 먼저 실행). spec §5.1에 정정만 기록했고 코드는 안 건드렸다.

### 6차 라이브 (2026-08-01, 수정 후 코드) — 축적 루프 수리 효과 확인

938.3s, `facts=193 anchored=15 targets=10 recipes=16`.

| 지표 | 5차 (수정 전) | **6차 (수정 후)** |
|---|---|---|
| 실행 후 KB 팩트 | 314 → **507** (복제) | 227 → **227** |
| `(project,source)` 중복 쌍 | 149 | **0** |
| `official_url` / `source_url` | — | **15 / 35** (회귀 없음, source_url은 34→35 증가) |
| 정찰된 고유 프로젝트 | **4** | **9** |
| 레시피 / 그중 고유 프로젝트 | 12 / 8 | **16 / 12** |

**KB가 전체 실행을 겪고도 227 → 227.** id 안정화 + 병합이 동작한다. 로테이션도 실측
확인 — 미정찰 앵커였던 MoonPay·Renaiss Protocol이 새로 정찰되고 Alberich Token·Arcus가
들어왔다. `automatable`: manual 9 / partial 7 — **`full`은 n=16에서도 0건.**

### `automatable: full` 정면 측정 (spec §12.1~12.3)

**계측 아티팩트 아님이 확정됐다.** `scout.py`가 `ACTIONS` 밖 action 때문에 `manual`로 강등한
레시피는 **0건**(전 스텝 174개가 허용 action 안). `full=0`은 모델의 실제 판단이다.

blocker 분포(12건 기준, 복수 해당): 이메일 가입·인증 **10**, 소셜 OAuth **8**,
캡차/Cloudflare **7**, 리퍼럴 6, 자본 5, KYC 3. **sybil 배제가 태스크의 목적**이다.

**council의 "prefix 실행" 재프레임은 현재 데이터로 구현 불가**다. `_drive`는 지갑 액션에서만
멈추는데, 그 기준으로 재면 `3DOS`가 prefix 100%로 나온다. 실제로는 스텝 3이 "이메일 회원가입
폼", 스텝 6이 "인증 메일 링크 열기"라 진짜 prefix는 0~2다. **잘못된 안전 신호**다. 원인은
`automatable`이 레시피 스칼라이고 **스텝에 자동화 가능 여부가 인코딩돼 있지 않은 것**.

**A갈래 상한**: 사람 게이트 blocker가 하나도 없는 레시피 **1/12 (~8%)**.

### 다음 액션

1. **§12.3 세 갈래 결정 (사용자 몫)** — A 대상군 교체 / B human-in-the-loop / C 실행 트랙 동결.
   제품 정의가 갈리므로 임의 선택하지 않았다. spec §12.3에 각 갈래의 비용 정리.
2. **`airdropalert.com` 소스 결정 (사용자 몫)** — detail_url 100%인데 `source_url` 0% 재확인.
3. **엔트리포인트 + cron 미등록** (council 1·2번, 사용자 미선택) — `run_pipeline` 호출자가
   `tests/`뿐이고 crontab이 비어 있다. Track A도 2026-05-25 이후 안 돈다.
4. **앵커링이 누적 KB를 안 본다** — spec §5.1에 정정만 기록. 룰(2도메인 합의)은 안 바꾸고
   입력 범위만 넓히는 변경이지만 미실행.
5. 기존 broadcast(`prompts/airdrop_digest.md`) 입력을 KB로 갈아끼우는 배선은 **아직 안 함**.

### 잘 작동한 것

- **방어 심층화** — 1차에서 환각 레시피 7건 전부 앵커 부재로 `rejected`. 게이트가 열려
  있었다면 33 스텝 환각이 서명까지 갔다. 3차에서는 앵커를 얻은 Polymarket이 규칙 ①을
  통과하고 **2차 규칙(`무제한 approve`)에 걸렸다** — 계층이 계층으로 작동함이 확인됐다.
- **2-pass enrichment** — `airdrops.io/visit/9ea3/` → `arcus.xyz` 등 리다이렉트 해소 정상.
- **정찰 판단 품질** — 접지된 뒤로도 보수적·정확. Aligned를 "B2B 인프라 마케팅 사이트,
  에어드랍·퀘스트 인터페이스 없음"으로, 1차에선 Alberich/EarnBIT를 "유료 IDO/IEO,
  무료 경로 없음"으로 정확히 분류.
- **fail-safe 설계** — 결함 3건이 전부 "조용히 건너뛰기"로 떨어져 파이프라인이 죽지 않았다.
  대가는 조용한 손실이었고, 계측을 붙이자 병목이 예상과 다른 곳임이 드러났다.

---

**마지막 갱신**: 2026-08-01 KST (링크 예산 수정 → 5차 라이브 → council → 축적 루프 수리).
**마지막 작업자**: ljk9121 (leejk206 GitHub identity)
**현재 HEAD**: `f318f3e` (master, pushed) — `d27f87c` 구현 / `6cfcfef` 결함 수정 4건 /
`16e19a4` enrichment 계측 / `d1cdc52`·`4b276d6` 레시피 데이터 / `f318f3e` 문서.

**미커밋 변경 있음** (2026-08-01, 사용자 승인 대기):
- `src/collectors/extract.py` — 링크 예산(§4.5) + `_fact_id` 안정화(§5.1.1)
- `src/kb/store.py` — `put()` 병합
- `src/selection.py` — 선정 재설계(§5.4)
- `src/orchestrator.py` — `reconned` 배선
- `tests/` 3파일 — 신규 13건 (총 193 passed)
- `docs/specs/…` — §4.5 파급 실측 / §5.1 정정 / §5.1.1·§5.4 신설
- `docs/council/2026-08-01-*.md` (신규), `actions.yaml`(레시피 6→12), 이 문서
- `cache/kb.yaml`은 gitignore. 마이그레이션 적용됨 (507→227). 백업은 세션 scratchpad

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
