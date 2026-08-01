---
date: 2026-08-01
project: airdropbot
topic: v1-pipeline-improvements
claim: 지금 코드 그대로 전체 파이프라인을 라이브 1회 돌리면 anchored는 4 이하에 머문다 (detail_url 수정에도 불구하고)
confidence: 85
status: miss
---

> ## ⚠ 판정 결과 — 예측 빗나감 (2026-08-01, 같은 날 검증)
>
> **`anchored = 15`** (예측 ≤4). 앵커 프로젝트 2 → **7**개. 신뢰도 85는 잘못 매겨졌다.
>
> **어디가 틀렸나**: 이 판정은 "multi-source 9개 중 8개가 `airdropalert.com` 다리이므로
> 앵커 상한이 포화"라는 논거에 기댔다. 그 9라는 숫자를 **누적 KB(2회 실행분이 섞인 319 팩트)**
> 에서 계산했는데, **앵커링은 런 단위로 동작한다**(`resolve_official_urls(collected)`).
> 이번 런의 per-run multi-source는 **14개**였다.
>
> 더 근본적으로는 소스↔프로젝트 겹침 집합을 **고정된 것으로 취급**한 것이 오류다.
> 링크 절단 수정은 각 소스가 *무엇을* 뽑는지를 바꿨다 — `skipped_no_detail_url`이
> **12 → 0**이 되면서 enrichment가 전 후보에 돌았고(`filled` 9 → 22), 우리가 쳐다보지도
> 않던 조합에서 합의가 성립했다. **7개 앵커 중 6개가 `cryptorank.io`를 다리로 쓴다**
> (`airdrops.io` × `cryptorank.io`가 5건).
>
> 아이러니하게도 이건 이 판정이 §5.1에서 **정정한 바로 그 오류**(누적 프레임과 런 프레임을
> 섞는 것)를 판정 자신이 반복한 것이다.
>
> **살아남은 부분**: `airdropalert.com`은 detail_url이 49/49(100%)가 됐는데도 `source_url`
> 산출은 여전히 **0/49** — 허위 커버리지 진단은 유지된다. 그리고 `automatable: full`은
> 레시피 12건에서도 **여전히 0건**이라 Red Team의 우려는 미해소 상태로 남는다.
>
> **부수 확인**: guard 규칙 6(`pointing_only`)이 **처음으로 도달했다**(5건). "규칙 6은 한 번도
> 도달된 적이 없다"는 판정 내 서술은 이 실행 이후로는 사실이 아니다.

# Council verdict: 수집 품질은 병목이 아니었다 — 축적 루프가 끊겨 있고, 유일한 산출물은 68일째 멈춰 있다

## Conclusion

**세 가지가 순서대로 사실이다.**

첫째, 방금 끝낸 `detail_url` 수정은 옳지만 **앵커를 늘리지 못한다.** 이건 예상이 아니라 구조다. KB에서 2개 이상 소스가 언급한 프로젝트는 **9개**뿐이고, 그중 **8개가 `airdropalert.com`을 한쪽 다리로 갖는다.** 그 소스는 per-project 상세 페이지가 없어 `source_url`을 **95건 중 0건** 냈다. Polymarket만 다른 다리가 있어 살아남고, **나머지 7개는 반대편 다리가 죽어 있는 한 앵커가 성립할 수 없다.** `airdrops.io` 커버리지를 100%로 만든 것은 이 7개의 *한쪽* 다리를 고친 것이다.

둘째, **레시피 축적 루프가 사실상 정지해 있다.** 세 결함이 곱해진 결과다: (a) `_fact_id`가 LLM이 매 런 새로 쓰는 한국어 요약을 해싱해서 **KB가 매 실행마다 자기를 복제한다** (319 팩트 = 160 프로젝트의 2중 적재, 170쌍 중 149쌍 중복). (b) `expires_at`이 **319건 전부 null**이라 정찰 대상 정렬이 **알파벳순으로 붕괴**했다 — `actions.yaml`의 6건이 3DOS/AIW3/Aligned/AlloX인 게 우연이 아니다. (c) 앵커링이 `resolve_official_urls(collected)`로 **이번 런 팩트만** 본다 (`orchestrator.py:82`가 `FactStore.load`보다 먼저다) — 누적 KB는 합의 판정에 입력되지 않는다. 그래서 `select_targets(limit=10)`의 실효 고유 프로젝트가 **4~5개**이고, 며칠 더 돌려도 같은 알파벳 머리를 재정찰한다. **spec §12의 "며칠 운영해 분포를 집계한다"는 전제가 실행 횟수에 반비례해 무너진다.**

