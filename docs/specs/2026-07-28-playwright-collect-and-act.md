# v1.0 — Playwright 수집 + 행동 포인팅 파이프라인

**날짜**: 2026-07-28
**입력**: 사용자 요청 — "playwright를 이용해서, 일간 에어드랍 항목 수집 및 자동으로 행동 실행을 포인팅". 참조 패턴은 `~/projects/autoinsta` 파이프라인(사용자 지정).
**상태**: 승인됨 (사용자 리뷰 게이트 스킵 지시)

---

## 0. 목표 한 줄

6개 큐레이트 소스를 Playwright로 수집해 **팩트 KB**를 쌓고, 상위 후보의 실제 활동 페이지를 정찰해 **액션 레시피**를 뽑아내고, 그 레시피를 **dry-run 게이트 뒤에서** 실행 가능한 형태로 축적한다.

## 1. 결정 사항 (브레인스토밍 확정분)

| 항목 | 결정 |
|---|---|
| 최종 실행 범위 | 지갑 서명 포함 전체 자동 실행 (v2에서 게이트 개방) |
| 지갑 운용 | 전용 버너 지갑 신규 생성 |
| 승인 모델 | 하이브리드 allowlist — 등록 도메인·액션은 무인, 신규는 포인팅만 |
| 체인 범위 | v1 실측 데이터 수집 후 v2에서 확정 |
| 참조 아키텍처 | autoinsta 파이프라인 이식 |

## 2. autoinsta에서 계승하는 5가지

1. **자격증명 무접촉 persistent context** (`publish/session.py`) — 코드가 비밀번호·시드를 만지지 않는다. `launch_persistent_context(user_data_dir)`로 띄우고 최초 1회만 headful로 사람이 직접 로그인, 세션은 디스크에 남아 이후 headless 재사용.
2. **`dry_run=True` 기본 + 명시적 실행 게이트** — 실행하려면 `dry_run=False`와 인증된 `page`를 둘 다 넘겨야 하고, 없으면 `ValueError`.
3. **verdict 게이트가 비가역 행동 앞에 선다.**
4. **council + KB grounding** — 자기검증 상관오류를 KB 대조로 상쇄.
5. **`LLMClient` Protocol + `FakeLLM`** — 생성·검증 단이 네트워크 없이 단위테스트된다.

### 2.1 각색 — LLM 비용

autoinsta 런타임은 `AnthropicClient`(유료 API)다. airdropbot의 핵심 정책은 claude CLI 구독으로 **LLM 비용 $0**이므로, `LLMClient` Protocol은 그대로 두고 구현만 `ClaudeCliClient`(기존 `claude_runner.py` subprocess 재사용)로 갈아끼운다. `FakeLLM` 테스트 전략은 손실 없이 계승.

### 2.2 각색 — council 배치

autoinsta는 발행이 비가역 행동이라 council이 발행 앞에 있다. airdropbot의 비가역 행동은 **서명**이므로 council은 서명 게이트로 간다. 수집·정찰 단계에는 council을 두지 않는다.

**근거 (실측)**: `claude --print` 최소 호출 3.5초. 레시피+KB를 실은 역할 호출은 ~15초 추정. 후보 15개 × 3역할 × 15초 ≈ 11분 → 기존 routine 7~8분과 합쳐 ~19분으로 어떤 타임아웃도 초과. 반면 실행 게이트는 해시 캐시 적용 시 정상 운영 하루 0~2건.

단계별 실패 대가:

| 단계 | 틀렸을 때 대가 | 되돌릴 수 있나 | 검증 방식 |
|---|---|---|---|
| collect | broadcast에 틀린 줄 하나 | O | 결정적 코드 검증 |
| recon (v1 dry-run) | 실행 계획에 틀린 URL 하나 | O | 결정적 코드 검증 |
| execute (서명) | 자산 영구 손실 | **X** | 코드 프리필터 + council |

### 2.3 LLM 호출 샌드박싱 (2026-07-29 라이브 검증 후 추가)

**최초 spec의 누락**: `ClaudeCliClient`가 `claude --print --dangerously-skip-permissions`로 돌았다. 이 서브프로세스는 **세션의 MCP 서버·툴 전권을 물려받는다.** 그래서 파이프라인이 넘긴 페이지가 비어 있으면, 모델이 "정보 부족"을 반환하는 대신 자기 브라우저를 띄워 독립적으로 조사한다.

**실측 증거 (AIW3)**: `aiw3.ai` 렌더 결과 0자 → 정찰 프롬프트 123자 → **233.8초** 소요 → 5,075자 응답 → **33 스텝** 레시피 (`chain=solana,bsc`, blocker에 지갑 목록, `entry_url`은 렌더한 적 없는 `aiw3.ai/airdrop`). 같은 구간에 레포 워킹 디렉토리로 `.playwright-mcp/` 스냅샷 7건 + 스크린샷 4장이 떨어졌다. 비교 기준: 1,579자 프롬프트의 순수 텍스트 완성은 3.7초.

세 가지가 동시에 깨진다.

1. **접지(grounding)** — 레시피가 파이프라인이 관측한 페이지의 함수가 아니다. `actions.yaml`이 v2 allowlist의 근거인데 그 근거가 재현 불가능해진다.
2. **부작용** — LLM 층이 레포에 파일을 쓰고 자체 브라우저를 몬다. 오케스트레이터가 통제하지 못하는 I/O다.
3. **보안** — 지갑 서명 앞단을 fail-closed로 지키는 설계인데 분석 층이 무제한 권한으로 돈다. guard가 지키는 것은 지갑이고, LLM 층은 아무도 안 지킨다.

**규칙**: LLM 호출은 **순수 텍스트 완성**이어야 한다. 파이프라인이 프롬프트에 실어 보낸 것만이 모델의 입력이다. 모델이 독립적으로 정보를 획득하는 경로는 전부 차단한다.

| 수단 | 목적 |
|---|---|
| `--strict-mcp-config` | MCP 서버 미로드. AIW3의 실제 벡터였던 Playwright MCP를 끊는다 |
| `--disallowedTools '*'` + 알려진 툴명 명시 열거 | 와일드카드가 신규 툴을 덮고, 명시 열거가 모델에게 "툴 없음"을 정직하게 인지시킨다 |
| `--dangerously-skip-permissions` 제거 | 자동 승인 제거 |
| `cwd=` 격리 임시 디렉토리 | 방어 심층화 — 어떤 쓰기도 레포에 닿지 않는다 |

**`--allowedTools ''`는 불충분하다** (실측): WebFetch만 막히고 Bash+curl로 우회된다. `--disallowedTools '*'` 단독도 불충분하다 — 실행은 막지만 모델이 성공 메시지를 위조해 응답에 섞는다. 명시 열거를 더하면 차단을 정직하게 보고한다.

**검증 기준**: 동일 AIW3 케이스가 12.3초에 `steps: []` + blocker "Page text is empty"를 반환하고 파일 부작용이 0이어야 한다.

## 3. 타임아웃 제약 해소

현재 `daily.py`는 claude CLI **한 번**이 수집·분석·서술을 전부 하므로 `CLAUDE_TIMEOUT_SEC=600`이 파이프라인 전체의 상한이었다. 신규 구조에서는 오케스트레이터가 Python이고 LLM은 짧게 잘린 조각으로만 호출된다. 타임아웃이 **호출당** 상한으로 바뀌고, 총 소요는 Playwright가 지배한다.

## 4. 컴포넌트 경계

| autoinsta | airdropbot | 책임 |
|---|---|---|
| `collectors/` | `collectors/` | 6개 소스 Playwright 렌더 수집 → 후보 레코드 + 2-pass detail enrichment |
| `kb/` | `kb/` | 프로젝트 팩트 저장/조회/만료 |
| `topics/bank` | `select/` | 오늘 정찰할 대상 선정 |
| `generate/` | `recon/` | Playwright로 활동 페이지 정찰 → 액션 레시피 |
| `verify/council` | `verify/council` | 레시피 안전성 판정 (execute 내부 게이트) |
| `render/` | — | 해당 없음 |
| `publish/` | `execute/` | Playwright 행동 실행. dry-run 기본 |
| `orchestrator.py` | `orchestrator.py` | 전 구간 오케스트레이션 + 실패복구 |
| — | `digest/` | 기존 텔레그램 broadcast (프롬프트 자산 유지) |

각 유닛은 단일 책임 + 명확한 인터페이스로 독립 테스트 가능해야 한다.

