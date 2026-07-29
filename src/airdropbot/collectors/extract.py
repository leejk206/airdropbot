"""렌더된 페이지 → 구조화된 :class:`Fact` 목록 (소스당 LLM 1회 호출)."""
from __future__ import annotations

import hashlib
import json
import re

from airdropbot.collectors.browser import RenderedPage
from airdropbot.kb.store import registrable_domain
from airdropbot.llm import LLMClient
from airdropbot.models import Fact

MAX_LINKS_IN_PROMPT = 80

_SYSTEM = (
    "You extract airdrop opportunities from a rendered web page. "
    "Return STRICT JSON only: an array of objects with keys "
    '"project", "content", "detail_url", "source_url", "chain", "tags", "expires_at". '
    '"content" is a one-line Korean summary. "detail_url" is the link on THIS site '
    "that describes the project in detail (take it from the provided links; this is "
    'usually an internal page of the aggregator). "source_url" is the project\'s OWN '
    "website if — and only if — it appears in the links; otherwise null. "
    '"expires_at" is YYYY-MM-DD or null. "tags" is a string array. '
    "Output nothing except the JSON array (a ```json fence is tolerated)."
)


def extract_facts(page: RenderedPage, llm: LLMClient, *, now: str) -> list[Fact]:
    """페이지에서 Fact 목록을 추출. 어떤 실패든 빈 목록으로 흡수한다.

    수집 오류의 대가는 broadcast의 틀린 줄 하나뿐이고 되돌릴 수 있으므로,
    여기서는 파이프라인을 죽이지 않는 쪽을 택한다.
    """
    source = registrable_domain(page.url) or page.url
    links = "\n".join(f"- {t}: {h}" for t, h in page.links[:MAX_LINKS_IN_PROMPT])
    prompt = f"URL: {page.url}\nTITLE: {page.title}\n\nTEXT:\n{page.text}\n\nLINKS:\n{links}"

    try:
        raw = llm.complete(_SYSTEM, prompt)
    except Exception:
        return []

    facts: list[Fact] = []
    for entry in _parse_json_array(raw):
        project = (entry.get("project") or "").strip()
        if not project:
            continue
        content = (entry.get("content") or "").strip()
        facts.append(
            Fact(
                id=_fact_id(source, project, content),
                project=project,
                content=content,
                source=source,
                collected_at=now,
                detail_url=entry.get("detail_url") or None,
                source_url=entry.get("source_url") or None,
                chain=entry.get("chain") or None,
                tags=tuple(entry.get("tags") or ()),
                expires_at=entry.get("expires_at") or None,
            )
        )
    return facts


def _parse_json_array(raw: str) -> list[dict]:
    try:
        data = json.loads(strip_fence(raw))
    except (ValueError, TypeError):
        return []
    return [d for d in data if isinstance(d, dict)] if isinstance(data, list) else []


def strip_fence(text: str) -> str:
    """```json ... ``` (또는 맨 ```) 펜스를 벗겨낸다."""
    s = text.strip()
    if s.startswith("```"):
        s = re.sub(r"^```[a-zA-Z]*\n?", "", s)
        s = re.sub(r"\n?```$", "", s)
    return s.strip()


def _fact_id(source: str, project: str, content: str) -> str:
    digest = hashlib.sha256(f"{source}|{project}|{content}".encode()).hexdigest()[:12]
    slug = re.sub(r"[^a-z0-9]+", "-", project.lower()).strip("-")
    return f"{slug}-{digest}"
