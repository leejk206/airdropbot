from airdropbot.collectors.browser import RenderedPage
from airdropbot.collectors.enrich import (
    FILLED,
    NO_URL_REPORTED,
    OUTCOMES,
    REJECTED_SOCIAL,
    UNPARSEABLE_OUTPUT,
)
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
    ' "steps": [{"action": "goto", "target": "https://citrea.xyz/faucet",'
    ' "automatable": true, "blocker": null}]}'
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


def test_pipeline_reports_enrich_outcome_counts(tmp_path):
    """계측이 요약에 실리지 않으면 관측할 수 없다 (spec §4.4)."""
    result = _run(tmp_path, list(_BOTH_SOURCES))

    counts = result["enrich"]
    assert counts[FILLED] == 2, f"두 소스 모두 URL을 캤어야 한다: {counts}"
    assert sum(counts.values()) >= 2


def test_pipeline_enrich_counts_only_declared_outcomes(tmp_path):
    """선언되지 않은 키가 섞이면 집계가 조용히 어긋난다."""
    result = _run(tmp_path, list(_BOTH_SOURCES))

    assert set(result["enrich"]) <= set(OUTCOMES)


def test_pipeline_records_why_enrichment_failed(tmp_path):
    """개수만으로는 못 고친다 — 무엇을 거부했는지가 남아야 한다."""
    responses = [
        _facts_json("https://airdrops.io/citrea/"),
        _facts_json("https://icodrops.com/citrea/"),
        '{"url": "https://twitter.com/citrea"}',   # 앵커링 국면: 소셜 → 거부
        "이건 JSON이 아니다 citrea.xyz",              # 앵커링 국면: 파싱 실패
        '{"url": null}',                           # 정찰 국면 재시도: 페이지에 없음
    ]
    result = _run(tmp_path, responses)

    counts = result["enrich"]
    assert counts[REJECTED_SOCIAL] == 1
    assert counts[UNPARSEABLE_OUTPUT] == 1
    assert counts[NO_URL_REPORTED] == 1
    assert FILLED not in counts

    log = {(e["project"], e["outcome"]): e["detail"] for e in result["enrich_log"]}
    assert ("Citrea", REJECTED_SOCIAL) in log
    assert "twitter.com" in log[("Citrea", REJECTED_SOCIAL)]
    assert ("Citrea", UNPARSEABLE_OUTPUT) in log


def test_failed_enrichment_is_retried_before_recon(tmp_path):
    """앵커링 국면에서 실패한 대상은 정찰 직전에 한 번 더 시도된다.

    계측 개수를 읽을 때 이 재시도를 모르면 "왜 후보 수보다 호출이 많은가"를 오해한다.
    """
    responses = [
        _facts_json("https://airdrops.io/citrea/"),
        _facts_json("https://icodrops.com/citrea/"),
        '{"url": null}',   # 앵커링 국면 × 2
        '{"url": null}',
        _ENRICH_JSON,      # 정찰 국면 재시도 — 여기서 성공
        _RECIPE_JSON,
    ]
    result = _run(tmp_path, responses)

    assert result["enrich"][NO_URL_REPORTED] == 2
    assert result["enrich"][FILLED] == 1
    assert result["recipes"] == 1, "재시도로 URL을 얻었으면 정찰까지 가야 한다"


def test_pipeline_enrich_log_omits_successes(tmp_path):
    """성공은 개수로 충분하다. 로그는 고칠 것만 담는다."""
    result = _run(tmp_path, list(_BOTH_SOURCES))

    assert [e for e in result["enrich_log"] if e["outcome"] == FILLED] == []
