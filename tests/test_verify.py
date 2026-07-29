from airdropbot.llm import FakeLLM
from airdropbot.models import Fact, Recipe, Step, Verdict
from airdropbot.verify.cache import load_verdicts, save_verdicts
from airdropbot.verify.council import verify_recipe

_RECIPE = Recipe(
    project="Citrea",
    entry_url="https://citrea.xyz/faucet",
    steps=(Step("goto", "https://citrea.xyz/faucet"),),
    automatable="full",
)
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


def test_council_passes_when_judge_says_so():
    llm = FakeLLM(["refuter text", '{"passed": true, "issues": []}'])
    assert verify_recipe(_RECIPE, _FACTS, llm).passed is True


def test_council_runs_refuter_then_judge():
    llm = FakeLLM(["refuter text", '{"passed": true, "issues": []}'])
    verify_recipe(_RECIPE, _FACTS, llm)
    assert len(llm.calls) == 2
    assert "Refuter" in llm.calls[0][0]
    assert "Judge" in llm.calls[1][0]


def test_council_keeps_refuter_text_in_log():
    llm = FakeLLM(["도메인이 수상하다", '{"passed": true, "issues": []}'])
    assert verify_recipe(_RECIPE, _FACTS, llm).log == "도메인이 수상하다"


def test_council_fails_and_keeps_issues():
    llm = FakeLLM(["refuter", '{"passed": false, "issues": ["도메인 위장"]}'])
    verdict = verify_recipe(_RECIPE, _FACTS, llm)
    assert verdict.passed is False
    assert verdict.issues == ("도메인 위장",)


def test_council_fails_closed_on_unparseable_judge():
    assert verify_recipe(_RECIPE, _FACTS, FakeLLM(["refuter", "probably fine"])).passed is False


def test_council_fails_closed_on_missing_passed_key():
    assert verify_recipe(_RECIPE, _FACTS, FakeLLM(["refuter", '{"issues": []}'])).passed is False


def test_council_fails_closed_on_non_bool_passed():
    llm = FakeLLM(["refuter", '{"passed": "yes", "issues": []}'])
    assert verify_recipe(_RECIPE, _FACTS, llm).passed is False


def test_council_fails_closed_on_llm_error():
    class _Boom:
        def complete(self, system, prompt):
            raise RuntimeError("down")

    assert verify_recipe(_RECIPE, _FACTS, _Boom()).passed is False


def test_council_tolerates_json_fence():
    llm = FakeLLM(["refuter", '```json\n{"passed": true, "issues": []}\n```'])
    assert verify_recipe(_RECIPE, _FACTS, llm).passed is True


def test_verdicts_roundtrip(tmp_path):
    path = tmp_path / "verdicts.yaml"
    save_verdicts(path, {"sha256:ab": Verdict(passed=False, issues=("bad",))})
    loaded = load_verdicts(path)
    assert loaded["sha256:ab"].passed is False
    assert loaded["sha256:ab"].issues == ("bad",)


def test_load_verdicts_missing_file_returns_empty(tmp_path):
    assert load_verdicts(tmp_path / "nope.yaml") == {}
