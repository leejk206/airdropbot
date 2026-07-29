from airdropbot.collectors.browser import RenderedPage
from airdropbot.collectors.enrich import (
    FILLED,
    LLM_FAILED,
    NO_URL_REPORTED,
    OUTCOMES,
    REJECTED_AGGREGATOR,
    REJECTED_NO_DOMAIN,
    REJECTED_SOCIAL,
    RENDER_FAILED,
    RESOLVE_FAILED,
    SKIPPED_ALREADY_KNOWN,
    SKIPPED_NO_DETAIL_URL,
    UNPARSEABLE_OUTPUT,
    enrich_source_url,
)
from airdropbot.llm import FakeLLM
from airdropbot.models import Fact

_DETAIL = RenderedPage(
    url="https://airdrops.io/solpump/",
    title="SolPump",
    text="SolPump airdrop",
    links=(
        ("Join now", "https://airdrops.io/visit/6t63/"),
        ("Twitter", "https://twitter.com/airdrops_io"),
    ),
)


def _fact(**kw) -> Fact:
    base = dict(
        id="a",
        project="SolPump",
        content="c",
        source="airdrops.io",
        collected_at="2026-07-28",
        detail_url="https://airdrops.io/solpump/",
    )
    base.update(kw)
    return Fact(**base)


def _render(url, **kw):
    return _DETAIL


def _resolve(url, **kw):
    return "https://solpump.com/"


# --- 성공 경로 ---------------------------------------------------------------


def test_resolves_aggregator_redirect_to_project_url():
    llm = FakeLLM(['{"url": "https://airdrops.io/visit/6t63/"}'])
    r = enrich_source_url(_fact(), llm, render_fn=_render, resolve_fn=_resolve)
    assert r.fact.source_url == "https://solpump.com/"
    assert r.outcome == FILLED


def test_accepts_direct_project_url_without_resolving():
    def _boom(url, **kw):
        raise AssertionError("resolve should not be called")

    llm = FakeLLM(['{"url": "https://solpump.com/"}'])
    r = enrich_source_url(_fact(), llm, render_fn=_render, resolve_fn=_boom)
    assert r.fact.source_url == "https://solpump.com/"
    assert r.outcome == FILLED


# --- 설계된 거부 (고칠 수 없는 것) -------------------------------------------


def test_rejects_social_url():
    llm = FakeLLM(['{"url": "https://twitter.com/airdrops_io"}'])
    r = enrich_source_url(_fact(), llm, render_fn=_render, resolve_fn=_resolve)
    assert r.fact.source_url is None
    assert r.outcome == REJECTED_SOCIAL
    assert "twitter.com" in r.detail, "무엇을 거부했는지 남지 않으면 개수만으로는 못 고친다"


def test_rejects_redirect_that_stays_on_aggregator():
    llm = FakeLLM(['{"url": "https://airdrops.io/visit/6t63/"}'])
    r = enrich_source_url(
        _fact(), llm, render_fn=_render, resolve_fn=lambda u, **kw: "https://airdrops.io/x/"
    )
    assert r.fact.source_url is None
    assert r.outcome == REJECTED_AGGREGATOR
    assert "airdrops.io" in r.detail


def test_rejects_url_without_parseable_domain():
    llm = FakeLLM(['{"url": "not-a-url"}'])
    r = enrich_source_url(_fact(), llm, render_fn=_render, resolve_fn=_resolve)
    assert r.fact.source_url is None
    assert r.outcome == REJECTED_NO_DOMAIN


# --- 건너뛴 경로 -------------------------------------------------------------


def test_skips_when_no_detail_url():
    llm = FakeLLM([])  # 호출되면 AssertionError
    r = enrich_source_url(_fact(detail_url=None), llm, render_fn=_render)
    assert r.fact == _fact(detail_url=None)
    assert r.outcome == SKIPPED_NO_DETAIL_URL


def test_skips_when_source_url_already_known():
    llm = FakeLLM([])
    fact = _fact(source_url="https://solpump.com/")
    r = enrich_source_url(fact, llm, render_fn=_render)
    assert r.fact is fact
    assert r.outcome == SKIPPED_ALREADY_KNOWN


