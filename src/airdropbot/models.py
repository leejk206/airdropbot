"""파이프라인 전역 데이터 모델."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass

ACTIONS = frozenset(
    {"goto", "click", "fill", "wait", "wallet_connect", "wallet_approve", "wallet_sign"}
)
SIGNATURE_KINDS = ("none", "message", "tx", "approve")
AUTOMATABLE = ("full", "partial", "manual")


@dataclass(frozen=True)
class Fact:
    """KB에 저장되는 사실 단위. ``official_url``은 교차소스 합의분만 채워진다."""

    id: str
    project: str
    content: str
    source: str
    collected_at: str
    # 집계 사이트가 이 프로젝트를 설명하는 자체 페이지. 프로젝트 실제 URL은 보통
    # 여기에만 있고(리다이렉트 뒤인 경우도 많다) 리스팅 페이지에는 없다.
    detail_url: str | None = None
    source_url: str | None = None
    official_url: str | None = None
    chain: str | None = None
    tags: tuple[str, ...] = ()
    expires_at: str | None = None
    # --- ROI 신호 (spec §11.1) ---
    # Track A의 별점 룰이 분자(보상)/분모(비용)로 쓰는 값들. 페이지에 명시된 것만
    # 채우고 없으면 None — 추정하면 별점이 근거 없이 움직인다.
    funding_usd: float | None = None
    backers: tuple[str, ...] = ()
    research_count: int | None = None
    capital_required_usd: float | None = None
    time_minutes: int | None = None


@dataclass(frozen=True)
class Step:
    """액션 레시피의 단일 스텝. ``action``은 :data:`ACTIONS` 중 하나.

    ``automatable``은 **warm 인증 세션**(spec §8.1)을 전제로 한 스텝 단위 판정이고,
    기본값은 보수적으로 ``False``다 — 태그가 없는 구 레시피는 실행 상한 0으로
    떨어져 종전처럼 포인팅 전용에 머문다. spec §12.5.2.
    """

    action: str
    target: str
    automatable: bool = False
    blocker: str | None = None


@dataclass(frozen=True)
class Recipe:
    """한 프로젝트의 활동 실행 절차. 기본값은 가장 보수적인 쪽으로 잡혀 있다."""

    project: str
    entry_url: str
    steps: tuple[Step, ...]
    chain: str | None = None
    signature_kind: str = "none"
    approve_unlimited: bool = False
    capital_required_usd: float = 0.0
    automatable: str = "manual"
    blockers: tuple[str, ...] = ()
    reconned_at: str = ""


@dataclass(frozen=True)
class Verdict:
    """council 판정. ``log``에는 Refuter 원문을 감사용으로 남긴다."""

    passed: bool
    issues: tuple[str, ...] = ()
    log: str = ""


def recipe_hash(recipe: Recipe) -> str:
    """entry_url + 정규화된 steps의 sha256. 레시피가 바뀌면 해시가 바뀐다.

    스텝 태그(``automatable``·``blocker``)는 **일부러 제외한다** — 절차가 같은데
    판정만 바뀐 것을 레시피 교체로 취급하면 verdict 캐시가 무의미해진다. spec §5.2.
    """
    payload = "\n".join([recipe.entry_url, *(f"{s.action}:{s.target}" for s in recipe.steps)])
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


def auto_prefix_len(recipe: Recipe) -> int:
    """자동 수행 가능한 **선두 연속** 스텝 수 = 실행 상한. spec §12.5.3.

    총합이 아니라 prefix다. 중간에 사람 스텝이 끼면 그 뒤는 셀 수 없다 — 스텝 3을
    건너뛰고 4를 실행하는 것은 절차 위반이고, 총합을 세면 §12.2가 지적한 잘못된
    안전 신호가 그대로 재발한다.
    """
    count = 0
    for step in recipe.steps:
        if not step.automatable:
            break
        count += 1
    return count
