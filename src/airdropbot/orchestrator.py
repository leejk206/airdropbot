"""전 구간 오케스트레이션: 수집 → enrichment → KB → 선정 → 정찰 → 실행 게이트.

오케스트레이터가 Python이므로 LLM은 짧게 잘린 조각으로만 호출된다. 기존
``daily.py``처럼 claude CLI 한 번이 전부를 처리하던 구조와 달리 타임아웃이
호출당 상한으로 바뀌고, 총 소요는 Playwright가 지배한다.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path

from airdropbot.collectors.browser import render, resolve_redirect
from airdropbot.collectors.enrich import FILLED, SKIPPED_ALREADY_KNOWN, enrich_source_url
from airdropbot.collectors.extract import extract_facts
from airdropbot.execute.guard import Limits
from airdropbot.execute.runner import run_recipe
from airdropbot.kb.store import FactStore, project_key, resolve_official_urls
from airdropbot.llm import LLMClient
from airdropbot.models import Fact
from airdropbot.recon.scout import scout_recipe
from airdropbot.recon.store import load_recipes, save_recipes
from airdropbot.selection import select_targets

_MIN_SOURCES_FOR_ANCHOR = 2


def run_pipeline(
    *,
    sources: list[str],
    kb_path: str | Path,
    actions_path: str | Path,
    llm: LLMClient,
    now: str,
    render_fn=render,
    resolve_fn=resolve_redirect,
    limit: int = 10,
    dry_run: bool = True,
    limits: Limits | None = None,
) -> dict:
    """하루치 파이프라인을 1회 실행하고 요약 dict를 반환한다.

    소스 하나가 죽어도 나머지로 진행한다. enrichment·정찰 실패는 해당 프로젝트만
    건너뛴다.
    """
    limits = limits or Limits()

    # enrichment는 앵커 성립의 병목이고 실패가 조용하다. 개수와 이유를 모아 요약에
    # 싣는다 — 무엇이 얼마나 새는지 모르면 고칠 곳을 정할 수 없다. spec §4.4.
    enrich_counts: Counter[str] = Counter()
    enrich_log: list[dict] = []

    def enrich(fact: Fact) -> Fact:
        result = enrich_source_url(fact, llm, render_fn=render_fn, resolve_fn=resolve_fn)
        enrich_counts[result.outcome] += 1
        # 성공과 "이미 알고 있음"은 개수로 충분하다. 로그는 고칠 것만 담는다.
        if result.outcome not in (FILLED, SKIPPED_ALREADY_KNOWN):
            enrich_log.append(
                {
                    "project": fact.project,
                    "source": fact.source,
                    "outcome": result.outcome,
                    "detail": result.detail,
                }
            )
        return result.fact

    collected: list[Fact] = []
    for url in sources:
        try:
            page = render_fn(url)
        except Exception:
            continue
        collected.extend(extract_facts(page, llm, now=now))

    # 앵커링 후보 = 2개 이상 소스가 이름을 언급한 프로젝트. 이들만 합의가 성립할 수
    # 있으므로 비싼 상세 방문을 여기에만 쓴다.
    anchor_candidates = _multi_source_projects(collected)
    collected = [
        enrich(f) if project_key(f.project) in anchor_candidates else f for f in collected
    ]

    anchored = resolve_official_urls(collected)
    store = FactStore.load(kb_path)
    for fact in anchored:
        store.put(fact)

    targets = select_targets(store.query(now=now), now=now, limit=limit)

    recipes = {r.entry_url: r for r in load_recipes(actions_path)}
    runs = []
    for fact in targets:
        # 정찰은 읽기 전용이므로 앵커가 없어도 수행한다 — v1의 목적이 실측 레시피
        # 축적이기 때문. 앵커 부재는 실행 게이트(guard)가 막는다.
        if not (fact.official_url or fact.source_url):
            fact = enrich(fact)
            store.put(fact)
        url = fact.official_url or fact.source_url
        if not url:
            continue
        try:
            page = render_fn(url)
        except Exception:
            continue
        recipe = scout_recipe(fact, page, llm, now=now)
        if recipe is None:
            continue
        recipes[recipe.entry_url] = recipe
        runs.append(run_recipe(recipe, store.all(), limits, llm=llm, dry_run=dry_run))

    store.save(kb_path)
    save_recipes(actions_path, list(recipes.values()))

    return {
        "facts": len(anchored),
        "anchored": sum(1 for f in anchored if f.official_url),
        "targets": len(targets),
        "recipes": len(recipes),
        "runs": runs,
        "enrich": dict(enrich_counts),
        "enrich_log": enrich_log,
    }


def _multi_source_projects(facts: list[Fact]) -> set[str]:
    """2개 이상 소스가 언급한 프로젝트의 정규화 키 집합."""
    by_project: dict[str, set[str]] = defaultdict(set)
    for fact in facts:
        by_project[project_key(fact.project)].add(fact.source)
    return {p for p, srcs in by_project.items() if len(srcs) >= _MIN_SOURCES_FOR_ANCHOR}
