"""claude_runner.py — Claude Code subprocess 호출 분기 테스트."""
from __future__ import annotations

import subprocess
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
    (tmp_path / "p.md").write_text("fake prompt", encoding="utf-8")
    md = "🪂 오늘의 에어드랍 Top 10 — " + ("x" * 1800)  # MIN_OUTPUT_LEN=1500 통과
    with patch("airdropbot.claude_runner.subprocess.run") as mock_run:
        mock_run.return_value = _fake_completed(md)
        result = run_digest_routine(workspace=tmp_path, prompt_path=tmp_path / "p.md")
        assert result == md


def test_raises_on_timeout(tmp_path):
    (tmp_path / "p.md").write_text("fake prompt", encoding="utf-8")
    with patch("airdropbot.claude_runner.subprocess.run") as mock_run:
        mock_run.side_effect = subprocess.TimeoutExpired(cmd=["claude"], timeout=600)
        with pytest.raises(ClaudeRunnerError, match="timeout"):
            run_digest_routine(workspace=tmp_path, prompt_path=tmp_path / "p.md")


def test_raises_on_nonzero_exit(tmp_path):
    (tmp_path / "p.md").write_text("fake prompt", encoding="utf-8")
    with patch("airdropbot.claude_runner.subprocess.run") as mock_run:
        mock_run.return_value = _fake_completed("", returncode=2, stderr="boom")
        with pytest.raises(ClaudeRunnerError, match="exit=2"):
            run_digest_routine(workspace=tmp_path, prompt_path=tmp_path / "p.md")


def test_raises_on_empty_output(tmp_path):
    (tmp_path / "p.md").write_text("fake prompt", encoding="utf-8")
    with patch("airdropbot.claude_runner.subprocess.run") as mock_run:
        mock_run.return_value = _fake_completed("짧음")  # <1500자
        with pytest.raises(EmptyOutputError):
            run_digest_routine(workspace=tmp_path, prompt_path=tmp_path / "p.md")
