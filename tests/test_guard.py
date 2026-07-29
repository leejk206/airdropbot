"""검증기의 검증 — 일부러 악성인 레시피를 넣어 거부가 나오는지 확인한다."""
from airdropbot.execute.guard import Limits, prefilter
from airdropbot.models import Fact, Recipe, Step

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


def _recipe(**kw) -> Recipe:
    base = dict(
        project="Citrea",
        entry_url="https://app.citrea.xyz/faucet",
        steps=(Step("goto", "https://app.citrea.xyz/faucet"),),
        automatable="full",
    )
    base.update(kw)
    return Recipe(**base)


def test_allows_clean_recipe_on_subdomain_of_official():
    assert prefilter(_recipe(), _FACTS, Limits()).allowed is True


def test_rejects_typosquatted_domain():
    result = prefilter(_recipe(entry_url="https://ctirea.xyz/faucet"), _FACTS, Limits())
    assert result.allowed is False
    assert "도메인" in result.reason


def test_rejects_lookalike_domain():
    assert prefilter(_recipe(entry_url="https://citrea-xyz.io/f"), _FACTS, Limits()).allowed is False


def test_rejects_lookalike_tld():
    assert prefilter(_recipe(entry_url="https://citrea.xyzz/f"), _FACTS, Limits()).allowed is False


def test_rejects_when_no_official_url_anchor():
    facts = [Fact(id="a", project="Citrea", content="c", source="s", collected_at="d")]
    result = prefilter(_recipe(), facts, Limits())
    assert result.allowed is False
    assert "official_url" in result.reason


def test_rejects_unlimited_approve():
    result = prefilter(
        _recipe(signature_kind="approve", approve_unlimited=True), _FACTS, Limits()
    )
    assert result.allowed is False
    assert "approve" in result.reason


def test_allows_bounded_approve():
    assert prefilter(_recipe(signature_kind="approve"), _FACTS, Limits()).allowed is True


def test_rejects_capital_over_cap():
    result = prefilter(_recipe(capital_required_usd=10.0), _FACTS, Limits(capital_cap_usd=0.0))
    assert result.allowed is False
    assert "자본" in result.reason


def test_rejects_wallet_balance_over_cap():
    result = prefilter(_recipe(), _FACTS, Limits(balance_cap_usd=50.0), wallet_balance_usd=500.0)
    assert result.allowed is False
    assert "잔고" in result.reason


def test_rejects_chain_outside_allowlist():
    limits = Limits(chain_allowlist=("base",))
    assert prefilter(_recipe(chain="citrea-testnet"), _FACTS, limits).allowed is False


def test_skips_chain_rule_when_allowlist_absent():
    assert prefilter(_recipe(chain="anything"), _FACTS, Limits()).allowed is True


def test_marks_partial_recipe_as_pointing_only():
    result = prefilter(_recipe(automatable="partial"), _FACTS, Limits())
    assert result.allowed is False
    assert result.pointing_only is True


def test_marks_manual_recipe_as_pointing_only():
    assert prefilter(_recipe(automatable="manual"), _FACTS, Limits()).pointing_only is True


def test_domain_rule_is_evaluated_before_approve_rule():
    recipe = _recipe(
        entry_url="https://evil.io", signature_kind="approve", approve_unlimited=True
    )
    assert "도메인" in prefilter(recipe, _FACTS, Limits()).reason


def test_anchor_matches_across_project_name_spelling_variants():
    assert prefilter(_recipe(project="  citrea "), _FACTS, Limits()).allowed is True


def test_other_projects_official_url_does_not_authorize():
    facts = _FACTS + [
        Fact(
            id="b",
            project="Other",
            content="c",
            source="s",
            collected_at="d",
            official_url="https://evil.io",
        )
    ]
    assert prefilter(_recipe(entry_url="https://evil.io"), facts, Limits()).allowed is False
