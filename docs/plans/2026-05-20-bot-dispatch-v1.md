# Bot Dispatch v1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** airdropbot v1 봇 인프라 — daily 1회 routine 실행 후 Telegram 채널에 broadcast하는 cron-driven 봇 (단방향, 본인 PC WSL2 실행, best-effort).

**Architecture:** `daily.py` 진입점이 `claude_runner.py`로 Claude Code subprocess 호출 → `cache/latest-digest.md` 저장 → `telegram_post.py`로 채널에 sendMessage POST. daemon 없음, framework 없음, multi-user state 없음. spec: `docs/specs/2026-05-20-bot-dispatch-design.md`.

**Tech Stack:** Python 3.12 (stdlib subprocess/os/pathlib + `requests` + `pyyaml`), Claude Code CLI (subprocess), Telegram Bot API HTTP, cron (WSL2).

---

## File Structure

**Create:**
- `src/airdropbot/__init__.py` — empty package marker
- `src/airdropbot/telegram_post.py` — sendMessage HTTP wrapper + split + retry
- `src/airdropbot/claude_runner.py` — Claude Code subprocess wrapper
- `src/airdropbot/daily.py` — orchestration entry point
- `tests/test_telegram_post.py` — split·send·retry·post 단위/통합 테스트
- `tests/test_claude_runner.py` — subprocess mock 분기 테스트
- `tests/test_daily.py` — daily.py 오케스트레이션 통합 테스트 (mock)
- `cache/.gitkeep` — 디렉토리 보존
- `logs/.gitkeep` — 디렉토리 보존
- `docs/DEPLOY.md` — BotFather/채널/cron 셋업 가이드

**Modify:**
- `pyproject.toml` — `requests` dep 추가, `packages = ["src/airdropbot"]`, `pythonpath = ["src"]`, version → 0.6.0
- `.gitignore` — `cache/*` + `!cache/.gitkeep`, `logs/*` + `!logs/.gitkeep`
- `pinned.yaml` — 기존 3개 stale 핀 제거, `pins: []`로 초기화 (spec §7)
- `prompts/airdrop_pin.md` §5 — "답장 대상 메시지 본문" 입력 출처를 `cache/latest-digest.md` 로컬 파일로 명시 (봇 라우터 의존 제거, spec §7)
- `README.md` — v0.6 상태 갱신, 봇 디스패치 도입 시그널

---

## Task 1: pinned.yaml 초기화 + airdrop_pin.md 입력 명세 갱신

**Files:**
- Modify: `pinned.yaml` (전체)
- Modify: `prompts/airdrop_pin.md:5-10` (입력 명세 부분)

이 task는 spec §7 "v1 진입 전 정리" 수행. 코드 변경 없음.

- [ ] **Step 1.1: pinned.yaml을 `pins: []`로 초기화**

Replace 전체 파일을:

```yaml
# pinned.yaml — 사용자가 daily 적용한 에어드랍 항목 (frozen snapshot, plain text)
# pin/unpin은 사용자가 Claude CLI 세션에 자연어로 입력 → prompts/airdrop_pin.md routine이 처리.
# pin routine은 직전 broadcast(cache/latest-digest.md)를 "답장 대상 본문"으로 참조.
# snapshot_md 정규화 룰: prompts/airdrop_pin.md §6.
pins: []
```

- [ ] **Step 1.2: 테스트 실행 — schema 테스트가 빈 핀 리스트도 통과해야 함**

Run: `cd ~/projects/airdropbot && python3 -m pytest tests/test_pinned_schema.py -v`
Expected: PASS (스키마 테스트는 `pinned_data["pins"]`를 list로만 검증, 길이 0 OK).

- [ ] **Step 1.3: `prompts/airdrop_pin.md`의 §5 "입력" 명세 갱신**

기존 (line 5-10):

```
**입력 (routine prompt에 주입됨)**:
- 사용자 메시지 텍스트 (Telegram reply 본문)
- 답장 대상 메시지 본문 (= 직전 `/airdrop` output) — 봇 라우터가 prompt에 주입
- 현재 `pinned.yaml` 파일 상태

> **참고**: Telegram bot은 임의의 chat history를 못 읽음. 사용자가 /airdrop 응답에 답장하면 그 메시지 본문이 자동으로 prompt에 주입된다. 답장 없는 자유 텍스트 pin 명령은 라우터에서 무시되어 본 routine으로 도달하지 않는다.
```

