"""렌더된 페이지 → 구조화된 :class:`Fact` 목록 (소스당 LLM 1회 호출)."""
from __future__ import annotations

import hashlib
import json
import re

from airdropbot.collectors.browser import MAX_LINKS, RenderedPage
from airdropbot.kb.store import project_key, registrable_domain
from airdropbot.llm import LLMClient
from airdropbot.models import Fact

# 링크 예산은 **수집 단 한 곳에서만** 정한다 (spec §4.5). 여기서 한 번 더 자르면
# 프롬프트 층이 조용히 detail_url 커버리지의 상한을 정하게 된다 — 실측(2026-08-01)에서
# 이 값이 80이던 동안 `airdrops.io`의 상세 링크는 index 1~147에 분포(중앙값 73)해서
# 정확히 절반이 잘렸고, 그것이 커버리지 49%의 원인이었다. 대조군인 100% 소스 두 곳은
# 상세 링크가 애초에 80 안에 들어와서 안 잘렸던 것뿐이다.
MAX_LINKS_IN_PROMPT = MAX_LINKS

_SYSTEM = (
    "You extract airdrop opportunities from a rendered web page. "
    "Return STRICT JSON only: an array of objects with keys "
    '"project", "content", "detail_url", "source_url", "chain", "tags", "expires_at", '
    '"funding_usd", "backers", "research_count", "capital_required_usd", "time_minutes". '
    '"content" is a one-line Korean summary. "detail_url" is the link on THIS site '
    "that describes the project in detail (take it from the provided links; this is "
    'usually an internal page of the aggregator). "source_url" is the project\'s OWN '
    "website if — and only if — it appears in the links; otherwise null. "
    '"expires_at" is the deadline or expected TGE date as YYYY-MM-DD, or null. '
    '"tags" is a string array. '
    '"funding_usd" is the total raised in USD as a number (45000000, not "45M"). '
    '"backers" is an array of named investors. "research_count" is the number of '
    'research/report entries the page states. "capital_required_usd" is the money the '
    'user must deploy (0 if the task is free apart from gas). "time_minutes" is the '
    "stated time to complete. "
    "CRITICAL: fill these ONLY from values the page states explicitly. Never estimate, "
    "infer, or recall from your own knowledge — use null (or [] for backers) when the "
    "page does not say. A wrong number here silently distorts downstream ranking. "
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
                id=_fact_id(source, project),
                project=project,
                content=content,
                source=source,
                collected_at=now,
                detail_url=entry.get("detail_url") or None,
                source_url=entry.get("source_url") or None,
                chain=entry.get("chain") or None,
                tags=tuple(entry.get("tags") or ()),
                expires_at=entry.get("expires_at") or None,
                funding_usd=_number(entry.get("funding_usd")),
                backers=tuple(str(b) for b in (entry.get("backers") or ()) if b),
                research_count=_integer(entry.get("research_count")),
                capital_required_usd=_number(entry.get("capital_required_usd")),
                time_minutes=_integer(entry.get("time_minutes")),
            )
        )
    return facts


def _number(value) -> float | None:
    """숫자만 통과시킨다. LLM이 "unknown"·"~10"·"45M"을 보내도 죽지 않는다.

    파싱 실패를 0으로 접으면 "자본 0"(분모 +1)이 근거 없이 켜진다. None이어야
    별점 룰의 "정보 부족 시 미부착"으로 떨어진다.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _integer(value) -> int | None:
    number = _number(value)
    return None if number is None else int(number)


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


def _fact_id(source: str, project: str) -> str:
    """``(source, project)``만의 함수 — spec §5.1.1 규칙 ①.

    한때 ``content``도 해싱했는데, 그건 LLM이 매 실행 새로 쓰는 한국어 요약이라
    문구가 한 글자만 달라도 id가 바뀌었다. `put`이 id 기준 upsert이므로 dedupe가
    전혀 걸리지 않아 **KB가 매 실행 자기를 복제했다** (실측 2026-08-01: 319 팩트가
    실은 160 프로젝트의 2중 적재, 170쌍 중 149쌍 중복).

    id가 안정되면 재추출본이 기존 팩트를 덮으므로 `FactStore.put`의 병합
    의미론(규칙 ②)이 필수 짝이다 — 없으면 enrichment 결과가 매일 날아간다.
    """
    digest = hashlib.sha256(f"{source}|{project_key(project)}".encode()).hexdigest()[:12]
    slug = re.sub(r"[^a-z0-9]+", "-", project.lower()).strip("-")
    return f"{slug}-{digest}"
