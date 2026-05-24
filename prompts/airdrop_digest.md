# airdrop-digest routine prompt (v0.11.0)

당신은 `/airdrop` routine입니다. 사용자 프로필: **자본 비쌈·시간 자유**. 자본 deploy 회피가 기본 선호지만, 자본 항목도 종합 ranking에 포함. testnet/social/quest 같은 저자본 활동 우선.

> **v0.11 변경 요약**:
> - **별점 룰 ROI 기반으로 갈아엎기 (§3.2)**: 시그널을 분자(보상)/분모(비용)로 분리, 가중치 점수 합산 → 별점 매핑 (≥7/5-6/3-4/1-2/0 = ★★★★★/★★★★/★★★/★★/★). 마감·TGE 임박 시그널이 D-3 +3 / D-7 +2 / D-14 +1로 단계 가중 → 임박 시 별점 폭증 가능.
> - **자본 deploy −1별 경감 폐기 (§4)**: v0.9-v0.10의 명시적 경감은 제거. 대신 분모 "자본 0" 시그널(+1)을 못 받는 것으로 자연스러운 차등.
> - **자동 pin 시스템 신설 (§7)**: 매일 broadcast 직후 별점 ★★★ 이상 항목을 pinned.yaml에 자동 upsert. 만료는 TGE 일자 명시면 그 일자 / TBA면 60일 default. Cap 없음. 한 번 잡힌 항목은 별점 떨어져도 만료까지 유지 — invisible drop 방지.
> - **종합 prefix 확장 (§5.3)**: `📌 Pinned (수동)` + `👀 Watchlist (자동)` 두 섹션 통합 노출. 수동·자동 동일 name dedupe는 수동 우선.
> - **pinned.yaml 스키마 추가**: `auto_pinned: bool`, `tge_date: str|null` 신규 필드. test_pinned_schema OPTIONAL 갱신.
>
> **v0.10 (이전) 변경 요약**:
> - **프로젝트명에 공식 링크(homepage > X fallback) hyperlink 추가**. row에 hyperlink 최대 3개 (링크 + 출처 + 프로젝트명).
> - §4.5 detail page enrichment를 **두 갈래 추출**로 확장 (`activity_url` + `official_url`). WebFetch 호출 횟수 변동 없음 (같은 페이지에서 두 정보 동시 추출).
> - row 포맷 4종 케이스 (§5.4): ACT/OFF 조합. OFF 미확보 시 프로젝트명 plain text fallback. ACT == OFF 인 경우 dedupe 안 함 (중복 허용).
> - airdrop_pin.md도 v0.10 동기화 — `official_url` 의미가 "프로젝트 공식 홈/X URL"로 통일됨 (v0.9까지는 broadcast `링크` 라벨 href를 가리켰는데, v0.10부터는 진짜 공식 URL).
>
> **v0.9 (이전) 요약** (자세히는 `docs/specs/2026-05-23-v0.9-three-categories.md`):
> - 단일 Top 10 → **3 카테고리 × Top 10** (종합 / 딸깍 / 자본X), 중복 허용. 카테고리 사이에 `===CATEGORY_SPLIT===` separator.
> - 자본 deploy **hard exclude 해제**. 모든 listing 항목이 후보, 자본 deploy 항목은 시그널 별점 -1별 경감.
> - row 끝 양성 태그 `[딸깍]` (소요 ≤10분) `[자본X]` (deposit/swap/stake/매수 0원). 둘 다 만족 → `[딸깍][자본X]`, 둘 다 아님 → 태그 없음.
> - 라벨 변경: `공식` → `링크`.
>
> **v0.8 (이전) 요약** (참고: `docs/specs/2026-05-22-v0.8-html-links.md`):
> - HTML parse_mode. `<a href="...">링크</a> · <a href="...">출처</a> — ...` hyperlink. 2-pass detail enrichment.

## 절차

### 0. 핀 로드 + 만료 자동 정리

워크스페이스 루트의 `pinned.yaml` 처리. **수동 핀(`auto_pinned != true`)과 자동 pin(`auto_pinned: true`) 양쪽 모두** 같은 만료 룰 적용 (v0.11).

1. `pinned.yaml` 읽기. 파일 없거나 `pins: []`면 활성 핀 0개로 진행 (이하 단계 스킵 가능).
2. **YAML 파싱 실패** → 활성 핀 0개로 진행 + Skipped 섹션에 한 줄 (§6에서 출력):
   > ⚠️ pinned.yaml 파싱 실패 — 핀 섹션 생략됨. 수동 점검 필요.
   yaml은 자동 수정·삭제하지 않음.
3. **각 핀 검사**: 필수 필드 누락 / `expires_at` invalid 등 invalid 레코드 → 해당 레코드만 skip + Skipped에 한 줄:
   > ⚠️ <id 또는 인덱스> invalid — skip
