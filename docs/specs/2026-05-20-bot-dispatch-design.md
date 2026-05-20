# 봇 디스패치 인프라 v1 — 디자인

**날짜**: 2026-05-20
**범위**: airdropbot v1 봇 인프라 (디스패치/스케줄/Telegram broadcast). 기존 routine prompts·데이터(`prompts/*.md`, `sources.yaml`, `pinned.yaml`)는 그대로 활용.
**다음 단계**: 본 spec 사용자 승인 후 implementation plan 작성 (writing-plans skill).

## 1. 사용 모델 (확정)

- **공유 봇** — open access. 사용자 채널 구독 형태.
- **Daily 1회 routine 실행** — 모든 사용자에게 동일한 결과 broadcast. user-specific 분기 없음.
- **인터페이스 = Telegram 채널** — 1:N 단방향. 봇이 채널 admin으로 daily post.
- **pin 명령** = 사용자(소유자) 본인이 Claude CLI 세션에 자연어로 입력 → 기존 `prompts/airdrop_pin.md` routine 트리거. 봇은 pin 명령 못 받음.
- **TGE 처리** — 봇 미관여. 사용자가 외부 Claude 세션으로 TGE 리서치 후 수동 unpin.
- **실행 환경** — 본인 PC (WSL2) + cron, best-effort. PC 꺼지면 그날 skip.

## 2. 아키텍처

### 디렉토리 구조

```
airdropbot/
├── .env                          # TELEGRAM_BOT_TOKEN, TELEGRAM_CHANNEL_ID
├── src/airdropbot/
│   ├── __init__.py
│   ├── daily.py                  # 진입점: `python -m airdropbot.daily`
│   ├── claude_runner.py          # Claude Code subprocess wrapper
│   └── telegram_post.py          # Telegram sendMessage HTTP wrapper
├── prompts/                      # (기존) routine prompts — 변경 없음
├── sources.yaml, pinned.yaml     # (기존) routine 데이터
├── cache/
│   └── latest-digest.md          # 최근 daily 실행 결과 (pin routine이 참조)
└── logs/
    └── daily-YYYY-MM-DD.log
```

### 컴포넌트 책임

| 모듈 | 책임 | 공개 인터페이스 |
|------|------|---------------|
| `daily.py` | 오케스트레이션: routine 실행 → cache 저장 → channel post → log | `python -m airdropbot.daily` |
| `claude_runner.py` | Claude Code subprocess 호출, stdout 회수, exit code/timeout 분류 | `run_digest_routine() -> str` (markdown) |
| `telegram_post.py` | Telegram sendMessage HTTP POST. 4096자 초과 자동 split. retry 1회. | `post(text: str) -> None` |

### 외부 의존

- `requests` (Telegram API HTTP)
- `python-dotenv` 또는 `os.environ` 수동 로드 — **후자 채택** (dep 최소화). cron에서 `set -a; source .env; set +a` 패턴.
- Python 표준 라이브러리만 외 추가 dep 없음.

### 데이터 플로우

**Daily 실행 (cron 09:00 KST)**:

```
cron → python -m airdropbot.daily
  1. claude_runner.run_digest_routine()
       → subprocess: claude --print --dangerously-skip-permissions
                    --add-dir ~/projects/airdropbot
       prompt: prompts/airdrop_digest.md 내용을 stdin/인자로 전달
       → stdout markdown 수집
  2. cache/latest-digest.md ← atomic write (tmp → rename)
  3. telegram_post.post(markdown)
       → POST https://api.telegram.org/bot<TOKEN>/sendMessage
         {chat_id: TELEGRAM_CHANNEL_ID, text: markdown}
  4. logs/daily-YYYY-MM-DD.log에 결과/오류 기록
```

**Pin 명령 (사용자 자연어, Claude CLI 세션)**:

```
사용자 → Claude CLI → "Citrea daily 영구로 핀해줘"
Claude:
  1. prompts/airdrop_pin.md 참조
  2. cache/latest-digest.md 참조 (직전 broadcast = "답장 대상 본문" 역할)
  3. pinned.yaml atomic update
  4. 응답 1-2줄 (`📌 Citrea 핀 — 만료: 영구`)
```

**핵심**: pin routine은 봇 디스패처 의존 제거. `cache/latest-digest.md`가 텔레그램 reply 본문 역할 대체. `prompts/airdrop_pin.md`의 "답장 대상 메시지 본문" 입력 출처 명시 갱신 필요.

## 3. 에러 처리