셋째, 그리고 이게 가장 불편한 결론인데 — **v1.0 파이프라인에는 프로덕션 엔트리포인트가 없다.** `run_pipeline`을 부르는 코드는 `tests/`뿐이고, `[project.scripts]`도 crontab도 없다. 4회의 "라이브 검증"은 레포에 남지 않은 애드혹 스크립트였다. 산출물 `cache/kb.yaml`·`actions.yaml`은 **아무도 읽지 않는다** (spec §11의 "broadcast 입력을 KB로 교체"는 미실행). 한편 실제 사용자 가치를 내는 Track A(v0.11 broadcast)는 `docs/DEPLOY.md`에 **완성된 crontab 한 줄이 놓인 채 2026-05-25 이후 68일간 한 번도 돌지 않았다.**

**따라서 다음 한 단위의 주의력은 수집 품질이 아니라 배선에 써야 한다.** 다만 배선만 먼저 하면 매일 KB를 두 배로 적재하고 같은 5개를 재정찰하는 cron이 생기므로, (a)(b)를 같이 묶어야 한다. Pragmatist의 견적으로 **Track A cron 5분 + Track B 엔트리포인트 2h + fact-id merge 2h + selection dedupe 1.5h ≈ 6시간**이고, 그 6시간이 사는 것은 **하루 10개 고유 프로젝트의 접지된 레시피**다. 2주면 n≈100~140이 되고, 그때 비로소 §12가 요구하는 분포를 셀 수 있다.

그리고 그 2주가 **실행 트랙의 생사를 결정한다.** 현재 `automatable`은 manual 4 / partial 2 / **full 0**이고, 6개 레시피의 반복 blocker는 소셜 OAuth·이메일 인증·캡차·리퍼럴 게이트 — **에어드랍 태스크는 봇을 배제하도록 설계된다.** n≈100에서도 `full`이 0이면 `execute/`+`verify/` 전체가 공집합을 위한 기계이고, Track B는 "실행 봇"이 아니라 **Track A용 구조화 수집기**로 재정의되는 것이 맞다 (그 경우 앵커도 `full`도 필요 없다).

## Falsifiable claim & confidence

- **Claim**: 지금 코드 그대로(=`MAX_LINKS_IN_PROMPT` 수정만 반영된 상태) 전체 파이프라인을 라이브 1회 돌리면 **`anchored`는 4 이하에 머문다.** NEXT.md 다음액션 1이 기대하는 "커버리지가 올랐으니 앵커도 는다"는 나타나지 않는다.
- **Confidence**: 85
- **What would flip it**: `anchored`가 6 이상으로 오르면 이 판정은 틀렸고, 내가 놓친 앵커 경로가 있다는 뜻이다. 그 경우 `airdropalert` 제거 권고도 재검토해야 한다. (반증 비용은 11분이므로 **먼저 돌려보는 것을 권한다** — 다만 결과를 배움으로 기대하지 말 것.)

## Key issues debated

### Issue 1: `detail_url` 수정이 앵커를 늘리는가

- **정렬**: 전원 "아니오". Steelman·Pragmatist가 독립적으로 같은 예측을 냈고, Moderator가 KB를 직접 집계해 확인했다 — multi-source 9개 중 8개가 airdropalert 다리, 그 소스의 `source_url` 산출 0/95.
- **갈린 지점**: Steelman은 "그래도 수정은 유효하며 다른 다리가 고쳐지면 즉시 발현된다"로, Red Team은 "이 착시가 정족수 룰을 잘못 건드리게 만들 위험"으로 읽었다.
- **무엇이 결론을 정했나**: Red Team의 실패 시나리오가 구체적이었다 — 앵커가 안 늘면 "정족수 룰이 문제"라는 결론으로 미끄러져 **1소스 허용으로 완화 = 유일하게 실전 검증된 드레이너 방어선 해체**. 그래서 예측을 **미리 기록**하는 것 자체가 조치가 된다. NEXT.md에 이미 그 취지의 문장이 있으나("아직 측정 안 된 예측") 더 못박아야 한다.