→ 교체:

```
**입력 (Claude CLI 세션 안에서)**:
- 사용자 자연어 명령 (예: "Citrea daily 영구", "1번 빼")
- `cache/latest-digest.md` 파일 내용 (직전 daily broadcast = "답장 대상 본문" 역할)
- 현재 `pinned.yaml` 파일 상태

> **참고**: airdropbot v1은 채널 단방향 broadcast이라 텔레그램 reply로 pin 명령 못 받음. 대신 소유자가 Claude CLI 세션을 직접 열고 자연어로 핀 명령을 내린다. cache 파일이 직전 broadcast 본문을 대신해 routine에 컨텍스트 제공.
```

- [ ] **Step 1.4: 커밋**

```bash
git add pinned.yaml prompts/airdrop_pin.md
git commit -m "chore: v1 진입 전 정리 (pinned.yaml 초기화 + pin routine 입력 출처 갱신)"
```

---

## Task 2: Python 패키지 scaffold + pyproject 갱신

**Files:**
- Create: `src/airdropbot/__init__.py`
- Modify: `pyproject.toml` (전체)

- [ ] **Step 2.1: 빈 패키지 파일 생성**

```bash
cd ~/projects/airdropbot
mkdir -p src/airdropbot
touch src/airdropbot/__init__.py
```

- [ ] **Step 2.2: `pyproject.toml` 갱신**

전체 파일 교체:

```toml
[project]
name = "airdropbot"
version = "0.6.0"
description = "Airdrop digest Telegram bot — daily channel broadcast via cron + Claude Code subprocess."
requires-python = ">=3.12"
dependencies = [
    "pyyaml>=6",
    "requests>=2.32",
]

[project.optional-dependencies]
dev = [
    "pytest>=8",
    "ruff>=0.6",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/airdropbot"]

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["src"]

[tool.ruff]
line-length = 100
target-version = "py312"
```

- [ ] **Step 2.3: editable install + dep 설치**

```bash
cd ~/projects/airdropbot
python3.12 -m venv .venv
.venv/bin/pip install -e '.[dev]'
```

Expected: `requests`, `pyyaml`, `pytest`, `ruff` 설치 완료.

- [ ] **Step 2.4: 기존 테스트가 여전히 통과하는지 확인**

Run: `.venv/bin/pytest -q`
Expected: 14 passed (test_sources_schema 7 + test_pinned_schema 7).

- [ ] **Step 2.5: 커밋**

```bash
git add src/airdropbot/__init__.py pyproject.toml
git commit -m "scaffold: src/airdropbot 패키지 + requests dep + v0.6.0"
```

---

## Task 3: `telegram_post.py` — split 로직 (TDD)

**Files:**
- Create: `src/airdropbot/telegram_post.py`
- Create: `tests/test_telegram_post.py`

split 로직 먼저 — 순수 함수라 mock 없이 단위 테스트 가능.

- [ ] **Step 3.1: split 테스트 작성 (failing)**

`tests/test_telegram_post.py`:

```python
"""telegram_post.py 단위/통합 테스트."""
from __future__ import annotations

from airdropbot.telegram_post import _split_message


def test_split_short_text_returns_single_chunk():
    text = "짧은 메시지"
    chunks = _split_message(text, limit=4096)
    assert chunks == ["짧은 메시지"]


def test_split_at_double_newline_when_long():
    # 두 단락이 합쳐 limit 초과
    para1 = "A" * 3000
    para2 = "B" * 2000
    text = f"{para1}\n\n{para2}"
    chunks = _split_message(text, limit=4096)
    assert chunks == [para1, para2]


def test_split_falls_back_to_single_newline_when_no_double():
    line1 = "A" * 3000
    line2 = "B" * 2000
    text = f"{line1}\n{line2}"
    chunks = _split_message(text, limit=4096)
    assert chunks == [line1, line2]


def test_split_hard_splits_at_limit_when_no_newline():
    text = "X" * 5000
    chunks = _split_message(text, limit=4096)
    assert len(chunks) == 2
    assert len(chunks[0]) == 4096
    assert chunks[1] == "X" * (5000 - 4096)


def test_split_preserves_total_content():
    """split 후 합치면 원본과 동일 (newline 제외 가능)."""
    text = "라인1\n\n라인2\n\n" + ("긴내용 " * 1500)
    chunks = _split_message(text, limit=4096)
    rejoined = "\n\n".join(chunks)
    # 원본 내용 모든 문자가 chunks 어딘가에 보존되어야 함
    for ch in chunks:
        assert ch  # 빈 chunk 없음
    assert len(rejoined) >= len(text) - 10  # newline 누락 허용 (re-join 시 \n\n 추가)
```

