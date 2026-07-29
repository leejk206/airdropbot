"""Playwright 렌더링 — 페이지를 텍스트 + 링크로 환원하는 얇은 층.

6개 소스를 결정적 셀렉터로 파싱하면 사이트 개편마다 깨진다. 여기서는 렌더 결과만
뽑고 구조화는 :mod:`airdropbot.collectors.extract`의 LLM 1회 호출이 담당한다.
"""
from __future__ import annotations

from dataclasses import dataclass

DEFAULT_TIMEOUT_MS = 30_000
SETTLE_MS = 2_000
MAX_TEXT_CHARS = 20_000
MAX_LINKS = 300


@dataclass(frozen=True)
class RenderedPage:
    url: str
    title: str
    text: str
    links: tuple[tuple[str, str], ...]


def render(
    url: str, *, timeout_ms: int = DEFAULT_TIMEOUT_MS, headless: bool = True
) -> RenderedPage:
    """URL을 렌더링해 본문 텍스트와 링크를 추출."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        try:
            page = browser.new_page()
            page.goto(url, timeout=timeout_ms, wait_until="domcontentloaded")
            page.wait_for_timeout(SETTLE_MS)
            title = page.title()
            text = page.inner_text("body")[:MAX_TEXT_CHARS]
            links = page.eval_on_selector_all(
                "a[href]", "els => els.map(e => [e.innerText.trim(), e.href])"
            )[:MAX_LINKS]
        finally:
            browser.close()

    return RenderedPage(url=url, title=title, text=text, links=tuple((t, h) for t, h in links))


def resolve_redirect(url: str, *, timeout_ms: int = DEFAULT_TIMEOUT_MS) -> str:
    """리다이렉트를 따라간 최종 URL을 반환.

    집계 사이트는 프로젝트 링크를 ``/visit/<code>/`` 같은 자체 리다이렉트 뒤에
    숨긴다. 실제 도메인을 알아야 교차소스 합의와 도메인 검사가 성립한다.
    """
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            page.goto(url, timeout=timeout_ms, wait_until="domcontentloaded")
            return page.url
        finally:
            browser.close()


def render_all(urls: list[str], **kwargs) -> list[RenderedPage]:
    """여러 URL을 순차 렌더링. 개별 실패는 건너뛴다 (소스 다운 내성)."""
    pages: list[RenderedPage] = []
    for url in urls:
        try:
            pages.append(render(url, **kwargs))
        except Exception:
            continue
    return pages