### 4.1 2-pass detail enrichment (실측으로 추가된 단계)

**최초 spec의 누락**: 리스팅 페이지에 프로젝트 자체 URL이 있다고 가정했으나, 실제로는 없다. 라이브 검증에서 airdrops.io 리스팅으로 수집한 46개 팩트 전부 `source_url=null`이었다 — 페이지의 링크가 전부 `airdrops.io/solpump/` 같은 집계 사이트 자체 페이지였기 때문이다. 프로젝트 실제 주소는 상세 페이지의 `airdrops.io/visit/<code>/` **리다이렉트 뒤**에 있다. (v0.8이 이미 발견했던 패턴 — `NEXT.md` §1 "airdrops.io `/visit/<코드>/` 채택 룰")

**해결**: `Fact.detail_url`(집계 사이트의 프로젝트 상세 페이지)을 수집 단계에서 확보하고, 상세 페이지를 한 번 더 방문해 프로젝트 실제 URL을 캐낸다. 집계 사이트 도메인으로 나오면 리다이렉트를 따라가 최종 URL을 취한다. 소셜(X/Telegram/Discord/Medium/GitHub)은 앵커로 승격하지 않는다 — 도메인 검사가 무의미해지기 때문.

**비용 통제** — 상세 방문은 렌더 1회 + LLM 1회이므로 전수 적용하면 비싸다. 두 국면으로 좁힌다:

1. **앵커링용** — 2개 이상 소스가 이름을 언급한 프로젝트만. 합의는 이들만 성립할 수 있으므로 정확히 필요한 만큼이다.
2. **정찰용** — 선정된 대상 중 URL이 아직 없는 것만 (`limit`으로 상한).

**정찰은 앵커를 요구하지 않는다.** 정찰은 읽기 전용이고 v1의 목적이 실측 레시피 축적이기 때문이다. 앵커 부재는 실행 게이트(guard 규칙 ①)가 막는다.

**프로젝트명 정규화** — 앵커 합의는 이름 매칭에 전적으로 의존하므로 대소문자·공백 차이를 흡수한다(`project_key`). 정규화 없이 원문 매칭하면 소스별 표기 흔들림으로 앵커를 놓친다.

### 4.2 실측 데이터 (2026-07-28)

6개 소스 라이브 수집 결과:

| 항목 | 값 |
|---|---|
| 렌더 성공 | 6/6 (cryptorank·coinmarketcap 포함) |
| 수집 팩트 | 177 |
| 고유 프로젝트 | 163 |
| **≥2 소스 중복 (앵커 후보)** | **12** |

소스 2개(airdrops.io + icodrops.com)만 쓰면 중복이 0~1개라 앵커링이 사실상 성립하지 않는다. **6개 소스 전량이 앵커링 규칙의 전제 조건이다.**

### 4.3 렌더 품질 하한 (2026-07-29 라이브 검증 후 추가)

**최초 spec의 누락**: `render()`가 성공(예외 없음)했으면 유효한 페이지를 얻었다고 가정했다. 실제로는 `domcontentloaded` + 2초 settle로는 SPA·봇차단 사이트에서 **빈 페이지**가 돌아온다. 집계 사이트는 잘 긁히지만 프로젝트 실사이트가 자주 비어 있다.

| URL | 렌더 결과 |
|---|---|
| `airdrops.io/aiw3/` (집계) | 7,481자 / 86 링크 |
| `aiw3.ai/` (프로젝트) | **0자 / 0 링크** |
| `rtg.arcium.com/` | **68자 / 1 링크** |
| `www.antdrop.io/` | **19자 / 0 링크** |
| `www.arc.network/` | 6,993자 / 95 링크 |
| `app.apyx.fi/join/...` | 1,480자 / 14 링크 |
| `freeairdrop.io` (소스) | **887자 / 5 링크** (21.6초) → 팩트 0건 |

두 갈래로 대응한다.

1. **렌더러 강화** — `domcontentloaded` 후 `networkidle`을 추가로 대기하고(도달 실패는 무시), 실제 브라우저 UA를 지정하고, **본문이 하한을 넘을 때까지 폴링**한다.

   폴링을 고른 이유는 실측이다. `aiw3.ai`를 시각별로 재봤더니 **2초 0자 / 5초 0자 / 10초 4,292자**였고, `inner_text`와 `document.body.innerText`가 정확히 일치했다 — **추출 방식 문제가 아니라 순전히 대기시간 부족이었다.** 즉 "빈 페이지"의 일부는 내가 너무 일찍 포기한 것이다.

   | URL | 2s | 5s | 10s | 50s | 판정 |
   |---|---|---|---|---|---|
   | `aiw3.ai` | 0 | 0 | **4,292** | 4,292 | 대기 부족 — 기다리면 나온다 |
   | `rtg.arcium.com` | 68 | 68 | 68 | 68 | 진짜 빈 페이지 (로그인 월) |
   | `www.antdrop.io` | 19 | 19 | 19 | 19 | 진짜 빈 페이지 (404) |

   그렇다고 고정 settle을 10초로 올리면 렌더 수십 회 × 10초가 그대로 총소요가 된다. 그래서 **하한 도달 시 즉시 중단하는 폴링**으로 한다 — 이미 그려진 페이지는 폴링 0회(`arc.network` 4.8초), 늦게 그려지는 페이지만 기다린다(`aiw3.ai` 9.2초). 예산을 다 써도 짧으면 짧은 대로 반환하고, 거부 판정은 소비 측이 한다.

   **검증 (수정 후 실측)**: `aiw3.ai` 0자 → **4,232자**(가드 통과), `freeairdrop.io` 887자 → **5,525자**(팩트 0건 → **55건**, 죽은 소스 부활). `rtg.arcium.com`·`antdrop.io`는 예산 소진 후 그대로 차단 — 판정이 옳았다. `coinmarketcap.com/airdrop`은 렌더 정상(2,430자)에 활성 캠페인이 실제로 없는 것으로, 결함이 아니다.
2. **소비 측 하한** — 렌더 강화는 완화책일 뿐 보장이 아니다. 빈 페이지가 여전히 나올 수 있으므로 **`scout_recipe`는 본문 길이 하한 미달 시 `None`을 반환한다.** 정찰을 건너뛰는 대가(오늘 그 프로젝트 하나 누락, 회복 가능)가 환각 레시피를 `actions.yaml`에 적재하는 대가(v2 allowlist 근거 오염, 회복 어려움)보다 훨씬 싸다.

**하한값**: 200자. 근거는 위 실측 분포 — 환각을 유발한 페이지는 0/19/68자, 정상 판단이 나온 최소 페이지는 1,480자다. 200자는 그 사이에서 넉넉히 보수적인 지점이다.

§2.3의 툴 차단과 이 가드는 **둘 다 필요하다.** 툴 차단은 모델이 빈 입력을 스스로 메우지 못하게 하고(정직하게 `steps: []`를 반환), 이 가드는 그 무의미한 호출 자체를 아낀다.

### 4.4 enrichment 계측 (2026-07-29 추가)

**왜 필요한가**: 앵커 성립의 병목이 enrichment임이 실측으로 드러났다 (§5.1). 앵커 후보 7건 중 성립 1건이고, 실패는 도메인 충돌이 아니라 **한쪽 소스에서 URL을 못 캐는 것**이었다. 그런데 `enrich_source_url`은 실패 반환 지점이 6개인데 전부 원본 `Fact`를 그대로 돌려준다 — fail-safe이지만 **어디서 샜는지 알 수 없다.** 개선의 상한조차 모르는 상태다.

**규칙**: enrichment는 결과와 함께 **왜 그렇게 됐는지**를 반환한다. fail-safe 계약(예외를 올리지 않고 항상 `Fact`를 돌려준다)은 그대로 유지한다.

**outcome 분류** — 현재 코드가 뭉쳐놓은 것을 분리하는 것이 핵심이다. 뭉쳐 있으면 분포를 봐도 고칠 곳이 안 정해진다.

| outcome | 의미 | 고칠 수 있나 |
|---|---|---|
| `filled` | `source_url` 확보 | — |
| `skipped_no_detail_url` | 상세 페이지 자체가 없다 | 수집 단 문제 |
| `skipped_already_known` | 이미 URL이 있다 | 정상 |
| `render_failed` | 상세 페이지 렌더 실패 | 렌더러 (§4.3) |
| `llm_failed` | LLM 호출 자체가 실패 | 타임아웃·재시도 |
| `unparseable_output` | LLM이 strict JSON을 안 냈다 | **프롬프트·파싱 (고칠 수 있다)** |
| `no_url_reported` | LLM이 정상적으로 `{"url": null}` | 페이지에 정말 없다 |
| `resolve_failed` | 리다이렉트 해소 실패 | 렌더러 |
| `rejected_social` | 소셜 도메인이라 승격 거부 | 정상 (설계된 거부) |
| `rejected_aggregator` | 해소했는데 여전히 집계 사이트 | 리다이렉트 룰 |
| `rejected_no_domain` | 도메인 파싱 불가 | 파싱 |

