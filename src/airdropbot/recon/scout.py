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
    "You inspect a project's page and describe the exact steps needed to complete its "
    "airdrop activity. Return STRICT JSON only, one object with keys: "
    '"entry_url" (string), "chain" (string|null), "signature_kind" '
    '(one of "none","message","tx","approve"), "approve_unlimited" (bool), '
    '"capital_required_usd" (number), "automatable" (one of "full","partial","manual"), '
    '"blockers" (string array), "steps" (array of '
    '{"action","target","automatable","blocker"}). '
    "Allowed actions: goto, click, fill, wait, wallet_connect, wallet_approve, "
    "wallet_sign. "
    # spec §12.5 — 레시피 스칼라만으로는 "어디까지 자동으로 갈 수 있는가"를 기계가
    # 알 수 없다. 실행 상한은 이 per-step 판정에서만 나온다.
    "PER-STEP JUDGEMENT: for EACH step also return "
    '"automatable" (boolean — can the automation perform this exact step unattended '
    'in the execution context described below?) and "blocker" (string|null — if '
    "automatable is false, one short phrase naming what a human must do). Judge every "
    "step on its own; do not copy the recipe-level rating down onto the steps. "
    '"automatable" must be a JSON boolean, not a string. '
    # spec §8.1 — 이 문단이 없으면 모델이 차가운 브라우저를 가정하고 로그인·메일
    # 인증을 사람 스텝으로 세어 automatable을 근거 없이 강등한다.
    "EXECUTION CONTEXT: the automation runs in a persistent browser profile that is "
    "ALREADY AUTHENTICATED — the operator logged in once by hand beforehand. The "
    "profile holds a live wallet extension (unlocked), social accounts (X, Discord, "
    "Telegram) and an email account, all logged in, with their cookies and history "
    "intact. Treat 'sign in', 'connect X/Discord/Telegram', 'log in to your account' "
    "and reading a verification email as ALREADY DONE or trivially automatable — do "
    "NOT count them as human steps and do NOT list them as blockers. "
    'Rate "automatable" against THAT context, not a fresh anonymous browser. '
    "Still downgrade, and DO list as blockers, anything a logged-in session cannot "
    "solve: CAPTCHA or bot-challenge walls, KYC document upload, geographic blocks, "
    "physical hardware requirements, or an invite/referral code the operator lacks. "
    "Be conservative on money and signatures: if unsure whether a wallet signature is "
    'needed, say "approve". Output nothing except the JSON object.'
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
        known_action = action in ACTIONS
        if not known_action:
            saw_unknown = True
        # `is True`인 이유: 문자열 "true"·1 같은 truthy 값은 모델이 스키마를 안 지켰다는
        # 신호다. 그런 응답에 실행 상한을 주지 않는다. 그리고 드라이버가 모르는
        # action은 애초에 수행할 수 없으므로 판정과 무관하게 prefix를 끊는다. spec §12.5.
        automatable = known_action and item.get("automatable") is True
        blocker = item.get("blocker")
        steps.append(
            Step(
                action=action,
                target=(item.get("target") or "").strip(),
                automatable=automatable,
                blocker=(str(blocker).strip() or None) if blocker else None,
            )
        )
    return tuple(steps), saw_unknown


def _parse_json_object(raw: str) -> dict:
    try:
        data = json.loads(strip_fence(raw))
    except (ValueError, TypeError):
        return {}
    return data if isinstance(data, dict) else {}