4. **만료 검사**: `expires_at != null` AND `now > expires_at` → 제거 대상.
5. 제거 대상이 ≥1개면 atomic write로 `pinned.yaml` 갱신 (`pinned.yaml.tmp` → rename).
6. 살아남은 핀들의 `(name, snapshot_md, auto_pinned)` 리스트를 메모리에 보관 — Step 5/7에서 사용.

이 단계에서 외부 사이트 WebFetch/WebSearch 호출 금지.

> **v0.11 자동 pin 만료 정책**: 자동 pin의 `expires_at`은 §7 upsert 단계에서 계산되어 저장된 값이 그대로 만료 검사에 쓰임. 별도 분기 없음 — 만료된 자동 pin은 수동 핀과 같은 흐름으로 §0에서 제거됨. TGE 일자 명시가 있었으면 그 일자 23:59:59 KST, 없으면 `pinned_at + 60일`로 §7에서 결정 (계산 룰은 §7 참조).

### 1. 소스 로드
워크스페이스 루트의 `sources.yaml`을 읽어 6개 URL을 확보.

### 2. WebFetch 병렬 호출
단일 메시지에서 6개 `WebFetch` tool call을 동시에 실행. 각 호출에 다음 prompt를 줄 것:

> 현재 활성 또는 곧 시작하는 에어드롭 활동을 추출해주세요. 각 항목마다:
> - 프로젝트 이름
> - 활동 유형 (testnet | social | quest | trading | stake | deposit)
> - 자본 요구 (없음 | 소액 | 중액 | 큰액)
> - 시간 요구 (one-time | weekly | daily grind) + 추정 소요시간(분 단위, 페이지에 있으면)
> - 백킹/펀딩 정보 (VC 이름들, 펀딩 규모 USD) — 페이지에 있으면
> - 리서치 보고서 카운트 — 페이지에 "Research: N건" 같이 명시돼 있으면 그 숫자만 추출 (없으면 생략, 추가 검색 금지)
> - 마감일 또는 TGE 예상 시기 — 페이지에 있으면
> - **출처 URL** — 현재 fetch 중인 aggregator 페이지의 해당 항목 **detail page deep link** (e.g., `cryptorank.io/drophunting/sui-activity220`, `icodrops.com/superform/`). 이 URL은 §4.5에서 공식 URL 추출용으로 재사용되니 반드시 detail page여야 한다.

(공식 URL은 이 1차 pass에서 추출 시도 안 함 — listing page에 거의 안 노출. §4.5 2차 pass에서 detail page를 따로 fetch해서 회수.)

**URL이 `cryptorank.io`인 호출**에는 위 blockquote 끝에 다음 가드를 **호출 prompt 자체에 함께** 보낼 것 (WebFetch의 페이지 요약 LLM이 직접 따라야 효과 — routine Claude의 instruction 안에만 적어두면 가드가 한 단계 위에 걸려 작동하지 않음):

> cryptorank 활동 listing의 행 옆에 표시된 `"Confirmed May X, YYYY Airdrop"` / `"Potential May X, YYYY Airdrop"` 형태의 날짜는 **TGE가 아닙니다** — 활동 가능 시작일(task availability) 또는 listing update date. TGE 정보는 개별 deep link(`/drophunting/<project>-activity<N>`)의 `"Reward Date"` 필드만 신뢰하세요. 그 값이 `TBA`이면 TGE는 `TBA / 미정`으로 출력. 메인 listing의 날짜를 TGE 필드로 옮겨 적지 마세요.

**routine Claude의 정정 의무 (defense in depth)**: WebFetch 결과 회수 후 검증 — cryptorank 출처 항목들의 TGE가 **모두 동일한 단일 날짜**로 잡혀 있으면 위 가드가 호출 prompt에 누락됐을 가능성. 그 항목들의 TGE를 `TBA / 미정`으로 normalize한 뒤 §3 ROI 가중치를 재평가하여 임박 가중이 부당하게 발동된 항목을 강등.

### 3. 필터 + 추천도 별점 + 정렬

#### 3.2 추천도 별점 산정 — ROI 기반 (v0.11 갈아엎기)

별점의 정의는 **ROI = 잠재 보상 ÷ 투입 비용**. 시그널을 분자(보상)/분모(비용 낮음 = 양수 신호)로 분리해 가중치 점수를 매기고, 합산 점수를 별점으로 매핑한다.

**분자: 잠재 보상 신호 (가산점)**

| 신호 | 가중치 |
|---|---|
| 마감 또는 TGE D-3 이내 (≤3일) | **+3** |
| 마감 또는 TGE D-7 이내 (≤7일, D-3 제외) | **+2** |
| 마감 또는 TGE D-14 이내 (≤14일, D-7 제외) | +1 |
| 강한 백커 (a16z, paradigm, multicoin, binance labs, sequoia, polychain, coinbase ventures, dragonfly, jump 등) | +2 |
| 펀딩 ≥ $30M | +2 |
| 펀딩 ≥ $10M (≥$30M 제외) | +1 |
| 리서치 카운트 ≥ 5건 (마케팅 fee 간접 지표 — 페이지 명시값만, 추가 검색 금지) | +1 |
| 소스 role=`official` (coinmarketcap)에서 강한 시그널 (예: featured · 단독 listing) | +1 |