`unparseable_output`과 `no_url_reported`의 구별이 특히 중요하다. 앞은 우리 잘못이고 뒤는 데이터의 한계다. 1차 라이브에서 enrichment LLM 호출 하나가 412자 산문을 반환한 것을 관측했는데, 현 코드에서는 `{"url": null}`과 구별되지 않고 똑같이 조용히 삼켜졌다.

**거부된 URL·도메인을 함께 남긴다.** 개수만 세면 "무엇을 거부했는지" 모른다.

**집계 위치**: `logging`을 쓰지 않는다. 파이프라인 층(`collectors`/`kb`/`recon`/`orchestrator`)은 데이터를 반환하고 집계는 호출자가 하는 것이 이 레포의 관례이며(`logging`은 cron 엔트리 `daily.py`만 사용), `run_pipeline`이 이미 요약 dict를 반환한다. 그 요약에 outcome 분포(`enrich`)와 실패 상세(`enrich_log`, 성공은 제외)를 싣는다.

**재시도 주의**: orchestrator는 앵커링 국면에서 실패한 대상을 정찰 직전에 한 번 더 enrich한다(§4.1 두 국면). 따라서 **호출 수 > 앵커 후보 수**가 정상이다. 수치를 읽을 때 이걸 모르면 오해한다.

#### 실측 (2026-07-29)

| outcome | 건수 |
|---|---|
| **`skipped_no_detail_url`** | **12** |
| `filled` | 9 |
| `skipped_already_known` | 1 |
| `no_url_reported` | 1 |
| 그 외 전부 | **0** |
| 총 호출 | 23 |

**계측이 가설을 반증했다.** 계측을 붙이기 전 추정한 주범은 "strict JSON 파싱 실패를 조용히 삼킨다"였는데 `unparseable_output`은 **0건**이었다. `render_failed`·`llm_failed`·`rejected_*`도 전부 0이다.

진짜 병목은 **`detail_url` 자체가 없어서 enrichment가 시작조차 못 하는 것**이다 — 23콜 중 12콜(52%)이 렌더도 LLM 호출도 없이 건너뛰어졌다. 그리고 detail_url이 있을 때 enrichment는 **10번 중 9번 성공한다** (`filled` 9 / `no_url_reported` 1). 메커니즘은 잘 작동하고, 절반의 후보에 대해 아예 호출되지 않는 것이 문제다.

원인은 enrichment가 아니라 **수집 단(`extract_facts`)의 `detail_url` 누락**이고, 소스별로 갈린다:

| 소스 | 팩트 | `detail_url` 있음 | 비율 |
|---|---|---|---|
| `freeairdrop.io` | 110 | 110 | **100%** |
| `icodrops.com` | 24 | 24 | **100%** |
| `cryptorank.io` | 20 | 20 | **100%** |
| `airdropalert.com` | 95 | 51 | **54%** |
| `airdrops.io` | 70 | 34 | **49%** |

(누적 KB 기준. `detail_url` 없는 80건은 `airdrops.io` 36 + `airdropalert.com` 44.)

세 소스는 100%인데 두 소스만 절반이다. 즉 추출 프롬프트나 파이프라인의 일반적 결함이 아니라 **이 두 소스의 리스팅 구조에서 링크를 못 집어내는 문제**다. `airdrops.io`는 상세 링크(`airdrops.io/<project>/`)가 분명히 존재하는데도 49%이므로, 링크가 없는 게 아니라 LLM이 일관되게 못 집는 쪽으로 보인다 — 리스팅 페이지 링크 수(153개)와 `MAX_LINKS` 절단, 프로젝트 대비 링크 밀도를 먼저 봐야 한다.

**다음 조치는 수정이 아니라 또 한 번의 측정이다** — 두 소스의 리스팅 페이지에서 프로젝트당 상세 링크가 실제로 프롬프트에 들어가는지 확인한 뒤에 프롬프트를 손댄다.

> **2026-08-01 정정**: 위 문단의 추정("링크가 없는 게 아니라 LLM이 일관되게 못 집는다")도 **틀렸다.** LLM은 못 집은 게 아니라 **링크를 보지 못했다** — `extract.py`가 앞 80개만 프롬프트에 넣는다. 그리고 `airdropalert.com`은 원인이 아예 다르다. §4.5 참조.

### 4.5 추출 프롬프트의 링크 예산 (2026-08-01 측정 후 추가)

**규칙**: 추출 LLM에게 주는 링크 목록은 **브라우저가 수집한 전량**이어야 한다. 수집 단(`browser.MAX_LINKS`)과 프롬프트 단(`extract.MAX_LINKS_IN_PROMPT`)에서 **두 번 자르지 않는다.** 링크 예산은 수집 단 한 곳에서만 정한다.

**근거 (실측 2026-08-01)**: `extract.MAX_LINKS_IN_PROMPT = 80`이 `airdrops.io`의 detail_url 커버리지 상한을 직접 정하고 있었다.

| 소스 | 전체 링크 | 고유 상세 링크 | 앞 80 내 | **구조적 상한** | KB 실측 |
|---|---|---|---|---|---|
| `airdrops.io` | 155 | 38 | 21 | **55%** | **49%** |
| `airdropalert.com/farm` | 87 | **0** | 0 | **0%** | 54% (허위) |
| `freeairdrop.io` | 109 | 53 | 53 | **100%** | **100%** |
| `icodrops.com` | 110 | 53 | 47 | **89%** | **100%** |

`airdrops.io`의 상세 링크는 index min 1 / **median 73** / max 147에 분포한다. 중앙값이 절단선에 정확히 걸쳐 있고, 그래서 정확히 절반이 잘린다.

**검증**: KB에 `detail_url`이 채워진 `airdrops.io` 항목 중 측정 시점 페이지에도 존재하는 13건은 **13/13 전부 `idx < 80`**이었다. 반대로 페이지에 있으나 KB에 없는 25건 중 17건(68%)이 `idx >= 80`이었다. 앞 80개에 들어오면 채워지고 넘어가면 안 채워진다.

**대조군이 규칙을 지지한다**: 100% 소스 두 곳은 상세 링크가 각각 53/53, 47/53으로 애초에 80 안에 대부분 들어온다. 즉 이들이 100%인 이유는 추출 품질이 아니라 **잘리지 않았기 때문**이다.

**바인딩되지 않는 한도는 건드리지 않는다**: `MAX_LINKS = 300`은 어느 소스에서도 도달하지 않고(최대 155), `MAX_TEXT_CHARS = 20,000`도 미달(최대 17,832)이다. 측정되지 않은 한도를 예방적으로 올리지 않는다.

#### 수정 후 검증 (2026-08-01, `airdrops.io` 단일 소스 실측)

`MAX_LINKS_IN_PROMPT = MAX_LINKS`로 바꾼 뒤 실제 렌더+LLM 1회:

| | 수정 전 | 수정 후 |
|---|---|---|
| detail_url 커버리지 | 49% | **100%** (30/30) |
| index ≥ 80 구간에서 채택된 detail_url | 0 (구조적으로 불가능) | **20건** |
| 렌더 / LLM 소요 | — | 4.7s / 71.6s |

30건 중 **20건이 이전에는 프롬프트에 들어갈 수조차 없던 구간**에서 나왔다 — 상관이 아니라 인과다. `polymarket.com`처럼 이미 앵커가 성립한 프로젝트도 이 구간에 있었다.

프롬프트 증가분의 대가는 LLM 1콜당 링크 75줄(~6KB)이고, 소스당 1회뿐이라 파이프라인 총 소요에 유의한 영향이 없다.

#### 전 구간 파급 (2026-08-01 5차 라이브, 915.0s)

단일 소스 실험이 아니라 전체 파이프라인에서 확인된 하류 효과. **이 수정의 영향은 detail_url에 그치지 않았다.**

