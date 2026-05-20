"""airdropbot 진입점 — daily routine 실행, 캐시 저장, 채널 post."""
from __future__ import annotations

import logging
import os
import sys
from datetime import datetime
from pathlib import Path

from airdropbot.claude_runner import (
    ClaudeRunnerError,
    EmptyOutputError,
    run_digest_routine,
)
from airdropbot.telegram_post import post

DEFAULT_WORKSPACE = Path(__file__).resolve().parent.parent.parent
PROMPT_REL = Path("prompts/airdrop_digest.md")
CACHE_REL = Path("cache/latest-digest.md")
LOG_REL = Path("logs")


def _atomic_write(path: Path, content: str) -> None:
    """atomic write: tmp → fsync → rename."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    os.replace(str(tmp), str(path))


def _setup_logger(workspace: Path) -> logging.Logger:
    log_dir = workspace / LOG_REL
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / f"daily-{datetime.now():%Y-%m-%d}.log"

    logger = logging.getLogger("airdropbot.daily")
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        fh = logging.FileHandler(str(log_file), encoding="utf-8")
        fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logger.addHandler(fh)
    return logger


def run(workspace: Path = DEFAULT_WORKSPACE) -> None:
    """Daily 실행: routine → cache → post. 모든 예외 swallow + log."""
    logger = _setup_logger(workspace)
    logger.info("daily run start")

    try:
        markdown = run_digest_routine(
            workspace=workspace,
            prompt_path=workspace / PROMPT_REL,
        )
    except EmptyOutputError as e:
        logger.error("routine empty output: %s — post skip, cache 유지", e)
        return
    except ClaudeRunnerError as e:
        logger.error("routine failure: %s — post skip, cache 유지", e)
        return

    try:
        _atomic_write(workspace / CACHE_REL, markdown)
        logger.info("cache 저장 완료 (%d chars)", len(markdown))
    except OSError as e:
        logger.error("cache write 실패: %s", e)
        return

    try:
        post(markdown)
        logger.info("Telegram channel post 완료")
    except Exception as e:
        logger.error("Telegram post 실패: %s", e)
        return


if __name__ == "__main__":
    run()
    sys.exit(0)
