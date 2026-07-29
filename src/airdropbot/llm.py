"""LLM 클라이언트 추상화.

생성·검증 단은 :class:`LLMClient` Protocol에만 의존하므로 :class:`FakeLLM`으로
네트워크 없이 단위테스트된다. 런타임 구현은 claude CLI subprocess — autoinsta의
``AnthropicClient``(유료 API)와 달리 구독 기반이라 LLM 비용이 0이다.
"""
from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path
from typing import Protocol

DEFAULT_TIMEOUT_SEC = 120

# claude CLI가 실제로 인정하는 툴 이름들 (2026-07-29 실측). ``AgentTool``·
# ``SlashCommand``은 존재하지 않는 이름이어서 넣으면 stderr 경고만 난다.
_DENIED_TOOLS = (
    "*",
    "Bash",
    "Read",
    "Write",
    "Edit",
    "Glob",
    "Grep",
    "WebFetch",
    "WebSearch",
    "NotebookEdit",
    "TodoWrite",
    "Task",
    "Skill",
    "BashOutput",
    "KillShell",
    "ExitPlanMode",
)


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
    """claude CLI subprocess 래퍼 — **순수 텍스트 완성**으로 묶인다.

    prompt는 stdin으로 전달한다 — 대형 prompt를 인자로 넘기면 subprocess capture가
    deadlock에 빠지는 문제가 있었다 (커밋 ``9790fb7``).

    툴을 열어두면 이 서브프로세스가 세션의 MCP·툴 전권을 물려받아, 넘겨준 페이지가
    비어 있을 때 **자기 브라우저를 띄워 독립적으로 조사한다**. 실측(2026-07-29):
    0자 페이지 + 123자 프롬프트에 233.8초를 쓰고 33 스텝 레시피를 지어내면서 레포에
    스크린샷 4장을 남겼다. 그러면 레시피가 관측 페이지의 함수가 아니게 되어
    ``actions.yaml``이 v2 allowlist 근거로 쓸 수 없게 된다. spec §2.3.
    """

    def __init__(
        self,
        timeout_sec: int = DEFAULT_TIMEOUT_SEC,
        workdir: str | Path | None = None,
    ):
        self.timeout_sec = timeout_sec
        # 방어 심층화: 툴 차단을 뚫는 쓰기가 있어도 레포에는 닿지 않는다.
        self.workdir = Path(workdir) if workdir else Path(tempfile.gettempdir()) / "airdropbot-llm"

    def complete(self, system: str, prompt: str) -> str:
        cmd = [
            "claude",
            "--print",
            "--strict-mcp-config",
            "--disallowedTools",
            *_DENIED_TOOLS,
        ]
        self.workdir.mkdir(parents=True, exist_ok=True)
        completed = subprocess.run(
            cmd,
            input=f"{system}\n\n---\n\n{prompt}",
            capture_output=True,
            text=True,
            timeout=self.timeout_sec,
            cwd=str(self.workdir),
        )
        if completed.returncode != 0:
            raise RuntimeError(
                f"claude exit={completed.returncode} stderr={completed.stderr[:300]}"
            )
        return completed.stdout.strip()