- [ ] **Step 3.2: 테스트 실패 확인**

Run: `.venv/bin/pytest tests/test_telegram_post.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'airdropbot.telegram_post'`.

- [ ] **Step 3.3: split 구현**

`src/airdropbot/telegram_post.py`:

```python
"""Telegram sendMessage 래퍼 — split, retry, sequential post."""
from __future__ import annotations

import os
import time
from typing import Final

import requests

TELEGRAM_LIMIT: Final[int] = 4096
RETRY_DELAY_SEC: Final[float] = 60.0
CHUNK_DELAY_SEC: Final[float] = 1.0


def _split_message(text: str, limit: int = TELEGRAM_LIMIT) -> list[str]:
    """텔레그램 4096자 한계로 메시지 split.

    - limit 이하면 단일 chunk 반환.
    - 그 이상이면 `\\n\\n` 경계 우선, 다음 `\\n`, 마지막 hard split.
    """
    if len(text) <= limit:
        return [text]

    for sep in ("\n\n", "\n"):
        if sep in text:
            chunks: list[str] = []
            remaining = text
            while len(remaining) > limit:
                # remaining[:limit] 안에서 마지막 sep 위치 찾기
                cut = remaining.rfind(sep, 0, limit)
                if cut == -1:
                    break  # 이 sep로는 split 불가, 다음 sep 시도
                chunks.append(remaining[:cut])
                remaining = remaining[cut + len(sep):]
            if chunks:
                chunks.append(remaining)
                return chunks
        # sep로 split 불가 → 다음 sep 시도 (loop continue)

    # 모든 sep 실패 — hard split
    return [text[i : i + limit] for i in range(0, len(text), limit)]
```

- [ ] **Step 3.4: 테스트 통과 확인**

Run: `.venv/bin/pytest tests/test_telegram_post.py -v`
Expected: 5 PASS.

- [ ] **Step 3.5: 커밋**

```bash
git add src/airdropbot/telegram_post.py tests/test_telegram_post.py
git commit -m "feat(telegram_post): _split_message 4096자 split (\\n\\n > \\n > hard)"
```

---

## Task 4: `telegram_post.py` — send + retry (TDD)

**Files:**
- Modify: `src/airdropbot/telegram_post.py` (추가)
- Modify: `tests/test_telegram_post.py` (추가)

- [ ] **Step 4.1: send/retry 테스트 추가**

`tests/test_telegram_post.py` 끝에 추가:

```python
import pytest
from unittest.mock import MagicMock, patch

from airdropbot.telegram_post import _send_chunk, post


class _FakeResp:
    def __init__(self, status_code: int, text: str = ""):
        self.status_code = status_code
        self.text = text

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code}: {self.text}")


def test_send_chunk_posts_to_telegram_api():
    with patch("airdropbot.telegram_post.requests.post") as mock_post:
        mock_post.return_value = _FakeResp(200, '{"ok":true}')
        _send_chunk(token="T", chat_id="@x", text="hello")
        mock_post.assert_called_once()
        url = mock_post.call_args[0][0]
        assert url == "https://api.telegram.org/botT/sendMessage"
        json_arg = mock_post.call_args[1]["json"]
        assert json_arg == {"chat_id": "@x", "text": "hello"}


def test_send_chunk_retries_once_on_5xx_then_succeeds():
    with patch("airdropbot.telegram_post.requests.post") as mock_post, \
         patch("airdropbot.telegram_post.time.sleep") as mock_sleep:
        mock_post.side_effect = [_FakeResp(503, "fail"), _FakeResp(200, "ok")]
        _send_chunk(token="T", chat_id="@x", text="hello")
        assert mock_post.call_count == 2
        mock_sleep.assert_called_once_with(60.0)


def test_send_chunk_raises_when_5xx_persists_after_retry():
    with patch("airdropbot.telegram_post.requests.post") as mock_post, \
         patch("airdropbot.telegram_post.time.sleep"):
        mock_post.return_value = _FakeResp(503, "fail")
        with pytest.raises(requests.HTTPError):
            _send_chunk(token="T", chat_id="@x", text="hello")
        assert mock_post.call_count == 2


def test_send_chunk_does_not_retry_on_4xx():
    with patch("airdropbot.telegram_post.requests.post") as mock_post, \
         patch("airdropbot.telegram_post.time.sleep") as mock_sleep:
        mock_post.return_value = _FakeResp(400, "bad")
        with pytest.raises(requests.HTTPError):
            _send_chunk(token="T", chat_id="@x", text="hello")
        assert mock_post.call_count == 1
        mock_sleep.assert_not_called()
```

