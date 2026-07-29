"""지갑 브라우저 세션.

autoinsta ``publish/session.py`` 이식. 코드가 개인키·시드를 **절대 만지지 않는다**:
전용 프로필 디렉토리에 지갑 확장을 두고 최초 1회만 사람이 headful 창에서 직접
시드 입력·잠금해제하면, 세션이 디스크에 남아 이후 실행이 이를 재사용한다.

사용법::

    with wallet_page(".wallet_profile", extension_path="./metamask") as page:
        run_recipe(recipe, facts, limits, llm=llm, dry_run=False, page=page)
"""
from __future__ import annotations

from contextlib import contextmanager

DEFAULT_SETUP_TIMEOUT_MS = 300_000


@contextmanager
def wallet_page(
    user_data_dir: str,
    *,
    headless: bool = False,
    extension_path: str | None = None,
    start_url: str = "about:blank",
):
    """지갑 프로필로 persistent context를 열어 Playwright ``page``를 yield한다.

    Args:
        user_data_dir: 지갑 프로필 디렉토리. 버전관리에서 제외할 것.
        headless: 세션이 이미 준비된 뒤에만 True로 쓸 것. 최초 셋업은 반드시 False.
        extension_path: 언팩된 지갑 확장 디렉토리. 지정 시 확장을 로드하며,
            확장 로딩은 headless에서 동작하지 않으므로 ``headless=False``가 강제된다.
        start_url: 세션 시작 시 열어둘 URL.
    """
    from playwright.sync_api import sync_playwright

    args: list[str] = []
    if extension_path:
        headless = False
        args += [
            f"--disable-extensions-except={extension_path}",
            f"--load-extension={extension_path}",
        ]

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir, headless=headless, args=args
        )
        try:
            page = context.pages[0] if context.pages else context.new_page()
            if start_url != "about:blank":
                page.goto(start_url)
            yield page
        finally:
            context.close()
