from airdropbot.models import Recipe, Step, auto_prefix_len, recipe_hash


def _recipe(**kw) -> Recipe:
    base = dict(
        project="Citrea",
        entry_url="https://citrea.xyz/faucet",
        steps=(Step("goto", "https://citrea.xyz/faucet"), Step("click", "Request")),
    )
    base.update(kw)
    return Recipe(**base)


def test_recipe_hash_is_stable():
    assert recipe_hash(_recipe()) == recipe_hash(_recipe())


def test_recipe_hash_changes_when_steps_change():
    other = _recipe(steps=(Step("goto", "https://citrea.xyz/faucet"),))
    assert recipe_hash(_recipe()) != recipe_hash(other)


def test_recipe_hash_changes_when_entry_url_changes():
    assert recipe_hash(_recipe()) != recipe_hash(_recipe(entry_url="https://evil.io"))


def test_recipe_hash_is_prefixed():
    assert recipe_hash(_recipe()).startswith("sha256:")


def test_recipe_defaults_are_safe():
    r = _recipe()
    assert r.signature_kind == "none"
    assert r.automatable == "manual"
    assert r.approve_unlimited is False
    assert r.capital_required_usd == 0.0


# --- 스텝 단위 자동화 태그 (spec §12.5) ---


def test_step_defaults_to_not_automatable():
    """모르면 가장 안전한 쪽 — 태그 없는 구 레시피는 실행 상한 0이 된다."""
    step = Step("goto", "https://citrea.xyz")
    assert step.automatable is False
    assert step.blocker is None


def test_auto_prefix_counts_leading_automatable_steps():
    recipe = _recipe(
        steps=(
            Step("goto", "a", automatable=True),
            Step("click", "b", automatable=True),
        )
    )
    assert auto_prefix_len(recipe) == 2


def test_auto_prefix_is_zero_when_first_step_is_blocked():
    recipe = _recipe(
        steps=(
            Step("fill", "email", blocker="이메일 가입"),
            Step("click", "b", automatable=True),
        )
    )
    assert auto_prefix_len(recipe) == 0


def test_auto_prefix_stops_at_first_blocked_step():
    """개수가 아니라 **선두 연속** prefix여야 한다 — spec §12.5.3.

    중간에 사람 스텝이 끼면 그 뒤는 셀 수 없다. 총합을 세면 §12.2가 지적한
    잘못된 안전 신호(3DOS의 '15/15')가 그대로 재발한다.
    """
    recipe = _recipe(
        steps=(
            Step("goto", "a", automatable=True),
            Step("click", "b", automatable=True),
            Step("fill", "signup form", blocker="이메일 회원가입"),
            Step("click", "d", automatable=True),
            Step("click", "e", automatable=True),
        )
    )
    assert auto_prefix_len(recipe) == 2


def test_auto_prefix_of_empty_recipe_is_zero():
    assert auto_prefix_len(_recipe(steps=())) == 0


def test_recipe_hash_ignores_step_tags():
    """절차가 같은데 판정만 바뀐 것을 레시피 교체로 취급하면 verdict 캐시가 무의미해진다."""
    untagged = _recipe(steps=(Step("goto", "a"), Step("click", "b")))
    tagged = _recipe(
        steps=(
            Step("goto", "a", automatable=True),
            Step("click", "b", automatable=False, blocker="캡차"),
        )
    )
    assert recipe_hash(untagged) == recipe_hash(tagged)
