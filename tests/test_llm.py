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


def test_claude_cli_client_raises_on_nonzero_exit(monkeypatch):
    class _Done:
        returncode = 1
        stdout = ""
        stderr = "boom"

    monkeypatch.setattr("airdropbot.llm.subprocess.run", lambda cmd, **kw: _Done())
    with pytest.raises(RuntimeError):
        ClaudeCliClient().complete("s", "p")
