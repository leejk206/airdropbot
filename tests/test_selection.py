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


# --- spec §5.4 재설계 -------------------------------------------------------
#
# 실측(2026-08-01): select_targets(limit=10)이 고유 프로젝트 4개만 돌려줬다
# (AIW3×2, Polymarket×4, 3DOS×2, AI Arena×2). 그중 AI Arena는 URL이 없어
# orchestrator가 버렸다 — 슬롯만 먹고 정찰 0회.


def test_dedupes_by_project():
    """규칙 ① — 같은 프로젝트가 결과에 두 번 나오지 않는다."""
    facts = [
        _f(id="p1", project="Polymarket", source="airdrops.io"),
        _f(id="p2", project="polymarket", source="icodrops.com"),
        _f(id="p3", project="Polymarket ", source="freeairdrop.io"),
        _f(id="other", project="Zeni", source="airdrops.io"),
    ]
    got = select_targets(facts, now="2026-07-28")
    assert len(got) == 2
    assert {f.project.strip().lower() for f in got} == {"polymarket", "zeni"}


def test_dedupe_prefers_representative_with_usable_url():
    """대표 팩트는 정찰에 쓸 URL을 가진 것 — official > source > detail."""
    facts = [
        _f(id="none", project="A", source="s1"),
        _f(id="detail", project="A", source="s2", detail_url="https://agg/a"),
        _f(id="src", project="A", source="s3", source_url="https://a.xyz"),
    ]
    assert [f.id for f in select_targets(facts, now="2026-07-28")] == ["src"]

    facts2 = [
        _f(id="none", project="A", source="s1"),
        _f(id="detail", project="A", source="s2", detail_url="https://agg/a"),
    ]
    assert [f.id for f in select_targets(facts2, now="2026-07-28")] == ["detail"]


def test_already_reconned_projects_are_deprioritized():
    """규칙 ② — 레시피가 이미 있는 프로젝트는 후순위(제외가 아니다)."""
    facts = [_f(id="a", project="Aaa"), _f(id="z", project="Zzz")]
    got = select_targets(facts, now="2026-07-28", reconned=frozenset({"aaa"}))
    assert [f.id for f in got] == ["z", "a"]


def test_reconned_still_selected_when_slots_remain():
    facts = [_f(id="a", project="Aaa")]
    got = select_targets(facts, now="2026-07-28", reconned=frozenset({"aaa"}))
    assert [f.id for f in got] == ["a"]


def test_anchor_outranks_rotation():
    """앵커 보유가 로테이션보다 앞선다 — 실행 후보가 우선."""
    anchored_seen = _f(id="anc", project="Aaa", official_url="https://a.io")
    fresh = _f(id="new", project="Zzz")
    got = select_targets([fresh, anchored_seen], now="2026-07-28", reconned=frozenset({"aaa"}))
    assert [f.id for f in got] == ["anc", "new"]


def test_more_sources_ranks_higher_when_otherwise_tied():
    """규칙 ③ — expires_at이 비면 소스 수가 tie-break. 알파벳 고착 해소."""
    facts = [
        _f(id="z1", project="Zzz", source="s1"),
        _f(id="z2", project="Zzz", source="s2"),
        _f(id="a1", project="Aaa", source="s1"),
    ]
    got = select_targets(facts, now="2026-07-28")
    assert [f.project for f in got] == ["Zzz", "Aaa"]


def test_deadline_still_outranks_source_count():
    soon = _f(id="soon", project="Aaa", expires_at="2026-08-01")
    many = [
        _f(id="m1", project="Zzz", source="s1"),
        _f(id="m2", project="Zzz", source="s2"),
        _f(id="m3", project="Zzz", source="s3"),
    ]
    got = select_targets([*many, soon], now="2026-07-28")
    assert [f.project for f in got] == ["Aaa", "Zzz"]
