"""서명 게이트 council — Refuter + Judge 2역할.

autoinsta의 3역할(Defender/Refuter/Judge)에서 Defender를 뺐다. 레시피가 반려돼도
비용이 0이므로(오늘 그 에어드랍을 건너뛰면 끝) 변호인이 필요 없고, 안전 게이트의
기본값은 "서명하지 않음"이어야 하기 때문이다. 비대칭 회의주의가 옳다.

council은 수집 단계가 아니라 **비가역 행동(서명) 직전**에만 선다. 후보마다 돌리면
런타임이 폭발하고, 되돌릴 수 있는 수집 오류에 LLM 심의를 살 이유도 없다.
"""
from __future__ import annotations

import json

from airdropbot.collectors.extract import strip_fence
from airdropbot.llm import LLMClient
from airdropbot.models import Fact, Recipe, Verdict

_REFUTER_SYSTEM = (
    "You are the Refuter in a security council guarding a crypto wallet. Given an "
    "action recipe and the KB facts it came from, construct the strongest possible "
    "case that executing it would lose the user's assets. Attack: domain spoofing "
    "(typosquatting, lookalike TLDs), URLs absent from the KB facts, the scope of any "
    "token approval, unexpected signature prompts mid-flow, and weak source provenance. "
    "Be ruthless and concrete."
)

_JUDGE_SYSTEM = (
    "You are the Judge in a security council guarding a crypto wallet. Given the "
    "Refuter's argument, the recipe, and the KB facts, decide whether it is safe to "
    "execute with a real wallet. Return STRICT JSON only, of the exact shape "
    '{"passed": bool, "issues": [str, ...]}. Default to false when uncertain. '
    "Output nothing except the JSON object (a ```json fence is tolerated)."
)


def verify_recipe(recipe: Recipe, facts: list[Fact], llm: LLMClient) -> Verdict:
    """레시피 실행 안전성을 판정.

    **fail-closed** — 파싱 실패·빈 응답·LLM 예외·``passed`` 키 부재는 전부 거부.
    """
    context = f"{_render_recipe(recipe)}\n\nKB FACTS:\n{_render_facts(facts)}"
    try:
        refutation = llm.complete(_REFUTER_SYSTEM, context)
        judgement = llm.complete(_JUDGE_SYSTEM, f"{context}\n\nREFUTER:\n{refutation}")
    except Exception as e:
        return Verdict(passed=False, issues=(f"council 실행 실패: {e}",))

    data = _parse_json_object(judgement)
    if not isinstance(data.get("passed"), bool):
        return Verdict(
            passed=False,
            issues=("Judge 응답을 파싱하지 못함 (fail-closed)",),
            log=refutation,
        )
    return Verdict(
        passed=data["passed"],
        issues=tuple(str(i) for i in (data.get("issues") or [])),
        log=refutation,
    )


def _render_recipe(recipe: Recipe) -> str:
    steps = "\n".join(f"  {i}. {s.action} -> {s.target}" for i, s in enumerate(recipe.steps, 1))
    return (
        f"RECIPE\nproject: {recipe.project}\nentry_url: {recipe.entry_url}\n"
        f"chain: {recipe.chain}\nsignature_kind: {recipe.signature_kind}\n"
        f"approve_unlimited: {recipe.approve_unlimited}\n"
        f"capital_required_usd: {recipe.capital_required_usd}\n"
        f"automatable: {recipe.automatable}\nblockers: {list(recipe.blockers)}\n"
        f"steps:\n{steps}"
    )


def _render_facts(facts: list[Fact]) -> str:
    if not facts:
        return "(no KB facts provided)"
    return "\n".join(
        f"- [{f.source}] {f.content} (official_url: {f.official_url})" for f in facts
    )


def _parse_json_object(raw: str) -> dict:
    try:
        data = json.loads(strip_fence(raw))
    except (ValueError, TypeError):
        return {}
    return data if isinstance(data, dict) else {}
