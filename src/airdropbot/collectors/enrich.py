"""2-pass detail enrichment — 집계 사이트 상세 페이지에서 프로젝트 실제 URL 캐내기.

리스팅 페이지의 링크는 대부분 집계 사이트 자체 페이지(``airdrops.io/solpump/``)이고,
프로젝트의 진짜 주소는 상세 페이지의 리다이렉트(``airdrops.io/visit/<code>/``) 뒤에
있다. 교차소스 합의도 도메인 검사도 실제 도메인을 알아야 성립하므로, 후보를 좁힌 뒤
상세 페이지를 한 번 더 방문한다.

**계측** (spec §4.4): 실패 경로가 6개인데 전부 원본 ``Fact``를 돌려주면 어디서 샜는지
알 수 없다. enrichment는 앵커 성립의 병목이므로(spec §5.1) 결과와 함께 이유를 반환한다.
fail-safe 계약은 그대로다 — 예외를 올리지 않고 항상 ``Fact``를 돌려준다.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, replace

from airdropbot.collectors.browser import render, resolve_redirect
from airdropbot.collectors.extract import strip_fence
from airdropbot.kb.store import registrable_domain
from airdropbot.llm import LLMClient
from airdropbot.models import Fact

MAX_LINKS_IN_PROMPT = 120
MAX_DETAIL_CHARS = 200

# outcome 상수. 뭉쳐 있으면 분포를 봐도 고칠 곳이 안 정해지므로 원인별로 쪼갠다.
FILLED = "filled"
SKIPPED_NO_DETAIL_URL = "skipped_no_detail_url"
SKIPPED_ALREADY_KNOWN = "skipped_already_known"
RENDER_FAILED = "render_failed"
LLM_FAILED = "llm_failed"
# 우리 잘못 — 프롬프트·파싱을 고치면 회수할 수 있다.
UNPARSEABLE_OUTPUT = "unparseable_output"
# 데이터의 한계 — 페이지에 정말 없다.
NO_URL_REPORTED = "no_url_reported"
RESOLVE_FAILED = "resolve_failed"
REJECTED_SOCIAL = "rejected_social"
REJECTED_AGGREGATOR = "rejected_aggregator"
REJECTED_NO_DOMAIN = "rejected_no_domain"

OUTCOMES = (
    FILLED,
    SKIPPED_NO_DETAIL_URL,
    SKIPPED_ALREADY_KNOWN,
    RENDER_FAILED,
    LLM_FAILED,
    UNPARSEABLE_OUTPUT,
    NO_URL_REPORTED,
    RESOLVE_FAILED,
    REJECTED_SOCIAL,
    REJECTED_AGGREGATOR,
    REJECTED_NO_DOMAIN,
)

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


@dataclass(frozen=True)
class EnrichResult:
    """enrichment 결과 + 왜 그렇게 됐는지.

    ``detail``은 거부된 URL·도메인이나 실패 원인을 담는다. 개수만 세면 "무엇을
    거부했는지" 모르기 때문이다.
    """

    fact: Fact
    outcome: str
    detail: str = ""


def enrich_source_url(
    fact: Fact,
    llm: LLMClient,
    *,
    render_fn=render,
    resolve_fn=resolve_redirect,
) -> EnrichResult:
    """상세 페이지를 방문해 ``source_url``을 프로젝트 실제 주소로 채운다.

    어떤 단계든 실패하면 원본 ``fact``를 그대로 돌려주고 실패 지점을 ``outcome``에
    남긴다 — enrichment 실패가 파이프라인을 죽여서는 안 된다.
    """
    if not fact.detail_url:
        return EnrichResult(fact, SKIPPED_NO_DETAIL_URL)
    if fact.source_url:
        return EnrichResult(fact, SKIPPED_ALREADY_KNOWN)

    try:
        page = render_fn(fact.detail_url)
    except Exception as exc:
        return EnrichResult(fact, RENDER_FAILED, _describe(exc))

    links = "\n".join(f"- {t}: {h}" for t, h in page.links[:MAX_LINKS_IN_PROMPT])
    prompt = f"PROJECT: {fact.project}\nPAGE: {page.url}\n\nLINKS:\n{links}"
    try:
        raw = llm.complete(_SYSTEM, prompt)
    except Exception as exc:
        return EnrichResult(fact, LLM_FAILED, _describe(exc))

    data = _parse_json_object(raw)
    if data is None or "url" not in data:
        # 스키마를 어긴 것과 null을 보고한 것은 다르다 — 앞은 고칠 수 있다.
        return EnrichResult(fact, UNPARSEABLE_OUTPUT, _clip(raw))

    url = (data.get("url") or "").strip()
    if not url:
        return EnrichResult(fact, NO_URL_REPORTED)

    aggregator = registrable_domain(fact.detail_url)
    if registrable_domain(url) == aggregator:
        try:
            url = resolve_fn(url)
        except Exception as exc:
            return EnrichResult(fact, RESOLVE_FAILED, _describe(exc))

    domain = registrable_domain(url)
    if not domain:
        return EnrichResult(fact, REJECTED_NO_DOMAIN, _clip(url))
    if domain == aggregator:
        return EnrichResult(fact, REJECTED_AGGREGATOR, f"{domain} ({_clip(url)})")
    if domain in _SOCIAL_DOMAINS:
        return EnrichResult(fact, REJECTED_SOCIAL, f"{domain} ({_clip(url)})")

    return EnrichResult(replace(fact, source_url=url), FILLED, url)


def _parse_json_object(raw: str) -> dict | None:
    """JSON 객체를 돌려준다. 파싱 불가면 ``None`` — ``{}``와 구별해야 한다."""
    try:
        data = json.loads(strip_fence(raw))
    except (ValueError, TypeError):
        return None
    return data if isinstance(data, dict) else None


def _describe(exc: Exception) -> str:
    return _clip(f"{type(exc).__name__}: {exc}")


def _clip(text: str) -> str:
    """원문 전체를 담으면 요약이 로그가 된다."""
    text = " ".join(str(text).split())
    return text if len(text) <= MAX_DETAIL_CHARS else text[:MAX_DETAIL_CHARS] + "…"