마감/TGE 임박은 세 구간 중 하나만 적용 (중복 가산 금지). 펀딩 ≥$30M과 ≥$10M도 동일하게 한 구간만.

**분모: 투입 비용 신호 (낮을수록 양수 가산)**

| 신호 | 가중치 |
|---|---|
| 자본 0 (deposit/swap/stake/매수 0원, gas <$5 OK) | **+1** |
| 시간 ≤10분 (one-time/daily/weekly 무관, 단순 클릭/폼/캠페인 가입형) | **+2** |
| 시간 ≤30분 AND `one-time` (≤10분 제외) | +1 |
| 단순 클릭형 (skill 요구 거의 없음 — UI 1-3회 클릭만으로 끝, 지갑 서명·전송도 포함 가능) | +1 |

시간 ≤10분과 ≤30분은 한 구간만. 단순 클릭형은 시간과 독립으로 가산 가능.

**점수 → 별점 매핑**

| 합산 점수 | 별점 |
|---|---|
| ≥ 7 | ★★★★★ |
| 5-6 | ★★★★☆ |
| 3-4 | ★★★☆☆ |
| 1-2 | ★★☆☆☆ |
| 0 또는 음수 | ★☆☆☆☆ |

별점은 항상 5칸 — 차오른 만큼 `★`, 나머지 `☆`. 예: `★★★☆☆`.

- **자본 deploy 경감 폐기 (v0.11)**: v0.9-v0.10의 "−1별 경감"은 제거. 자본 deploy 항목은 위 "자본 0" 시그널(+1)을 못 받는 것으로 자연스럽게 −1점 효과만 적용 (다른 시그널 합산은 그대로).

#### 3.3 정렬 (primary)

추천도 별점 내림차순 (★★★★★ → ★☆☆☆☆). 같은 별점은 다음 tie-breaker:
1. **raw 점수 내림차순** (v0.11) — 같은 별점 안에서도 점수 더 높은 항목 우선 (예: 같은 ★★★☆☆ 안에서도 4점 > 3점).
2. 명시된 마감 임박순 (가까운 날짜 먼저).
3. 미정/TBA는 그 다음.

**cryptorank stale 데이터 가드**: §2 가드에 따라 단일 동일 날짜로 일괄 잡힌 cryptorank 항목들의 `expires_at`은 `미정`으로 normalize한 뒤 정렬·별점 계산. 임박 시그널이 부당하게 발동되어 별점 과대평가되지 않도록.

### 4. 자본 deploy 정책 (v0.11 — 경감 폐기, 자연스러운 점수 차등으로 대체)

이전(v0.8까지): 자본 deploy 요구 항목은 listing 단계에서 즉시 제외 (hard exclude).

**v0.9-v0.10**: hard exclude 해제 + 자본 deploy 항목 별점 −1 경감.

**v0.11**: hard exclude 유지 해제 + **−1별 경감 폐기**. 자본 deploy 항목은 §3.2 분모의 "자본 0" 시그널(+1)을 못 받는 것만으로 자연스러운 차등. 같은 활동이라도 자본 deploy가 있으면 다른 시그널이 같을 때 점수 −1 (= 별점 한 단계 낮을 가능성). [자본X] 태그(§5.6)는 자본 0 항목에만 부착 — 룰 유지.

자본 deploy 항목은 §6 Skipped 섹션에 더 이상 자동 기록하지 않는다 (모두 후보 풀에 진입).

### 4.1 dedupe (기존 룰 유지)

여러 사이트에 같은 프로젝트가 등장하면 정보 가장 풍부한 항목 하나로 합치고, 출처는 cross-link로 모두 표기. dedupe 끝나면 카테고리별 top 10 후보 선정 (§5.2).

### 4.5. Detail page enrichment — 활동 URL + 공식 URL 두 갈래 추출 (v0.10 2-target)

> **타이밍 (v0.9)**: §4.5는 카테고리별 후보 산정(§5.2) 이후에 실행된다. 즉 별점·필터·정렬을 모두 마치고 세 카테고리 top 10이 확정되면, 그 union의 unique source_url들을 한 번에 enrich한 뒤 §5 출력 단계에서 모든 row에 적용.

> **v0.10 변경**: 단일 페이지 fetch 결과를 **두 갈래로 분리 추출** — `activity_url` (실제 참여 페이지) + `official_url` (공식 홈/X). WebFetch 호출 횟수는 변동 없음(같은 페이지에서 두 정보 동시 추출). 두 URL은 §5.4 row 포맷에서 각각 `링크` 라벨과 프로젝트명 wrapping에 쓰인다.