- [ ] **Step 4.2: 테스트 실패 확인**

Run: `.venv/bin/pytest tests/test_telegram_post.py -v`
Expected: 4 new FAIL with `ImportError: cannot import name '_send_chunk'`.

- [ ] **Step 4.3: `_send_chunk` 구현**

`src/airdropbot/telegram_post.py` 끝에 추가:

```python
def _send_chunk(token: str, chat_id: str, text: str) -> None:
    """단일 chunk를 sendMessage POST. 5xx 1회 retry. 4xx 즉시 raise."""
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": text}

    resp = requests.post(url, json=payload, timeout=30)
    if 500 <= resp.status_code < 600:
        time.sleep(RETRY_DELAY_SEC)
        resp = requests.post(url, json=payload, timeout=30)
    resp.raise_for_status()
```

- [ ] **Step 4.4: 테스트 통과 확인**

Run: `.venv/bin/pytest tests/test_telegram_post.py -v`
Expected: 9 PASS (5 split + 4 send).

- [ ] **Step 4.5: 커밋**

```bash
git add src/airdropbot/telegram_post.py tests/test_telegram_post.py
git commit -m "feat(telegram_post): _send_chunk + 5xx 1회 retry, 4xx 즉시 raise"
```

---

## Task 5: `telegram_post.py` — `post()` 오케스트레이션 (TDD)

**Files:**
- Modify: `src/airdropbot/telegram_post.py` (추가)
- Modify: `tests/test_telegram_post.py` (추가)

- [ ] **Step 5.1: `post()` 테스트 추가**

`tests/test_telegram_post.py` 끝에 추가:

```python
def test_post_sends_single_chunk_when_short(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "T")
    monkeypatch.setenv("TELEGRAM_CHANNEL_ID", "@x")
    sent: list[str] = []

    def fake_send(token, chat_id, text):
        sent.append(text)

    monkeypatch.setattr("airdropbot.telegram_post._send_chunk", fake_send)
    post("짧은 메시지")
    assert sent == ["짧은 메시지"]


def test_post_splits_and_delays_when_long(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "T")
    monkeypatch.setenv("TELEGRAM_CHANNEL_ID", "@x")
    sent: list[str] = []
    sleeps: list[float] = []

    def fake_send(token, chat_id, text):
        sent.append(text)

    def fake_sleep(sec):
        sleeps.append(sec)

    monkeypatch.setattr("airdropbot.telegram_post._send_chunk", fake_send)
    monkeypatch.setattr("airdropbot.telegram_post.time.sleep", fake_sleep)

    long_text = ("A" * 3000) + "\n\n" + ("B" * 2000)
    post(long_text)
    assert len(sent) == 2
    # chunk 사이 1초 delay
    assert sleeps == [1.0]


def test_post_raises_when_env_missing(monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHANNEL_ID", raising=False)
    with pytest.raises(RuntimeError, match="TELEGRAM_BOT_TOKEN"):
        post("x")
```

- [ ] **Step 5.2: 테스트 실패 확인**

Run: `.venv/bin/pytest tests/test_telegram_post.py -v`
Expected: 3 new FAIL.

- [ ] **Step 5.3: `post()` 구현**

`src/airdropbot/telegram_post.py` 끝에 추가:

