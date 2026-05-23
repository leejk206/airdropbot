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


CATEGORY_SEPARATOR: Final[str] = "===CATEGORY_SPLIT==="


def _split_by_separator(text: str, separator: str = CATEGORY_SEPARATOR) -> list[str]:
    """카테고리 separator 기준 1차 split. 각 chunk는 strip(), 빈 chunk 제거.

    - separator 없으면 [text.strip()] 반환 (단일 chunk).
    - separator로 나뉜 chunk 중 strip 후 빈 것은 제외.
    """
    parts = text.split(separator)
    return [p.strip() for p in parts if p.strip()]


def _send_chunk(
    token: str,
    chat_id: str,
    text: str,
    parse_mode: str | None = "HTML",
) -> None:
    """단일 chunk를 sendMessage POST.

    - 5xx: 60초 후 1회 재시도 (parse_mode 그대로).
    - 400 with parse_mode: parse_mode 제거 후 1회 재시도 (HTML 깨졌을 가능성).
      plain text라도 메시지 도달 우선.
    - 그 외 4xx: 즉시 raise.
    """
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload: dict = {"chat_id": chat_id, "text": text}
    if parse_mode:
        payload["parse_mode"] = parse_mode

    resp = requests.post(url, json=payload, timeout=30)
    if 500 <= resp.status_code < 600:
        time.sleep(RETRY_DELAY_SEC)
        resp = requests.post(url, json=payload, timeout=30)
    elif resp.status_code == 400 and parse_mode:
        plain_payload = {"chat_id": chat_id, "text": text}
        resp = requests.post(url, json=plain_payload, timeout=30)
    resp.raise_for_status()


def post(text: str) -> None:
    """Telegram 채널에 text post.

    1차 split: `===CATEGORY_SPLIT===` separator 기준 카테고리별 분리.
    2차 split: 각 카테고리 chunk가 4096자 초과 시 추가 split.
    chunk 사이 1초 delay (separator 경계든 4096자 경계든 동일).
    """
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHANNEL_ID")
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN env 미설정")
    if not chat_id:
        raise RuntimeError("TELEGRAM_CHANNEL_ID env 미설정")

    categories = _split_by_separator(text)
    all_chunks: list[str] = []
    for cat in categories:
        all_chunks.extend(_split_message(cat))

    for i, chunk in enumerate(all_chunks):
        if i > 0:
            time.sleep(CHUNK_DELAY_SEC)
        _send_chunk(token=token, chat_id=chat_id, text=chunk)
