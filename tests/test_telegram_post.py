"""telegram_post.py 단위/통합 테스트."""
from __future__ import annotations

import pytest
import requests
from unittest.mock import patch

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


# ============ send/retry 테스트 (Task 4) ============


class _FakeResp:
    def __init__(self, status_code: int, text: str = ""):
        self.status_code = status_code
        self.text = text

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code}: {self.text}")


def test_send_chunk_posts_to_telegram_api():
    from airdropbot.telegram_post import _send_chunk

    with patch("airdropbot.telegram_post.requests.post") as mock_post:
        mock_post.return_value = _FakeResp(200, '{"ok":true}')
        _send_chunk(token="T", chat_id="@x", text="hello")
        mock_post.assert_called_once()
        url = mock_post.call_args[0][0]
        assert url == "https://api.telegram.org/botT/sendMessage"
        json_arg = mock_post.call_args[1]["json"]
        assert json_arg == {"chat_id": "@x", "text": "hello"}


def test_send_chunk_retries_once_on_5xx_then_succeeds():
    from airdropbot.telegram_post import _send_chunk

    with patch("airdropbot.telegram_post.requests.post") as mock_post, \
         patch("airdropbot.telegram_post.time.sleep") as mock_sleep:
        mock_post.side_effect = [_FakeResp(503, "fail"), _FakeResp(200, "ok")]
        _send_chunk(token="T", chat_id="@x", text="hello")
        assert mock_post.call_count == 2
        mock_sleep.assert_called_once_with(60.0)


def test_send_chunk_raises_when_5xx_persists_after_retry():
    from airdropbot.telegram_post import _send_chunk

    with patch("airdropbot.telegram_post.requests.post") as mock_post, \
         patch("airdropbot.telegram_post.time.sleep"):
        mock_post.return_value = _FakeResp(503, "fail")
        with pytest.raises(requests.HTTPError):
            _send_chunk(token="T", chat_id="@x", text="hello")
        assert mock_post.call_count == 2


def test_send_chunk_does_not_retry_on_4xx():
    from airdropbot.telegram_post import _send_chunk

    with patch("airdropbot.telegram_post.requests.post") as mock_post, \
         patch("airdropbot.telegram_post.time.sleep") as mock_sleep:
        mock_post.return_value = _FakeResp(400, "bad")
        with pytest.raises(requests.HTTPError):
            _send_chunk(token="T", chat_id="@x", text="hello")
        assert mock_post.call_count == 1
        mock_sleep.assert_not_called()
