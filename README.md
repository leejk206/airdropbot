# airdropbot

`/airdrop` 텔레그램 슬래시 호출 시 큐레이트된 6개 웹 소스를 fetch해 자본=없음 활동을 **마감 임박순** Top 10으로 응답하는 on-demand routine. 사용자가 자연어로 핀한 항목은 출력 상단 `📌 Pinned` 섹션에 매일 노출 (`pinned.yaml` frozen snapshot, 만료 시 자동 정리).

## 상태

- **현재 버전**: v0.6.0 (2026-05-20 봇 디스패치 인프라 도입).
- **봇 디스패치**: cron + Claude Code subprocess + Telegram 채널 단방향 broadcast. spec: `docs/specs/2026-05-20-bot-dispatch-design.md`, plan: `docs/plans/2026-05-20-bot-dispatch-v1.md`.
- **외부 셋업**: BotFather 토큰 + 채널 + cron 항목. `docs/DEPLOY.md` 참고.
- **사용 모델**: 사용자가 채널 구독, daily 1회 자동 broadcast. /airdrop 명령 없음 (채널 단방향).
- **pin 명령**: 소유자가 Claude CLI 자연어 입력 → `prompts/airdrop_pin.md` routine 트리거.

## 동작

`/airdrop` 텔레그램 슬래시 호출 시 실행되는 on-demand routine. 24/7 데몬 없음.

1. 사용자가 텔레그램 봇한테 `/airdrop` 입력
2. routine 워크스페이스에서 Claude 가:
   - `sources.yaml` 로드 (큐레이트된 에어드롭 사이트 6개)
   - 6개 URL을 `WebFetch` 병렬 호출 → 활동 후보 추출 (펀딩·VC·리서치 카운트 포함)
   - 자본 deploy 요구 항목 hard exclude → 통과 항목에 `[비용없음]` `[딸각]` 태그 부착
   - **마감 임박순** 정렬 + dedupe → top 10 한국어 plain text 출력
   - `pinned.yaml` 로드 → 만료 자동 정리 → 활성 핀의 snapshot을 출력 상단에 노출
3. stdout이 텔레그램 응답으로 전달됨

### 출력 row 포맷 (v0.5)

```
1. <프로젝트명> [비용없음][딸각] · <활동유형> · 시간=<...>
   백킹: <VC1 · VC2> · 펀딩 $<X.XM>
   리서치: <N>건                          (페이지에 명시된 경우만)
   할 일: ...
   마감: <YYYY-MM-DD 또는 미정>
   출처: <URL>
```

자세한 포맷·필터·정렬 규칙은 `prompts/airdrop_digest.md` §3, §5.

### 핀 (pinned daily)

사용자가 `/airdrop` 결과를 보고 자연어로 핀 명령을 내리면, 그 항목이 `pinned.yaml`에 박제되어 매 /airdrop 출력의 `📌 Pinned` 섹션에 노출된다. LLM이 다시 검색하지 않는다.

- 추가: `1번 daily` / `Citrea daily 7일` / `Unicity daily 영구`
- 만료: default 30일. `YYYY-MM-DD까지`, `N일`, `영구` 표현 지원. `TGE까지`는 v1 미지원.
- 제거: `Citrea 빼` / `1번 unpin`
- 만료 도달 시 다음 /airdrop에서 자동 삭제.

routine prompt: `prompts/airdrop_pin.md`. 데이터: `pinned.yaml`.

## LLM 비용

추가 비용 **$0**. routine 자체가 본인 Claude Code 구독으로 동작. routine 의 Claude 가 fetch + 분석 모두 처리 — 별도 LLM subprocess 호출 없음.

## 설정 파일

- `sources.yaml` — fetch할 URL + role + note. role enum: `primary | backing-data | low-effort | catalog | official`. 변경 후 `pytest tests/test_sources_schema.py` 로 검증.
- `pinned.yaml` — 사용자 핀 데이터(frozen snapshot). 자연어 명령으로 추가/제거. 변경 후 `pytest tests/test_pinned_schema.py`로 검증.
- `prompts/airdrop_pin.md` — pin/unpin routine instruction.
- `prompts/airdrop_digest.md` — routine instruction. ROI 가중치 튜닝은 여기서.

## 개발

```bash
python3.12 -m venv .venv
.venv/bin/pip install -e '.[dev]'
.venv/bin/pytest -v
```

## Smoke test 체크리스트

`/airdrop` 1회 실행 후 사람 눈으로 다음 항목 확인:

- [ ] 6개 URL 중 5개 이상 성공 fetch (Skipped 섹션 확인)
- [ ] top 10 출력 형식이 `prompts/airdrop_digest.md` 가이드와 일치
- [ ] 마감 임박 또는 백커 강한 항목이 상위에 잡힘
- [ ] "Skipped / excluded" 섹션 존재
- [ ] /airdrop 호출 시 pinned.yaml 없거나 `pins: []`이면 기본 출력
- [ ] "1번 daily" 명령 후 pinned.yaml 갱신되고 다음 /airdrop에 📌 Pinned 섹션 노출
- [ ] 만료 지난 핀이 다음 /airdrop에서 자동 제거 + Skipped에 "📌 만료 자동 정리" 한 줄
- [ ] "Citrea 빼" 명령 후 다음 /airdrop에서 Citrea 핀 사라짐
- [ ] pinned.yaml 일부러 손상시 → 핀 섹션 생략 + Skipped에 ⚠️ 경고
