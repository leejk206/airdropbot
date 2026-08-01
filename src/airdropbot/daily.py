"""airdropbot 진입점 — daily routine 실행, 캐시 저장, 채널 post."""
from __future__ import annotations

import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

from airdropbot.claude_runner import (
    ClaudeRunnerError,
    EmptyOutputError,
    run_digest_routine,
)
from airdropbot.llm import ClaudeCliClient
from airdropbot.orchestrator import run_pipeline
from airdropbot.telegram_post import post

DEFAULT_WORKSPACE = Path(__file__).resolve().parent.parent.parent
PROMPT_REL = Path("prompts/airdrop_digest.md")
CACHE_REL = Path("cache/latest-digest.md")
LOG_REL = Path("logs")
SOURCES_REL = Path("sources.yaml")
KB_REL = Path("cache/kb.yaml")
ACTIONS_REL = Path("actions.yaml")

# 정찰 LLM 호출은 페이지가 크면 길어진다. 실측 라이브 1회가 ~915s / ~30콜.
COLLECT_LLM_TIMEOUT_SEC = 300


def _atomic_write(path: Path, content: str) -> None:
    """atomic write: tmp → rename (crash-safe at OS level via os.replace)."""
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


def _collect(workspace: Path, logger: logging.Logger) -> None:
    """Track B 수집을 1회 돌려 KB를 갱신한다 (spec §11.2).

    Track A 프롬프트는 이제 ``cache/kb.yaml``을 입력으로 읽으므로, 방송 전에
    KB가 갱신되어 있어야 한다. 실패해도 방송은 계속한다 — 어제 KB라도 쓸 만할 수
    있고, 낡았는지 판단은 프롬프트의 신선도 가드(§1.1)가 한다.
    """
    sources_path = workspace / SOURCES_REL
    if not sources_path.exists():
        logger.error("sources.yaml 없음 — 수집 skip, 기존 KB로 진행")
        return

    try:
        raw = yaml.safe_load(sources_path.read_text(encoding="utf-8")) or {}
        urls = [s["url"] for s in raw.get("sources") or []]
    except (OSError, yaml.YAMLError, KeyError, TypeError) as e:
        logger.error("sources.yaml 파싱 실패: %s — 수집 skip", e)
        return

    if not urls:
        logger.error("sources.yaml에 URL 없음 — 수집 skip")
        return

    try:
        summary = run_pipeline(
            sources=urls,
            kb_path=workspace / KB_REL,
            actions_path=workspace / ACTIONS_REL,
            llm=ClaudeCliClient(timeout_sec=COLLECT_LLM_TIMEOUT_SEC),
            now=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        )
    except Exception as e:  # noqa: BLE001 — 수집 실패가 방송을 막으면 안 된다
        logger.error("수집 실패: %s — 기존 KB로 방송 진행", e)
        return

    logger.info(
        "수집 완료 facts=%s anchored=%s recipes=%s",
        summary.get("facts"),
        summary.get("anchored"),
        summary.get("recipes"),
    )


def run(workspace: Path = DEFAULT_WORKSPACE) -> None:
    """Daily 실행: 수집 → routine → cache → post. 모든 예외 swallow + log."""
    logger = _setup_logger(workspace)
    logger.info("daily run start")

    _collect(workspace, logger)

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