| 지표 | 4차 (수정 전) | **5차 (수정 후)** |
|---|---|---|
| detail_url 커버리지 | 5소스 중 3개만 100% | **5소스 전부 100%** |
| `skipped_no_detail_url` | **12** (전체 콜의 52%) | **0** |
| `filled` (source_url 확보) | 9 | **22** |
| 팩트 | 160 | 193 |
| **앵커 성립 팩트** | 4 | **15** |
| **앵커 프로젝트** | 2 | **7** |
| 레시피 누적 | 6 | **12** |

앵커 프로젝트: AIW3, Abstract, GRVT, KOR Protocol, MoonPay, Polymarket, Renaiss Protocol. **7개 중 6개가 `cryptorank.io`를 한쪽 다리로 쓴다** (`airdrops.io` × `cryptorank.io` 조합이 5건).

즉 §4.4가 지목한 병목("detail_url이 없어 enrichment가 시작조차 못 한다")이 **완전히 해소됐고**, 그 효과가 enrichment → source_url → 도메인 합의 → 앵커까지 전 구간으로 전파됐다.

**`airdropalert.com`은 예외로 남는다** — detail_url은 49/49(100%)가 됐지만 `source_url` 산출은 여전히 **0/49**다. §4.5의 허위 커버리지 진단(카테고리 필터·제휴 링크를 detail_url로 낸다)이 재확인됐다.

**게이트 거동이 처음으로 바뀌었다**: 규칙 1(앵커 부재)이 더 이상 지배적 거부 사유가 아니고, **규칙 6(`pointing_only`)이 처음으로 도달했다**(5건). 나머지 5건은 규칙 3(자본 상한 $0). 다만 `automatable`은 레시피 12건에서 partial 8 / manual 4로 **`full`은 여전히 0건**이다 — §12 승격의 열쇠는 아직 열리지 않았다.

#### `airdropalert.com/farm` — 별개의 원인 (코드 문제가 아니다)

이 소스는 링크가 87개뿐이라 **절단을 겪지 않는다.** 대신 **per-project 상세 페이지가 존재하지 않는다.** 링크 87개 중 21개가 `browse-airdrops/?category=...`(고유 URL 9개)로 프로젝트별 페이지가 아니라 카테고리 필터 리스팅이고, 나머지 후보는 거래소 제휴 링크(`/affiliate/<거래소>`)다.

따라서 KB의 `airdropalert.com` `detail_url` 51건은 **전부 허위 커버리지**다 (일반 리스팅 41 + 제휴 링크 10). 실질 커버리지는 54%가 아니라 **0%**다.

오염 검사: 이 41건에서 승격된 `source_url`은 **0건**이다. 잘못된 앵커가 KB에 들어가지는 않았고, 대가는 enrichment 렌더+LLM 호출 낭비에 그쳤다 — §4.1의 도메인 검사가 2차 방어층으로 작동한 것이다.

**이 소스에 대한 조치는 코드가 아니라 소스 선택의 문제**이므로 spec에서 결정하지 않고 사용자 결정 대기로 남긴다. 후보는 (a) `sources.yaml`의 URL을 per-project 페이지가 있는 경로로 교체, (b) 이 소스를 detail_url 비대상으로 명시. 임의로 바꾸지 않는다.

## 5. 데이터 스키마

### 5.1 KB 팩트 (`cache/kb.yaml`)

```yaml
facts:
  - id: citrea-bridge-2026q3
    project: Citrea
    content: "Citrea 테스트넷 브리지 활동, 마감 2026-08-15"
    source: airdrops.io
    detail_url: https://airdrops.io/citrea/   # 집계 사이트의 상세 페이지
    source_url: https://citrea.xyz            # enrichment가 캐낸 프로젝트 실제 주소
    official_url: https://citrea.xyz          # 신뢰 앵커 (2소스 합의분만)
    chain: citrea-testnet
    tags: [testnet, bridge, no-capital]
    collected_at: 2026-07-28
    expires_at: 2026-08-15
```

**핵심 규칙**: `official_url`은 **2개 이상 소스에서 도메인이 일치할 때만** 채워진다. 단일 소스 URL은 `official_url: null`로 남고 후보로만 존재한다. 이것이 드레이너 1차 방어선이자 "URL은 KB에서만 인출" 규칙의 근거다.

> **⚠ 실측 (2026-07-29) — 이 정족수 룰은 작동하지만 수율이 극히 낮다.**
>
> 두 번 측정했고, 첫 판정을 두 번째가 뒤집었다.
>
> | | 1차 (결함 상태) | 2차 (§2.3·§4.3 수정 후) |
> |---|---|---|
> | 팩트 | 114 | **160** |
> | 고유 프로젝트 | 110 | 151 |
> | 팩트를 내는 소스 | **4**/6 | **5**/6 |
> | ≥2 소스 중복 (앵커 후보) | 4 (3.6%) | **7** |
> | **앵커 성립** | **0** | **1** (Polymarket) |
>
> **1차의 `anchored=0`은 룰의 결함이 아니라 굶주림이었다.** `freeairdrop.io`가 렌더 결함으로 팩트 0건이었고(§4.3), 그 소스를 살리자 55 팩트가 유입되어 첫 앵커가 성립했다 — `polymarket.com`을 `freeairdrop.io`와 `icodrops.com`이 동의했다. 따라서 "정족수 룰은 구조적으로 달성 불가"라는 1차 결론은 **철회한다.**
>
> 다만 수율은 여전히 얇다: 151개 프로젝트 중 앵커 성립 **1개(0.7%)**. 실패 지점은 도메인 충돌이 아니라 **한쪽 소스에서 URL을 못 캐는 것**이다 — 4건이 한쪽만 확보(arcus/metamask/tradoor0/zeni), 2건은 양쪽 실패(dango/truenorth).
>
> **그 원인을 §4.4 계측이 특정했다** — enrichment의 파싱·프롬프트 문제가 아니라(`unparseable_output` 0건), 수집 단에서 **`detail_url`을 못 캐서 enrichment가 시작조차 못 하는 것**이다. `airdrops.io` 49% / `airdropalert.com` 54%만 `detail_url`을 갖는다. detail_url이 있으면 enrichment는 10번 중 9번 성공한다. 즉 **앵커 수율의 상한은 지금 enrichment가 아니라 `detail_url` 커버리지가 정한다.**
>
> ~~KB 누적도 수율을 올린다 — 팩트가 쌓이면 교차 소스 일치 기회가 늘어난다. 3차 `anchored=2` → 4차 `anchored=4`.~~
>
> **2026-08-01 정정 — 이 문장은 틀렸다.** 코드가 그렇게 되어 있지 않다. `orchestrator.py`는 `anchored = resolve_official_urls(collected)`를 **`FactStore.load`보다 먼저** 실행한다. 즉 합의 판정의 입력은 **이번 런에서 방금 수집한 팩트뿐**이고, 누적 KB는 앵커 성립에 기여하지 않는다. 어제 A소스가 URL을 캐고 오늘 B소스가 캐면 합의는 **영원히 성립하지 않는다**. 3차→4차 증가는 누적 효과가 아니라 4차 런 **안에서** AIW3가 자체적으로 2소스 합의를 이룬 것이다(`airdrops.io` + `cryptorank.io`, 같은 `collected_at`). 저장된 옛 팩트의 `official_url`은 옛 판정이 얼어붙어 남아 있는 것뿐이다.
>
> 따라서 **"며칠 운영하면 누적으로 앵커가 올라간다"는 전제는 성립하지 않는다.** 누적 KB를 합의 입력에 포함시킬지는 별도 결정 사항으로 남긴다 — 룰(2도메인 합의) 자체는 안 바꾸고 입력 범위만 넓히는 변경이지만, 지금은 다른 병목(§5.4)을 먼저 푼다.
>
> **결정 대기**: 정족수 근거를 넓힐지는 **`detail_url` 커버리지를 올린 뒤에 판단한다.** 병목이 다른 곳인 상태에서 룰을 바꾸면 무엇이 효과를 냈는지 알 수 없다. 지금 룰을 바꿀 근거는 없다 — 작동하고 있고, 굶고 있는 것이다.

**필수 필드**: `id`, `project`, `content`, `source`, `collected_at`.
**선택 필드**: `detail_url`, `source_url`, `official_url`, `chain`, `tags`, `expires_at`.

만료 팩트는 `query()`에서 제외된다. 소스 다운 시에도 만료 팩트는 사용 금지.

#### 5.1.1 팩트 id 계약 + `put()` 병합 (2026-08-01 추가)

**규칙 ①**: `id`는 **`(source, project)`의 함수**다. LLM이 매 실행 새로 쓰는 텍스트는 id에 들어가지 않는다.

