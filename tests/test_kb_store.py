from airdropbot.kb.store import (
    FactStore,
    project_key,
    registrable_domain,
    resolve_official_urls,
)
from airdropbot.models import Fact


def _f(**kw) -> Fact:
    base = dict(id="x", project="P", content="c", source="airdrops.io", collected_at="2026-07-28")
    base.update(kw)
    return Fact(**base)


def test_registrable_domain_strips_subdomain():
    assert registrable_domain("https://app.citrea.xyz/faucet") == "citrea.xyz"


def test_registrable_domain_strips_www():
    assert registrable_domain("https://www.citrea.xyz") == "citrea.xyz"


def test_registrable_domain_handles_multipart_suffix():
    assert registrable_domain("https://foo.example.co.uk/a") == "example.co.uk"


def test_registrable_domain_separates_lookalike_domains():
    assert registrable_domain("https://citrea.xyz") != registrable_domain("https://citrea-xyz.io")


def test_registrable_domain_returns_none_for_garbage():
    assert registrable_domain("not-a-url") is None
    assert registrable_domain(None) is None


def test_official_url_requires_two_distinct_sources():
    facts = [
        _f(id="a", source="airdrops.io", source_url="https://citrea.xyz"),
        _f(id="b", source="icodrops.com", source_url="https://citrea.xyz/app"),
    ]
    out = {f.id: f for f in resolve_official_urls(facts)}
    assert out["a"].official_url == "https://citrea.xyz"
    assert out["b"].official_url == "https://citrea.xyz/app"


def test_project_key_normalizes_case_and_whitespace():
    assert project_key("  Poly  Market ") == project_key("poly market")
    assert project_key("Citrea") != project_key("Citrea Labs")


def test_official_url_matches_across_project_name_spelling_variants():
    facts = [
        _f(id="a", project="Polymarket", source="airdrops.io", source_url="https://polymarket.com"),
        _f(
            id="b",
            project="  polymarket ",
            source="icodrops.com",
            source_url="https://polymarket.com/app",
        ),
    ]
    assert all(f.official_url for f in resolve_official_urls(facts))


def test_official_url_stays_none_for_single_source():
    facts = [_f(id="a", source="airdrops.io", source_url="https://citrea.xyz")]
    assert resolve_official_urls(facts)[0].official_url is None


def test_official_url_stays_none_when_same_source_repeats():
    facts = [
        _f(id="a", source="airdrops.io", source_url="https://citrea.xyz"),
        _f(id="b", source="airdrops.io", source_url="https://citrea.xyz/app"),
    ]
    assert all(f.official_url is None for f in resolve_official_urls(facts))


def test_official_url_not_shared_across_projects():
    facts = [
        _f(id="a", project="A", source="airdrops.io", source_url="https://citrea.xyz"),
        _f(id="b", project="B", source="icodrops.com", source_url="https://citrea.xyz"),
    ]
    assert all(f.official_url is None for f in resolve_official_urls(facts))


def test_query_excludes_expired_facts():
    store = FactStore([_f(id="old", expires_at="2026-07-01"), _f(id="live")])
    assert [f.id for f in store.query(now="2026-07-28")] == ["live"]


def test_query_filters_by_tag():
    store = FactStore([_f(id="a", tags=("testnet",)), _f(id="b", tags=("mainnet",))])
    assert [f.id for f in store.query(now="2026-07-28", tags=["testnet"])] == ["a"]


def test_put_upserts_by_id():
    store = FactStore([_f(id="a", content="old")])
    store.put(_f(id="a", content="new"))
    assert len(store.all()) == 1
    assert store.all()[0].content == "new"


# --- put() 병합 (spec §5.1.1 규칙 ②) --------------------------------------
#
# id가 (source, project)로 안정되면 매 런의 재추출 팩트가 같은 id로 들어온다.
# 재추출본은 대개 source_url/official_url이 None이므로, 통째 replace면
# enrichment가 어렵게 채운 값을 매일 null로 덮어쓴다. 규칙 ①의 필수 짝이다.


def test_put_keeps_existing_optional_when_incoming_is_none():
    store = FactStore([_f(id="a", source_url="https://p.xyz", official_url="https://p.xyz")])
    store.put(_f(id="a", content="재추출", source_url=None, official_url=None))

    kept = store.all()[0]
    assert kept.source_url == "https://p.xyz"
    assert kept.official_url == "https://p.xyz"
    # 서술과 관측 시각은 최신이 맞다
    assert kept.content == "재추출"


def test_put_overwrites_optional_when_incoming_has_value():
    store = FactStore([_f(id="a", source_url="https://old.xyz")])
    store.put(_f(id="a", source_url="https://new.xyz"))
    assert store.all()[0].source_url == "https://new.xyz"


def test_put_keeps_existing_tags_when_incoming_empty():
    store = FactStore([_f(id="a", tags=("testnet",))])
    store.put(_f(id="a", tags=()))
    assert store.all()[0].tags == ("testnet",)


def test_put_merges_roi_signals_too():
    """ROI 신호도 병합 대상 — 안 그러면 재추출이 매번 지운다 (spec §11.1).

    이 필드들은 페이지에 명시될 때만 채워지므로 런마다 들쭉날쭉하다. 통째 replace면
    어제 잡은 펀딩 규모가 오늘 null로 날아가고 별점이 이유 없이 흔들린다.
    """
    store = FactStore([_f(id="a", funding_usd=45e6, backers=("a16z",), time_minutes=8)])
    store.put(_f(id="a", funding_usd=None, backers=(), time_minutes=None))

    kept = store.all()[0]
    assert kept.funding_usd == 45e6
    assert kept.backers == ("a16z",)
    assert kept.time_minutes == 8


def test_put_overwrites_roi_signal_when_incoming_has_value():
    store = FactStore([_f(id="a", funding_usd=10e6)])
    store.put(_f(id="a", funding_usd=45e6))
    assert store.all()[0].funding_usd == 45e6


def test_put_keeps_zero_capital_signal():
    """0은 유효한 값이다 — falsy라고 버리면 '자본 0'(분모 +1)이 사라진다."""
    store = FactStore([_f(id="a", capital_required_usd=0.0)])
    store.put(_f(id="a", capital_required_usd=None))
    assert store.all()[0].capital_required_usd == 0.0


def test_put_updates_collected_at():
    store = FactStore([_f(id="a", collected_at="2026-07-28")])
    store.put(_f(id="a", collected_at="2026-08-01"))
    assert store.all()[0].collected_at == "2026-08-01"


def test_save_load_roundtrip(tmp_path):
    path = tmp_path / "kb.yaml"
    FactStore([_f(id="a", tags=("t",), expires_at="2026-09-01")]).save(path)
    loaded = FactStore.load(path)
    assert loaded.all()[0].tags == ("t",)
    assert loaded.all()[0].expires_at == "2026-09-01"


def test_load_missing_file_returns_empty_store(tmp_path):
    assert FactStore.load(tmp_path / "nope.yaml").all() == []
