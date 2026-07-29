from airdropbot.models import Fact
from airdropbot.selection import select_targets


def _f(**kw) -> Fact:
    base = dict(id="x", project="P", content="c", source="s", collected_at="2026-07-28")
    base.update(kw)
    return Fact(**base)


def test_prefers_facts_with_official_url():
    anchored = _f(id="a", project="A", official_url="https://a.io")
    plain = _f(id="b", project="B")
    assert [f.id for f in select_targets([plain, anchored], now="2026-07-28")] == ["a", "b"]


def test_orders_by_imminent_deadline_within_same_anchor_state():
    soon = _f(id="soon", project="S", official_url="https://s.io", expires_at="2026-08-01")
    later = _f(id="later", project="L", official_url="https://l.io", expires_at="2026-09-01")
    assert [f.id for f in select_targets([later, soon], now="2026-07-28")] == ["soon", "later"]


def test_facts_without_deadline_come_after_dated_ones():
    dated = _f(id="d", project="D", expires_at="2026-09-01")
    undated = _f(id="u", project="U")
    assert [f.id for f in select_targets([undated, dated], now="2026-07-28")] == ["d", "u"]


def test_excludes_expired_facts():
    assert select_targets([_f(id="old", expires_at="2026-07-01")], now="2026-07-28") == []


def test_respects_limit():
    facts = [_f(id=str(i), project=f"P{i}") for i in range(5)]
    assert len(select_targets(facts, now="2026-07-28", limit=2)) == 2


def test_is_deterministic_for_equal_ranking():
    facts = [_f(id="b", project="B"), _f(id="a", project="A")]
    assert [f.id for f in select_targets(facts, now="2026-07-28")] == ["a", "b"]
