"""서명 이전 결정적 프리필터.

거부의 대부분을 LLM 호출 없이 처리한다. 여기를 통과한 것만 council로 간다.
규칙 순서는 spec §6을 따른다 — 도메인 검사가 가장 먼저다.
"""
from __future__ import annotations

from dataclasses import dataclass

from airdropbot.kb.store import project_key, registrable_domain
from airdropbot.models import Fact, Recipe, auto_prefix_len


@dataclass(frozen=True)
class Limits:
    """실행 상한. 버너 지갑에는 gas + 최소 자본만 둔다는 전제."""

    capital_cap_usd: float = 0.0
    balance_cap_usd: float = 50.0
    # None이면 체인 규칙을 건너뛴다 (v1). v2에서 실측 데이터로 채운다.
    chain_allowlist: tuple[str, ...] | None = None


@dataclass(frozen=True)
class GuardResult:
    """``ceiling``은 자동 수행이 허용된 선두 스텝 수다 (spec §12.5.4)."""

    allowed: bool
    reason: str | None = None
    pointing_only: bool = False
    ceiling: int = 0


def prefilter(
    recipe: Recipe,
    facts: list[Fact],
    limits: Limits,
    *,
    wallet_balance_usd: float = 0.0,
) -> GuardResult:
    """spec §6 규칙을 순서대로 평가. 하나라도 걸리면 즉시 거부."""
    entry_domain = registrable_domain(recipe.entry_url)
    wanted = project_key(recipe.project)
    official_domains = {
        d
        for d in (
            registrable_domain(f.official_url)
            for f in facts
            if project_key(f.project) == wanted
        )
        if d
    }
    if not official_domains:
        return GuardResult(False, f"{recipe.project}: KB에 합의된 official_url 없음")
    if entry_domain not in official_domains:
        return GuardResult(False, f"entry_url 도메인({entry_domain})이 KB official_url과 불일치")

    if recipe.signature_kind == "approve" and recipe.approve_unlimited:
        return GuardResult(False, "무제한 approve 서명 요구")

    if recipe.capital_required_usd > limits.capital_cap_usd:
        return GuardResult(
            False,
            f"요구 자본 ${recipe.capital_required_usd} > 상한 ${limits.capital_cap_usd}",
        )

    if wallet_balance_usd > limits.balance_cap_usd:
        return GuardResult(
            False, f"지갑 잔고 ${wallet_balance_usd} > 상한 ${limits.balance_cap_usd}"
        )

    if limits.chain_allowlist is not None and recipe.chain not in limits.chain_allowlist:
        return GuardResult(False, f"체인({recipe.chain})이 allowlist 밖")

    # 규칙 6 — 이진 거부가 아니라 **실행 상한**이다 (spec §12.5.4). 레시피 스칼라
    # ``automatable``은 계속 기록되지만 여기서는 보지 않는다. `full`을 기다리는 것이
    # 잘못된 목표였고(§12.5), 어디까지 갈 수 있는지는 스텝 태그만이 안다.
    ceiling = auto_prefix_len(recipe)
    if ceiling == 0:
        first_blocker = next((s.blocker for s in recipe.steps if s.blocker), None)
        reason = "자동 수행 가능한 선두 스텝 없음 — 포인팅만"
        if first_blocker:
            reason = f"{reason} (첫 장벽: {first_blocker})"
        return GuardResult(False, reason, pointing_only=True, ceiling=0)

    return GuardResult(True, ceiling=ceiling)
