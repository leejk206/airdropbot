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
    """기본 픽스처는 **스텝 태그가 붙은** 실행 가능 레시피다.

    2026-08-02(spec §12.5)부터 규칙 6은 레시피 스칼라 ``automatable``이 아니라
    스텝 태그의 선두 prefix를 본다. 태그가 없으면 상한 0 = 포인팅 전용이다.
    """
    base = dict(
        project="Citrea",
        entry_url="https://app.citrea.xyz/faucet",
        steps=(Step("goto", "https://app.citrea.xyz/faucet", automatable=True),),
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


# --- 규칙 6: 이진 거부 → 실행 상한 (spec §12.5.4) ----------------------------


def test_marks_fully_blocked_recipe_as_pointing_only():
    """선두 스텝부터 막혀 있으면 자동으로 갈 수 있는 곳이 없다 — 종전 거동 유지."""
    recipe = _recipe(steps=(Step("fill", "signup", blocker="이메일 가입"),))
    result = prefilter(recipe, _FACTS, Limits())
    assert result.allowed is False
    assert result.pointing_only is True
    assert result.ceiling == 0


def test_untagged_legacy_recipe_is_pointing_only_even_if_rated_full():
    """구 레시피는 스칼라가 full이어도 실행 권한이 없다 — spec §12.5.2."""
    recipe = _recipe(steps=(Step("goto", "https://app.citrea.xyz/f"),), automatable="full")
    assert prefilter(recipe, _FACTS, Limits()).pointing_only is True


def test_partial_recipe_with_automatable_prefix_is_allowed_with_ceiling():
    """B갈래의 핵심 — `full`이 아니어도 자동 가능한 구간까지는 실행한다."""
    recipe = _recipe(
        automatable="partial",
        steps=(
            Step("goto", "https://app.citrea.xyz/f", automatable=True),
            Step("click", "Start", automatable=True),
            Step("fill", "email", blocker="이메일 인증"),
            Step("click", "Claim", automatable=True),
        ),
    )
    result = prefilter(recipe, _FACTS, Limits())
    assert result.allowed is True
    assert result.ceiling == 2


def test_manual_scalar_does_not_block_when_prefix_exists():
    """레시피 스칼라는 신호로만 남는다 — 게이트 판정에서 빠졌다."""
    recipe = _recipe(
        automatable="manual",
        steps=(Step("goto", "https://app.citrea.xyz/f", automatable=True),),
    )
    assert prefilter(recipe, _FACTS, Limits()).allowed is True


def test_ceiling_rule_runs_after_safety_rules():
    """상한이 열렸다고 안전 규칙(1~5)이 우회되면 안 된다 — spec §12.5.5."""
    recipe = _recipe(signature_kind="approve", approve_unlimited=True)
    result = prefilter(recipe, _FACTS, Limits())
    assert result.allowed is False
    assert "approve" in result.reason
    assert result.pointing_only is False


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