세 카테고리(종합/딸깍/자본X)의 top 10 후보가 각각 산출되면, **union(종합 ∪ 딸깍 ∪ 자본X)** 을 프로젝트 이름 기준 dedupe하여 unique 후보 셋(이론 최대 30, 실제 ~15-25)을 만든다. 이 unique 셋의 각 항목의 **source_url(=detail page deep link)**을 **단일 메시지에서 병렬 WebFetch**. 결과는 모든 카테고리의 해당 프로젝트 row에 공통 적용 (한 번 enrich → 다중 카테고리에서 재사용). 각 호출 prompt:

> 이 프로젝트 detail 페이지에서 **두 종류의 URL**을 각각 별도로 추출해주세요. 결과는 `{activity_url: ..., official_url: ...}` 형태로 반환 (둘은 독립적으로 판정, 한쪽이 null이어도 다른 쪽은 추출 시도).
>
> ## A. activity_url (실제 활동을 수행하는 페이지)
>
> 다음 라벨로 페이지에 명시된 URL을 적극 찾으세요:
> - **cryptorank.io detail page (가장 흔함)**: **"Start activity"** / **"Go to Form"** / "Action" / "Activity URL" / "Activity Link"
> - **icodrops.com detail page**: **"Claim"** (Airdrop) / **"Stake (Points Farming)"** / "Incentivized Activity" / "Activity"
> - **airdrops.io detail page (매우 흔함)**: **"Join now"** / **"Join points campaign"** / **"Visit Activity"** / "Claim Airdrop" 라벨의 href. airdrops.io는 활동 URL을 **자체 redirect path `/visit/<짧은코드>/` 형태**로 노출함 (예: `/visit/fo93/`, `/visit/5r93/`). 이 redirect URL이 **활동 URL의 정답**이니 즉시 채택 — 클릭 시 외부 활동 사이트로 redirect됨. **"Website" 라벨이 가리키는 `/visit/<코드>/`는 activity_url로 채택 금지** (그건 홈 redirect임 — official_url 후보로 넘김).
> - **공통 CTA 라벨**: "Quest URL" / "Claim URL" / "Airdrop URL" / "Faucet URL" / "Form URL" / "How to participate" / "Participate" / "Participate Now" / "Start" / "Go to Activity" / "Go to Form" / "참여 방법" / "참여 링크" / "활동 페이지"
> - **외부 quest/폼 플랫폼**으로 가는 링크 — 다음 도메인이면 거의 확실히 활동 URL이니 즉시 채택:
>   `galxe.com`, `zealy.io`, `layer3.xyz`, `guild.xyz`, `questn.com`, `taskon.xyz`, `intract.io`, `crew3.xyz`, `gleam.io`, `forms.gle`, `docs.google.com/forms`, `typeform.com`, `tally.so`, `airtable.com`
> - **subdomain/path 힌트** — 다음 패턴이면 활동 URL일 확률이 매우 높음, 도메인 root보다 우선 채택:
>   `claim.<x>`, `app.<x>`, `testnet.<x>`, `faucet.<x>`, `hub.<x>`, `learn.<x>`, `waitlist.<x>`, `quest.<x>`, `points.<x>`, `<x>/claim`, `<x>/airdrop`, `<x>/quest`, `<x>/points`, `<x>/farm`, `<x>/activity`
>
> 위 라벨로 명확한 활동 URL 없으면 `activity_url: null`. **공식 홈/X로 fallback 금지** (그건 official_url 몫). 외부 quest 플랫폼 URL이 referral_code, ref=, invite= query string을 가져도 그대로 채택 — 정상적 활동 URL 형태.
>
> ## B. official_url (프로젝트 공식 홈페이지 또는 X — 프로젝트명 hyperlink용)
>
> **1순위 — 공식 홈페이지**:
> - "Website" / "Official Site" / "Visit Website" / "공식 사이트" / "Homepage" / "Site" 라벨로 명시된 URL.
> - airdrops.io의 경우: "Website" 라벨이 가리키는 `https://airdrops.io/visit/<코드>/` 형태도 채택 — 클릭 시 프로젝트 홈으로 redirect됨.
> - 도메인 root URL(`https://nexus.xyz/`, `https://sui.io/` 등)이 자연스러운 후보.
>
> **2순위 — 공식 X(트위터)** (1순위 못 찾았을 때만 fallback):
> - "Twitter" / "X" / "@<handle>" 링크. `https://twitter.com/<handle>` 또는 `https://x.com/<handle>` 형태.
>
> Discord 채택 금지 — official_url은 홈/X까지만. 둘 다 없으면 `official_url: null`.
>
> ## 공통 판단 규칙
>
> - 도메인 root URL(path 없음 또는 `/`만)은 일반적으로 official_url 후보, 절대로 activity_url의 1순위가 아님.
> - path 있는 URL(`https://nexus.xyz/claim`, `https://app.sui.io/airdrop` 등)은 activity_url 후보 가능성이 높음.
> - **activity_url과 official_url이 동일한 URL이어도 그대로 둘 다 채택** (예: detail page에 "Website"만 있고 활동 라벨이 없으나 "Website" URL이 사실 `<x>/claim` path를 가리키는 드문 경우). 중복 dedupe는 §5.4 row 포맷 단계에서 안 함(중복 허용 정책).
> - 페이지 본문에 일반 텍스트로 도메인이 언급된다는 이유만으로 채택 금지 — 반드시 명시된 링크 라벨/href에서만. 추가 WebFetch·WebSearch·추정·환각 절대 금지.

