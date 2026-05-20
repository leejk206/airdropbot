# Deploy / Setup — airdropbot v1

## 1. BotFather에서 봇 생성

1. Telegram에서 [@BotFather](https://t.me/BotFather) 대화 시작.
2. `/newbot` → 표시 이름(예: "Airdrop Digest KR") + username(예: `airdropbot_kr_bot`) 입력.
3. **봇 토큰 받음** (예: `123456:ABC-DEF...`). 안전한 곳에 보관.

## 2. Telegram 채널 생성

1. Telegram에서 **새 채널 만들기** — Public 권장 (검색 가능, username 핸들 설정 가능).
2. 채널 username 설정 (예: `airdropbot_kr`) → `@airdropbot_kr`로 사용.

## 3. 봇을 채널 admin 추가

1. 채널 → Administrators → Add Admin.
2. 1단계에서 만든 봇 검색해서 추가.
3. 권한: **"Post Messages"만 체크**, 나머지 끄기.

## 4. `.env` 채우기

`~/projects/airdropbot/.env`:

```
TELEGRAM_BOT_TOKEN=123456:ABC-DEF...
TELEGRAM_CHANNEL_ID=@airdropbot_kr
```

권한 제한:
```bash
chmod 600 ~/projects/airdropbot/.env
```

## 5. cron 등록

`crontab -e`로 다음 추가:

```cron
SHELL=/bin/bash
CRON_TZ=Asia/Seoul
PATH=/home/ljk9121/.local/bin:/usr/local/bin:/usr/bin:/bin

0 9 * * * cd /home/ljk9121/projects/airdropbot && set -a && source .env && set +a && .venv/bin/python -m airdropbot.daily >> logs/daily-$(date +\%Y-\%m-\%d).log 2>&1
```

등록 확인:
```bash
crontab -l
```

## 6. 첫 수동 smoke test

cron 기다리지 말고 즉시 1회 실행:

```bash
cd ~/projects/airdropbot
set -a && source .env && set +a
.venv/bin/python -m airdropbot.daily
```

확인:
- Telegram 채널에 daily digest 한 메시지 (또는 split된 여러 메시지) 도착.
- `cache/latest-digest.md` 생성됨.
- `logs/daily-<오늘>.log`에 "daily run start" + "cache 저장 완료" + "Telegram channel post 완료" 라인.

## 7. Pin 명령 사용법 (소유자 본인)

채널은 단방향이므로 텔레그램에서 pin 명령 불가. 대신:

1. `~/projects/airdropbot`에서 `claude` (Claude Code CLI) 세션 열기.
2. 자연어로 입력: `Citrea daily 영구로 핀해줘` / `Unicity 빼` / `1번 daily` 같이.
3. Claude가 `prompts/airdrop_pin.md` routine 따라 `pinned.yaml` 갱신.
4. 다음 daily broadcast 9시에 핀 섹션 반영.

## 8. 디버깅

- **routine 결과만 보고 싶음** (Telegram post 없이): `.venv/bin/python -c "from airdropbot.claude_runner import run_digest_routine; from pathlib import Path; print(run_digest_routine(workspace=Path.cwd(), prompt_path=Path('prompts/airdrop_digest.md')))"`
- **로그 따라가기**: `tail -f logs/daily-$(date +%Y-%m-%d).log`
- **수동 send 테스트**: `.venv/bin/python -c "from airdropbot.telegram_post import post; post('test from bot')"`
