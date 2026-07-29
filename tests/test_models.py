from airdropbot.models import Recipe, Step, recipe_hash


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
