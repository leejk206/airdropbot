"""활동 페이지 정찰 → 액션 레시피 추출.

모호할 때는 항상 보수적인 쪽으로 강제한다: 알 수 없는 ``signature_kind``는 가장
위험한 ``approve``로, 알 수 없는 ``automatable``이나 알 수 없는 action이 섞인
레시피는 ``manual``로 낮춘다. 실행 게이트가 이 값들을 근거로 판단하기 때문이다.
"""
from __future__ import annotations

import json

from airdropbot.collectors.browser import RenderedPage
from airdropbot.collectors.extract import strip_fence
from airdropbot.llm import LLMClient
from airdropbot.models import ACTIONS, AUTOMATABLE, SIGNATURE_KINDS, Fact, Recipe, Step

_MOST_DANGEROUS_SIGNATURE = "approve"
_LEAST_AUTOMATABLE = "manual"

# 정찰에 쓸 만한 페이지의 본문 길이 하한. 실측(2026-07-29) 환각 유발 페이지는
# 0자(aiw3.ai)·19자(antdrop.io)·68자(rtg.arcium.com), 정상 판단이 나온 최소 페이지는
# 1,480자(app.apyx.fi)였다. spec §4.3.
MIN_PAGE_TEXT_CHARS = 200

_SYSTEM = (
    "You inspect a project's page and describe the exact steps a user must perform "
    "to complete its airdrop activity. Return STRICT JSON only, one object with keys: "
    '"entry_url" (string), "chain" (string|null), "signature_kind" '
    '(one of "none","message","tx","approve"), "approve_unlimited" (bool), '
    '"capital_required_usd" (number), "automatable" (one of "full","partial","manual"), '
    '"blockers" (string array), "steps" (array of {"action","target"}). '
    "Allowed actions: goto, click, fill, wait, wallet_connect, wallet_approve, "
    "wallet_sign. Be conservative: if unsure whether a wallet signature is needed, "
    'say "approve". Output nothing except the JSON object.'
)


def scout_recipe(fact: Fact, page: RenderedPage, llm: LLMClient, *, now: str) -> Recipe | None:
    """페이지에서 액션 레시피를 뽑는다. 실패하면 None (그 프로젝트는 오늘 건너뛴다).

    본문이 하한 미달이면 LLM을 부르지 않는다. 정찰을 건너뛰는 대가(오늘 그 프로젝트
    하나 누락, 회복 가능)가 환각 레시피를 ``actions.yaml``에 적재하는 대가(v2
    allowlist 근거 오염, 회복 어려움)보다 훨씬 싸다. spec §4.3.
    """
    if len(page.text.strip()) < MIN_PAGE_TEXT_CHARS:
        return None

    prompt = (
        f"PROJECT: {fact.project}\nOFFICIAL_URL: {fact.official_url}\n"
        f"KNOWN: {fact.content}\n\nPAGE_URL: {page.url}\nTITLE: {page.title}\n\n"
        f"TEXT:\n{page.text}"
    )
    try:
        raw = llm.complete(_SYSTEM, prompt)
    except Exception:
        return None

    data = _parse_json_object(raw)
    entry_url = (data.get("entry_url") or "").strip()
    if not entry_url:
        return None

    steps, saw_unknown_action = _parse_steps(data.get("steps") or [])

    automatable = data.get("automatable")
    if automatable not in AUTOMATABLE or saw_unknown_action:
        automatable = _LEAST_AUTOMATABLE

    signature_kind = data.get("signature_kind")
    if signature_kind not in SIGNATURE_KINDS:
        signature_kind = _MOST_DANGEROUS_SIGNATURE

    return Recipe(
        project=fact.project,
        entry_url=entry_url,
        steps=steps,
        chain=data.get("chain") or fact.chain,
        signature_kind=signature_kind,
        approve_unlimited=bool(data.get("approve_unlimited")),
        capital_required_usd=float(data.get("capital_required_usd") or 0),
        automatable=automatable,
        blockers=tuple(data.get("blockers") or ()),
        reconned_at=now,
    )


def _parse_steps(raw_steps: list) -> tuple[tuple[Step, ...], bool]:
    steps: list[Step] = []
    saw_unknown = False
    for item in raw_steps:
        if not isinstance(item, dict):
            saw_unknown = True
            continue
        action = (item.get("action") or "").strip()
        if action not in ACTIONS:
            saw_unknown = True
        steps.append(Step(action=action, target=(item.get("target") or "").strip()))
    return tuple(steps), saw_unknown


def _parse_json_object(raw: str) -> dict:
    try:
        data = json.loads(strip_fence(raw))
    except (ValueError, TypeError):
        return {}
    return data if isinstance(data, dict) else {}
