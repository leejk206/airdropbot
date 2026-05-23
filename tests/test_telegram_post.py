"""telegram_post.py 단위/통합 테스트."""
from __future__ import annotations

import pytest
import requests
from unittest.mock import patch

from airdropbot.telegram_post import _split_message, post


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


def test_send_chunk_posts_to_telegram_api_with_html_parse_mode():
    from airdropbot.telegram_post import _send_chunk

    with patch("airdropbot.telegram_post.requests.post") as mock_post:
        mock_post.return_value = _FakeResp(200, '{"ok":true}')
        _send_chunk(token="T", chat_id="@x", text="hello")
        mock_post.assert_called_once()
        url = mock_post.call_args[0][0]
        assert url == "https://api.telegram.org/botT/sendMessage"
        json_arg = mock_post.call_args[1]["json"]
        assert json_arg == {"chat_id": "@x", "text": "hello", "parse_mode": "HTML"}


def test_send_chunk_omits_parse_mode_when_none():
    from airdropbot.telegram_post import _send_chunk

    with patch("airdropbot.telegram_post.requests.post") as mock_post:
        mock_post.return_value = _FakeResp(200, '{"ok":true}')
        _send_chunk(token="T", chat_id="@x", text="hello", parse_mode=None)
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


def test_send_chunk_400_fallback_strips_parse_mode_and_retries():
    """HTML 400 → parse_mode 빼고 재전송 → 200이면 성공."""
    from airdropbot.telegram_post import _send_chunk

    with patch("airdropbot.telegram_post.requests.post") as mock_post, \
         patch("airdropbot.telegram_post.time.sleep") as mock_sleep:
        mock_post.side_effect = [_FakeResp(400, "bad html"), _FakeResp(200, "ok")]
        _send_chunk(token="T", chat_id="@x", text="<a>bad")
        assert mock_post.call_count == 2
        first_payload = mock_post.call_args_list[0][1]["json"]
        second_payload = mock_post.call_args_list[1][1]["json"]
        assert first_payload.get("parse_mode") == "HTML"
        assert "parse_mode" not in second_payload
        assert second_payload == {"chat_id": "@x", "text": "<a>bad"}
        mock_sleep.assert_not_called()


def test_send_chunk_400_fallback_raises_when_plain_also_fails():
    """HTML 400 → plain 재전송도 400 → raise."""
    from airdropbot.telegram_post import _send_chunk

    with patch("airdropbot.telegram_post.requests.post") as mock_post, \
         patch("airdropbot.telegram_post.time.sleep"):
        mock_post.return_value = _FakeResp(400, "still bad")
        with pytest.raises(requests.HTTPError):
            _send_chunk(token="T", chat_id="@x", text="hello")
        assert mock_post.call_count == 2


def test_send_chunk_400_without_parse_mode_does_not_retry():
    """parse_mode 없는 호출의 400은 fallback 안 함 — 즉시 raise."""
    from airdropbot.telegram_post import _send_chunk

    with patch("airdropbot.telegram_post.requests.post") as mock_post, \
         patch("airdropbot.telegram_post.time.sleep") as mock_sleep:
        mock_post.return_value = _FakeResp(400, "bad")
        with pytest.raises(requests.HTTPError):
            _send_chunk(token="T", chat_id="@x", text="hello", parse_mode=None)
        assert mock_post.call_count == 1
        mock_sleep.assert_not_called()


# ============ post() 오케스트레이션 테스트 (Task 5) ============


def test_post_sends_single_chunk_when_short(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "T")
    monkeypatch.setenv("TELEGRAM_CHANNEL_ID", "@x")
    sent: list[str] = []

    def fake_send(token, chat_id, text):
        sent.append(text)

    monkeypatch.setattr("airdropbot.telegram_post._send_chunk", fake_send)
    post("짧은 메시지")
    assert sent == ["짧은 메시지"]


def test_post_splits_and_delays_when_long(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "T")
    monkeypatch.setenv("TELEGRAM_CHANNEL_ID", "@x")
    sent: list[str] = []
    sleeps: list[float] = []

    def fake_send(token, chat_id, text):
        sent.append(text)

    def fake_sleep(sec):
        sleeps.append(sec)

    monkeypatch.setattr("airdropbot.telegram_post._send_chunk", fake_send)
    monkeypatch.setattr("airdropbot.telegram_post.time.sleep", fake_sleep)

    long_text = ("A" * 3000) + "\n\n" + ("B" * 2000)
    post(long_text)
    assert len(sent) == 2
    # chunk 사이 1초 delay
    assert sleeps == [1.0]