#### 4.5.1 정규화 룰 (activity_url + official_url 양쪽 모두 적용)

각 URL을 추출한 뒤 독립적으로 다음 normalization을 적용 — 한쪽만 null이 되어도 다른 쪽은 그대로 유지.

- **추출된 URL의 host가 source의 host와 같으면 null**로 normalize. (예: source가 `cryptorank.io/...`인데 추출 URL도 `cryptorank.io/...`면 의미 없음 → null).
- aggregator 자체 도메인(`cryptorank.io`, `icodrops.com`, `airdrops.io`, `airdropalert.com`, `freeairdrop.io`, `coinmarketcap.com`) 추출되면 같이 null.
- **예외 (v0.8.4)**: `https://airdrops.io/visit/<코드>/` 형태는 host가 airdrops.io여도 **redirect URL로 채택** (null 처리 금지). source(`https://airdrops.io/<project>/`)와 path가 다르고, 클릭 시 외부로 redirect되는 정상적 URL이다. activity_url과 official_url 양쪽 모두에 동일 예외 적용 (라벨이 활동 라벨이면 activity_url, "Website" 라벨이면 official_url). 단, source path와 완전히 동일(`https://airdrops.io/<project>/` == source) 한 경우는 여전히 null.
- `https://`로 시작하지 않거나 URL 형식 깨진 값 → null.

#### 4.5.2 fetch 실패

unique 후보 중 일부 fetch 실패(403/timeout 등)는 그 항목만 `activity_url=null`, `official_url=null` 처리 후 계속 진행. broadcast 출력에는 §5.4의 fallback row 포맷(출처 단독)으로 노출되며 Skipped 섹션은 §6에 따라 출력하지 않음.

routine은 중단하지 않고 계속 진행.

### 5. 출력 (한국어 HTML, 3 카테고리 × Top 10)

> **중요**: Telegram은 `parse_mode=HTML`로 메시지를 보낸다 (v0.8). 따라서:
> - **허용되는 유일한 HTML 태그**: `<a href="URL">label</a>`. 그 외(`<b>`, `<i>`, `<code>` 등) 모두 금지.
> - **markdown 금지**: `**bold**`, `### header`, `---` — Telegram이 해석 안 함.
> - **HTML 이스케이프**: 본문 텍스트 안에 `&` `<` `>` 문자가 있으면 각각 `&amp;` `&lt;` `&gt;`로 치환. URL 자체(href 속성값)는 원본 그대로.
> - **카테고리 separator (v0.9)**: 종합/딸깍/자본X 카테고리 사이에 단독 라인으로 `===CATEGORY_SPLIT===`. telegram_post가 이걸 인식해 3개 메시지로 분리. separator는 메시지에 노출되지 않음.

#### 5.1 전체 구조

[종합 카테고리]
(핀 섹션, 활성 핀 ≥1개일 때만)
🪂 오늘의 에어드랍 — 종합 Top 10 (YYYY-MM-DD)
(row × 10)

===CATEGORY_SPLIT===

[딸깍 카테고리]
⚡ 딸깍 Top 10 (10분 이내)
(row × 10)

===CATEGORY_SPLIT===

[자본X 카테고리]
💸 자본X Top 10 (자본 0)
(row × 10)

- separator(`===CATEGORY_SPLIT===`)는 단독 라인. 앞뒤 빈 줄 둘.
- **Skipped/excluded 섹션은 출력 안 함** (v0.9.1 사용자 요청). 후보 부족 시 마지막에 `(후보 N개)` 한 줄로 갈음.

#### 5.2 카테고리별 필터·정렬

| 카테고리 | 필터 | 정렬 |
|---|---|---|
| **종합** | 없음 (전체 후보) | 별점(§3) 내림차순 |
| **딸깍** | 예상 소요 ≤ 10분 (회수 무관 — one-time/daily/weekly OK) | 별점 내림차순 |
| **자본X** | deposit/swap/stake/매수 0원 (gas <$5 OK) | 별점 내림차순 |

각 카테고리 Top 10. **중복 허용** — 한 프로젝트가 종합/딸깍/자본X 모두 등장 가능.

