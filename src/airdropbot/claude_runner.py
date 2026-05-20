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
    ]
    try:
        completed = subprocess.run(
            cmd,
            cwd=str(workspace),
            input=prompt_text,
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