def test_post_raises_when_env_missing(monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHANNEL_ID", raising=False)
    with pytest.raises(RuntimeError, match="TELEGRAM_BOT_TOKEN"):
        post("x")


# ============ _split_by_separator 테스트 (Task 1) ============


def test_split_by_separator_single():
    from airdropbot.telegram_post import _split_by_separator
    text = "part1\n\n===CATEGORY_SPLIT===\n\npart2"
    result = _split_by_separator(text, "===CATEGORY_SPLIT===")
    assert result == ["part1", "part2"]


def test_split_by_separator_multiple():
    from airdropbot.telegram_post import _split_by_separator
    text = "a\n\n===CATEGORY_SPLIT===\n\nb\n\n===CATEGORY_SPLIT===\n\nc"
    result = _split_by_separator(text, "===CATEGORY_SPLIT===")
    assert result == ["a", "b", "c"]


def test_split_by_separator_absent_returns_single_chunk():
    from airdropbot.telegram_post import _split_by_separator
    text = "no separator here"
    result = _split_by_separator(text, "===CATEGORY_SPLIT===")
    assert result == ["no separator here"]


def test_split_by_separator_strips_surrounding_whitespace():
    """separator 앞뒤 공백·개행 정리. chunk 자체 trim()."""
    from airdropbot.telegram_post import _split_by_separator
    text = "  part1  \n\n===CATEGORY_SPLIT===\n\n  part2  "
    result = _split_by_separator(text, "===CATEGORY_SPLIT===")
    assert result == ["part1", "part2"]


def test_split_by_separator_skips_empty_chunks():
    """연속 separator나 leading/trailing separator로 인한 빈 chunk 제거."""
    from airdropbot.telegram_post import _split_by_separator
    text = "===CATEGORY_SPLIT===\na\n===CATEGORY_SPLIT===\n===CATEGORY_SPLIT===\nb\n===CATEGORY_SPLIT==="
    result = _split_by_separator(text, "===CATEGORY_SPLIT===")
    assert result == ["a", "b"]


# ============ post() separator integration 테스트 (Task 2) ============


def test_post_splits_by_separator_then_sends_each_chunk(monkeypatch):
    """post()가 separator 기준 분리 후 각 chunk를 별도 _send_chunk 호출."""
    from airdropbot import telegram_post

    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "T")
    monkeypatch.setenv("TELEGRAM_CHANNEL_ID", "@x")

    text = "category1\n\n===CATEGORY_SPLIT===\n\ncategory2\n\n===CATEGORY_SPLIT===\n\ncategory3"

    sent: list[str] = []
    monkeypatch.setattr(
        "airdropbot.telegram_post._send_chunk",
        lambda token, chat_id, text: sent.append(text),
    )
    with patch("airdropbot.telegram_post.time.sleep") as mock_sleep:
        telegram_post.post(text)

    assert sent == ["category1", "category2", "category3"]
    assert mock_sleep.call_count == 2


def test_post_falls_back_to_size_split_when_no_separator(monkeypatch):
    """separator 없으면 전체를 단일 카테고리로 보고 4096자 split만 적용."""
    from airdropbot import telegram_post

    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "T")
    monkeypatch.setenv("TELEGRAM_CHANNEL_ID", "@x")

    text = "short message no separator"

    sent: list[str] = []
    monkeypatch.setattr(
        "airdropbot.telegram_post._send_chunk",
        lambda token, chat_id, text: sent.append(text),
    )
    telegram_post.post(text)

    assert len(sent) == 1
    assert sent[0] == "short message no separator"


def test_post_splits_oversized_category_chunk_within_4096(monkeypatch):
    """단일 카테고리 chunk가 4096자 초과면 추가 split."""
    from airdropbot import telegram_post

    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "T")
    monkeypatch.setenv("TELEGRAM_CHANNEL_ID", "@x")

    big = ("line\n\n" * 1000).strip()
    # big = 5998자 → _split_message가 \n\n 기준으로 2개로 분리
    # 총 chunk: 1 (small) + 2 (big split) = 3
    text = f"small\n\n===CATEGORY_SPLIT===\n\n{big}"

    sent: list[str] = []
    monkeypatch.setattr(
        "airdropbot.telegram_post._send_chunk",
        lambda token, chat_id, text: sent.append(text),
    )
    with patch("airdropbot.telegram_post.time.sleep"):
        telegram_post.post(text)

    assert len(sent) == 3
    assert sent[0] == "small"
    for t in sent[1:]:
        assert len(t) <= 4096


def test_post_empty_string_is_noop(monkeypatch):
    """빈 문자열 입력 시 _send_chunk 호출 없음 (silent no-op)."""
    from airdropbot import telegram_post

    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "T")
    monkeypatch.setenv("TELEGRAM_CHANNEL_ID", "@x")

    called: list = []
    monkeypatch.setattr(
        "airdropbot.telegram_post._send_chunk",
        lambda **kwargs: called.append(kwargs),
    )
    telegram_post.post("")
    assert called == []
