from airdropbot.collectors.browser import RenderedPage
from airdropbot.llm import FakeLLM
from airdropbot.models import Fact, Recipe, Step, auto_prefix_len
from airdropbot.recon.scout import MIN_PAGE_TEXT_CHARS, scout_recipe
from airdropbot.recon.store import load_recipes, save_recipes

_FACT = Fact(
    id="citrea",
    project="Citrea",
    content="브리지",
    source="airdrops.io",
    collected_at="2026-07-28",
    official_url="https://citrea.xyz",
)
# 실제 렌더 결과는 수천 자다. 짧은 픽스처는 빈 페이지 가드(spec §4.3)에 걸리므로
# 현실적인 분량을 준다.
_PAGE_TEXT = (
    "Citrea Testnet Faucet. Connect your wallet to request test tokens. "
    "Complete the bridge activity to become eligible for the upcoming airdrop. "
    "Steps: connect wallet, request tokens from the faucet, bridge to Citrea, "
    "then check your eligibility on the dashboard. No capital required beyond gas."
)
_PAGE = RenderedPage(url="https://citrea.xyz", title="Citrea", text=_PAGE_TEXT, links=())

_GOOD = """{"entry_url": "https://citrea.xyz/faucet", "chain": "citrea-testnet",
 "signature_kind": "message", "approve_unlimited": false, "capital_required_usd": 0,
 "automatable": "full", "blockers": [],
 "steps": [{"action": "goto", "target": "https://citrea.xyz/faucet"},
           {"action": "click", "target": "Request"}]}"""


def test_scout_builds_recipe():
    r = scout_recipe(_FACT, _PAGE, FakeLLM([_GOOD]), now="2026-07-28")
    assert r.project == "Citrea"
    assert r.entry_url == "https://citrea.xyz/faucet"
    assert r.steps[0] == Step("goto", "https://citrea.xyz/faucet")
    assert r.signature_kind == "message"
    assert r.automatable == "full"
    assert r.reconned_at == "2026-07-28"


def test_scout_skips_empty_page_without_calling_llm():
    """0자 페이지에 LLM을 부르면 환각 레시피가 나온다 (AIW3 33 스텝, spec §4.3)."""
    page = RenderedPage(url="https://aiw3.ai/", title="", text="", links=())
    llm = FakeLLM([_GOOD])

    assert scout_recipe(_FACT, page, llm, now="2026-07-29") is None
    assert llm.calls == [], "빈 페이지인데 LLM을 호출했다"


def test_scout_skips_page_below_text_floor():
    """실측 환각 유발 페이지는 19~68자였다 (antdrop.io / rtg.arcium.com)."""
    page = RenderedPage(url="https://rtg.arcium.com/", title="RTG", text="x" * 68, links=())
    llm = FakeLLM([_GOOD])

    assert scout_recipe(_FACT, page, llm, now="2026-07-29") is None
    assert llm.calls == []


def test_scout_ignores_whitespace_when_measuring_page():
    """공백만 있는 페이지는 내용이 없는 페이지다."""
    page = RenderedPage(url="https://x.dev/", title="", text="   \n\t  " * 60, links=())
    llm = FakeLLM([_GOOD])

    assert scout_recipe(_FACT, page, llm, now="2026-07-29") is None
    assert llm.calls == []


def test_scout_proceeds_at_text_floor():
    """하한을 만족하면 정찰한다 — 가드가 정상 페이지를 막아선 안 된다."""
    page = RenderedPage(url="https://citrea.xyz", title="C", text="y" * MIN_PAGE_TEXT_CHARS,
                        links=())
    llm = FakeLLM([_GOOD])

    assert scout_recipe(_FACT, page, llm, now="2026-07-29") is not None
    assert len(llm.calls) == 1


def test_scout_returns_none_on_unparseable_output():
    assert scout_recipe(_FACT, _PAGE, FakeLLM(["nope"]), now="x") is None


def test_scout_returns_none_on_llm_error():
    class _Boom:
        def complete(self, system, prompt):
            raise RuntimeError("down")

    assert scout_recipe(_FACT, _PAGE, _Boom(), now="x") is None


def test_scout_returns_none_without_entry_url():
    assert scout_recipe(_FACT, _PAGE, FakeLLM(['{"steps": []}']), now="x") is None


