from airdropbot.collectors.browser import RenderedPage
from airdropbot.collectors.extract import extract_facts
from airdropbot.llm import FakeLLM

_PAGE = RenderedPage(
    url="https://airdrops.io",
    title="Airdrops",
    text="Citrea testnet bridge, ends 2026-08-15",
    links=(("Citrea", "https://citrea.xyz"),),
)

_GOOD = """```json
[{"project": "Citrea", "content": "Citrea 테스트넷 브리지",
  "source_url": "https://citrea.xyz", "chain": "citrea-testnet",
  "tags": ["testnet"], "expires_at": "2026-08-15"}]
```"""


def test_extract_facts_parses_json_and_stamps_source():
    facts = extract_facts(_PAGE, FakeLLM([_GOOD]), now="2026-07-28")
    assert len(facts) == 1
    assert facts[0].project == "Citrea"
    assert facts[0].source == "airdrops.io"
    assert facts[0].collected_at == "2026-07-28"
    assert facts[0].tags == ("testnet",)
    assert facts[0].expires_at == "2026-08-15"


def test_extract_facts_generates_stable_ids():
    a = extract_facts(_PAGE, FakeLLM([_GOOD]), now="2026-07-28")[0]
    b = extract_facts(_PAGE, FakeLLM([_GOOD]), now="2026-07-28")[0]
    assert a.id == b.id


def test_extract_facts_returns_empty_on_unparseable_output():
    assert extract_facts(_PAGE, FakeLLM(["I could not find anything"]), now="x") == []


def test_extract_facts_returns_empty_on_llm_error():
    class _Boom:
        def complete(self, system, prompt):
            raise RuntimeError("down")

    assert extract_facts(_PAGE, _Boom(), now="x") == []


def test_extract_facts_skips_entries_without_project():
    assert extract_facts(_PAGE, FakeLLM(['[{"content": "no project"}]']), now="x") == []


def test_extract_facts_ignores_non_array_json():
    assert extract_facts(_PAGE, FakeLLM(['{"project": "X"}']), now="x") == []