**근거 (실측 2026-08-01)**: `_fact_id`가 `sha256(source|project|content)`였고 `content`는 LLM이 매 런 새로 작성하는 한국어 한 줄 요약이다. 문구가 한 글자만 달라도 id가 바뀌고, `FactStore.put`은 id 기준 upsert이므로 **dedupe가 전혀 걸리지 않았다.**

| 지표 | 값 |
|---|---|
| KB 팩트 | 319 |
| 고유 id | 319 (겹침 **0**) |
| **고유 프로젝트** | **160** |
| `(project, source)` 쌍 | 170 |
| **2회 이상 중복된 쌍** | **149** |
| `collected_at` 분포 | 2개 타임스탬프에 159 + 160 |

즉 **저장된 2회 실행이 KB를 정확히 2배로 만들었다.** 매 실행마다 ~160 팩트가 순증하고 만료도 없으므로 무한 증식한다. 그리고 이 증식이 §5.4의 정찰 슬롯을 잠식한다.

**규칙 ②**: `put()`은 **병합**이다. 새 팩트의 선택 필드가 `None`이면 **기존 값을 유지한다.**

**이 규칙이 규칙 ①의 필수 짝인 이유**: `put()`은 통째 replace(`self._facts[fact.id] = fact`)다. 규칙 ①로 id가 안정되는 순간, 매 런의 **재추출 팩트**(대개 `source_url`·`official_url`이 `None`)가 같은 id로 들어와 **enrichment가 어렵게 채운 값을 매일 null로 덮어쓴다.** 지금 이 버그가 보이지 않는 유일한 이유는 id가 매번 달라서 충돌 자체가 없었기 때문이다. 규칙 ①만 단독으로 적용하면 **회귀한다.**

병합 대상은 선택 필드 전부(`detail_url`, `source_url`, `official_url`, `chain`, `expires_at`)와 `tags`(비어 있으면 기존 유지)다. `content`·`collected_at`은 최신값으로 갱신한다 — 이쪽은 "가장 최근에 관측한 서술"이 맞다.

**기존 KB 마이그레이션**: 149쌍의 중복은 일회성으로 접는다. 같은 `(source, project)`의 팩트들을 규칙 ②와 같은 병합으로 합치되, `collected_at`이 늦은 쪽을 기준으로 삼는다.

### 5.2 액션 레시피 (`actions.yaml`)

```yaml
recipes:
  - project: Citrea
    recipe_hash: "sha256:ab12..."
    entry_url: https://citrea.xyz/faucet
    chain: citrea-testnet
    signature_kind: none            # none | message | tx | approve
    capital_required_usd: 0
    steps:
      - {action: goto,           target: "https://citrea.xyz/faucet"}
      - {action: click,          target: "Connect Wallet"}
      - {action: wallet_approve, target: "connect"}
      - {action: click,          target: "Request tokens"}
    automatable: full               # full | partial | manual
    blockers: []                    # partial/manual 사유
    reconned_at: 2026-07-28
    verdict: null                   # v1은 항상 null (dry-run)
```

`recipe_hash`는 `entry_url` + 정규화된 `steps`의 sha256이다. 레시피가 바뀌면 해시가 바뀌어 verdict 캐시가 **자동 무효화**된다. 별도 만료 로직이 필요 없다.

`signature_kind` 위험도 순서: `none` < `message` < `tx` < `approve`.

`action` enum: `goto`, `click`, `fill`, `wait`, `wallet_connect`, `wallet_approve`, `wallet_sign`.

### 5.3 verdict 캐시 (`cache/verdicts.yaml`)

```yaml
verdicts:
  "sha256:ab12...":
    passed: false
    issues: ["entry_url 도메인이 KB official_url과 불일치"]
    decided_at: 2026-07-28
```

### 5.4 정찰 대상 선정 (`selection.py`) — 2026-08-01 재설계

**문제 (실측)**: v1의 목적은 레시피 축적인데(§4.1, §12), 선정 규칙이 **매 실행 같은 소수 프로젝트를 반복 정찰**하고 있었다.

원 정렬 키는 `(official_url 유무, expires_at or "9999-12-31", project)`였다. 그런데:

1. **`expires_at`이 319건 전부 `null`이다.** 추출 프롬프트가 요구하지만 LLM이 한 번도 채우지 않았다. 2번 키가 상수로 붕괴한다.
2. 따라서 실효 정렬은 **①앵커 유무 ②프로젝트명 사전순**이다.
3. §5.1.1의 중복이 여기에 곱해진다. 실측 `select_targets(limit=10)` 출력: `AIW3×2, Polymarket×4, 3DOS×2, AI Arena×2` — **10슬롯에 고유 프로젝트 4개.**
4. 그중 `AI Arena` 2건은 `official_url`·`source_url`이 둘 다 `None`이라 orchestrator가 `continue`로 버린다 — **슬롯만 소모하고 정찰 0회.**

증거: `actions.yaml` 6건이 `3DOS / AIW3 / Aligned / AlloX` + Polymarket(앵커라 1차 키로 선행) — **KB 160개 프로젝트의 알파벳 머리**다. 회당 640~830초와 LLM 30콜을 "A로 시작하는 것들"에 쓰고 있었다.

**규칙 ①: 프로젝트 단위 dedupe.** 결과에 같은 프로젝트가 두 번 나오지 않는다. 대표 팩트는 **정찰에 쓸 URL을 가진 것을 우선**한다: `official_url` > `source_url` > `detail_url` > 그 외. 슬롯을 URL 없는 팩트에 낭비하지 않기 위해서다.

**규칙 ②: 정찰 이력 로테이션.** 이미 레시피가 있는 프로젝트는 **후순위**로 민다. v1의 목적은 같은 대상의 재확인이 아니라 **분포 축적**이므로, 매 실행이 새 대상을 우선 소비해야 한다. 재정찰이 무가치한 것은 아니므로(페이지는 변한다) 제외가 아니라 **후순위**다 — 새 대상이 `limit`보다 적으면 남은 슬롯을 재정찰이 채운다.

**규칙 ③: 죽은 정렬 키를 살아 있는 키로 대체.** `expires_at`은 채워질 때 여전히 유효하므로 **유지**한다(마감 임박 우선). 그 뒤에 **소스 수 내림차순**을 넣는다 — 여러 소스가 언급한 프로젝트가 앵커에 가깝고 실체일 확률이 높다. 최종 tie-break는 결정성을 위해 프로젝트명.

최종 정렬 키:

```
(0 if official_url else 1,      # ① 앵커 보유 우선
 0 if 미정찰 else 1,             # ② 로테이션
 expires_at or "9999-12-31",    # ③ 마감 임박 (채워질 때만 작동)
 -소스 수,                       # ④ 교차 언급이 많을수록 우선
 project)                       # ⑤ 결정적 tie-break
```

**호출 계약 변경**: `select_targets(facts, *, now, limit, reconned=frozenset())`. `reconned`는 이미 레시피가 있는 프로젝트의 정규화 키 집합이고, orchestrator가 `load_recipes`의 결과에서 만들어 넘긴다. 기본값이 빈 집합이므로 기존 호출부는 규칙 ②만 비활성화된 채 그대로 동작한다.

**기대 효과**: 런당 실효 고유 정찰 대상 4~5 → `limit`(10)에 근접. 이것이 §12가 요구하는 분포 집계의 전제다 — 표본이 늘지 않으면 며칠을 돌려도 `automatable` 분포는 n=6에서 움직이지 않는다.

#### 실측 (2026-08-01, 마이그레이션 후 KB 226 팩트 / 206 프로젝트 / 기정찰 8)

| | 고유 프로젝트 | URL 보유 |
|---|---|---|
| 5차 라이브 (구 규칙) | **4** (AIW3×4, Abstract×2, GRVT×2, KOR×2) | — |
| 신규 규칙 | **10** | 8/10 |

로테이션이 실제로 작동한다 — 기정찰 8개 프로젝트가 뒤로 밀리고 미정찰 앵커(`MoonPay`, `Renaiss Protocol`)가 앞으로 나온다. 앵커 보유가 로테이션보다 상위 키이므로 실행 후보는 여전히 우선된다.

## 6. 코드 프리필터 (`execute/guard.py`)

LLM 호출 이전의 결정적 거부. 순서대로 평가하고 하나라도 걸리면 즉시 REJECT.

