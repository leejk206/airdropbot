"""팩트 KB — 저장/조회/만료 + 교차소스 ``official_url`` 합의."""
from __future__ import annotations

import os
from collections import defaultdict
from dataclasses import asdict, replace
from pathlib import Path
from urllib.parse import urlparse

import yaml

from airdropbot.models import Fact

_MULTIPART_SUFFIXES = frozenset(
    {"co.uk", "co.kr", "com.br", "com.au", "co.jp", "co.in", "com.cn", "co.za"}
)
_MIN_SOURCES_FOR_OFFICIAL = 2


def registrable_domain(url: str | None) -> str | None:
    """등록 도메인(eTLD+1)을 반환. 판정 불가 시 None.

    서브도메인 차이는 흡수하고 타이포스쿼팅·유사 TLD는 다른 값으로 갈라놓는 것이
    목적이다. 외부 의존성(tldextract) 없이 다중 파트 접미사만 예외 처리한다.
    """
    if not url:
        return None
    parsed = urlparse(url if "//" in url else f"//{url}")
    host = (parsed.hostname or "").lower().removeprefix("www.")
    if not host or "." not in host:
        return None
    labels = host.split(".")
    if len(labels) >= 3 and ".".join(labels[-2:]) in _MULTIPART_SUFFIXES:
        return ".".join(labels[-3:])
    return ".".join(labels[-2:])


def project_key(project: str) -> str:
    """프로젝트명 매칭용 정규화 키.

    소스마다 표기가 흔들린다("Polymarket" / "polymarket " / "Poly  market").
    앵커 합의는 이름 매칭에 전적으로 의존하므로 대소문자·공백 차이는 흡수한다.
    """
    return " ".join(project.lower().split())


def resolve_official_urls(facts: list[Fact]) -> list[Fact]:
    """서로 다른 2개 이상 소스가 동의한 도메인만 ``official_url``로 승격.

    단일 소스 URL은 ``official_url=None``으로 남아 실행 게이트를 통과하지 못한다.
    드레이너 1차 방어선이다.
    """
    by_project: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    for fact in facts:
        domain = registrable_domain(fact.source_url)
        if domain:
            by_project[project_key(fact.project)][domain].add(fact.source)

    out: list[Fact] = []
    for fact in facts:
        domain = registrable_domain(fact.source_url)
        agreed = bool(
            domain
            and len(by_project[project_key(fact.project)][domain]) >= _MIN_SOURCES_FOR_OFFICIAL
        )
        out.append(replace(fact, official_url=fact.source_url if agreed else None))
    return out


class FactStore:
    """팩트 저장소. id 기준 upsert, 만료 팩트는 :meth:`query`에서 제외된다."""

    def __init__(self, facts: list[Fact] | None = None):
        self._facts: dict[str, Fact] = {f.id: f for f in (facts or [])}

    def put(self, fact: Fact) -> None:
        """id 기준 upsert. 단, 들어온 선택 필드가 비어 있으면 기존 값을 유지한다.

        spec §5.1.1 규칙 ②. id가 ``(source, project)``로 안정된 뒤로는 매 실행의
        **재추출 팩트**가 같은 id로 들어오는데, 그 팩트는 대개 ``source_url``·
        ``official_url``이 ``None``이다. 통째 replace면 enrichment가 렌더+LLM을
        써서 캐낸 값을 매일 null로 덮어쓴다 — 병합은 선택이 아니라 규칙 ①의 짝이다.

        반대로 ``content``·``collected_at``은 최신값으로 갱신한다. 이쪽은
        "가장 최근에 관측한 서술"이 맞기 때문이다.
        """
        existing = self._facts.get(fact.id)
        self._facts[fact.id] = _merge_facts(existing, fact) if existing else fact

    def all(self) -> list[Fact]:
        return list(self._facts.values())

    def query(self, *, now: str, tags: list[str] | None = None) -> list[Fact]:
        wanted = set(tags or [])
        return [
            f
            for f in self._facts.values()
            if not (f.expires_at and f.expires_at < now) and (not wanted or wanted & set(f.tags))
        ]

    def save(self, path: str | Path) -> None:
        path = Path(path)
        payload = {"facts": [_fact_to_dict(f) for f in self._facts.values()]}
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(
            yaml.safe_dump(payload, allow_unicode=True, sort_keys=False), encoding="utf-8"
        )
        os.replace(str(tmp), str(path))

    @classmethod
    def load(cls, path: str | Path) -> FactStore:
        path = Path(path)
        if not path.exists():
            return cls([])
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return cls([_fact_from_dict(d) for d in raw.get("facts") or []])


# 비어 있으면 기존 값을 유지하는 선택 필드 (spec §5.1.1 규칙 ②).
_MERGED_OPTIONAL_FIELDS = ("detail_url", "source_url", "official_url", "chain", "expires_at")


def _merge_facts(old: Fact, new: Fact) -> Fact:
    """``new``를 기준으로 하되, 비어 있는 선택 필드는 ``old``에서 가져온다."""
    filled = {
        name: getattr(old, name)
        for name in _MERGED_OPTIONAL_FIELDS
        if getattr(new, name) is None and getattr(old, name) is not None
    }
    if not new.tags and old.tags:
        filled["tags"] = old.tags
    return replace(new, **filled) if filled else new


def _fact_to_dict(fact: Fact) -> dict:
    data = asdict(fact)
    data["tags"] = list(fact.tags)
    return data


def _fact_from_dict(data: dict) -> Fact:
    data = dict(data)
    data["tags"] = tuple(data.get("tags") or ())
    return Fact(**data)
