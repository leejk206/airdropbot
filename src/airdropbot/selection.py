"""오늘 정찰할 대상 선정."""
from __future__ import annotations

from airdropbot.models import Fact

DEFAULT_LIMIT = 10
_NO_DEADLINE = "9999-12-31"


def select_targets(facts: list[Fact], *, now: str, limit: int = DEFAULT_LIMIT) -> list[Fact]:
    """만료분을 제외하고 신뢰 앵커·마감 임박 순으로 상위 ``limit``개를 고른다.

    정렬 키: ① ``official_url`` 보유(교차소스 합의분 우선) ② 마감 임박순
    ③ 프로젝트명 사전순(결정적 tie-break).
    """
    live = [f for f in facts if not (f.expires_at and f.expires_at < now)]
    ranked = sorted(
        live,
        key=lambda f: (0 if f.official_url else 1, f.expires_at or _NO_DEADLINE, f.project),
    )
    return ranked[:limit]