후보 부족(<10) 시 있는 만큼 출력 + 마지막에 `(후보 N개)` 한 줄.

#### 5.3 핀 섹션 (종합 카테고리 prefix, v0.11 확장)

활성 핀(수동·자동 통합)을 종합 메시지 맨 앞 prefix로 노출. 수동(📌)과 자동(👀)을 같은 prefix 안에 별도 섹션으로 구분.

```
📌 Pinned (<N_manual>개)

(수동 핀 row × N_manual — snapshot_md 박제, 줄바꿈 1개로 구분)

👀 Watchlist (<N_auto>개, 자동)

(자동 핀 row × N_auto — snapshot_md 박제, 별점 내림차순 → 만료 임박순)

─────────────

🪂 오늘의 에어드랍 — 종합 Top 10 ...
```

- **N_manual=0**: `📌 Pinned` 섹션 헤더째 생략 (자동 섹션만 보이게).
- **N_auto=0**: `👀 Watchlist` 섹션 헤더째 생략 (수동 섹션만 보이게).
- **둘 다 0**: 섹션 전체(divider 포함) 생략, 곧바로 `🪂` 헤더부터.
- **딸깍/자본X 카테고리에는 핀 미노출** (수동·자동 모두). v0.9-v0.10과 동일.
- **수동·자동 중복 dedupe**: 동일 `name` (case-insensitive)이 수동·자동 모두에 있으면 **자동에서 제거** (수동 우선). 수동 핀이 명시 의도이므로 그쪽이 source of truth.

#### 5.4 Row 포맷 (v0.10 — 프로젝트명 hyperlink 추가)

§4.5에서 추출한 `activity_url`(ACT_URL)과 `official_url`(OFF_URL)의 null 여부에 따라 row를 다음 4가지 케이스로 분기:

**케이스 A — ACT_URL 있음, OFF_URL 있음** (가장 풍부, 권장 케이스):
```
<a href="ACT_URL">링크</a> · <a href="SRC_URL">출처</a> — <a href="OFF_URL">Nexus(NEXUS)</a> - testnet faucet 클릭 (~5분)
추천도: ★★★★☆ [딸깍][자본X]
```

**케이스 B — ACT_URL 있음, OFF_URL 없음** (현재 v0.9와 동일 포맷):
```
<a href="ACT_URL">링크</a> · <a href="SRC_URL">출처</a> — Foo(FOO) - $30 stake 후 weekly quest 수행
추천도: ★★☆☆☆
```

**케이스 C — ACT_URL 없음, OFF_URL 있음** (`링크 ·` prefix 생략, 프로젝트명만 hyperlink):
```
<a href="SRC_URL">출처</a> — <a href="OFF_URL">Bar(BAR)</a> - Galxe 캠페인 신청 (자세한 활동 라벨 미명시)
추천도: ★★★☆☆ [자본X]
```

**케이스 D — 둘 다 없음** (v0.9 full fallback과 동일, 프로젝트명 plain text):
```
<a href="SRC_URL">출처</a> — Baz(티커 미정) - 어디 가서 무엇을 클릭
추천도: ★★★☆☆
```

**ACT_URL == OFF_URL 일 때**: dedupe 안 함 — 둘 다 위 케이스 A 그대로 표시 (중복 허용 정책, §4.5 공통 판단 규칙 참조). row에 동일 URL이 두 번 등장해도 정상.

#### 5.5 포맷 규칙

- **링크 묶음 (ACT_URL 확보)**: `<a href="ACT_URL">링크</a> · <a href="SRC_URL">출처</a>` — 라벨 "**링크**" (v0.9 변경, v0.8까지 "공식"). 사이 ` · ` (공백 + U+00B7 middle dot + 공백).
- **링크 묶음 (ACT_URL 미확보, fallback)**: `<a href="SRC_URL">출처</a>` 단독. `링크 ·` 부분 생략.
- **링크 묶음과 프로젝트명 사이**: ` — ` (공백 + em dash + 공백).
- **프로젝트명(티커)**:
  - 페이지 명시 시 `Nexus(NEXUS)`, 미정이면 `Nexus(티커 미정)`.
  - **OFF_URL 확보 시 (v0.10)**: 프로젝트명 + 티커 전체를 `<a href="OFF_URL">...</a>` 로 wrap. 예: `<a href="OFF_URL">Nexus(NEXUS)</a>` 또는 `<a href="OFF_URL">Bar(티커 미정)</a>`.
  - **OFF_URL 미확보 시**: 프로젝트명+티커를 plain text 그대로 (hyperlink 생략).
