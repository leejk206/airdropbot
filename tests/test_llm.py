import pytest

from airdropbot.llm import ClaudeCliClient, FakeLLM


def test_fake_llm_returns_scripted_replies_in_order():
    llm = FakeLLM(["first", "second"])
    assert llm.complete("sys", "a") == "first"
    assert llm.complete("sys", "b") == "second"
    assert llm.calls == [("sys", "a"), ("sys", "b")]


def test_fake_llm_raises_when_exhausted():
    llm = FakeLLM([])
    with pytest.raises(AssertionError):
        llm.complete("sys", "a")


def test_claude_cli_client_passes_prompt_on_stdin(monkeypatch):
    seen = {}

    class _Done:
        returncode = 0
        stdout = "hello\n"
        stderr = ""

    def _fake_run(cmd, **kwargs):
        seen["cmd"] = cmd
        seen["input"] = kwargs["input"]
        return _Done()

    monkeypatch.setattr("airdropbot.llm.subprocess.run", _fake_run)
    out = ClaudeCliClient().complete("SYSTEM", "PROMPT")

    assert out == "hello"
    assert seen["cmd"][0] == "claude"
    assert "SYSTEM" in seen["input"] and "PROMPT" in seen["input"]


def _capture_run(monkeypatch, stdout="ok\n"):
    """``subprocess.run``을 가로채 호출 인자를 반환한다."""
    seen = {}

    class _Done:
        returncode = 0
        stderr = ""

    _Done.stdout = stdout

    def _fake_run(cmd, **kwargs):
        seen["cmd"] = cmd
        seen["kwargs"] = kwargs
        return _Done()

    monkeypatch.setattr("airdropbot.llm.subprocess.run", _fake_run)
    return seen


def test_claude_cli_client_does_not_skip_permissions(monkeypatch):
    """자동 승인 플래그가 붙으면 서브프로세스가 툴 전권을 얻는다 (spec §2.3)."""
    seen = _capture_run(monkeypatch)
    ClaudeCliClient().complete("s", "p")
    assert "--dangerously-skip-permissions" not in seen["cmd"]


def test_claude_cli_client_blocks_mcp_servers(monkeypatch):
    """MCP 미차단이 AIW3 환각의 실제 벡터였다 (spec §2.3)."""
    seen = _capture_run(monkeypatch)
    ClaudeCliClient().complete("s", "p")
    assert "--strict-mcp-config" in seen["cmd"]


def test_claude_cli_client_denies_tools_by_wildcard_and_name(monkeypatch):
    """와일드카드는 신규 툴을, 명시 열거는 정직한 차단 보고를 담당한다 (spec §2.3)."""
    seen = _capture_run(monkeypatch)
    ClaudeCliClient().complete("s", "p")

    cmd = seen["cmd"]
    assert "--disallowedTools" in cmd
    denied = cmd[cmd.index("--disallowedTools") + 1 :]
    assert "*" in denied
    for tool in ("Bash", "Read", "Write", "WebFetch", "WebSearch", "Task"):
        assert tool in denied, f"{tool} 미차단"


def test_claude_cli_client_denies_only_real_tool_names(monkeypatch):
    """존재하지 않는 이름은 stderr 경고만 낸다 — 실측으로 걸러낸 목록을 지킨다."""
    seen = _capture_run(monkeypatch)
    ClaudeCliClient().complete("s", "p")

    denied = seen["cmd"][seen["cmd"].index("--disallowedTools") + 1 :]
    assert "AgentTool" not in denied
    assert "SlashCommand" not in denied


def test_claude_cli_client_runs_outside_the_repo(monkeypatch, tmp_path):
    """방어 심층화 — 어떤 쓰기도 레포에 닿지 않아야 한다 (spec §2.3)."""
    seen = _capture_run(monkeypatch)
    ClaudeCliClient(workdir=tmp_path).complete("s", "p")
    assert seen["kwargs"]["cwd"] == str(tmp_path)


def test_claude_cli_client_creates_its_workdir(monkeypatch, tmp_path):
    """격리 디렉토리가 없으면 subprocess가 FileNotFoundError로 죽는다."""
    target = tmp_path / "nested" / "sandbox"
    seen = _capture_run(monkeypatch)
    ClaudeCliClient(workdir=target).complete("s", "p")
    assert target.is_dir()
    assert seen["kwargs"]["cwd"] == str(target)


def test_claude_cli_client_raises_on_nonzero_exit(monkeypatch):
    class _Done:
        returncode = 1
        stdout = ""
        stderr = "boom"

    monkeypatch.setattr("airdropbot.llm.subprocess.run", lambda cmd, **kw: _Done())
    with pytest.raises(RuntimeError):
        ClaudeCliClient().complete("s", "p")
