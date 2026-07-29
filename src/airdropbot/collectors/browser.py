"""Playwright 렌더링 — 페이지를 텍스트 + 링크로 환원하는 얇은 층.

6개 소스를 결정적 셀렉터로 파싱하면 사이트 개편마다 깨진다. 여기서는 렌더 결과만
뽑고 구조화는 :mod:`airdropbot.collectors.extract`의 LLM 1회 호출이 담당한다.
"""
from __future__ import annotations

from dataclasses import dataclass

DEFAULT_TIMEOUT_MS = 30_000
MAX_TEXT_CHARS = 20_000
MAX_LINKS = 300

# networkidle 미도달은 흔하다(폴링·웹소켓·애널리틱스). 도달하면 이득, 아니면 넘어간다.
NETWORK_IDLE_TIMEOUT_MS = 8_000

# 본문이 하한을 넘을 때까지 기다리는 예산. 고정 settle이 아니라 폴링인 이유: 실측에서
# aiw3.ai는 2초·5초에 0자였고 **10초에 4,292자**였다. 반면 이미 그려진 페이지에
# 고정 대기를 물리면 렌더 수십 회 × 대기가 그대로 총소요가 된다. spec §4.3.
TEXT_WAIT_MS = 12_000
POLL_MS = 500

# 이 길이를 넘으면 "본문이 그려졌다"고 보고 폴링을 멈춘다. ``scout`` 쪽 하한과 같은
# 값이지만 다른 판단이다 — 여기는 "더 기다릴까", 저기는 "정찰을 거부할까".
MIN_USEFUL_TEXT_CHARS = 200

# 기본 headless UA는 봇차단에 걸린다. 실측(2026-07-29) 빈 렌더 사례:
# aiw3.ai 0자, rtg.arcium.com 68자, antdrop.io 19자, freeairdrop.io 887자. spec §4.3.
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)


@dataclass(frozen=True)
class RenderedPage:
    url: str
    title: str
    text: str
    links: tuple[tuple[str, str], ...]


def render(
    url: str,
    *,
    timeout_ms: int = DEFAULT_TIMEOUT_MS,
    headless: bool = True,
    text_wait_ms: int = TEXT_WAIT_MS,
) -> RenderedPage:
    """URL을 렌더링해 본문 텍스트와 링크를 추출."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        try:
            page = browser.new_context(user_agent=USER_AGENT).new_page()
            page.goto(url, timeout=timeout_ms, wait_until="domcontentloaded")
            # SPA는 domcontentloaded 시점에 본문이 비어 있다. 미도달은 실패가 아니다.
            try:
                page.wait_for_load_state("networkidle", timeout=NETWORK_IDLE_TIMEOUT_MS)
            except Exception:
                pass
            text = _wait_for_body_text(page, text_wait_ms)[:MAX_TEXT_CHARS]
            title = page.title()
            links = page.eval_on_selector_all(
                "a[href]", "els => els.map(e => [e.innerText.trim(), e.href])"
            )[:MAX_LINKS]
        finally:
            browser.close()

    return RenderedPage(url=url, title=title, text=text, links=tuple((t, h) for t, h in links))


def _wait_for_body_text(page, budget_ms: int) -> str:
    """본문이 하한을 넘거나 예산이 소진될 때까지 폴링한 뒤 마지막 본문을 돌려준다.

    예산을 다 써도 짧으면 짧은 대로 돌려준다 — 진짜 빈 페이지(로그인 월·404)는
    아무리 기다려도 안 채워지고, 그 판정은 소비 측(``scout``)이 한다.
    """
    text = page.inner_text("body")
    waited = 0
    while len(text.strip()) < MIN_USEFUL_TEXT_CHARS and waited < budget_ms:
        page.wait_for_timeout(POLL_MS)
        waited += POLL_MS
        text = page.inner_text("body")
    return text


def resolve_redirect(url: str, *, timeout_ms: int = DEFAULT_TIMEOUT_MS) -> str:
    """리다이렉트를 따라간 최종 URL을 반환.

    집계 사이트는 프로젝트 링크를 ``/visit/<code>/`` 같은 자체 리다이렉트 뒤에
    숨긴다. 실제 도메인을 알아야 교차소스 합의와 도메인 검사가 성립한다.
    """
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            page = browser.new_context(user_agent=USER_AGENT).new_page()
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
