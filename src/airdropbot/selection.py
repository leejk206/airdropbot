"""오늘 정찰할 대상 선정 — spec §5.4."""
from __future__ import annotations

from collections import defaultdict

from airdropbot.kb.store import project_key
from airdropbot.models import Fact

DEFAULT_LIMIT = 10
_NO_DEADLINE = "9999-12-31"


def select_targets(
    facts: list[Fact],
    *,
    now: str,
    limit: int = DEFAULT_LIMIT,
    reconned: frozenset[str] = frozenset(),
) -> list[Fact]:
    """만료분을 제외하고 **프로젝트당 하나씩** 상위 ``limit``개를 고른다.

    ``reconned``는 이미 레시피가 있는 프로젝트의 정규화 키 집합이다. 해당
    프로젝트는 제외가 아니라 **후순위**로 밀린다 — 페이지는 변하므로 재정찰이
    무가치하진 않지만, v1의 목적은 같은 대상의 재확인이 아니라 분포 축적이다.

    정렬 키 (spec §5.4):
      ① ``official_url`` 보유 — 실행 후보가 우선
      ② 미정찰 우선 — 로테이션
      ③ 마감 임박순 — ``expires_at``이 채워질 때만 작동
      ④ 소스 수 내림차순 — 교차 언급이 많을수록 실체일 확률이 높다
      ⑤ 프로젝트명 — 결정적 tie-break

    ③이 실측에서 죽어 있었기 때문에(319건 전부 null) 정렬이 사실상 알파벳순으로
    붕괴했고, 매 실행 같은 알파벳 머리만 정찰했다. ④가 그 자리를 메운다.
    """
    live = [f for f in facts if not (f.expires_at and f.expires_at < now)]

    sources_of: dict[str, set[str]] = defaultdict(set)
    for fact in live:
        sources_of[project_key(fact.project)].add(fact.source)

    ranked = sorted(
        (_pick_representative(group) for group in _by_project(live).values()),
        key=lambda f: (
            0 if f.official_url else 1,
            1 if project_key(f.project) in reconned else 0,
            f.expires_at or _NO_DEADLINE,
            -len(sources_of[project_key(f.project)]),
            project_key(f.project),
        ),
    )
    return ranked[:limit]


def _by_project(facts: list[Fact]) -> dict[str, list[Fact]]:
    groups: dict[str, list[Fact]] = defaultdict(list)
    for fact in facts:
        groups[project_key(fact.project)].append(fact)
    return groups


def _pick_representative(group: list[Fact]) -> Fact:
    """한 프로젝트의 여러 소스 팩트 중 정찰에 쓸 하나를 고른다.

    orchestrator는 ``official_url or source_url``이 없으면 그 슬롯을 버린다.
    URL 없는 팩트를 대표로 뽑으면 정찰 예산만 소모되므로 URL 보유분을 우선한다.
    """
    return min(group, key=lambda f: (_url_rank(f), f.id))


def _url_rank(fact: Fact) -> int:
    if fact.official_url:
        return 0
    if fact.source_url:
        return 1
    if fact.detail_url:
        return 2
    return 3