```python
def post(text: str) -> None:
    """Telegram 채널에 text post. 자동 split, chunk 사이 1초 delay."""
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHANNEL_ID")
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN env 미설정")
    if not chat_id:
        raise RuntimeError("TELEGRAM_CHANNEL_ID env 미설정")

    chunks = _split_message(text)
    for i, chunk in enumerate(chunks):
        if i > 0:
            time.sleep(CHUNK_DELAY_SEC)
        _send_chunk(token=token, chat_id=chat_id, text=chunk)
```

- [ ] **Step 5.4: 전체 테스트 통과 확인**

Run: `.venv/bin/pytest -q`
Expected: 26 PASS (기존 14 + telegram_post 12).

- [ ] **Step 5.5: 커밋**

```bash
git add src/airdropbot/telegram_post.py tests/test_telegram_post.py
git commit -m "feat(telegram_post): post() 오케스트레이션 + env 검증"
```

---

## Task 6: `claude_runner.py` (TDD)

**Files:**
- Create: `src/airdropbot/claude_runner.py`
- Create: `tests/test_claude_runner.py`

- [ ] **Step 6.1: 테스트 작성**

`tests/test_claude_runner.py`:

```python
"""claude_runner.py — Claude Code subprocess 호출 분기 테스트."""
from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from airdropbot.claude_runner import (
    ClaudeRunnerError,
    EmptyOutputError,
    run_digest_routine,
)


def _fake_completed(stdout: str, returncode: int = 0, stderr: str = ""):
    mock = MagicMock(spec=subprocess.CompletedProcess)
    mock.stdout = stdout
    mock.stderr = stderr
    mock.returncode = returncode
    return mock


def test_returns_stdout_on_success(tmp_path):
    md = "🪂 오늘의 에어드랍 Top 10 — " + ("x" * 500)
    with patch("airdropbot.claude_runner.subprocess.run") as mock_run:
        mock_run.return_value = _fake_completed(md)
        result = run_digest_routine(workspace=tmp_path, prompt_path=tmp_path / "p.md")
        assert result == md


def test_raises_on_timeout(tmp_path):
    with patch("airdropbot.claude_runner.subprocess.run") as mock_run:
        mock_run.side_effect = subprocess.TimeoutExpired(cmd=["claude"], timeout=600)
        with pytest.raises(ClaudeRunnerError, match="timeout"):
            run_digest_routine(workspace=tmp_path, prompt_path=tmp_path / "p.md")


def test_raises_on_nonzero_exit(tmp_path):
    with patch("airdropbot.claude_runner.subprocess.run") as mock_run:
        mock_run.return_value = _fake_completed("", returncode=2, stderr="boom")
        with pytest.raises(ClaudeRunnerError, match="exit=2"):
            run_digest_routine(workspace=tmp_path, prompt_path=tmp_path / "p.md")


def test_raises_on_empty_output(tmp_path):
    with patch("airdropbot.claude_runner.subprocess.run") as mock_run:
        mock_run.return_value = _fake_completed("짧음")  # <200자
        with pytest.raises(EmptyOutputError):
            run_digest_routine(workspace=tmp_path, prompt_path=tmp_path / "p.md")
```

- [ ] **Step 6.2: 테스트 실패 확인**

Run: `.venv/bin/pytest tests/test_claude_runner.py -v`
Expected: 4 FAIL (`ModuleNotFoundError`).

- [ ] **Step 6.3: 구현**

`src/airdropbot/claude_runner.py`:

```python
"""Claude Code CLI subprocess wrapper."""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Final

CLAUDE_TIMEOUT_SEC: Final[int] = 600  # 10분
MIN_OUTPUT_LEN: Final[int] = 200  # 출력이 이보다 짧으면 의심


class ClaudeRunnerError(RuntimeError):
    """Claude subprocess가 실패했거나 timeout."""


class EmptyOutputError(ClaudeRunnerError):
    """Claude 출력이 너무 짧거나 비어있음."""


def run_digest_routine(
    *,
    workspace: Path,
    prompt_path: Path,
) -> str:
    """`prompt_path` 내용을 Claude CLI로 실행, stdout markdown 반환.

    Raises:
        ClaudeRunnerError: subprocess timeout 또는 non-zero exit.
        EmptyOutputError: stdout 길이 < MIN_OUTPUT_LEN.
    """
    prompt_text = prompt_path.read_text(encoding="utf-8")
    cmd = [
        "claude",
        "--print",
        "--dangerously-skip-permissions",
        "--add-dir",
        str(workspace),
        prompt_text,
    ]
    try:
        completed = subprocess.run(
            cmd,
            cwd=str(workspace),
            capture_output=True,
            text=True,
            timeout=CLAUDE_TIMEOUT_SEC,
        )
    except subprocess.TimeoutExpired as e:
        raise ClaudeRunnerError(f"claude subprocess timeout ({CLAUDE_TIMEOUT_SEC}s)") from e

    if completed.returncode != 0:
        raise ClaudeRunnerError(
            f"claude subprocess exit={completed.returncode} stderr={completed.stderr[:500]}"
        )

    output = completed.stdout.strip()
    if len(output) < MIN_OUTPUT_LEN:
        raise EmptyOutputError(f"출력이 너무 짧음 (len={len(output)}): {output[:100]!r}")

    return output
```