def test_scout_coerces_unknown_signature_kind_to_most_dangerous():
    raw = _GOOD.replace('"signature_kind": "message"', '"signature_kind": "weird"')
    assert scout_recipe(_FACT, _PAGE, FakeLLM([raw]), now="x").signature_kind == "approve"


def test_scout_downgrades_automatable_on_unknown_action():
    raw = _GOOD.replace('"action": "click"', '"action": "teleport"')
    assert scout_recipe(_FACT, _PAGE, FakeLLM([raw]), now="x").automatable == "manual"


def test_scout_coerces_unknown_automatable_to_manual():
    raw = _GOOD.replace('"automatable": "full"', '"automatable": "maybe"')
    assert scout_recipe(_FACT, _PAGE, FakeLLM([raw]), now="x").automatable == "manual"


# --- warm 인증 세션 전제 (spec §8.1) ----------------------------------------
#
# 실행 컨텍스트는 사람이 1회 로그인해둔 persistent profile이다. 프롬프트가 이걸
# 안 알려주면 모델이 차가운 브라우저를 가정해 "Sign in with X"·"인증 메일 열기"를
# 사람 스텝으로 세고 automatable을 강등한다 — §12.1의 full=0이 그렇게 나왔다.


def test_scout_prompt_declares_warm_session():
    llm = FakeLLM([_GOOD])
    scout_recipe(_FACT, _PAGE, llm, now="x")
    system = llm.calls[0][0].lower()

    # 이미 로그인돼 있다는 사실이 프롬프트에 있어야 한다.
    assert "logged in" in system or "already authenticated" in system
    for account in ("wallet", "email", "social"):
        assert account in system


def test_scout_prompt_still_demands_downgrade_for_human_only_gates():
    """세션으로 해소되지 않는 것(캡차·KYC)은 여전히 강등 사유여야 한다."""
    llm = FakeLLM([_GOOD])
    scout_recipe(_FACT, _PAGE, llm, now="x")
    system = llm.calls[0][0].lower()

    for gate in ("captcha", "kyc"):
        assert gate in system


def test_scout_keeps_conservative_coercion_under_warm_session():
    """세션 전제를 넣었다고 보수적 강등 규칙이 풀리면 안 된다 (spec §4 대전제)."""
    unknown = _GOOD.replace('"automatable": "full"', '"automatable": "obviously-fine"')
    r = scout_recipe(_FACT, _PAGE, FakeLLM([unknown]), now="x")
    assert r.automatable == "manual"


# --- 스텝 단위 판정 (spec §12.5) --------------------------------------------

_TAGGED = """{"entry_url": "https://citrea.xyz/faucet", "chain": "citrea-testnet",
 "signature_kind": "message", "approve_unlimited": false, "capital_required_usd": 0,
 "automatable": "partial", "blockers": ["초대 코드"],
 "steps": [{"action": "goto", "target": "https://citrea.xyz/faucet",
            "automatable": true, "blocker": null},
           {"action": "fill", "target": "#code=INVITE",
            "automatable": false, "blocker": "초대 코드 미보유"},
           {"action": "click", "target": "Request", "automatable": true}]}"""


def test_scout_parses_per_step_tags():
    r = scout_recipe(_FACT, _PAGE, FakeLLM([_TAGGED]), now="x")
    assert [s.automatable for s in r.steps] == [True, False, True]
    assert r.steps[1].blocker == "초대 코드 미보유"
    assert auto_prefix_len(r) == 1


def test_scout_prompt_demands_per_step_judgment():
    llm = FakeLLM([_TAGGED])
    scout_recipe(_FACT, _PAGE, llm, now="x")
    system = llm.calls[0][0].lower()
    assert "per-step" in system or "each step" in system
    assert '"blocker"' in system


def test_scout_defaults_untagged_step_to_not_automatable():
    """모델이 태그를 빠뜨리면 사람 스텝으로 본다 (spec §4 보수적 강제)."""
    r = scout_recipe(_FACT, _PAGE, FakeLLM([_GOOD]), now="x")
    assert [s.automatable for s in r.steps] == [False, False]
    assert auto_prefix_len(r) == 0