1. `entry_url` 등록 도메인 ≠ KB `official_url` 등록 도메인 → REJECT
   (`official_url`이 null이면 비교 불가 → REJECT)
2. `signature_kind == "approve"` 이고 한도가 무제한 → REJECT
3. `capital_required_usd > CAPITAL_CAP_USD` → REJECT
4. 버너 지갑 잔고 > `BALANCE_CAP_USD` → REJECT (자산 과다 노출 방지)
5. `chain` ∉ allowlist → REJECT (**v2부터 활성**, v1은 allowlist 파일 부재 시 이 규칙 스킵)
6. `automatable != "full"` → 실행 대상 아님 (거부가 아니라 포인팅 전용 분류)

도메인 비교는 **등록 도메인(eTLD+1)** 기준이다. 서브도메인 차이는 허용하고 타이포스쿼팅·유사 TLD는 걸러낸다.

프리필터를 통과한 것만 council로 간다.

## 7. council (`verify/council.py`)

autoinsta의 3역할(Defender/Refuter/Judge)에서 **Defender를 제거**하고 2역할로 운영한다.

**근거**: autoinsta에 Defender가 있는 이유는 카드가 반려되면 생성 작업이 낭비되기 때문이다. 여기서는 레시피가 반려돼도 비용이 0이다(오늘 그 에어드랍을 건너뛰면 끝). 안전 게이트의 기본값은 "서명하지 않음"이어야 하므로 변호인이 필요 없다. 비대칭 회의주의가 옳다.

- **Refuter** — "이 레시피를 실행하면 사용자가 자산을 잃는 시나리오를 최대한 구성하라." 공격 축: 도메인 위장(타이포스쿼팅·유사 TLD), KB에 없는 URL 등장, approve 범위, 스텝 중간의 예상 밖 서명 요구, 소스 신뢰도.
- **Judge** — STRICT JSON `{"passed": bool, "issues": [str, ...]}`만 출력.

**fail-closed**: JSON 파싱 실패, 빈 응답, LLM 예외, 판단 애매 — 전부 `passed: false`.

## 8. 실행 게이트 (`execute/`)

autoinsta `publish/`의 계약을 그대로 따른다.

```python
def run_recipe(recipe, *, dry_run: bool = True, page=None) -> dict:
    """dry_run=True(기본): 브라우저를 구동하지 않고 plan dict 반환.
    dry_run=False: 인증된 page 필수, 없으면 ValueError."""
```

반환: `{"status": "dry_run" | "executed" | "rejected", ...}`.

**지갑 세션** (`execute/session.py`) — autoinsta `publish/session.py` 이식. 전용 프로필 디렉토리에 MetaMask 확장을 두고, 최초 1회 headful로 사람이 버너 지갑 시드 입력·잠금해제. 이후 코드는 개인키를 모른 채 서명할 수 있다. 프로필 디렉토리는 gitignore.

### 8.1 실행 컨텍스트는 **warm 인증 세션**이다 (2026-08-01 정정)

**이것이 이 프로젝트의 원래 전제였고, spec이 명시하지 않아 측정이 틀어졌다.**

같은 persistent profile이 지갑만이 아니라 **소셜(X·Discord·Telegram)과 이메일 로그인 세션도 함께** 보유한다. 사람이 최초 1회 headful 창에서 직접 로그인하고, 이후 실행은 그 세션을 재사용한다. 지갑에 이미 쓰고 있는 방식(§8)을 계정 전반으로 확장하는 것일 뿐 새 메커니즘이 아니다.

**인증 우회가 아니다** — 사람이 자기 계정에 정상 로그인한 세션을 재사용하는 것이다. 코드는 비밀번호·시드·토큰을 만지지 않는다.

#### 이 전제가 `automatable` 판정을 바꾼다

`recon/scout.py`의 프롬프트는 *"the exact steps **a user** must perform"*을 묻는다 — **차가운 브라우저**를 가정한다. 그래서 모델이 "Sign in with X", "회원가입 폼 작성", "인증 메일 링크 열기"를 전부 사람 스텝으로 세고 레시피를 `manual`/`partial`로 강등했다. **§12.1의 `full = 0`은 데이터가 아니라 이 가정의 산물이다.**

blocker 텍스트를 warm/hard로 재분류한 desk 측정 (n=16):

| | 값 |
|---|---|
| warm profile로 **blocker가 전부 해소**되는 레시피 | **5/16 (31%)** |
| 캡차·Cloudflare를 언급한 레시피 | **3/16** |
| 잔존 장벽 | 자본 4 · KYC 3 · 지역제한 4 · 리퍼럴/물리장비 1 |

해소되는 5건: AIW3 · Abstract · Aligned · AlloX · KOR Protocol.

**캡차는 지배적 장벽이 아니다** (3/16). 그리고 자본은 기술 장벽이 아니라 `Limits.capital_cap = 0.0` **정책**이다 — 사용자가 상한을 올리면 열린다.

**규칙**: `automatable`은 **warm 인증 세션을 전제로** 판정한다. 이미 로그인된 계정으로 수행 가능한 스텝은 자동화 가능으로 센다. 세션이 있어도 사람이 필요한 것(캡차, KYC 서류, 물리 장비, 지역 차단)만 강등 사유다.

#### 8.1.1 재측정 (2026-08-01, n=15) — 세션은 로그인 장벽만 녹였다

기존 `actions.yaml`의 **같은 `entry_url`**을 세션 컨텍스트를 넣은 프롬프트로 다시 정찰했다. 같은 페이지·같은 모델에 문단 하나만 다르므로 차이는 그 문단의 효과다. (16건 중 1건은 빈 페이지 가드로 제외.)

| | before | after |
|---|---|---|
| `manual` | 8 | **3** |
| `partial` | 7 | **12** |
| **`full`** | **0** | **0** |
| blocker 총합 | 89 | **73** (-18%) |

`manual → partial` 승격 5건: Polymarket · AlloX · GRVT · KOR Protocol · Renaiss Protocol.

**세션 전제는 실제로 효과가 있었다** — `manual`이 8에서 3으로 줄었고 blocker가 13/15 케이스에서 감소했다. 로그인·소셜·메일 인증이 강등 사유에서 빠진 결과다.

**그러나 `full`은 여전히 0이다.** 그리고 그 이유는 로그인이 아니었다. 남은 blocker의 성격:

| 유형 | 예시 |
|---|---|
| **가치 판단 (자동화 장벽 아님)** | "공식 에어드랍 프로그램·클레임 페이지가 없음 — speculative", "whitelist/snapshot 단계, TGE 카운트다운 중" |
| 자본 | USDC 입금·CTF Exchange allowance |
| 지역·규제 | US 등 관할 차단 |
| 봇 챌린지 | Cloudflare (2건) |
| 물리·외부 자원 | 3D 프린터 연결, 리퍼럴 코드 |

**앞선 desk 추정(정규식 키워드 분류로 "5/16이 전부 해소")은 틀렸다.** 그 분류는 login/email 패턴만 warm으로, capital/kyc/captcha 계열만 hard로 셌고 "speculative"·"whitelist 단계" 같은 나머지를 어느 쪽으로도 안 셌다. 모델에게 직접 물으니 그 5건에도 4~5개씩 blocker가 남았다.

**함의**:
- §12.1의 "`full`은 이 소스군에서 도달하지 않는다"는 **재측정에서도 유지된다.** 다만 **원인 진단은 정정한다** — 지배적 원인은 이메일·소셜(그건 세션이 녹였다)이 아니라 **자본·지역·투기성·물리 자원**이다.
- 반면 §12.2에서 "prefix 실행은 구현 불가"로 판정한 근거는 **약해졌다.** 그 판정은 "`_drive`가 이메일 스텝을 지나쳐 버린다"였는데, warm 세션에서는 로그인·메일 스텝이 실제로 자동 수행 가능하다. `partial`이 7 → 12로 늘었다는 것은 **자동 수행 가능한 구간이 그만큼 길어졌다**는 뜻이다. 스텝 단위 태그(§12.3 B갈래)가 있으면 실행 상한을 계산할 수 있다.
- 즉 선택지는 여전히 §12.3의 세 갈래이되, **B(human-in-the-loop)의 비용이 처음 추정보다 낮아졌다.**

### 8.2 탐지 회피 자세 — 하는 것과 안 하는 것

목표는 **캡차를 푸는 것이 아니라 캡차 트리거를 발동시키지 않는 것**이다. 자기 계정·단일 신원의 정상적 자동화가 *망가져 보이지 않게* 만드는 선까지만 간다.

