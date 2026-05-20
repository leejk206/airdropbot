"""sources.yaml 스키마 검증.

routine 실행 전 sources.yaml이 깨지지 않았는지 빠르게 잡기 위함.
"""
from pathlib import Path
from urllib.parse import urlparse

import pytest
import yaml

VALID_ROLES = {"primary", "backing-data", "low-effort", "catalog", "official"}
SOURCES_PATH = Path(__file__).resolve().parent.parent / "sources.yaml"


@pytest.fixture(scope="module")
def sources_data() -> dict:
    with SOURCES_PATH.open(encoding="utf-8") as f:
        return yaml.safe_load(f)


def test_sources_yaml_top_level_shape(sources_data: dict) -> None:
    assert "sources" in sources_data, "top-level key 'sources' 누락"
    assert isinstance(sources_data["sources"], list)
    assert len(sources_data["sources"]) > 0, "sources 비어있음"


def test_each_source_has_required_fields(sources_data: dict) -> None:
    required = {"url", "role", "note"}
    for i, src in enumerate(sources_data["sources"]):
        missing = required - set(src.keys())
        assert not missing, f"sources[{i}]에 누락된 필드: {missing}"


def test_each_source_url_is_http(sources_data: dict) -> None:
    for src in sources_data["sources"]:
        parsed = urlparse(src["url"])
        assert parsed.scheme in {"http", "https"}, f"bad scheme: {src['url']}"
        assert parsed.netloc, f"missing host: {src['url']}"


def test_each_source_role_is_in_enum(sources_data: dict) -> None:
    for src in sources_data["sources"]:
        assert src["role"] in VALID_ROLES, (
            f"invalid role {src['role']!r} (allowed: {sorted(VALID_ROLES)})"
        )


def test_each_source_note_nonempty(sources_data: dict) -> None:
    for src in sources_data["sources"]:
        note = src["note"]
        assert isinstance(note, str) and note.strip(), (
            f"note 비어있음: {src['url']}"
        )