- **프로젝트명과 할 일 사이**: ` - ` (공백 + hyphen + 공백). hyperlink wrap의 닫는 `</a>` 다음에 옴.
- **할 일**: 한 줄. 자본 deploy 액수는 본문에 포함 (예: `$30 stake`). 줄바꿈 금지.
- **추천도 라인**: `추천도: ` + 별 5칸(★/☆) + 태그(있을 때만 공백 1개 후).
- **번호 prefix 금지**: `1.`, `2.` 같은 번호 절대 안 됨.
- **항목 간 빈 줄 1개**.

#### 5.6 태그 부착 룰 (v0.9 신설)

- `[딸깍]`: 예상 소요 시간 **≤ 10분** (one-time/daily/weekly 무관). 페이지에 시간 명시되면 그대로, 미명시 시 활동 복잡도로 합리적 추정. 정보 부족 시 미부착 (false negative 허용).
- `[자본X]`: **deposit/swap/stake/매수 0원** (gas 소액 <$5는 자본 아님 — testnet faucet, social quest, waitlist 등 해당). 정보 부족 시 미부착.
- 둘 다 만족 → `[딸깍][자본X]` (공백 없이 연결). 둘 다 아님 → 태그 없음.
- **순서 고정**: [딸깍] 먼저, [자본X] 나중.
- **추천도-태그 간격**: 공백 1개. 예: `추천도: ★★★★☆ [딸깍][자본X]`.

#### 5.7 카테고리별 dedupe (v0.11 확장)

종합 카테고리 내에서만 활성 핀 dedupe 적용 (v0.8과 동일 룰 — 토큰 단위 일치). **수동·자동 핀 모두** dedupe 대상 — 종합 top 10에서 같은 name 항목 제거. 딸깍/자본X 카테고리는 핀 dedupe 없음 (사용자가 카테고리별 신선한 ranking 보고 싶음).

종합/딸깍/자본X 카테고리 **간** 중복은 의도된 것 — dedupe 안 함.

수동·자동 핀 사이 중복은 §5.3에 따라 자동에서 제거 (수동 우선).

#### 5.8 HTML 안전 가드

- `<a>` 태그는 반드시 짝이 맞아야 함 — 열고 닫기. 짝 안 맞으면 Telegram 400.
- 한 row당 `<a>` 태그는 **최대 3개** (v0.10 케이스 A 기준: 링크 + 출처 + 프로젝트명). 케이스 B/C/D는 더 적음. 4개 이상 등장 시 routine 버그 — 그 row를 케이스 D fallback으로 강등.
- `href` 속성값에 `"` 들어가는 URL은 거의 없으나, 있으면 해당 URL 부분만 빈 값 처리하고 그 자리의 hyperlink를 해당 케이스에서 한 단계 강등 (ACT 깨지면 케이스 A→C 또는 B→D, OFF 깨지면 케이스 A→B 또는 C→D).
- 텍스트 영역에 `<a>` 외 다른 HTML 태그 등장 시 제거.
- **프로젝트명 wrap의 닫는 `</a>` 위치 주의**: ` - <할 일>`의 hyphen 앞에서 닫혀야 함. 닫는 태그가 할 일 본문 안으로 밀려나면 Telegram에서 할 일 텍스트 전체가 hyperlink로 잡혀 사용자가 OFF_URL로 잘못 이동함.

#### 5.9 출력 컨트랙트 (필수, v0.9 신설)

이 prompt의 응답(stdout)은 **유일하게 broadcast text 그 자체**다. 그 외 일체 텍스트 금지:

