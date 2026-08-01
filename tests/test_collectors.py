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


def test_fact_id_survives_reworded_content():
    """id는 ``(source, project)``의 함수다 — spec §5.1.1 규칙 ①.

    ``content``는 LLM이 매 실행 새로 쓰는 한국어 요약이다. 이게 id에 들어가면
    같은 프로젝트가 런마다 새 id를 받아 KB가 자기를 복제한다 (실측: 319 팩트 =
    160 프로젝트의 2중 적재, 170쌍 중 149쌍 중복).
    """
    reworded = _GOOD.replace("Citrea 테스트넷 브리지", "Citrea 테스트넷에서 브리지 활동")
    a = extract_facts(_PAGE, FakeLLM([_GOOD]), now="2026-07-28")[0]
    b = extract_facts(_PAGE, FakeLLM([reworded]), now="2026-07-29")[0]

    assert a.content != b.content
    assert a.id == b.id


def test_fact_id_differs_across_projects_and_sources():
    from airdropbot.collectors.extract import _fact_id

    assert _fact_id("airdrops.io", "Citrea") != _fact_id("airdrops.io", "Polymarket")
    assert _fact_id("airdrops.io", "Citrea") != _fact_id("icodrops.com", "Citrea")


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


# --- 링크 예산 (spec §4.5) -------------------------------------------------
#
# 실측(2026-08-01): `airdrops.io`의 상세 링크는 index 1~147에 분포하고 중앙값이 73이다.
# 앞 80개만 프롬프트에 넣으면 절반이 잘리고, 그것이 detail_url 커버리지 49%의 원인이었다.
# 브라우저가 수집한 링크는 전량 프롬프트에 들어가야 한다 — 두 번 자르지 않는다.


def _page_with_links(n: int) -> RenderedPage:
    return RenderedPage(
        url="https://airdrops.io",
        title="Airdrops",
        text="listing",
        links=tuple((f"P{i}", f"https://airdrops.io/p{i}/") for i in range(n)),
    )


def test_extract_prompt_includes_every_collected_link():
    llm = FakeLLM(["[]"])
    extract_facts(_page_with_links(155), llm, now="x")

    prompt = llm.calls[0][1]
    # 실측 최악 사례(airdrops.io 155링크, 상세 링크 max index 147)를 덮어야 한다.
    assert "https://airdrops.io/p154/" in prompt
    assert "https://airdrops.io/p147/" in prompt


def test_extract_prompt_link_budget_matches_collection_cap():
    from airdropbot.collectors import browser, extract

    # 절단선이 수집 단보다 낮으면 프롬프트 단이 조용히 상한을 정하게 된다.
    assert extract.MAX_LINKS_IN_PROMPT >= browser.MAX_LINKS


def test_extract_prompt_is_still_bounded():
    llm = FakeLLM(["[]"])
    extract_facts(_page_with_links(500), llm, now="x")

    prompt = llm.calls[0][1]
    # 무한정은 아니다 — 수집 단 한도(300)가 유일한 예산이다.
    assert "https://airdrops.io/p299/" in prompt
    assert "https://airdrops.io/p300/" not in prompt
