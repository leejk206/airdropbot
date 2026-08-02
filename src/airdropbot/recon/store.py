"""``actions.yaml`` — 액션 레시피 영속화.

Phase 2(실행 엔진)의 입력이자, v1 운영 며칠치가 쌓이면 체인·액션 범위를 정하는
실측 데이터가 된다.
"""
from __future__ import annotations

import os
from pathlib import Path

import yaml

from airdropbot.models import Recipe, Step, recipe_hash


def load_recipes(path: str | Path) -> list[Recipe]:
    path = Path(path)
    if not path.exists():
        return []
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return [_recipe_from_dict(d) for d in raw.get("recipes") or []]


def save_recipes(path: str | Path, recipes: list[Recipe]) -> None:
    path = Path(path)
    payload = {"recipes": [_recipe_to_dict(r) for r in recipes]}
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        yaml.safe_dump(payload, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    os.replace(str(tmp), str(path))


def _recipe_to_dict(recipe: Recipe) -> dict:
    return {
        "project": recipe.project,
        "recipe_hash": recipe_hash(recipe),
        "entry_url": recipe.entry_url,
        "chain": recipe.chain,
        "signature_kind": recipe.signature_kind,
        "approve_unlimited": recipe.approve_unlimited,
        "capital_required_usd": recipe.capital_required_usd,
        "steps": [
            {
                "action": s.action,
                "target": s.target,
                # 스텝 단위 자동화 판정 (spec §12.5). 실행 상한의 유일한 근거다.
                "automatable": s.automatable,
                "blocker": s.blocker,
            }
            for s in recipe.steps
        ],
        "automatable": recipe.automatable,
        "blockers": list(recipe.blockers),
        "reconned_at": recipe.reconned_at,
        # v1은 실행하지 않으므로 항상 null. v2에서 council 판정이 채워진다.
        "verdict": None,
    }


def _recipe_from_dict(data: dict) -> Recipe:
    return Recipe(
        project=data["project"],
        entry_url=data["entry_url"],
        steps=tuple(
            Step(
                action=s.get("action", ""),
                target=s.get("target", ""),
                # 태그가 없는 구 레시피는 False로 읽힌다 — 실행 권한을 소급 부여하지
                # 않는다. 읽히기는 하되 실행 상한 0이다. spec §12.5.2.
                automatable=bool(s.get("automatable")),
                blocker=s.get("blocker") or None,
            )
            for s in data.get("steps") or []
        ),
        chain=data.get("chain"),
        signature_kind=data.get("signature_kind") or "none",
        approve_unlimited=bool(data.get("approve_unlimited")),
        capital_required_usd=float(data.get("capital_required_usd") or 0),
        automatable=data.get("automatable") or "manual",
        blockers=tuple(data.get("blockers") or ()),
        reconned_at=data.get("reconned_at") or "",
    )
