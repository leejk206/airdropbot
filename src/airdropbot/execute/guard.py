"""서명 이전 결정적 프리필터.

거부의 대부분을 LLM 호출 없이 처리한다. 여기를 통과한 것만 council로 간다.
규칙 순서는 spec §6을 따른다 — 도메인 검사가 가장 먼저다.
"""
from __future__ import annotations

from dataclasses import dataclass

from airdropbot.kb.store import project_key, registrable_domain
from airdropbot.models import Fact, Recipe


@dataclass(frozen=True)
class Limits:
    """실행 상한. 버너 지갑에는 gas + 최소 자본만 둔다는 전제."""

    capital_cap_usd: float = 0.0
    balance_cap_usd: float = 50.0
    # None이면 체인 규칙을 건너뛴다 (v1). v2에서 실측 데이터로 채운다.
    chain_allowlist: tuple[str, ...] | None = None


@dataclass(frozen=True)
class GuardResult:
    allowed: bool
    reason: str | None = None
    pointing_only: bool = False


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

    if recipe.automatable != "full":
        return GuardResult(
            False, f"자동화 불가({recipe.automatable}) — 포인팅만", pointing_only=True
        )

    return GuardResult(True)