| 실패 지점 | 동작 |
|----------|------|
| Claude subprocess timeout/non-zero exit | log에 stderr 기록 → post skip. cache 안 덮어씀 (기존 cache 유지). 다음 cron 재시도. |
| Claude 출력이 비어있거나 너무 짧음 (<200자) | post skip + log "출력 의심". cache 안 덮어씀. |
| `sources.yaml` / `pinned.yaml` 파싱 실패 | routine 내부에서 처리 (기존 spec). daily.py는 stdout 그대로 전달. |
| Telegram sendMessage 4xx/5xx | log + retry 1회 (1분 대기) → 그래도 실패면 그날 skip. cache는 이미 저장됨. |
| Telegram sendMessage 4096자 초과 | telegram_post가 자동 split (`\n\n` 경계 우선) + 1초 간격 순차 post. |
| 네트워크 전체 down | 모든 단계 fail. log만 남음. 다음날 정상 실행. |

전반: **fail-quiet, log-loud**. 알림/escalation 없음.

## 4. 테스팅

- **기존 yaml schema 테스트 유지**: `tests/test_sources_schema.py`, `tests/test_pinned_schema.py` (14개 통과 중).
- **`telegram_post.py` 단위 테스트**: 4096자 split 로직, boundary, retry, mock `requests.post`.
- **`claude_runner.py` 단위 테스트**: timeout, non-zero exit, 빈 stdout 분기. mock `subprocess.run`.
- **`daily.py` 통합 테스트**: `claude_runner`와 `telegram_post`를 mock → cache 저장·error 분기 검증.
- **수동 smoke 테스트**: `python -m airdropbot.daily` 1회 실행 → 채널에 실제 메시지 확인. Telegram 줄바꿈/한글 깨짐 점검.

## 5. Secrets / 환경변수

`.env` (이미 `.gitignore`):
```
TELEGRAM_BOT_TOKEN=<BotFather 토큰>
TELEGRAM_CHANNEL_ID=@airdropbot_kr 또는 -100xxxxxxxxxx
```

`os.environ`만 사용 (`python-dotenv` dep 없음). cron 항목에서 `.env` 로드:
```cron
SHELL=/bin/bash
CRON_TZ=Asia/Seoul
PATH=/home/ljk9121/.local/bin:/usr/local/bin:/usr/bin:/bin
0 9 * * * cd ~/projects/airdropbot && set -a && source .env && set +a && .venv/bin/python -m airdropbot.daily >> logs/daily-$(date +\%Y-\%m-\%d).log 2>&1
```

- `SHELL=/bin/bash`: cron 기본 sh가 `source` 명령 미지원할 수 있음 → bash 명시.
- `CRON_TZ=Asia/Seoul`: WSL2 cron이 host 시간대 안 따라가는 경우 대비.
- `PATH`: `claude` 바이너리(보통 `~/.local/bin/claude`) cron 환경 PATH에서 못 찾으면 subprocess 실패 → 명시.

## 6. 외부 manual 셋업 (사용자 1회)

1. BotFather에서 봇 생성 → 토큰 받음.
2. Telegram 채널 생성 (public 권장 — 검색 가능, username `@airdropbot_kr` 같은 핸들).
3. 봇을 채널 admin 추가 — 권한 = "Post Messages" 만.
4. `.env` 채우기.
5. `crontab -e`에 항목 등록.

이 단계는 구현 후 별도 `docs/DEPLOY.md`로 안내.

## 7. v1 진입 전 정리

- **`pinned.yaml` 초기화** — 기존 3개 stale 핀(Unicity / dTelecom / heyAura, v0.4 포맷)을 `pins: []`로 비움. v1 봇은 사용자가 의도적으로 핀한 항목만 노출.
- **`prompts/airdrop_pin.md` §5 입력 명세 갱신** — "답장 대상 메시지 본문" 출처를 `cache/latest-digest.md` 로컬 파일로 변경. 봇 라우터 의존 제거.

## 8. v1에서 다루지 않는 것 (의도된 제외)

- 사용자 명령 수신 (`/airdrop`, `/help` 등) — 채널 1:N broadcast 모델에 부합 안 함.
- multi-user state (구독자 목록, 사용자별 pin) — 글로벌 단일.
- TGE 자동 감지/auto-unpin — 사용자 외부 처리.
- 24/7 보장 / missed-run catch-up — best-effort.
- 알림/escalation 채널 — 실패 시 log만.
- 봇 라이브러리 framework (python-telegram-bot 등) — 명령 수신 없어 불필요.

## 9. v0.5 → v0.6 변경 요약

| 영역 | v0.5 | v0.6 (이 spec) |
|------|------|--------------|
| 디스패치 | TBD | cron + subprocess + sendMessage |
| 인터페이스 | 미정 | Telegram 채널 단방향 |
| pin 명령 통로 | "봇 라우터" placeholder | Claude CLI 세션 자연어 |
| Python 코드 | `src/` 비어있음 | `daily.py` / `claude_runner.py` / `telegram_post.py` |
| `pinned.yaml` 상태 | stale 3개 핀 잔존 | `pins: []`로 초기화 |
| 캐시 | 없음 | `cache/latest-digest.md` (pin routine 참조용) |