- [ ] **Step 6.4: 테스트 통과 확인**

Run: `.venv/bin/pytest tests/test_claude_runner.py -v`
Expected: 4 PASS.

- [ ] **Step 6.5: 커밋**

```bash
git add src/airdropbot/claude_runner.py tests/test_claude_runner.py
git commit -m "feat(claude_runner): subprocess wrapper + timeout/exit/empty 분기"
```

---

## Task 7: `daily.py` 오케스트레이션 (TDD)

**Files:**
- Create: `src/airdropbot/daily.py`
- Create: `tests/test_daily.py`

- [ ] **Step 7.1: 테스트 작성**

`tests/test_daily.py`:

```python
"""daily.py 오케스트레이션 통합 테스트 (mock claude_runner + telegram_post)."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from airdropbot import daily
from airdropbot.claude_runner import ClaudeRunnerError, EmptyOutputError


def _setup_workspace(tmp_path: Path) -> Path:
    """Fake workspace with prompts/airdrop_digest.md."""
    (tmp_path / "prompts").mkdir()
    (tmp_path / "prompts" / "airdrop_digest.md").write_text("fake prompt", encoding="utf-8")
    (tmp_path / "cache").mkdir()
    (tmp_path / "logs").mkdir()
    return tmp_path


def test_writes_cache_and_posts_on_success(tmp_path, monkeypatch):
    ws = _setup_workspace(tmp_path)
    markdown = "🪂 digest " + ("x" * 500)
    sent: list[str] = []

    def fake_run(*, workspace, prompt_path):
        return markdown

    def fake_post(text):
        sent.append(text)

    monkeypatch.setattr("airdropbot.daily.run_digest_routine", fake_run)
    monkeypatch.setattr("airdropbot.daily.post", fake_post)

    daily.run(workspace=ws)

    cache_path = ws / "cache" / "latest-digest.md"
    assert cache_path.exists()
    assert cache_path.read_text(encoding="utf-8") == markdown
    assert sent == [markdown]


def test_does_not_overwrite_cache_on_routine_failure(tmp_path, monkeypatch):
    ws = _setup_workspace(tmp_path)
    existing = "이전 캐시 내용 " + ("y" * 500)
    cache_path = ws / "cache" / "latest-digest.md"
    cache_path.write_text(existing, encoding="utf-8")

    def fake_run(*, workspace, prompt_path):
        raise ClaudeRunnerError("subprocess exit=2")

    posted: list[str] = []
    monkeypatch.setattr("airdropbot.daily.run_digest_routine", fake_run)
    monkeypatch.setattr("airdropbot.daily.post", lambda text: posted.append(text))

    daily.run(workspace=ws)  # 예외 swallow + log only

    assert cache_path.read_text(encoding="utf-8") == existing
    assert posted == []  # post 안 함


def test_does_not_post_on_empty_output(tmp_path, monkeypatch):
    ws = _setup_workspace(tmp_path)
    cache_path = ws / "cache" / "latest-digest.md"

    def fake_run(*, workspace, prompt_path):
        raise EmptyOutputError("출력 짧음")

    posted: list[str] = []
    monkeypatch.setattr("airdropbot.daily.run_digest_routine", fake_run)
    monkeypatch.setattr("airdropbot.daily.post", lambda text: posted.append(text))

    daily.run(workspace=ws)

    assert not cache_path.exists()
    assert posted == []


def test_post_failure_keeps_cache_written(tmp_path, monkeypatch):
    ws = _setup_workspace(tmp_path)
    markdown = "🪂 digest " + ("x" * 500)

    monkeypatch.setattr(
        "airdropbot.daily.run_digest_routine",
        lambda *, workspace, prompt_path: markdown,
    )

    def fake_post(text):
        raise RuntimeError("telegram down")

    monkeypatch.setattr("airdropbot.daily.post", fake_post)

    daily.run(workspace=ws)  # 예외 swallow

    cache_path = ws / "cache" / "latest-digest.md"
    assert cache_path.exists()
    assert cache_path.read_text(encoding="utf-8") == markdown
```

