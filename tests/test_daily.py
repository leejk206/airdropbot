"""daily.py 오케스트레이션 통합 테스트 (mock claude_runner + telegram_post)."""
from __future__ import annotations

from pathlib import Path

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