def test_scout_rejects_non_boolean_step_tag():
    """문자열 "true"는 truthy지만 모델이 스키마를 지키지 않았다는 신호다."""
    raw = _TAGGED.replace(
        '"automatable": true, "blocker": null', '"automatable": "true", "blocker": null'
    )
    assert '"automatable": "true"' in raw, "픽스처 치환이 빗나갔다"
    r = scout_recipe(_FACT, _PAGE, FakeLLM([raw]), now="x")
    assert r.steps[0].automatable is False


def test_scout_marks_unknown_action_step_as_not_automatable():
    """드라이버가 모르는 action은 수행할 수 없다 — 모델이 뭐라 하든 prefix를 끊어야 한다."""
    raw = _TAGGED.replace('"action": "goto"', '"action": "teleport"')
    r = scout_recipe(_FACT, _PAGE, FakeLLM([raw]), now="x")
    assert r.steps[0].automatable is False
    assert auto_prefix_len(r) == 0
    assert r.automatable == "manual"


def test_scout_tolerates_json_fence():
    r = scout_recipe(_FACT, _PAGE, FakeLLM([f"```json\n{_GOOD}\n```"]), now="x")
    assert r.entry_url == "https://citrea.xyz/faucet"


def test_recipes_roundtrip(tmp_path):
    path = tmp_path / "actions.yaml"
    recipe = Recipe(
        project="Citrea",
        entry_url="https://citrea.xyz/faucet",
        steps=(Step("goto", "https://citrea.xyz/faucet"),),
        automatable="full",
    )
    save_recipes(path, [recipe])
    loaded = load_recipes(path)
    assert loaded[0].steps == (Step("goto", "https://citrea.xyz/faucet"),)
    assert loaded[0].automatable == "full"


def test_load_recipes_missing_file_returns_empty(tmp_path):
    assert load_recipes(tmp_path / "nope.yaml") == []


def test_save_recipes_writes_recipe_hash_and_null_verdict(tmp_path):
    path = tmp_path / "actions.yaml"
    save_recipes(path, [Recipe(project="P", entry_url="https://p.io", steps=())])
    text = path.read_text(encoding="utf-8")
    assert "recipe_hash" in text
    assert "verdict: null" in text


# --- 스텝 태그 영속화 (spec §5.2 / §12.5.2) ---------------------------------


def test_recipes_roundtrip_preserves_step_tags(tmp_path):
    path = tmp_path / "actions.yaml"
    recipe = Recipe(
        project="Citrea",
        entry_url="https://citrea.xyz/faucet",
        steps=(
            Step("goto", "https://citrea.xyz/faucet", automatable=True),
            Step("fill", "#code=INVITE", automatable=False, blocker="초대 코드 미보유"),
        ),
    )
    save_recipes(path, [recipe])

    loaded = load_recipes(path)[0]
    assert loaded.steps[0].automatable is True
    assert loaded.steps[0].blocker is None
    assert loaded.steps[1].automatable is False
    assert loaded.steps[1].blocker == "초대 코드 미보유"


def test_legacy_recipe_without_tags_loads_as_not_automatable(tmp_path):
    """구 ``actions.yaml``에 실행 권한을 소급 부여하지 않는다 — spec §12.5.2.

    태그 없는 레시피를 자동화 가능으로 읽으면 정확히 §12.2가 경고한 잘못된 안전
    신호가 된다. 읽히기는 하되 실행 상한은 0이어야 한다.
    """
    path = tmp_path / "actions.yaml"
    path.write_text(
        "recipes:\n"
        "  - project: Legacy\n"
        "    entry_url: https://legacy.io\n"
        "    steps:\n"
        "      - {action: goto, target: 'https://legacy.io'}\n"
        "      - {action: click, target: 'Claim'}\n"
        "    automatable: full\n",
        encoding="utf-8",
    )

    loaded = load_recipes(path)[0]
    assert [s.automatable for s in loaded.steps] == [False, False]
    assert auto_prefix_len(loaded) == 0


def test_save_recipes_writes_step_tags(tmp_path):
    path = tmp_path / "actions.yaml"
    save_recipes(
        path,
        [
            Recipe(
                project="P",
                entry_url="https://p.io",
                steps=(Step("goto", "https://p.io", automatable=True),),
            )
        ],
    )
    text = path.read_text(encoding="utf-8")
    assert "automatable: true" in text
    assert "blocker" in text
