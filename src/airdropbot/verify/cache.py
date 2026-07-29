"""verdict 캐시.

키는 ``recipe_hash``다. 레시피가 바뀌면 해시가 바뀌어 캐시가 **자동 무효화**되므로
별도 만료 로직이 필요 없다. 같은 프로젝트의 반복 활동(데일리 체크인 등)은 최초
1회만 심의하면 된다.
"""
from __future__ import annotations

import os
from pathlib import Path

import yaml

from airdropbot.models import Verdict


def load_verdicts(path: str | Path) -> dict[str, Verdict]:
    path = Path(path)
    if not path.exists():
        return {}
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return {
        key: Verdict(passed=bool(value.get("passed")), issues=tuple(value.get("issues") or ()))
        for key, value in (raw.get("verdicts") or {}).items()
    }


def save_verdicts(path: str | Path, verdicts: dict[str, Verdict]) -> None:
    path = Path(path)
    payload = {
        "verdicts": {
            key: {"passed": v.passed, "issues": list(v.issues)} for key, v in verdicts.items()
        }
    }
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        yaml.safe_dump(payload, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    os.replace(str(tmp), str(path))
