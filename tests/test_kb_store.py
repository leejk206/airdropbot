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


def test_save_load_roundtrip(tmp_path):
    path = tmp_path / "kb.yaml"
    FactStore([_f(id="a", tags=("t",), expires_at="2026-09-01")]).save(path)
    loaded = FactStore.load(path)
    assert loaded.all()[0].tags == ("t",)
    assert loaded.all()[0].expires_at == "2026-09-01"


def test_load_missing_file_returns_empty_store(tmp_path):
    assert FactStore.load(tmp_path / "nope.yaml").all() == []