**한다**:
- persistent context 재사용 (§8.1) — 실제 쿠키·히스토리를 가진 프로필은 그 자체로 신선한 자동화 프로필과 구별된다
- `channel="chrome"` — 번들 Chromium 대신 실제 Chrome. headless 전용 지문을 피한다
- UA·locale·timezone·viewport를 **실제 환경과 일치**시킨다. 불일치 자체가 탐지 신호다
- Playwright가 남기는 자동화 플래그(`navigator.webdriver` 등) 정리
- 스텝 간 human-like 간격 — 초인적 클릭 속도가 트리거다

**안 한다**:
- **캡차 solving** (외부 solver·ML). 통제를 무력화하는 것이고, 목표도 아니다
- **지문 로테이션·다중 신원 위장.** 이 프로젝트는 **버너 지갑 1개, 단일 신원**이고, 다중 신원은 곧 sybil이라 실격 사유다

**ToS**: 일부 사이트는 UI 자동화를 명시적으로 금지한다 (Polymarket 레시피 blocker에 기록됨). 감수 여부는 사용자 판단이고, 레시피는 그 사실을 계속 기록한다.

## 9. 실패복구

| 실패 지점 | 처리 |
|---|---|
| 소스 다운/타임아웃 | 나머지 소스로 진행, KB 캐시 폴백. 만료 팩트는 사용 금지 |
| recon 실패 (구조 못 읽음) | `automatable: manual`로 기록, 포인팅만 |
| council fail | 실행 안 함. 사유를 broadcast Skipped에 노출 |
| 실행 중 예상 밖 서명 팝업 | **즉시 중단** + 스크린샷 + 알림. 재시도 없음 |
| 지갑 세션 만료 | 실행 전량 중단, 사람 개입 알림 (headful 재로그인) |
| Playwright 실패 | 스냅샷 저장, 해당 건만 스킵 |

## 10. 테스트 전략

autoinsta의 "검증기의 검증"을 계승한다.

- `collectors/` — 소스 HTML fixture 파싱 단위테스트 (네트워크 없음)
- `kb/` — put/query/expire 라운드트립 + 만료 팩트 배제
- `guard/` — **일부러 악성인 레시피**(도메인 위장, unlimited approve, 잔고 초과, official_url 없음)를 넣어 REJECT가 나는지
- `council/` — `FakeLLM`으로 Judge JSON 파싱 + fail-closed(파싱 실패 → fail) 확인
- `execute/` — dry-run이 plan을 반환하는지, `dry_run=False`인데 `page`가 없으면 `ValueError`인지

## 11. v1 범위 경계 — 하지 않는 것

- 실제 서명 실행 (dry-run 전용)
- allowlist 파일 작성 (실측 데이터 확보 후 v2)
- 체인 범위 확정 (v2)
- 멀티 지갑 로테이션
- 기존 broadcast 프롬프트 자산(`prompts/airdrop_digest.md` 32KB — 별점·pin·3카테고리 규칙) 재작성. **그대로 유지**하고 입력만 KB로 갈아끼운다.

### 11.1 배선 선행조건 — KB가 ROI 신호를 실어야 한다 (2026-08-01 측정 후 추가)

**"입력만 KB로 갈아끼운다"는 지금 그대로는 실행 불가하다.** Track A의 별점 룰(`airdrop_digest.md` §3.2)이 쓰는 신호를 KB가 담고 있지 않기 때문이다.

| 별점 룰 신호 | 가중치 | KB 보유 (n=227) |
|---|---|---|
| 마감 / TGE 임박 | 분자 **+3 / +2 / +1** | `expires_at` **2건** |
| 강한 백커 (a16z·paradigm·binance labs 등) | +2 | **없음** |
| 펀딩 ≥$30M / ≥$10M | +2 / +1 | **없음** |
| 리서치 카운트 ≥5 | +1 | **없음** |
| `coinmarketcap` official 시그널 | +1 | 해당 소스 팩트 **0건** |
| 자본 0 | 분모 +1 | **없음** |
| 소요 ≤10분 / ≤30분 | +2 / +1 | **없음** |
| 단순 클릭형 | +1 | **없음** |

그대로 배선하면 **분자 신호가 전멸**하고, v0.11.1의 분자 가드(분자 합이 0이면 ★★로 cap)가 거의 전 항목에 걸린다. 별점이 평탄해지면 3 카테고리 × Top 10의 정렬 근거 자체가 사라지므로, **다이제스트 품질이 지금보다 나빠진다.**

**원인은 데이터 부재가 아니라 추출 프롬프트다.** 소스는 이 정보를 노출한다 — KB의 `Base` 팩트 `content`에 "예상 비용 약 $72, 소요 158분"이 우연히 섞여 들어와 있고, `sources.yaml`은 `icodrops.com`을 "early stage + **펀딩 규모 prior**", `cryptorank.io`를 "데이터 풍부"로 기록한다. 현재 `extract._SYSTEM`은 7개 필드만 요구하고 그중 `expires_at`조차 227건 중 2건만 채워진다.

**따라서 배선 순서는**: ① `Fact` 스키마에 ROI 신호 추가 → ② 추출 프롬프트가 그것을 요구 → ③ 라이브로 커버리지 실측 → ④ 커버리지가 충분할 때 배선. ③ 없이 ④로 가면 별점 룰이 조용히 망가진다.

**추출 규약**: 페이지에 **명시된 값만** 채운다. 추정·환각 금지, 없으면 `null`. Track A의 §4.5가 이미 같은 규약을 쓰고 있고, 별점 룰도 "정보 부족 시 미부착"을 허용한다.

#### 11.1.1 확장 후 실측 (2026-08-01, 3소스 66 팩트)

| 신호 | `icodrops` | `cryptorank` | `airdrops.io` | 합계 |
|---|---|---|---|---|
| `funding_usd` | 58% | 58% | 0% | **31%** |
| `backers` | 0% | **62%** | 0% | **22%** |
| `capital_required_usd` | 0% | 20% | **43%** | **27%** |
| `time_minutes` | 0% | 20% | 0% | 7% |
| `expires_at` | 0% | 0% | 0% | **0%** |
| `research_count` | 0% | 0% | 0% | **0%** |

**분자 신호가 0%에서 생겼다.** 각 소스가 `sources.yaml`의 role대로 기여한다 — `icodrops`/`cryptorank`는 펀딩·백커, `airdrops.io`는 비용. 백커 값도 별점 룰의 "강한 백커" 명단과 직접 매칭된다 (Paradigm, Binance Labs, Coinbase Ventures, Jump Crypto, Blockchain Capital 등).

**`expires_at` 0%는 결함이 아니라 정확한 동작이다.** Track A의 cryptorank 가드가 이미 못박고 있다 — *"listing 행 옆의 날짜는 TGE가 아니다(활동 시작일·갱신일). TGE는 개별 deep link의 `Reward Date` 필드만 신뢰하라."* 즉 **TGE는 리스팅에서 오면 안 되고**, detail 페이지에서 와야 한다. 리스팅 추출이 날짜를 비워두는 것이 옳다.

따라서 배선은 리스팅 수집만 KB로 대체하고, **TGE는 §4.5의 detail 단계에서 회수**한다 (§11.2).

`research_count` 0%는 세 소스가 그 값을 노출하지 않는다는 뜻이다. 별점 가중치가 +1로 가장 작으므로 지금은 두고 본다.

### 11.2 배선 설계 (2026-08-01)

**대체 범위** — Track A(`prompts/airdrop_digest.md`)에서 바꾸는 것은 **수집 단계뿐**이다.

| 절 | 지금 | 배선 후 |
|---|---|---|
| §1 소스 로드 | `sources.yaml` 읽기 | **삭제** |
| §2 WebFetch 병렬 6회 | 리스팅 6개 스크래핑 | **`cache/kb.yaml` 읽기로 대체** |
| §4.5 detail enrichment | 후보의 deep link를 WebFetch | **유지.** deep link를 KB `detail_url`에서 가져오고, **TGE(`Reward Date`)도 함께 추출** |
| §3 별점·§5 출력·§7 auto-pin | — | **한 줄도 안 건드린다** (spec §11 확정) |

**KB가 §2를 대체할 수 있는 근거**: §2의 WebFetch prompt가 요구하는 항목(프로젝트명·활동유형·자본·시간·백커/펀딩·리서치 카운트·마감/TGE·detail deep link)이 §11.1의 스키마 확장으로 KB 필드와 **1:1 대응**된다. 유일한 예외가 TGE인데, 그건 위에서 본 대로 애초에 리스팅에서 오면 안 되는 값이다.