### Issue 2: `airdropalert.com`을 어떻게 할 것인가 — "결정 대기"인가 이미 답이 나온 것인가

- **정렬**: 제거/교체 쪽.
- **갈린 지점**: spec §4.5는 이걸 "코드가 아니라 소스 선택 문제 → 사용자 결정 대기"로 남겼다. Pragmatist는 **"데이터가 이미 답했다"**고 반박했다 — 95 팩트 / `source_url` 0건 / 실질 detail 커버리지 0%. 앵커 다리로 기여한 적이 없고 구조적으로 못 한다. 현재 유일한 효과는 **성립 불가능한 멀티소스 후보 7개를 만들어 enrichment 예산을 헛되이 쓰게 하는 것.**
- **무엇이 결론을 정했나**: "제거하면 후보가 9→2로 준다"는 반론이 성립하지 않는다는 점. 그 7개는 애초에 앵커가 될 수 없었으므로 **수율 손실 0, 낭비 절감**이다. 다만 이건 여전히 사용자 결정 사항이고, Pragmatist의 대안(Issue 5의 enrichment 게이트 분리)을 하면 이 소스를 리스팅용으로 남겨도 무해해진다.

### Issue 3: v2 승격 경로(spec §12)는 도달 가능한가

- **정렬**: 현 상태로는 도달 불가. 이유가 두 겹이라는 데 합의.
- **갈린 지점**: Steelman은 "축적 루프의 소규모 결함 3개 때문이고, 고치면 복리로 돈다"(수리 가능). Red Team은 "고쳐도 `automatable: full`이 공집합일 수 있다 — 태스크가 봇 배제를 목적으로 설계되므로"(근본적).
- **무엇이 결론을 정했나**: 둘 다 맞고 **순서가 있다.** 지금 n=6으로는 어느 쪽인지 알 수 없다. 6시간을 써서 n≈100을 만드는 것이 이 논쟁을 해소하는 유일한 방법이고, 그건 Steelman의 수리를 하되 Red Team의 질문에 답하기 위해 하는 것이다. 부수적으로 확인된 것: **guard 규칙 6은 한 번도 도달된 적이 없다** — 전건이 규칙 1·2에서 먼저 죽었으므로 `automatable`은 아직 시험되지 않은 규칙이다.

### Issue 4: 프레임 자체가 맞는가 (First Principles의 반전)

- **정렬**: 없음 — 이건 Round 2에서 새로 열린 축이다.
- **주장**: `prompts/airdrop_digest.md:3`이 사용자 프로필을 **"자본 비쌈·시간 자유"**로 명시한다. Track B는 **풍부한 자원(시간)을 자동화하고 희소한 자원(자본: 버너 지갑·gas·unlimited approve·sybil 프로파일 노출)을 지불한다.** 방향이 뒤집혀 있고, 성공 케이스에서 버는 것이 하루 10분이라 EV가 음수일 수 있다. 또한 Track B의 타겟 선정에는 **ROI·딸깍·자본X·마감 가중치가 한 줄도 없다** — 32KB의 튜닝된 선호함수를 참조하지 않고 targeting을 처음부터 다시 유도했고, 그 결과가 알파벳순 붕괴다.
- **무엇이 결론을 정했나**: 이 지적은 **강하지만 사용자의 결정을 뒤집을 근거는 아니다.** spec §1이 "최종 실행 범위: 지갑 서명 포함 전체 자동 실행"을 브레인스토밍 확정분으로 기록하고 있고, 사용자가 명시 요청한 방향이다. 다만 **spec §11 대비 미완**(Track B 산출물을 Track A가 소비)은 주관이 아니라 측정 가능한 사실이고, First Principles가 지적한 "가치 산출 0"은 그 미완의 직접 결과다. → **방향은 유지, 순서는 재배치.**

### Issue 5: 계측 설계 — §4.4의 교훈이 일반화되지 않았다

