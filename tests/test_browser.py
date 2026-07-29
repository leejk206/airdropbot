"""``collectors/browser.py`` — Playwright 구동부를 가짜로 갈아끼워 검증한다.

실측(2026-07-29)에서 ``domcontentloaded`` + 2초 settle만으로는 SPA·봇차단 사이트가
빈 페이지로 돌아왔다 (aiw3.ai 0자, rtg.arcium.com 68자, antdrop.io 19자). spec §4.3.
"""
from __future__ import annotations

import pytest

from airdropbot.collectors import browser


class _FakePage:
    def __init__(self, calls: dict, idle_raises: Exception | None = None, growth=None):
        self._calls = calls
        self._idle_raises = idle_raises
        # growth: inner_text 호출 순서별 반환 길이. 늦게 그려지는 SPA를 흉내낸다.
        self._growth = list(growth) if growth else None
        self.url = "https://final.example/"

    def goto(self, url, **kw):
        self._calls.setdefault("goto", []).append((url, kw))

    def wait_for_load_state(self, state, **kw):
        self._calls.setdefault("load_state", []).append((state, kw))
        if self._idle_raises is not None:
            raise self._idle_raises

    def wait_for_timeout(self, ms):
        self._calls.setdefault("settle_ms", []).append(ms)

    def title(self):
        return "T"

    def inner_text(self, sel):
        self._calls["inner_text_calls"] = self._calls.get("inner_text_calls", 0) + 1
        if self._growth is None:
            return "body text"
        n = self._growth.pop(0) if len(self._growth) > 1 else self._growth[0]
        return "x" * n

    def eval_on_selector_all(self, sel, script):
        return [["label", "https://a.example/"]]


class _FakeBrowser:
    def __init__(self, calls: dict, idle_raises=None, growth=None):
        self._calls = calls
        self._idle_raises = idle_raises
        self._growth = growth

    def new_context(self, **kw):
        self._calls["new_context"] = kw
        return self

    def new_page(self):
        return _FakePage(self._calls, self._idle_raises, self._growth)

    def close(self):
        self._calls["closed"] = True


class _FakeChromium:
    def __init__(self, calls: dict, idle_raises=None, growth=None):
        self._calls = calls
        self._idle_raises = idle_raises
        self._growth = growth

    def launch(self, **kw):
        self._calls["launch"] = kw
        return _FakeBrowser(self._calls, self._idle_raises, self._growth)


class _FakePlaywright:
    def __init__(self, calls: dict, idle_raises=None, growth=None):
        self.chromium = _FakeChromium(calls, idle_raises, growth)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


@pytest.fixture
def calls(monkeypatch):
    """``sync_playwright``를 가짜로 대체하고 호출 기록을 돌려준다."""
    recorded: dict = {}

    def _install(idle_raises=None, growth=None):
        import playwright.sync_api

        monkeypatch.setattr(
            playwright.sync_api,
            "sync_playwright",
            lambda: _FakePlaywright(recorded, idle_raises, growth),
        )
        return recorded

    recorded["_install"] = _install
    return recorded


def test_render_sets_a_desktop_user_agent(calls):
    """기본 headless UA는 봇차단에 걸린다 — 실제 브라우저 UA로 위장한다."""
    calls["_install"]()
    browser.render("https://x.example/")

    ua = calls["new_context"].get("user_agent", "")
    assert "Mozilla" in ua, f"데스크톱 UA 미지정: {ua!r}"


def test_render_waits_for_network_idle_after_domcontentloaded(calls):
    """SPA는 domcontentloaded 시점에 본문이 비어 있다."""
    calls["_install"]()
    browser.render("https://x.example/")

    states = [s for s, _ in calls.get("load_state", [])]
    assert "networkidle" in states
    assert calls["goto"][0][1]["wait_until"] == "domcontentloaded"


def test_render_returns_page_even_if_network_never_idles(calls):
    """networkidle 미도달은 흔하다 (폴링·웹소켓). 실패로 취급하면 수집이 멈춘다."""
    calls["_install"](idle_raises=TimeoutError("networkidle timeout"))

    page = browser.render("https://x.example/")

    assert page.text == "body text"
    assert calls["closed"] is True


def test_render_text_wait_budget_beats_the_old_two_second_settle():
    """aiw3.ai는 10초에 본문이 나왔다. 2초 고정 settle로는 절대 못 잡는다."""
    assert browser.TEXT_WAIT_MS >= 10_000


def test_render_keeps_waiting_until_body_text_appears(calls):
    """aiw3.ai 실측: 2s·5s에 0자, **10s에 4,292자**. 일찍 포기하면 빈 페이지를 얻는다."""
    calls["_install"](growth=[0, 0, 0, 5_000])
    page = browser.render("https://x.example/")

    assert len(page.text) == 5_000, "본문이 그려질 때까지 기다리지 않았다"


def test_render_stops_polling_once_text_clears_the_floor(calls):
    """이미 충분한 페이지를 붙잡고 있으면 낭비다 — 6소스 × 낭비는 그대로 총소요다."""
    calls["_install"](growth=[5_000])
    browser.render("https://x.example/")

    assert calls["inner_text_calls"] <= 2, f"불필요한 폴링 {calls['inner_text_calls']}회"


def test_render_returns_short_text_after_deadline(calls):
    """rtg.arcium.com은 50초를 기다려도 68자다. 영원히 기다릴 수는 없다."""
    calls["_install"](growth=[68])
    page = browser.render("https://x.example/", text_wait_ms=1_500)

    assert len(page.text) == 68
    assert calls["closed"] is True


def test_resolve_redirect_sets_a_desktop_user_agent(calls):
    """리다이렉트 해소도 같은 봇차단에 노출된다 — 앵커 도메인 판정의 입력이다."""
    calls["_install"]()
    assert browser.resolve_redirect("https://airdrops.io/visit/9ea3/") == "https://final.example/"

    ua = calls["new_context"].get("user_agent", "")
    assert "Mozilla" in ua, f"데스크톱 UA 미지정: {ua!r}"


def test_render_closes_browser_on_failure(calls):
    """브라우저 누수는 이후 실행을 망친다."""
    calls["_install"]()

    def _boom(self, url, **kw):
        raise RuntimeError("nav failed")

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(_FakePage, "goto", _boom)
        with pytest.raises(RuntimeError):
            browser.render("https://x.example/")

    assert calls["closed"] is True
