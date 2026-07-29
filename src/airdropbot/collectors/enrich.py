"""2-pass detail enrichment — 집계 사이트 상세 페이지에서 프로젝트 실제 URL 캐내기.

리스팅 페이지의 링크는 대부분 집계 사이트 자체 페이지(``airdrops.io/solpump/``)이고,
프로젝트의 진짜 주소는 상세 페이지의 리다이렉트(``airdrops.io/visit/<code>/``) 뒤에
있다. 교차소스 합의도 도메인 검사도 실제 도메인을 알아야 성립하므로, 후보를 좁힌 뒤
상세 페이지를 한 번 더 방문한다.
"""
from __future__ import annotations

import json
from dataclasses import replace

from airdropbot.collectors.browser import render, resolve_redirect
from airdropbot.collectors.extract import strip_fence
from airdropbot.kb.store import registrable_domain
from airdropbot.llm import LLMClient
from airdropbot.models import Fact

MAX_LINKS_IN_PROMPT = 120

# 소셜 계정은 프로젝트의 "사이트"가 아니다. official_url 앵커로 쓰면 도메인 검사가
# 무의미해지므로 승격 대상에서 뺀다.
_SOCIAL_DOMAINS = frozenset(
    {"x.com", "twitter.com", "t.me", "telegram.org", "discord.com", "discord.gg",
     "medium.com", "github.com", "youtube.com", "linktr.ee"}
)

_SYSTEM = (
    "You are given a project's page on an airdrop aggregator. Identify the URL of the "
    "PROJECT'S OWN website — not the aggregator's own pages, not a social network "
    "(X/Twitter, Telegram, Discord, Medium, GitHub). Prefer a link labelled as the "
    "official site, app, dashboard, or platform. The aggregator often hides it behind "
    "its own redirect link; pick that redirect if it is the one leading to the project. "
    'Return STRICT JSON only: {"url": "<url>"} or {"url": null} if none is present.'
)


def enrich_source_url(
    fact: Fact,
    llm: LLMClient,
    *,
    render_fn=render,
    resolve_fn=resolve_redirect,
) -> Fact:
    """상세 페이지를 방문해 ``source_url``을 프로젝트 실제 주소로 채운다.

    어떤 단계든 실패하면 원본 ``fact``를 그대로 돌려준다 — enrichment 실패가
    파이프라인을 죽여서는 안 된다.
    """
    if not fact.detail_url or fact.source_url:
        return fact

    try:
        page = render_fn(fact.detail_url)
    except Exception:
        return fact

    links = "\n".join(f"- {t}: {h}" for t, h in page.links[:MAX_LINKS_IN_PROMPT])
    prompt = f"PROJECT: {fact.project}\nPAGE: {page.url}\n\nLINKS:\n{links}"
    try:
        raw = llm.complete(_SYSTEM, prompt)
    except Exception:
        return fact

    url = (_parse_json_object(raw).get("url") or "").strip()
    if not url:
        return fact

    aggregator = registrable_domain(fact.detail_url)
    if registrable_domain(url) == aggregator:
        try:
            url = resolve_fn(url)
        except Exception:
            return fact

    domain = registrable_domain(url)
    if not domain or domain == aggregator or domain in _SOCIAL_DOMAINS:
        return fact

    return replace(fact, source_url=url)


def _parse_json_object(raw: str) -> dict:
    try:
        data = json.loads(strip_fence(raw))
    except (ValueError, TypeError):
        return {}
    return data if isinstance(data, dict) else {}