- **정렬**: 전원 동의. enrichment에만 outcome을 붙였고 같은 "조용한 실패"가 더 비싼 단계에 그대로 남아 있다.
- **확인된 목록**: `extract_facts`의 `except → return []`(렌더/LLM/파싱 미구별), orchestrator 소스 루프의 `except → continue`, `scout_recipe`의 `None` 반환 4경로(**파이프라인 최고가 단계인데 계측 0**), guard 거부 사유의 미집계, 그리고 **`run_pipeline`의 요약 dict가 반환 즉시 버려진다** — §12가 요구하는 "며칠치 집계"의 물리적 근거가 없다.
- **추가 발견 (Round 1에 없던 것)**: enrichment가 `_multi_source_projects`로 게이팅되어 **`source_url`이 27/319(고유 14 프로젝트)에 묶여 있다.** 앵커링·DefiLlama 같은 모든 후속 아이디어의 상한이 이 숫자다. Pragmatist는 "`detail_url` 있고 `source_url` 없는 전건에 런당 30건 예산"(~25줄, 런타임 +10분)이 DefiLlama(~100줄)보다 먼저라고 판정했고, 이게 맞다.

### Issue 6: 게이트를 열기 전에 고쳐야 할 안전 결함 3건 (실측 확인)

- **`approve_unlimited`가 유일한 fail-open이다.** `scout.py`는 모르는 `signature_kind`→`approve`, 모르는 `automatable`→`manual`로 최악값 강등하는데, `approve_unlimited`만 `bool(data.get(...))` → **키 부재 = False = 규칙 2 통과.** 실제로 `Aligned`·`AlloX` 레시피가 blocker에 "signature requirement is unverified, assumed conservatively"라고 자백하면서 `approve_unlimited: false`를 달고 있다.
- **council이 8회 실행 동안 0회 돌았다.** `runner.py`가 `dry_run=True`에서 `verify_recipe` 앞에 조기 반환하고, v1은 항상 dry_run이다. `verify/cache.py`는 테스트에서만 참조되는 **죽은 코드**이고 `cache/verdicts.yaml`은 존재하지 않는다 — spec §2.2가 council 비용을 정당화한 근거(해시 캐시)가 미구현 캐시에 기대고 있다. **서명 직전의 마지막 방어층이 실전 미검증 상태로 v2를 맞는다.**
- **guard가 만료 필터를 우회한다.** `orchestrator.py:108`이 `store.all()`을 넘긴다(`store.query(now=...)`가 아니다). 지금은 `expires_at`이 전부 null이라 무해하지만, 만료가 채워지기 시작하면 **철회된 앵커로 실행이 승인되는 경로**다. 규칙 4(`wallet_balance_usd`)도 배선되지 않아 항상 기본값 0.0으로 평가된다.
- **무엇이 결론을 정했나**: 셋 다 "게이트를 여는 순간에" 필요하지 지금 당장은 관측 변화가 없다 (전건이 규칙 1에서 먼저 죽으므로). 단 **council 검증은 예외** — Pragmatist가 지적한 대로 파이프라인 배선 없이 **기존 `actions.yaml` 6건에 `verify_recipe`를 수동 1회(30분)** 돌리면 "한 번도 실행된 적 없는 코드 경로"의 위험이 거의 다 걷힌다. Polymarket(unlimited approve)·Aligned(미검증 approve)에 `passed: false`가 나오는지가 게이트 개방의 선행 조건이 되어야 한다.

### Issue 7: "명백한 수정"이 회귀를 부르는 지점 (Pragmatist의 catch)

- `_fact_id`에서 `content`를 빼는 것은 1줄로 보이지만 **그대로 하면 회귀한다.** `FactStore.put`은 통째 replace(`kb/store.py`)다. id가 안정되면 매 런의 재추출 팩트가 같은 id로 들어오는데 재추출본의 `source_url`은 대개 null이므로, **enrichment로 어렵게 채운 `source_url`·`official_url`을 매일 null로 덮어쓴다.** 지금은 id가 매번 달라서 이 버그가 우연히 안 보일 뿐이다.
- **필수 세트**: `put()`을 "새 값이 None이면 기존 값 유지"하는 merge로 바꾸는 것 + 기존 149쌍 중복을 접는 일회성 병합. 합쳐서 ~2h.

## 권고 순서 (합의된 결론)