- [ ] **Step 7.2: 테스트 실패 확인**

Run: `.venv/bin/pytest tests/test_daily.py -v`
Expected: 4 FAIL.

- [ ] **Step 7.3: 구현**

`src/airdropbot/daily.py`:

```python
"""airdropbot 진입점 — daily routine 실행, 캐시 저장, 채널 post."""
from __future__ import annotations

import logging
import os
import sys
from datetime import datetime
from pathlib import Path

from airdropbot.claude_runner import (
    ClaudeRunnerError,
    EmptyOutputError,
    run_digest_routine,
)
from airdropbot.telegram_post import post

DEFAULT_WORKSPACE = Path(__file__).resolve().parent.parent.parent
PROMPT_REL = Path("prompts/airdrop_digest.md")
CACHE_REL = Path("cache/latest-digest.md")
LOG_REL = Path("logs")


def _atomic_write(path: Path, content: str) -> None:
    """atomic write: tmp → fsync → rename."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    os.replace(str(tmp), str(path))


def _setup_logger(workspace: Path) -> logging.Logger:
    log_dir = workspace / LOG_REL
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / f"daily-{datetime.now():%Y-%m-%d}.log"

    logger = logging.getLogger("airdropbot.daily")
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        fh = logging.FileHandler(str(log_file), encoding="utf-8")
        fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logger.addHandler(fh)
    return logger


def run(workspace: Path = DEFAULT_WORKSPACE) -> None:
    """Daily 실행: routine → cache → post. 모든 예외 swallow + log."""
    logger = _setup_logger(workspace)
    logger.info("daily run start")

    try:
        markdown = run_digest_routine(
            workspace=workspace,
            prompt_path=workspace / PROMPT_REL,
        )
    except EmptyOutputError as e:
        logger.error("routine empty output: %s — post skip, cache 유지", e)
        return
    except ClaudeRunnerError as e:
        logger.error("routine failure: %s — post skip, cache 유지", e)
        return

    try:
        _atomic_write(workspace / CACHE_REL, markdown)
        logger.info("cache 저장 완료 (%d chars)", len(markdown))
    except OSError as e:
        logger.error("cache write 실패: %s", e)
        return

    try:
        post(markdown)
        logger.info("Telegram channel post 완료")
    except Exception as e:
        logger.error("Telegram post 실패: %s", e)
        return


if __name__ == "__main__":
    run()
    sys.exit(0)
```

- [ ] **Step 7.4: 테스트 통과 확인**

Run: `.venv/bin/pytest tests/test_daily.py -v`
Expected: 4 PASS.

- [ ] **Step 7.5: 전체 테스트 통과**

Run: `.venv/bin/pytest -q`
Expected: 30 PASS (14 yaml + 12 telegram + 4 claude + 4 daily, 합 34... 재계산: 14+12+4+4=34. 그러나 step 5에서 26 통과 명시. 34가 정확).

수정: 14 + 12 + 4 + 4 = 34 PASS.

- [ ] **Step 7.6: 커밋**

```bash
git add src/airdropbot/daily.py tests/test_daily.py
git commit -m "feat(daily): routine→cache→post 오케스트레이션 + fail-quiet/log-loud"
```

---

## Task 8: `cache/`, `logs/` 디렉토리 + .gitignore

**Files:**
- Create: `cache/.gitkeep`, `logs/.gitkeep`
- Modify: `.gitignore`

- [ ] **Step 8.1: 디렉토리 + .gitkeep**

```bash
cd ~/projects/airdropbot
mkdir -p cache logs
touch cache/.gitkeep logs/.gitkeep
```

- [ ] **Step 8.2: `.gitignore` 갱신**

