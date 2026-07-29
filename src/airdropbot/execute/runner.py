"""액션 레시피 실행기.

계약은 autoinsta ``publish/instagram.py``를 따른다 — ``dry_run=True``가 기본이고
브라우저를 구동하지 않으며, live 실행은 인증된 ``page``를 명시적으로 요구한다.
v1은 여기서 더 나아가 지갑 스텝을 만나면 실행을 중단한다.
"""
from __future__ import annotations

from airdropbot.execute.guard import Limits, prefilter
from airdropbot.llm import LLMClient
from airdropbot.models import Fact, Recipe, Step, recipe_hash
from airdropbot.verify.council import verify_recipe

_WALLET_ACTIONS = frozenset({"wallet_connect", "wallet_approve", "wallet_sign"})
_STEP_WAIT_MS = 1_000


def run_recipe(
    recipe: Recipe,
    facts: list[Fact],
    limits: Limits,
    *,
    llm: LLMClient | None = None,
    dry_run: bool = True,
    page=None,
    wallet_balance_usd: float = 0.0,
) -> dict:
    """레시피를 실행한다. 기본은 dry-run으로 브라우저를 구동하지 않는다.

    Returns:
        ``{"status": "dry_run"|"rejected"|"pointing_only"|"executed"|"aborted", ...}``

    Raises:
        ValueError: ``dry_run=False``인데 ``page`` 또는 ``llm``이 없을 때.
    """
    guard = prefilter(recipe, facts, limits, wallet_balance_usd=wallet_balance_usd)
    base = {"project": recipe.project, "recipe_hash": recipe_hash(recipe)}

    if not guard.allowed:
        return {
            **base,
            "status": "pointing_only" if guard.pointing_only else "rejected",
            "reason": guard.reason,
        }

    if dry_run:
        return {**base, "status": "dry_run", "plan": plan_of(recipe)}

    if page is None:
        raise ValueError(
            "live run requires an authenticated Playwright `page` "
            "(dry_run=False, page=<wallet_page(...)>)"
        )
    if llm is None:
        raise ValueError("live run requires an `llm` for the council gate")

    verdict = verify_recipe(recipe, facts, llm)
    if not verdict.passed:
        return {**base, "status": "rejected", "issues": list(verdict.issues)}

    return {**base, **_drive(page, recipe)}


def plan_of(recipe: Recipe) -> list[str]:
    """실행하지 않고 사람이 읽을 수 있는 단계 목록으로 환원한다."""
    return [f"{s.action} -> {s.target}" for s in recipe.steps]


def _drive(page, recipe: Recipe) -> dict:
    """스텝을 순서대로 실행. 지갑 서명 스텝을 만나면 v1은 중단한다."""
    done: list[str] = []
    for step in recipe.steps:
        if step.action in _WALLET_ACTIONS:
            return {
                "status": "aborted",
                "reason": f"v1은 지갑 스텝을 실행하지 않음: {step.action}",
                "completed": done,
            }
        try:
            _apply(page, step)
        except Exception as e:
            return {
                "status": "aborted",
                "reason": f"{step.action} 실패: {e}",
                "completed": done,
            }
        done.append(f"{step.action} -> {step.target}")
    return {"status": "executed", "completed": done}


def _apply(page, step: Step) -> None:
    if step.action == "goto":
        page.goto(step.target)
    elif step.action == "click":
        page.get_by_text(step.target).first.click()
    elif step.action == "fill":
        selector, _, value = step.target.partition("=")
        page.fill(selector.strip(), value.strip())
    elif step.action == "wait":
        page.wait_for_timeout(_STEP_WAIT_MS)
