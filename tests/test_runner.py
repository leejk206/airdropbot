import pytest

from airdropbot.execute.guard import Limits
from airdropbot.execute.runner import run_recipe
from airdropbot.llm import FakeLLM
from airdropbot.models import Fact, Recipe, Step

_FACTS = [
    Fact(
        id="a",
        project="Citrea",
        content="브리지",
        source="airdrops.io",
        collected_at="2026-07-28",
        official_url="https://citrea.xyz",
    )
]
_RECIPE = Recipe(
    project="Citrea",
    entry_url="https://citrea.xyz/faucet",
    steps=(Step("goto", "https://citrea.xyz/faucet"), Step("click", "Request")),
    automatable="full",
)


class _Locator:
    def __init__(self, page, text):
        self._page = page
        self._text = text

    @property
    def first(self):
        return self

    def click(self):
        self._page.actions.append(("click", self._text))


class _FakePage:
    def __init__(self):
        self.actions: list[tuple[str, str]] = []

    def goto(self, url, **kw):
        self.actions.append(("goto", url))

    def get_by_text(self, text):
        return _Locator(self, text)

    def fill(self, selector, value):
        self.actions.append(("fill", f"{selector}={value}"))

    def wait_for_timeout(self, ms):
        self.actions.append(("wait", str(ms)))


def test_dry_run_returns_plan_without_browser():
    result = run_recipe(_RECIPE, _FACTS, Limits())
    assert result["status"] == "dry_run"
    assert result["plan"] == [
        "goto -> https://citrea.xyz/faucet",
        "click -> Request",
    ]


def test_dry_run_reports_recipe_hash():
    assert run_recipe(_RECIPE, _FACTS, Limits())["recipe_hash"].startswith("sha256:")


def test_guard_rejection_short_circuits_before_council():
    bad = Recipe(project="Citrea", entry_url="https://evil.io", steps=(), automatable="full")
    llm = FakeLLM([])  # 호출되면 AssertionError
    result = run_recipe(bad, _FACTS, Limits(), llm=llm)
    assert result["status"] == "rejected"
    assert llm.calls == []


def test_pointing_only_status():
    manual = Recipe(
        project="Citrea", entry_url="https://citrea.xyz/faucet", steps=(), automatable="manual"
    )
    assert run_recipe(manual, _FACTS, Limits())["status"] == "pointing_only"


def test_live_run_without_page_raises():
    with pytest.raises(ValueError):
        run_recipe(_RECIPE, _FACTS, Limits(), llm=FakeLLM([]), dry_run=False)


def test_live_run_requires_llm():
    with pytest.raises(ValueError):
        run_recipe(_RECIPE, _FACTS, Limits(), dry_run=False, page=_FakePage())


def test_live_run_blocked_by_failed_council():
    llm = FakeLLM(["refuter", '{"passed": false, "issues": ["의심 도메인"]}'])
    result = run_recipe(_RECIPE, _FACTS, Limits(), llm=llm, dry_run=False, page=_FakePage())
    assert result["status"] == "rejected"
    assert result["issues"] == ["의심 도메인"]


def test_live_run_executes_steps_when_council_passes():
    page = _FakePage()
    llm = FakeLLM(["refuter", '{"passed": true, "issues": []}'])
    result = run_recipe(_RECIPE, _FACTS, Limits(), llm=llm, dry_run=False, page=page)
    assert result["status"] == "executed"
    assert page.actions == [("goto", "https://citrea.xyz/faucet"), ("click", "Request")]


def test_live_run_aborts_on_wallet_step_in_v1():
    recipe = Recipe(
        project="Citrea",
        entry_url="https://citrea.xyz/faucet",
        steps=(Step("wallet_sign", "confirm"),),
        automatable="full",
    )
    llm = FakeLLM(["refuter", '{"passed": true, "issues": []}'])
    result = run_recipe(recipe, _FACTS, Limits(), llm=llm, dry_run=False, page=_FakePage())
    assert result["status"] == "aborted"
    assert "wallet_sign" in result["reason"]


def test_live_run_aborts_when_a_step_raises():
    class _BrokenPage(_FakePage):
        def goto(self, url, **kw):
            raise RuntimeError("navigation failed")

    llm = FakeLLM(["refuter", '{"passed": true, "issues": []}'])
    result = run_recipe(_RECIPE, _FACTS, Limits(), llm=llm, dry_run=False, page=_BrokenPage())
    assert result["status"] == "aborted"
    assert result["completed"] == []
