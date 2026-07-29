"""LLM 클라이언트 추상화.

생성·검증 단은 :class:`LLMClient` Protocol에만 의존하므로 :class:`FakeLLM`으로
네트워크 없이 단위테스트된다. 런타임 구현은 claude CLI subprocess — autoinsta의
``AnthropicClient``(유료 API)와 달리 구독 기반이라 LLM 비용이 0이다.
"""
from __future__ import annotations

import subprocess
from typing import Protocol

DEFAULT_TIMEOUT_SEC = 120


class LLMClient(Protocol):
    def complete(self, system: str, prompt: str) -> str:
        """(system, prompt)에 대한 모델 텍스트 응답을 반환."""
        ...


class FakeLLM:
    """스크립트된 응답을 순서대로 반환하는 테스트 더블."""

    def __init__(self, responses: list[str]):
        self._responses = list(responses)
        self.calls: list[tuple[str, str]] = []

    def complete(self, system: str, prompt: str) -> str:
        self.calls.append((system, prompt))
        if not self._responses:
            raise AssertionError("FakeLLM ran out of scripted responses")
        return self._responses.pop(0)


class ClaudeCliClient:
    """claude CLI subprocess 래퍼.

    prompt는 stdin으로 전달한다 — 대형 prompt를 인자로 넘기면 subprocess capture가
    deadlock에 빠지는 문제가 있었다 (커밋 ``9790fb7``).
    """

    def __init__(self, timeout_sec: int = DEFAULT_TIMEOUT_SEC):
        self.timeout_sec = timeout_sec

    def complete(self, system: str, prompt: str) -> str:
        cmd = ["claude", "--print", "--dangerously-skip-permissions"]
        completed = subprocess.run(
            cmd,
            input=f"{system}\n\n---\n\n{prompt}",
            capture_output=True,
            text=True,
            timeout=self.timeout_sec,
        )
        if completed.returncode != 0:
            raise RuntimeError(
                f"claude exit={completed.returncode} stderr={completed.stderr[:300]}"
            )
        return completed.stdout.strip()
