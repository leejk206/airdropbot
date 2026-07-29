from airdropbot.collectors.browser import RenderedPage
from airdropbot.collectors.enrich import enrich_source_url
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


def test_resolves_aggregator_redirect_to_project_url():
    llm = FakeLLM(['{"url": "https://airdrops.io/visit/6t63/"}'])
    out = enrich_source_url(_fact(), llm, render_fn=_render, resolve_fn=_resolve)
    assert out.source_url == "https://solpump.com/"


def test_accepts_direct_project_url_without_resolving():
    def _boom(url, **kw):
        raise AssertionError("resolve should not be called")

    llm = FakeLLM(['{"url": "https://solpump.com/"}'])
    out = enrich_source_url(_fact(), llm, render_fn=_render, resolve_fn=_boom)
    assert out.source_url == "https://solpump.com/"


def test_rejects_social_url():
    llm = FakeLLM(['{"url": "https://twitter.com/airdrops_io"}'])
    assert enrich_source_url(_fact(), llm, render_fn=_render, resolve_fn=_resolve).source_url is None


def test_rejects_redirect_that_stays_on_aggregator():
    llm = FakeLLM(['{"url": "https://airdrops.io/visit/6t63/"}'])
    out = enrich_source_url(
        _fact(), llm, render_fn=_render, resolve_fn=lambda u, **kw: "https://airdrops.io/x/"
    )
    assert out.source_url is None


def test_skips_when_no_detail_url():
    llm = FakeLLM([])  # 호출되면 AssertionError
    assert enrich_source_url(_fact(detail_url=None), llm, render_fn=_render) == _fact(
        detail_url=None
    )


def test_skips_when_source_url_already_known():
    llm = FakeLLM([])
    fact = _fact(source_url="https://solpump.com/")
    assert enrich_source_url(fact, llm, render_fn=_render) is fact


def test_returns_original_on_null_url():
    llm = FakeLLM(['{"url": null}'])
    assert enrich_source_url(_fact(), llm, render_fn=_render, resolve_fn=_resolve).source_url is None


def test_returns_original_on_render_failure():
    def _boom(url, **kw):
        raise RuntimeError("down")

    assert enrich_source_url(_fact(), FakeLLM([]), render_fn=_boom).source_url is None


def test_returns_original_on_llm_failure():
    class _Boom:
        def complete(self, system, prompt):
            raise RuntimeError("down")

    assert enrich_source_url(_fact(), _Boom(), render_fn=_render).source_url is None


def test_returns_original_on_resolve_failure():
    def _boom(url, **kw):
        raise RuntimeError("redirect failed")

    llm = FakeLLM(['{"url": "https://airdrops.io/visit/6t63/"}'])
    assert enrich_source_url(_fact(), llm, render_fn=_render, resolve_fn=_boom).source_url is None