# --- 핵심: 뭉쳐 있던 두 원인의 분리 -----------------------------------------


def test_llm_saying_null_is_not_the_same_as_broken_output():
    """페이지에 정말 없는 것 — 데이터의 한계이므로 고칠 수 없다."""
    llm = FakeLLM(['{"url": null}'])
    r = enrich_source_url(_fact(), llm, render_fn=_render, resolve_fn=_resolve)
    assert r.fact.source_url is None
    assert r.outcome == NO_URL_REPORTED


def test_non_json_output_is_reported_as_unparseable():
    """1차 라이브에서 412자 산문을 반환한 호출이 있었다 — 우리 잘못이므로 고칠 수 있다."""
    llm = FakeLLM(["I looked at the page and the project's site appears to be solpump.com."])
    r = enrich_source_url(_fact(), llm, render_fn=_render, resolve_fn=_resolve)
    assert r.fact.source_url is None
    assert r.outcome == UNPARSEABLE_OUTPUT
    assert "solpump.com" in r.detail, "원문 일부가 남아야 프롬프트를 고칠 수 있다"


def test_unparseable_detail_is_truncated():
    """원문 전체를 담으면 요약이 로그가 된다."""
    llm = FakeLLM(["z" * 5_000])
    r = enrich_source_url(_fact(), llm, render_fn=_render, resolve_fn=_resolve)
    assert r.outcome == UNPARSEABLE_OUTPUT
    assert len(r.detail) < 500


def test_json_object_without_url_key_is_unparseable_not_null():
    """스키마를 어긴 것과 null을 보고한 것은 다르다."""
    llm = FakeLLM(['{"website": "https://solpump.com/"}'])
    r = enrich_source_url(_fact(), llm, render_fn=_render, resolve_fn=_resolve)
    assert r.outcome == UNPARSEABLE_OUTPUT


# --- 인프라 실패 -------------------------------------------------------------


def test_render_failure_is_reported():
    def _boom(url, **kw):
        raise RuntimeError("down")

    r = enrich_source_url(_fact(), FakeLLM([]), render_fn=_boom)
    assert r.fact.source_url is None
    assert r.outcome == RENDER_FAILED
    assert "RuntimeError" in r.detail


def test_llm_failure_is_reported():
    class _Boom:
        def complete(self, system, prompt):
            raise RuntimeError("down")

    r = enrich_source_url(_fact(), _Boom(), render_fn=_render)
    assert r.fact.source_url is None
    assert r.outcome == LLM_FAILED
    assert "RuntimeError" in r.detail


def test_resolve_failure_is_reported():
    def _boom(url, **kw):
        raise RuntimeError("redirect failed")

    llm = FakeLLM(['{"url": "https://airdrops.io/visit/6t63/"}'])
    r = enrich_source_url(_fact(), llm, render_fn=_render, resolve_fn=_boom)
    assert r.fact.source_url is None
    assert r.outcome == RESOLVE_FAILED


# --- 계약 -------------------------------------------------------------------


def test_every_outcome_is_declared():
    """집계는 OUTCOMES를 순회하므로 누락된 outcome은 조용히 사라진다."""
    for name in (
        FILLED,
        SKIPPED_NO_DETAIL_URL,
        SKIPPED_ALREADY_KNOWN,
        RENDER_FAILED,
        LLM_FAILED,
        UNPARSEABLE_OUTPUT,
        NO_URL_REPORTED,
        RESOLVE_FAILED,
        REJECTED_SOCIAL,
        REJECTED_AGGREGATOR,
        REJECTED_NO_DOMAIN,
    ):
        assert name in OUTCOMES


def test_enrichment_never_raises():
    """fail-safe 계약 — 계측이 파이프라인을 죽여서는 안 된다."""

    class _Chaos:
        def complete(self, system, prompt):
            raise KeyboardInterrupt  # BaseException 계열

    def _boom(url, **kw):
        raise MemoryError("brutal")

    r = enrich_source_url(_fact(), FakeLLM(['{"url": null}']), render_fn=_boom)
    assert r.outcome == RENDER_FAILED
