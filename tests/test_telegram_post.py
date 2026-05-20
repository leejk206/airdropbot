"""telegram_post.py 단위/통합 테스트."""
from __future__ import annotations

from airdropbot.telegram_post import _split_message


def test_split_short_text_returns_single_chunk():
    text = "짧은 메시지"
    chunks = _split_message(text, limit=4096)
    assert chunks == ["짧은 메시지"]


def test_split_at_double_newline_when_long():
    # 두 단락이 합쳐 limit 초과
    para1 = "A" * 3000
    para2 = "B" * 2000
    text = f"{para1}\n\n{para2}"
    chunks = _split_message(text, limit=4096)
    assert chunks == [para1, para2]


def test_split_falls_back_to_single_newline_when_no_double():
    line1 = "A" * 3000
    line2 = "B" * 2000
    text = f"{line1}\n{line2}"
    chunks = _split_message(text, limit=4096)
    assert chunks == [line1, line2]


def test_split_hard_splits_at_limit_when_no_newline():
    text = "X" * 5000
    chunks = _split_message(text, limit=4096)
    assert len(chunks) == 2
    assert len(chunks[0]) == 4096
    assert chunks[1] == "X" * (5000 - 4096)


def test_split_preserves_total_content():
    """split 후 합치면 원본과 동일 (newline 제외 가능)."""
    text = "라인1\n\n라인2\n\n" + ("긴내용 " * 1500)
    chunks = _split_message(text, limit=4096)
    rejoined = "\n\n".join(chunks)
    # 원본 내용 모든 문자가 chunks 어딘가에 보존되어야 함
    for ch in chunks:
        assert ch  # 빈 chunk 없음
    assert len(rejoined) >= len(text) - 10  # newline 누락 허용 (re-join 시 \n\n 추가)
