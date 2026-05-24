"""pinned.yaml 스키마 검증.

routine 실행 전 pinned.yaml이 깨지지 않았는지 빠르게 잡기 위함.
"""
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

import pytest
import yaml

PINNED_PATH = Path(__file__).resolve().parent.parent / "pinned.yaml"
ID_PATTERN = re.compile(r"^[a-z0-9-]+$")
ID_MAX_LEN = 64
REQUIRED = {"id", "name", "pinned_at", "expires_at", "source_url", "snapshot_md"}
OPTIONAL = {"expires_label", "activity_url", "official_url", "auto_pinned", "tge_date"}


def _load() -> dict:
    with PINNED_PATH.open(encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _parse_iso(value: str) -> datetime:
    """Parse ISO 8601 datetime, requiring tzinfo (offset 또는 Z)."""
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    assert dt.tzinfo is not None, f"timezone-aware datetime 필요: {value!r}"
    return dt


@pytest.fixture(scope="module")
def pinned_data() -> dict:
    return _load()


def test_pinned_yaml_top_level_shape(pinned_data: dict) -> None:
    assert "pins" in pinned_data, "top-level key 'pins' 누락"
    assert isinstance(pinned_data["pins"], list)


def test_each_pin_has_required_fields(pinned_data: dict) -> None:
    for i, pin in enumerate(pinned_data["pins"]):
        missing = REQUIRED - set(pin.keys())
        assert not missing, f"pins[{i}]에 누락된 필드: {missing}"
        unknown = set(pin.keys()) - REQUIRED - OPTIONAL
        assert not unknown, f"pins[{i}]에 알 수 없는 필드: {unknown}"


def test_each_pin_id_pattern(pinned_data: dict) -> None:
    for pin in pinned_data["pins"]:
        pid = pin["id"]
        assert isinstance(pid, str)
        assert ID_PATTERN.match(pid), f"id 패턴 위반: {pid!r}"
        assert len(pid) <= ID_MAX_LEN, f"id 너무 김: {pid!r}"


def test_pin_ids_unique(pinned_data: dict) -> None:
    ids = [pin["id"] for pin in pinned_data["pins"]]
    assert len(ids) == len(set(ids)), f"id 중복: {ids}"


def test_each_pin_datetime_aware(pinned_data: dict) -> None:
    for i, pin in enumerate(pinned_data["pins"]):
        _parse_iso(pin["pinned_at"])
        if pin["expires_at"] is not None:
            _parse_iso(pin["expires_at"])


def test_expires_at_after_pinned_at(pinned_data: dict) -> None:
    for i, pin in enumerate(pinned_data["pins"]):
        if pin["expires_at"] is None:
            continue
        pinned_at = _parse_iso(pin["pinned_at"])
        expires_at = _parse_iso(pin["expires_at"])
        assert expires_at >= pinned_at, (
            f"pins[{i}] expires_at({expires_at}) < pinned_at({pinned_at})"
        )


def test_each_pin_snapshot_md_nonempty(pinned_data: dict) -> None:
    for i, pin in enumerate(pinned_data["pins"]):
        snap = pin["snapshot_md"]
        assert isinstance(snap, str) and snap.strip(), (
            f"pins[{i}].snapshot_md 비어있음"
        )


def test_each_pin_name_nonempty(pinned_data: dict) -> None:
    for i, pin in enumerate(pinned_data["pins"]):
        name = pin["name"]
        assert isinstance(name, str) and name.strip(), (
            f"pins[{i}].name 비어있음"
        )


def test_each_pin_source_url_http(pinned_data: dict) -> None:
    from urllib.parse import urlparse
    for i, pin in enumerate(pinned_data["pins"]):
        parsed = urlparse(pin["source_url"])
        assert parsed.scheme in {"http", "https"}, (
            f"pins[{i}].source_url scheme 위반: {pin['source_url']!r}"
        )
        assert parsed.netloc, f"pins[{i}].source_url host 누락"
