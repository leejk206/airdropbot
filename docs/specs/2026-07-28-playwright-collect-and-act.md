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
> KB 누적도 수율을 올린다 — 팩트가 쌓이면 교차 소스 일치 기회가 늘어난다. 3차 `anchored=2` → 4차 `anchored=4`.
>
> **결정 대기**: 정족수 근거를 넓힐지는 **`detail_url` 커버리지를 올린 뒤에 판단한다.** 병목이 다른 곳인 상태에서 룰을 바꾸면 무엇이 효과를 냈는지 알 수 없다. 지금 룰을 바꿀 근거는 없다 — 작동하고 있고, 굶고 있는 것이다.

**필수 필드**: `id`, `project`, `content`, `source`, `collected_at`.
**선택 필드**: `detail_url`, `source_url`, `official_url`, `chain`, `tags`, `expires_at`.

만료 팩트는 `query()`에서 제외된다. 소스 다운 시에도 만료 팩트는 사용 금지.

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

## 12. v1 → v2 승격 조건

v1을 며칠 운영해 `actions.yaml`에 레시피가 쌓이면:

1. 어떤 체인·`signature_kind`·`automatable` 분포가 실제로 잡히는지 집계
2. 그 데이터로 도메인·액션 타입·체인 allowlist 작성
3. `execute/`의 게이트를 allowlist 매칭 건에 한해 개방

버려지는 코드가 없다. 게이트만 열린다.