**부수 효과 — 위험 하나가 사라진다**: §2에는 "cryptorank 리스팅 날짜를 TGE로 옮겨 적지 마라"는 가드와 "모든 TGE가 같은 날짜면 정정하라"는 defense-in-depth가 붙어 있다. 리스팅 스크래핑 자체가 사라지면 **이 오염 경로가 원천 차단**된다.

**얻는 것**: WebFetch 6회(리스팅) 제거 → routine 소요 단축(NEXT.md 기록상 ~7~8분, `CLAUDE_TIMEOUT_SEC=600` 마진이 좁았다). 그리고 입력이 자유 텍스트 요약이 아니라 **교차소스 합의(`official_url`)와 구조화 필드를 가진 팩트**가 된다.

**남는 위험**: KB가 비어 있거나 오래되면 다이제스트가 빈약해진다. Track B 파이프라인이 실패해도 Track A가 조용히 나쁜 출력을 내지 않도록, 프롬프트가 **KB의 신선도를 확인하고 부족하면 명시적으로 보고**해야 한다.

## 12. v1 → v2 승격 조건

v1을 며칠 운영해 `actions.yaml`에 레시피가 쌓이면:

1. 어떤 체인·`signature_kind`·`automatable` 분포가 실제로 잡히는지 집계
2. 그 데이터로 도메인·액션 타입·체인 allowlist 작성
3. `execute/`의 게이트를 allowlist 매칭 건에 한해 개방

버려지는 코드가 없다. 게이트만 열린다.

### 12.1 실측 (2026-08-01, n=12) — `automatable: full`은 이 소스군에서 도달하지 않는다

승격의 열쇠는 규칙 6(`automatable == "full"`)이다. 레시피 12건에서 **`full`은 0건**이고(`partial` 8 / `manual` 4), 이건 표본 부족이 아니라 **구조**로 보인다.

**먼저 계측 아티팩트 가능성을 배제했다.** `scout.py`는 `ACTIONS` 밖의 action이 하나라도 섞이면 레시피를 `manual`로 강등한다(`saw_unknown_action`). 그 강등에 걸린 레시피는 **0건**이었다 — 전 스텝(174개)이 허용 action 안에 있다. 따라서 `full=0`은 강등 아티팩트가 아니라 **모델의 실제 판단**이다.

blocker 유형 분포 (12건 중, 복수 해당):

| 유형 | 레시피 수 |
|---|---|
| 이메일 가입·인증 | **10** |
| 소셜 OAuth (X·Discord·Telegram) | **8** |
| 캡차 / Cloudflare | **7** |
| 리퍼럴·초대 코드 | 6 |
| 자본 입금 | 5 |
| KYC·지역 제한 | 3 |

**이것들은 우연한 마찰이 아니라 에어드랍 태스크의 목적**이다 — 태스크는 sybil을 배제하도록 설계된다. 소스 6개가 계속 이 계열(계정 기반 퀘스트 플랫폼)을 수집하는 한 `full`을 기다리는 것은 무기한 대기에 가깝다.

### 12.2 "prefix 실행" 재프레임은 현재 데이터로 구현 불가하다

`runner._drive`가 이미 지갑 스텝에서 멈추므로, 규칙 6을 이진 거부에서 **실행 상한**으로 바꾸면 `partial`도 자동화 가능한 앞부분까지는 돌릴 수 있다는 제안이 있었다. **측정 결과 이 제안은 지금 성립하지 않는다.**

`_drive`는 **지갑 액션에서만** 멈춘다. 이메일 인증·캡차·소셜 로그인은 개념 자체가 없다. 지갑 액션 기준으로 재면 prefix 비율이 이렇게 나온다:

| 레시피 | 스텝 | 지갑 이전 prefix |
|---|---|---|
| 3DOS | 15 | **15 (100%)** |
| Aligned | 5 | **5 (100%)** |
| 나머지 10건 | — | 6~33% |
| **합계** | 174 | 49 (28%) |

그런데 `3DOS`의 "100%"는 지갑 스텝이 아예 없다는 뜻일 뿐이다. 실제 스텝은:

```
 3 fill   Registration form: full name, email address, password, confirm password
 6 wait   Verification email delivery, then open the confirmation link in the inbox
 9 click  Login button
```

**진짜 자동화 가능 prefix는 스텝 0~2다.** 지갑 기준 지표는 이걸 15로 보고한다. 이 상태로 게이트를 열면 실행기는 가짜 이메일을 채우고 로그인에서 실패한다 — **잘못된 안전 신호**다.

**근본 원인**: `automatable`은 레시피 전체에 대한 스칼라이고, `blockers`는 자유 텍스트이며, **스텝에는 자동화 가능 여부가 전혀 인코딩되어 있지 않다.** 따라서 "어디까지 자동으로 갈 수 있는가"는 기계가 알 수 없다.

### 12.3 결정 대기 — 세 갈래 (사용자 몫)

§12.1·12.2는 §12의 승격 경로가 현재 소스 구성에서 **도달 불가**함을 보인다. 코드로 답할 수 있는 문제가 아니므로 임의로 고르지 않는다.

| 갈래 | 무엇을 바꾸나 | 필요한 것 |
|---|---|---|
| **A. 대상군 교체** | 계정 기반 퀘스트 대신 **지갑만으로 완결되는** 태스크(온체인 퀘스트·테스트넷 브리지/faucet)를 겨냥 | `sources.yaml` 교체 — 코드 변경 최소. 그런 태스크가 실제로 수집되는지 먼저 측정해야 |
| **B. human-in-the-loop** | "완전 자동 실행" → "자동 가능한 구간까지 수행하고 사람에게 넘김". `full`을 기다리지 않는다 | 스텝 단위 자동화 태그(모델·프롬프트·스키마 변경) + 규칙 6을 실행 상한으로 + 인계 UX. **제품 정의가 바뀐다** |
| **C. 실행 트랙 동결** | Track B를 실행 봇이 아니라 **Track A용 구조화 수집기**로 재정의 (§11 배선) | `execute/`·`verify/` 동결. 앵커도 `full`도 불필요해짐 |

**A의 상한도 측정했다** (n=12): 사람 게이트(이메일·소셜·캡차·KYC·가입) blocker가 **하나도 없는** 레시피는 **1건**(AIW3, `partial`). 폼 입력(`fill`)이 아예 없는 레시피는 3건(AIW3·Aligned·AlloX).

즉 현재 소스군에서 지갑 완결형은 **약 8%(1/12)**다. 희소하지만 0은 아니다. §5.4 수정으로 런당 고유 정찰 대상이 10이 되었으므로 **런당 ~0.8건** 페이스가 기대되고, 그렇다면 A는 소스를 안 바꿔도 시간이 해결해줄 수 있다 — 다만 이건 **아직 측정 안 된 외삽**이다.

B는 세 갈래 중 유일하게 큰 구현이 따르고(스텝 스키마·프롬프트·게이트·인계 UX), C는 구현이 아니라 동결·배선이다.

### 12.4 결정 — C+A 병행 (사용자, 2026-08-01)

**C**: `execute/`·`verify/`를 **동결**한다. **삭제하지 않는다** — 코드·테스트·spec 모두 그대로 두고, 파이프라인이 계속 `dry_run=True`로 게이트를 통과시키며 판정만 기록한다. Track B의 산출물은 §11.1의 선행조건을 채운 뒤 Track A의 입력으로 배선한다.

**A**: 지갑 완결형 태스크(측정 ~8%)는 계속 누적한다. §5.4 수정으로 런당 고유 정찰 대상이 10이 되었으므로 런당 ~0.8건 페이스가 기대된다 — **아직 측정 안 된 외삽이다.**

**동결 해제 조건**: `actions.yaml`에 `automatable: full`이 누적 **1건 이상** 나타나거나, 사람 게이트 blocker가 없는 레시피가 유의미하게 쌓이면 §12.3을 다시 연다. 그전까지 `execute/`에 새 기능을 넣지 않는다.

**동결이 삭제가 아닌 이유**: 게이트는 이미 실전에서 값을 했다 — 1차의 환각 레시피 7건을 전부 막았고, 5차·6차에서 규칙 2(무제한 approve)·3(자본 상한)·6(`pointing_only`)이 각각 작동했다. 실행을 안 한다고 해서 이 판정을 버릴 이유는 없다. 판정은 `actions.yaml`의 품질 신호로 계속 쓰인다.