| # | 항목 | 규모 | 왜 이 순서인가 |
|---|---|---|---|
| 0 | 현 상태로 라이브 1회 | 11분 | 위 falsifiable claim의 반증 기회. 먼저 돌리고 기록 |
| 1 | **Track A cron 등록** | **5분, 0줄** | `DEPLOY.md`에 완성된 한 줄. 68일간 멈춘 유일한 가치 산출물 |
| 2 | Track B 엔트리포인트 + cron | ~60줄 / 2h | §12의 물리적 전제. **cron 비대화형 `claude` CLI는 미검증 — 하루로 잡을 것** |
| 3 | `_fact_id` + `put()` merge | ~15줄 / 2h | 안 하면 매일 KB가 자기를 복제. Issue 7의 merge가 필수 세트 |
| 4 | selection dedupe + 정찰 로테이션 | ~20줄 / 1.5h | 안 하면 매일 같은 4~5개. 3+4 없이 2를 돌리면 중복만 쌓인다 |
| 5 | **2주 방치 후 `automatable` 분포 집계** | 0줄 | 실행 트랙의 생사 판정. `full`이 0이면 Track B를 수집기로 재정의 |
| 6 | enrichment 게이트 분리(예산제) | ~25줄 / 2h | `source_url` 27→수십. 앵커링·DefiLlama의 상한을 푸는 선행 조건 |
| 7 | `airdropalert` 결정 | 1줄 | 사용자 결정. 데이터는 이미 답했으나 소스 선택은 사용자 몫 |
| 8 | council 수동 1회 (기존 6건) | 30분 | 미검증 방어층 해소. 파이프라인 배선은 5의 결과 이후 |
| 9 | guard all-rules + run ledger, `approve_unlimited` flip, `wallet_balance_usd` 배선 | ~70줄 | **게이트 개방 직전에.** 지금 하면 관측 변화 0 |
| 10 | DefiLlama 둘째 다리 | ~100줄 / 1일 | 6의 상한에 묶임. 그리고 **fuzzy 이름 매칭은 fail-closed 원칙 위반** — 정확 매칭만 |

## Assumptions and caveats

- **작업가정 1(최종 목표 = 버너 지갑 자동 참여)은 확인됐다** — spec §1이 브레인스토밍 확정분으로 기록. First Principles의 반전은 이 결정을 뒤집는 근거가 아니라 **순서를 재배치하는 근거**로 채택했다.
- **Moderator가 직접 재현한 것**: KB 집계(319/160/149/0), `orchestrator.py:82` 앵커 순서, 엔트리포인트·crontab 부재, `selection.py` 정렬 키, `scout.py`의 `approve_unlimited` 비대칭, `runner.py` 조기 반환, `verify/cache.py` 미호출, `FactStore.put` 통째 replace, multi-source 9개 중 airdropalert 8개, `DEPLOY.md` crontab, Track A 마지막 로그 2026-05-25.
- **미검증으로 남은 것**: Red Team의 sybil 필터 주장(Linea가 자격 주소의 ~40%를 필터링했다는 2차 출처)과 Polymarket ToS의 "CLOB API만 허용" 정확한 문구. **버너 지갑이 실제로 에어드랍을 받는지는 이 프로젝트에서 한 번도 측정된 적이 없고, 코드로 답할 수 없는 월 단위 대기 실험이다.** Pragmatist 제안: 지금 버너 지갑 만들고 손으로 3건 참여해 시계를 시작 (코드 0줄, 1시간, 위 순서와 **병렬**).
- **Steelman의 "airdropalert 6/9"는 실측 8/9이 맞다** (Moderator 재집계). 앵커가 실제로 막힌 것은 7개 — Polymarket은 다른 다리가 있어 살아남는다.
- 이 council은 단일 모델 5석이라 사실 환각이 공유될 수 있다. 그래서 **판정에 실린 모든 수치는 Moderator가 레포에서 직접 재현했고**, 재현하지 못한 외부 주장은 위에 미검증으로 분리했다.

## Council composition

Round 1: Steelman Advocate, Red Team, Context Keeper (병렬). Round 2 (targeted): First Principles, Pragmatist (병렬). 총 5석 2라운드 + Moderator의 독립 검증 3회.
