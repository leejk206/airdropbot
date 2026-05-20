# airdropbot

큐레이트된 6개 웹 소스를 fetch해 자본=없음 활동을 **마감 임박순** Top 10으로 정리하는 daily airdrop digest bot. cron이 매일 1회 routine을 실행해 Telegram 채널에 자동 broadcast. 사용자가 자연어로 핀한 항목은 출력 상단 `📌 Pinned` 섹션에 매일 노출 (`pinned.yaml` frozen snapshot, 만료 시 자동 정리).

## 상태

- **현재 버전**: v0.6.0 (2026-05-20 봇 디스패치 인프라 도입).
- **봇 디스패치**: cron + Claude Code subprocess + Telegram 채널 단방향 broadcast. spec: `docs/specs/2026-05-20-bot-dispatch-design.md`, plan: `docs/plans/2026-05-20-bot-dispatch-v1.md`.
- **외부 셋업**: BotFather 토큰 + 채널 + cron 항목. `docs/DEPLOY.md` 참고.
- **사용 모델**: 사용자가 채널 구독, daily 1회 자동 broadcast. /airdrop 명령 없음 (채널 단방향).
- **pin 명령**: 소유자가 Claude CLI 자연어 입력 → `prompts/airdrop_pin.md` routine 트리거.

## 동작

cron이 매일 1회 routine 실행 → Telegram 채널에 broadcast (단방향, 사용자 명령 없음). 24/7 데몬 없음.

1. cron 09:00 KST 트리거 → `python -m airdropbot.daily`
2. routine 워크스페이스에서 Claude Code subprocess가:
   - `sources.yaml` 로드 (큐레이트된 에어드롭 사이트 6개)
   - 6개 URL을 `WebFetch` 병렬 호출 → 활동 후보 추출 (펀딩·VC·리서치 카운트 포함)
   - 자본 deploy 요구 항목 hard exclude → 통과 항목에 `[비용없음]` `[딸각]` 태그 부착
   - **마감 임박순** 정렬 + dedupe → top 10 한국어 plain text 출력
   - `pinned.yaml` 로드 → 만료 자동 정리 → 활성 핀의 snapshot을 출력 상단에 노출
3. stdout이 `cache/latest-digest.md`에 저장 + Telegram Bot API `sendMessage`로 채널 broadcast

### 출력 row 포맷

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

채널은 단방향이라 텔레그램에서 pin 명령 못 받음. 소유자 본인이 `~/projects/airdropbot`에서 Claude Code CLI 세션을 열고 자연어로 명령:

- 추가: `1번 daily` / `Citrea daily 7일` / `Unicity daily 영구`
- 만료: default 30일. `YYYY-MM-DD까지`, `N일`, `영구` 표현 지원. `TGE까지`도 표기는 받되 봇은 자동 처리 안 함 (소유자가 외부 Claude 세션으로 TGE 리서치 후 수동 unpin).
- 제거: `Citrea 빼` / `1번 unpin`
- 만료 도달 시 다음 daily broadcast에서 자동 삭제.

Claude는 `prompts/airdrop_pin.md` routine 따라 `cache/latest-digest.md`를 직전 broadcast 컨텍스트로 참조해 `pinned.yaml` atomic update.

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

`python -m airdropbot.daily` 1회 실행 후 (또는 cron 트리거 후):

- [ ] Telegram 채널에 daily digest 메시지 도착 (split된 다중 메시지일 수 있음)
- [ ] `cache/latest-digest.md` 생성·갱신됨
- [ ] `logs/daily-YYYY-MM-DD.log`에 "daily run start" + "cache 저장 완료" + "Telegram channel post 완료" 라인
- [ ] 6개 URL 중 5개 이상 성공 fetch (출력의 Skipped 섹션 확인)
- [ ] top 10 출력 형식이 `prompts/airdrop_digest.md` 가이드와 일치
- [ ] 마감 임박 또는 백커 강한 항목이 상위
- [ ] pinned.yaml `pins: []`이면 핀 섹션 생략, 핀 추가하면 다음 daily에 `📌 Pinned` 노출
- [ ] 만료 지난 핀이 다음 daily에서 자동 제거 + Skipped에 "📌 만료 자동 정리" 한 줄
- [ ] pinned.yaml 일부러 손상 시 → 핀 섹션 생략 + Skipped에 ⚠️ 경고
