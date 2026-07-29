from airdropbot.collectors.browser import RenderedPage
from airdropbot.llm import FakeLLM
from airdropbot.models import Fact, Recipe, Step
from airdropbot.recon.scout import scout_recipe
from airdropbot.recon.store import load_recipes, save_recipes

_FACT = Fact(
    id="citrea",
    project="Citrea",
    content="브리지",
    source="airdrops.io",
    collected_at="2026-07-28",
    official_url="https://citrea.xyz",
)
_PAGE = RenderedPage(url="https://citrea.xyz", title="Citrea", text="Faucet", links=())

_GOOD = """{"entry_url": "https://citrea.xyz/faucet", "chain": "citrea-testnet",
 "signature_kind": "message", "approve_unlimited": false, "capital_required_usd": 0,
 "automatable": "full", "blockers": [],
 "steps": [{"action": "goto", "target": "https://citrea.xyz/faucet"},
           {"action": "click", "target": "Request"}]}"""


def test_scout_builds_recipe():
    r = scout_recipe(_FACT, _PAGE, FakeLLM([_GOOD]), now="2026-07-28")
    assert r.project == "Citrea"
    assert r.entry_url == "https://citrea.xyz/faucet"
    assert r.steps[0] == Step("goto", "https://citrea.xyz/faucet")
    assert r.signature_kind == "message"
    assert r.automatable == "full"
    assert r.reconned_at == "2026-07-28"


def test_scout_returns_none_on_unparseable_output():
    assert scout_recipe(_FACT, _PAGE, FakeLLM(["nope"]), now="x") is None


def test_scout_returns_none_on_llm_error():
    class _Boom:
        def complete(self, system, prompt):
            raise RuntimeError("down")

    assert scout_recipe(_FACT, _PAGE, _Boom(), now="x") is None


def test_scout_returns_none_without_entry_url():
    assert scout_recipe(_FACT, _PAGE, FakeLLM(['{"steps": []}']), now="x") is None


def test_scout_coerces_unknown_signature_kind_to_most_dangerous():
    raw = _GOOD.replace('"signature_kind": "message"', '"signature_kind": "weird"')
    assert scout_recipe(_FACT, _PAGE, FakeLLM([raw]), now="x").signature_kind == "approve"


def test_scout_downgrades_automatable_on_unknown_action():
    raw = _GOOD.replace('"action": "click"', '"action": "teleport"')
    assert scout_recipe(_FACT, _PAGE, FakeLLM([raw]), now="x").automatable == "manual"


def test_scout_coerces_unknown_automatable_to_manual():
    raw = _GOOD.replace('"automatable": "full"', '"automatable": "maybe"')
    assert scout_recipe(_FACT, _PAGE, FakeLLM([raw]), now="x").automatable == "manual"


def test_scout_tolerates_json_fence():
    r = scout_recipe(_FACT, _PAGE, FakeLLM([f"```json\n{_GOOD}\n```"]), now="x")
    assert r.entry_url == "https://citrea.xyz/faucet"


def test_recipes_roundtrip(tmp_path):
    path = tmp_path / "actions.yaml"
    recipe = Recipe(
        project="Citrea",
        entry_url="https://citrea.xyz/faucet",
        steps=(Step("goto", "https://citrea.xyz/faucet"),),
        automatable="full",
    )
    save_recipes(path, [recipe])
    loaded = load_recipes(path)
    assert loaded[0].steps == (Step("goto", "https://citrea.xyz/faucet"),)
    assert loaded[0].automatable == "full"


def test_load_recipes_missing_file_returns_empty(tmp_path):
    assert load_recipes(tmp_path / "nope.yaml") == []


def test_save_recipes_writes_recipe_hash_and_null_verdict(tmp_path):
    path = tmp_path / "actions.yaml"
    save_recipes(path, [Recipe(project="P", entry_url="https://p.io", steps=())])
    text = path.read_text(encoding="utf-8")
    assert "recipe_hash" in text
    assert "verdict: null" in text
