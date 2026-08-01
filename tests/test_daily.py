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


# --- Track B → Track A 배선 (spec §11.2) ------------------------------------
#
# daily가 수집(Track B)을 먼저 돌려야 KB가 신선하게 유지된다. 안 그러면 프롬프트의
# §1.1 신선도 가드가 매일 경고를 달거나 KB_EMPTY로 중단된다.


def _collect_ws(tmp_path: Path) -> Path:
    ws = _setup_workspace(tmp_path)
    (ws / "sources.yaml").write_text(
        "sources:\n  - url: https://airdrops.io\n", encoding="utf-8"
    )
    return ws


def test_runs_collection_before_digest(tmp_path, monkeypatch):
    ws = _collect_ws(tmp_path)
    order: list[str] = []

    monkeypatch.setattr(
        "airdropbot.daily.run_pipeline",
        lambda **kw: order.append("collect") or {"facts": 1, "anchored": 0, "recipes": 0},
    )
    monkeypatch.setattr(
        "airdropbot.daily.run_digest_routine",
        lambda *, workspace, prompt_path: order.append("digest") or ("d" * 2000),
    )
    monkeypatch.setattr("airdropbot.daily.post", lambda text: order.append("post"))

    daily.run(workspace=ws)

    assert order == ["collect", "digest", "post"]


def test_digest_still_runs_when_collection_fails(tmp_path, monkeypatch):
    """수집이 죽어도 방송은 시도한다 — KB가 어제 것이라도 쓸 만할 수 있고,
    낡았는지 판단은 프롬프트의 §1.1 신선도 가드가 한다."""
    ws = _collect_ws(tmp_path)
    posted: list[str] = []

    def boom(**kw):
        raise RuntimeError("playwright down")

    monkeypatch.setattr("airdropbot.daily.run_pipeline", boom)
    monkeypatch.setattr(
        "airdropbot.daily.run_digest_routine",
        lambda *, workspace, prompt_path: "d" * 2000,
    )
    monkeypatch.setattr("airdropbot.daily.post", lambda text: posted.append(text))

    daily.run(workspace=ws)

    assert len(posted) == 1


def test_collection_skipped_when_sources_missing(tmp_path, monkeypatch):
    """sources.yaml이 없으면 수집을 건너뛰되 방송은 계속한다."""
    ws = _setup_workspace(tmp_path)  # sources.yaml 없음
    called: list[str] = []

    monkeypatch.setattr(
        "airdropbot.daily.run_pipeline", lambda **kw: called.append("collect")
    )
    monkeypatch.setattr(
        "airdropbot.daily.run_digest_routine",
        lambda *, workspace, prompt_path: "d" * 2000,
    )
    monkeypatch.setattr("airdropbot.daily.post", lambda text: None)

    daily.run(workspace=ws)

    assert called == []


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