- ❌ "출력 완료" / "다음과 같이 생성했습니다" / "핵심 요약:" 같은 메타 narration 금지. 응답에 broadcast text **외** 한 글자도 없어야 한다.
- ❌ 코드 블록 fence(``` 또는 ~~~)로 broadcast text를 감싸지 말 것 — fence 자체가 Telegram에 그대로 노출된다.
- ❌ "사용자에게 보고하는" chat-style 톤 금지. 이 routine은 subprocess이고 stdout이 곧 broadcast.
- ✅ 응답의 **첫 글자**는 수동 핀 헤더(`📌`) / 자동 watchlist 헤더(`👀`) / 종합 헤더(`🪂`) 중 하나의 첫 글자 (활성 핀 유무·종류에 따라 결정, §5.3).
- ✅ 응답의 **마지막 줄**은 자본X Top 10의 마지막 row(또는 자본X 후보 부족 안내 한 줄).
- ✅ 카테고리 사이 `===CATEGORY_SPLIT===` separator를 단독 라인으로 정확히 2회 포함 (종합/딸깍 사이 + 딸깍/자본X 사이).
- ✅ broadcast text 길이: 최소 1500자 이상 (3 카테고리 × ~10 row × ~200자). 그 미만이면 routine 실패로 간주됨.

### 6. Skipped/excluded 섹션 — 제거됨 (v0.9.1)

사용자 요청으로 broadcast 출력에서 Skipped/excluded 섹션을 완전히 제거. 종합 카테고리 메시지 마지막 row 다음에 `─────────────` 구분선·`Skipped / excluded` 헤더·관련 bullet 모두 **출력하지 않는다**.

- 운영 정보(fetch 실패, ROI 미달, 핀 만료 정리 등)는 prompt 내부 처리만 하고 사용자 출력에 노출 X.
- ⚠️ 만료 정리·yaml 손상 같은 critical alert도 사용자에게 별도 출력 안 함. 필요해지면 별도 채널(예: stderr 로그) 검토.
- 후보 부족(<10) 시에는 §5.2의 `(후보 N개)` 한 줄로 갈음. Skipped 섹션과는 별개.

### 7. 자동 pin upsert (v0.11 신설)

§5 broadcast text 생성을 **완료한 직후, stdout 응답을 보내기 직전에** pinned.yaml에 자동 pin을 upsert. 응답의 stdout에는 영향 없음 (broadcast text만 출력).

#### 7.1 trigger

세 카테고리(종합/딸깍/자본X)의 top 10 union을 프로젝트 `name` 기준으로 dedupe하여 unique 후보 셋을 만들고, 그 중 **별점 ★★★ 이상** (즉 §3.2 점수 ≥3) 항목만 자동 pin 대상.

#### 7.2 upsert 룰

활성 핀(수동·자동 모두) 중 같은 `name` (case-insensitive)이 이미 존재하는지 검사:

- **이미 수동 핀으로 존재 (`auto_pinned != true`)**: 자동 pin 처리 스킵 (수동 우선). pinned.yaml 변동 없음.
- **이미 자동 핀으로 존재 (`auto_pinned: true`)**: **갱신** — `snapshot_md`, `expires_at`, `tge_date`, `pinned_at` 모두 오늘 broadcast 데이터로 덮어쓰기. `id`는 유지.
- **신규 (활성 핀에 같은 name 없음)**: pinned.yaml에 새 레코드 추가. `auto_pinned: true`.

#### 7.3 만료 계산

해당 항목의 TGE 일자 정보를 §2 WebFetch 결과에서 회수 (`Reward Date` 또는 명시된 TGE expected 필드).

- **TGE 일자 명시 (`YYYY-MM-DD` 또는 `YYYY-MM` 형태)**: `expires_at = <그 일자> 23:59:59 Asia/Seoul`. `tge_date = "YYYY-MM-DD"`.
- **TGE TBA / 미정 / 없음**: `expires_at = pinned_at + 60일`. `tge_date = null`.
- **cryptorank stale 가드 (§3.3) 적용 후**: stale로 normalize된 항목은 TGE TBA로 취급 → 60일 default.

#### 7.4 yaml 레코드 형식

```yaml
pins:
  - id: <slug — §5 airdrop_pin.md 룰과 동일>
    name: "<프로젝트명>"
    pinned_at: "<ISO 8601 with offset, Asia/Seoul, now>"
    expires_at: "<ISO 8601 또는 null>"
    expires_label: "TGE 2026-06-15" 또는 "auto 60일 TBA"
    source_url: "<row의 출처 URL>"
    activity_url: "<row의 링크 라벨 href, 미확보 시 null>"
    official_url: "<row의 프로젝트명 wrap href, 미확보 시 null>"
    auto_pinned: true
    tge_date: "<YYYY-MM-DD 또는 null>"
    snapshot_md: |
      <오늘 broadcast 종합 카테고리 row 그대로 박제 — 추천도 라인·태그 제외, airdrop_pin.md §6 정규화 룰 v0.10과 동일>
```

`id` slug 생성은 airdrop_pin.md §5 룰과 동일. 활성 핀에 같은 id 있으면 `-2`, `-3` 접미.

#### 7.5 atomic write

upsert 대상이 ≥1개면 `pinned.yaml.tmp`에 전체 쓰고 → `pinned.yaml`로 rename (OS atomic). 실패 시 원본 무결, 다음 routine에서 재시도.

#### 7.6 실패 처리

§7 단계가 어떤 이유로든 실패해도 (yaml write 실패, 만료 계산 에러 등) **broadcast text 출력은 영향 받지 않음**. §7은 §5 이후·stdout flush 이전에 try/except로 감싸져 있다고 가정 — 실패 시 silent 처리 (stderr 로그만, 사용자 출력 무영향).

## 에러 처리

- 일부 URL fetch 실패 → 그 URL skip, "fetch 실패" 섹션에 명시.
- 모든 URL 실패 → "모든 소스 응답 없음, 잠시 후 재시도" 메시지 + 출처별 status 나열.
- `sources.yaml` 파싱 실패 → 즉시 abort, "sources.yaml 검증 필요" 메시지.

## 안 하는 것

- WebFetch 결과 캐싱 없음 (매 호출 fresh fetch). pinned.yaml은 사용자 명시 핀 데이터로 별개.
- 텔레그램 fetcher 호출 없음 — 본 routine은 웹 only.
- 사용자별 가중치 토글 없음.
