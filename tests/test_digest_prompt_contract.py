"""Track A 프롬프트 ↔ KB 배선의 계약 테스트 (spec §11.2).

프롬프트는 32KB의 튜닝된 자산이고 코드가 아니라 자연어라 회귀를 조용히 겪는다.
여기서 고정하는 것은 **배선의 뼈대**뿐이다 — 별점 가중치나 출력 포맷 같은 판단
규칙은 건드리지 않았음을 확인하는 것이 목적이지, 그 내용을 테스트하는 게 아니다.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from airdropbot.models import Fact

PROMPT = Path(__file__).resolve().parent.parent / "prompts" / "airdrop_digest.md"


@pytest.fixture(scope="module")
def prompt() -> str:
    return PROMPT.read_text(encoding="utf-8")


def test_prompt_reads_kb_instead_of_scraping_listings(prompt):
    assert "cache/kb.yaml" in prompt
    # 리스팅 6개 병렬 WebFetch 지시가 남아 있으면 배선이 안 된 것이다.
    assert "6개 `WebFetch` tool call" not in prompt
    assert "### 1. 소스 로드" not in prompt


def test_prompt_documents_every_kb_field_it_consumes(prompt):
    """KB 스키마와 프롬프트가 어긋나면 신호가 조용히 누락된다."""
    consumed = (
        "project", "content", "tags", "source", "detail_url", "official_url",
        "source_url", "funding_usd", "backers", "research_count",
        "capital_required_usd", "time_minutes", "expires_at", "collected_at",
    )
    for field in consumed:
        assert field in prompt, f"프롬프트가 KB 필드 {field}를 언급하지 않는다"


def test_consumed_fields_exist_on_fact_model(prompt):
    """프롬프트가 기대하는 필드가 실제 Fact에 있는지 — 스키마 드리프트 방지."""
    for field in (
        "funding_usd", "backers", "research_count",
        "capital_required_usd", "time_minutes", "detail_url", "official_url",
    ):
        assert field in Fact.__dataclass_fields__


def test_tge_comes_only_from_detail_page(prompt):
    """리스팅 날짜를 TGE로 쓰는 것은 알려진 오염원이다 (spec §11.1.1)."""
    assert "Reward Date" in prompt
    # §7.3 만료 계산이 더 이상 리스팅(§2) 결과를 참조하면 안 된다.
    assert "TGE 일자 정보를 §2 WebFetch 결과에서 회수" not in prompt


def test_kb_freshness_guard_present(prompt):
    """KB가 비었을 때 조용히 낡은 다이제스트를 내지 않아야 한다."""
    assert "KB_EMPTY" in prompt


def test_judgment_assets_untouched(prompt):
    """spec §11 확정사항 — 별점·출력·auto-pin 규칙은 배선 대상이 아니다."""
    for anchor in (
        "#### 3.2 추천도 별점 산정",
        "분자 가드",
        "#### 5.9 출력 컨트랙트",
        "### 7. 자동 pin upsert",
        "===CATEGORY_SPLIT===",
    ):
        assert anchor in prompt, f"판단 자산 {anchor!r}이 사라졌다"