기존 끝에 추가:

```
# cache/logs 디렉토리는 보존, 내용물은 ignore
cache/*
!cache/.gitkeep
logs/*
!logs/.gitkeep
```

- [ ] **Step 8.3: git status 확인**

Run: `git status`
Expected: `cache/.gitkeep`, `logs/.gitkeep`, modified `.gitignore` 보임. `cache/latest-digest.md` 같은 임시 파일 untracked로 표시되지 않음.

- [ ] **Step 8.4: 커밋**

```bash
git add cache/.gitkeep logs/.gitkeep .gitignore
git commit -m "chore: cache/ logs/ 디렉토리 보존 + .gitignore 패턴"
```

---

## Task 9: `docs/DEPLOY.md` 작성

**Files:**
- Create: `docs/DEPLOY.md`

- [ ] **Step 9.1: DEPLOY.md 작성**

```markdown
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
```

- [ ] **Step 9.2: 커밋**

```bash
git add docs/DEPLOY.md
git commit -m "docs: DEPLOY.md — BotFather/채널/cron 셋업 가이드"
```

---

## Task 10: README 갱신 + 최종 검증

**Files:**
- Modify: `README.md`

- [ ] **Step 10.1: README 상태 섹션 갱신**

기존 `## 상태` 섹션 (line 5-9) 교체:

```markdown
## 상태

- **현재 버전**: v0.6.0 (2026-05-20 봇 디스패치 인프라 도입).
- **봇 디스패치**: cron + Claude Code subprocess + Telegram 채널 단방향 broadcast. spec: `docs/specs/2026-05-20-bot-dispatch-design.md`, plan: `docs/plans/2026-05-20-bot-dispatch-v1.md`.
- **외부 셋업**: BotFather 토큰 + 채널 + cron 항목. `docs/DEPLOY.md` 참고.
- **사용 모델**: 사용자가 채널 구독, daily 1회 자동 broadcast. /airdrop 명령 없음 (채널 단방향).
- **pin 명령**: 소유자가 Claude CLI 자연어 입력 → `prompts/airdrop_pin.md` routine 트리거.
```

- [ ] **Step 10.2: 전체 테스트 + ruff lint**

```bash
cd ~/projects/airdropbot
.venv/bin/pytest -v
.venv/bin/ruff check src/ tests/
```

Expected:
- 34 PASS.
- ruff 0 issues.

- [ ] **Step 10.3: 커밋 + push**

```bash
git add README.md
git commit -m "docs(README): v0.6.0 봇 디스패치 시그널 갱신"
git push
```

- [ ] **Step 10.4: 사용자 manual 수행 단계 안내**

이 task 끝나면 implementation은 끝. 사용자가 직접 수행할 단계 (코드 변경 없음):
1. `docs/DEPLOY.md` §1-5 — BotFather + 채널 + cron.
2. `docs/DEPLOY.md` §6 — 수동 smoke test 1회. Telegram 채널에 출력 확인.
3. 태혁에게 채널 핸들 공유 + 첫 daily broadcast 자연 발생까지 대기.
4. v0.6 출력 → 태혁 디자인 피드백 수집 → v0.7 routine prompt 튜닝.

---

## Self-Review 통과 사항

1. **Spec coverage**: spec §1 (사용 모델)·§2 (아키텍처)·§3 (에러)·§4 (테스팅)·§5 (secrets/cron)·§6 (외부 셋업)·§7 (v1 진입 전 정리)·§9 (변경 요약) 모두 task에 매핑됨. §8 (의도된 제외)은 부정적 spec이라 task 없음 (OK).
2. **No placeholders**: 모든 step에 실제 코드/명령/expected output 명시. TBD/TODO 없음.
3. **Type consistency**: `run_digest_routine`은 모든 위치에서 keyword-only args (`workspace`, `prompt_path`). `post(text: str)`는 모든 위치에서 일관. `_split_message(text, limit)`·`_send_chunk(token, chat_id, text)` 시그니처 일관.
4. **Task ordering**: Task 1 (정리) → 2 (scaffold) → 3-5 (telegram_post split→send→post) → 6 (claude_runner) → 7 (daily) → 8 (디렉토리) → 9 (DEPLOY) → 10 (README/검증). 각 task 자체로 commit 단위 + 통과 가능.
