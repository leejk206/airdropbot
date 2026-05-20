"""Telegram sendMessage 래퍼 — split + send + post 오케스트레이션."""
from __future__ import annotations

import os
import time
from typing import Final

import requests

TELEGRAM_LIMIT: Final[int] = 4096
RETRY_DELAY_SEC: Final[float] = 60.0
CHUNK_DELAY_SEC: Final[float] = 1.0


def _split_message(text: str, limit: int = TELEGRAM_LIMIT) -> list[str]:
    """텔레그램 4096자 한계로 메시지 split.

    - limit 이하면 단일 chunk 반환.
    - 그 이상이면 `\\n\\n` 경계 우선, 다음 `\\n`, 마지막 hard split.
    """
    if len(text) <= limit:
        return [text]

    for sep in ("\n\n", "\n"):
        if sep in text:
            chunks: list[str] = []
            remaining = text
            while len(remaining) > limit:
                # remaining[:limit] 안에서 마지막 sep 위치 찾기
                cut = remaining.rfind(sep, 0, limit)
                if cut == -1:
                    break  # 이 sep로는 split 불가, 다음 sep 시도
                chunks.append(remaining[:cut])
                remaining = remaining[cut + len(sep):]
            if chunks:
                chunks.append(remaining)
                return chunks
        # sep로 split 불가 → 다음 sep 시도 (loop continue)

    # 모든 sep 실패 — hard split
    return [text[i : i + limit] for i in range(0, len(text), limit)]


def _send_chunk(token: str, chat_id: str, text: str) -> None:
    """단일 chunk를 sendMessage POST. 5xx 1회 retry. 4xx 즉시 raise."""
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": text}

    resp = requests.post(url, json=payload, timeout=30)
    if 500 <= resp.status_code < 600:
        time.sleep(RETRY_DELAY_SEC)
        resp = requests.post(url, json=payload, timeout=30)
    resp.raise_for_status()


def post(text: str) -> None:
    """Telegram 채널에 text post. 자동 split, chunk 사이 1초 delay."""
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHANNEL_ID")
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN env 미설정")
    if not chat_id:
        raise RuntimeError("TELEGRAM_CHANNEL_ID env 미설정")

    chunks = _split_message(text)
    for i, chunk in enumerate(chunks):
        if i > 0:
            time.sleep(CHUNK_DELAY_SEC)
        _send_chunk(token=token, chat_id=chat_id, text=chunk)
