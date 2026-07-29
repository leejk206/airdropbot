from airdropbot.collectors.browser import RenderedPage
from airdropbot.llm import FakeLLM
from airdropbot.orchestrator import run_pipeline

_SOURCES = ["https://airdrops.io", "https://icodrops.com"]

_LIST_A = RenderedPage(
    url="https://airdrops.io",
    title="Airdrops",
    text="Citrea bridge",
    links=(("Citrea", "https://airdrops.io/citrea/"),),
)
_LIST_B = RenderedPage(
    url="https://icodrops.com",
    title="ICO Drops",
    text="Citrea bridge",
    links=(("Citrea", "https://icodrops.com/citrea/"),),
)
# 정찰 대상 페이지는 빈 페이지 가드(spec §4.3, 하한 200자)를 넘겨야 한다 — 실제 렌더
# 결과는 수천 자다.
_PROJECT = RenderedPage(
    url="https://citrea.xyz",
    title="Citrea",
    text=(
        "Citrea Testnet Faucet. Connect your wallet to request test tokens. "
        "Complete the bridge activity to become eligible for the upcoming airdrop. "
        "Steps: connect wallet, request tokens, bridge to Citrea, then check "
        "eligibility on the dashboard. No capital required beyond gas fees."
    ),
    links=(),
)


def _detail(url: str) -> RenderedPage:
    return RenderedPage(
        url=url, title="Citrea", text="detail", links=(("Website", "https://citrea.xyz"),)
    )


def _render_fn(url, **kw):
    if url == "https://airdrops.io":
        return _LIST_A
    if url == "https://icodrops.com":
        return _LIST_B
    if url.endswith("/citrea/"):
        return _detail(url)
    return _PROJECT


def _facts_json(detail_url: str) -> str:
    return (
        '[{"project": "Citrea", "content": "브리지",'
        f' "detail_url": "{detail_url}", "source_url": null,'
        ' "chain": "citrea-testnet", "tags": ["testnet"], "expires_at": "2026-12-01"}]'
    )


_ENRICH_JSON = '{"url": "https://citrea.xyz"}'
_RECIPE_JSON = (
    '{"entry_url": "https://citrea.xyz/faucet", "chain": "citrea-testnet",'
    ' "signature_kind": "none", "approve_unlimited": false, "capital_required_usd": 0,'
    ' "automatable": "full", "blockers": [],'
    ' "steps": [{"action": "goto", "target": "https://citrea.xyz/faucet"}]}'
)

_BOTH_SOURCES = [
    _facts_json("https://airdrops.io/citrea/"),
    _facts_json("https://icodrops.com/citrea/"),
    _ENRICH_JSON,
    _ENRICH_JSON,
    _RECIPE_JSON,
]


def _run(tmp_path, responses, render_fn=_render_fn, **kw):
    return run_pipeline(
        sources=_SOURCES,
        kb_path=tmp_path / "kb.yaml",
        actions_path=tmp_path / "actions.yaml",
        llm=FakeLLM(responses),
        now="2026-07-28",
        render_fn=render_fn,
        resolve_fn=lambda u, **k: u,
        limit=1,
        **kw,
    )


def test_pipeline_persists_facts_and_recipes(tmp_path):
    result = _run(tmp_path, _BOTH_SOURCES)

    assert result["facts"] == 2
    assert result["recipes"] == 1
    assert (tmp_path / "kb.yaml").exists()
    assert (tmp_path / "actions.yaml").exists()


def test_pipeline_promotes_official_url_on_two_source_agreement(tmp_path):
    assert _run(tmp_path, _BOTH_SOURCES)["anchored"] == 2


def test_pipeline_is_dry_run_by_default(tmp_path):
    assert [r["status"] for r in _run(tmp_path, _BOTH_SOURCES)["runs"]] == ["dry_run"]


def test_pipeline_survives_a_dead_source(tmp_path):
    def _flaky(url, **kw):
        if url == "https://icodrops.com":
            raise RuntimeError("source down")
        return _render_fn(url)

    responses = [_facts_json("https://airdrops.io/citrea/"), _ENRICH_JSON, _RECIPE_JSON]
    result = _run(tmp_path, responses, render_fn=_flaky)

    assert result["facts"] == 1
    assert result["anchored"] == 0


def test_unanchored_project_is_still_reconned_but_never_executed(tmp_path):
    """v1의 목적은 레시피 축적이므로 정찰은 하되, 실행은 guard가 막아야 한다."""

    def _flaky(url, **kw):
        if url == "https://icodrops.com":
            raise RuntimeError("source down")
        return _render_fn(url)

    responses = [_facts_json("https://airdrops.io/citrea/"), _ENRICH_JSON, _RECIPE_JSON]
    result = _run(tmp_path, responses, render_fn=_flaky)

    assert result["recipes"] == 1
    assert [r["status"] for r in result["runs"]] == ["rejected"]
    assert "official_url" in result["runs"][0]["reason"]


def test_pipeline_accumulates_recipes_across_runs(tmp_path):
    _run(tmp_path, _BOTH_SOURCES)
    result = _run(tmp_path, _BOTH_SOURCES)
    assert result["recipes"] == 1  # 같은 entry_url은 upsert
