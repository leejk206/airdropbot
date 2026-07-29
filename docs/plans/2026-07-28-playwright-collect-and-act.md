# Playwright 수집 + 행동 포인팅 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 6개 큐레이트 소스를 Playwright로 수집해 팩트 KB를 쌓고, 상위 후보의 활동 페이지를 정찰해 액션 레시피를 뽑아내며, dry-run 게이트 뒤에서 실행 경로를 완성한다.

**Architecture:** autoinsta 파이프라인 이식 — Python 오케스트레이터가 collectors → kb → selection → recon → (execute 게이트: guard → council) 순으로 구동한다. 대량 반복은 Playwright 코드가, 판단은 `LLMClient`를 통한 짧은 LLM 호출이 담당한다. 모든 행동 함수는 `dry_run=True`가 기본이며 비가역 행동(서명) 직전에만 council이 선다.

**Tech Stack:** Python 3.12+, playwright(신규), pyyaml, requests, pytest 8, ruff (line-length 100). LLM은 claude CLI subprocess(구독, 비용 $0).

## Global Constraints

- 기존 자산 보존: `prompts/airdrop_digest.md`(32KB, 별점·pin·3카테고리 규칙), `prompts/airdrop_pin.md`, `pinned.yaml`, `sources.yaml`, `src/airdropbot/{daily,claude_runner,telegram_post}.py`는 **재작성하지 않는다**.
- 신규 외부 의존성은 `playwright`만 추가한다. `tldextract` 등 그 외 라이브러리 추가 금지 — 등록 도메인 판정은 자체 휴리스틱으로 구현한다.
- ruff `line-length = 100`, `target-version = "py312"`.
- 모든 신규 모듈은 네트워크 없이 단위테스트 가능해야 한다. Playwright를 직접 호출하는 모듈은 얇게 유지하고, 로직은 주입 가능한 함수/객체 뒤로 뺀다.
- council은 **fail-closed** — JSON 파싱 실패·빈 응답·LLM 예외·판단 애매는 전부 `passed: false`.
- `execute/`의 모든 진입점은 `dry_run: bool = True` 기본값을 가지며, `dry_run=False`인데 `page`가 없으면 `ValueError`.
- v1은 실제 서명을 실행하지 않는다. `Recipe.verdict`는 항상 null로 축적된다.
- 커밋은 사용자 명시 요청 시에만 (레포 정책). 각 Task의 커밋 스텝은 사용자 승인 후 일괄 수행한다.

## File Structure

| 파일 | 책임 |
|---|---|
| `src/airdropbot/models.py` | `Fact`, `Step`, `Recipe`, `Verdict` 데이터클래스 + `recipe_hash()` |
| `src/airdropbot/llm.py` | `LLMClient` Protocol, `FakeLLM`, `ClaudeCliClient` |
| `src/airdropbot/kb/store.py` | `FactStore` (put/query/save/load) + `resolve_official_urls`, `registrable_domain` |
| `src/airdropbot/collectors/browser.py` | Playwright 렌더 → `RenderedPage` |
| `src/airdropbot/collectors/extract.py` | `RenderedPage` + LLM → `Fact` 목록 |
| `src/airdropbot/collectors/enrich.py` | 상세 페이지 방문 → 프로젝트 실제 URL (2-pass, Task 11) |
| `src/airdropbot/selection.py` | 오늘 정찰할 대상 선정 |
| `src/airdropbot/recon/scout.py` | `RenderedPage` + LLM → `Recipe` |
| `src/airdropbot/recon/store.py` | `actions.yaml` 로드/저장 |
| `src/airdropbot/verify/council.py` | Refuter + Judge → `Verdict` (fail-closed) |
| `src/airdropbot/verify/cache.py` | `recipe_hash → Verdict` 캐시 로드/저장 |
| `src/airdropbot/execute/guard.py` | 결정적 프리필터 (`Limits`, `GuardResult`, `prefilter`) |
| `src/airdropbot/execute/session.py` | 지갑 persistent context 세션 |
| `src/airdropbot/execute/runner.py` | `run_recipe(dry_run=True)` |
| `src/airdropbot/orchestrator.py` | 전 구간 오케스트레이션 |

테스트는 `tests/test_<module>.py`로 미러링한다.

---

### Task 1: models.py — 데이터 모델 + 레시피 해시

**Files:**
- Create: `src/airdropbot/models.py`
- Test: `tests/test_models.py`

**Interfaces:**
- Produces: `Fact`, `Step`, `Recipe`, `Verdict` (frozen dataclass), `recipe_hash(recipe) -> str`, 상수 `ACTIONS`, `SIGNATURE_KINDS`, `AUTOMATABLE`.

- [x] **Step 1: 실패하는 테스트 작성**

```python
from airdropbot.models import Recipe, Step, recipe_hash


def _recipe(**kw) -> Recipe:
    base = dict(
        project="Citrea",
        entry_url="https://citrea.xyz/faucet",
        steps=(Step("goto", "https://citrea.xyz/faucet"), Step("click", "Request")),
    )
    base.update(kw)
    return Recipe(**base)


def test_recipe_hash_is_stable():
    assert recipe_hash(_recipe()) == recipe_hash(_recipe())


def test_recipe_hash_changes_when_steps_change():
    other = _recipe(steps=(Step("goto", "https://citrea.xyz/faucet"),))
    assert recipe_hash(_recipe()) != recipe_hash(other)


def test_recipe_hash_is_prefixed():
    assert recipe_hash(_recipe()).startswith("sha256:")


def test_recipe_defaults_are_safe():
    r = _recipe()
    assert r.signature_kind == "none"
    assert r.automatable == "manual"
    assert r.approve_unlimited is False
    assert r.capital_required_usd == 0.0
```

- [x] **Step 2: 테스트가 실패하는지 확인**

Run: `.venv/bin/pytest tests/test_models.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'airdropbot.models'`

- [x] **Step 3: 최소 구현**

```python
"""파이프라인 전역 데이터 모델."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

ACTIONS = frozenset(
    {"goto", "click", "fill", "wait", "wallet_connect", "wallet_approve", "wallet_sign"}
)
SIGNATURE_KINDS = ("none", "message", "tx", "approve")
AUTOMATABLE = ("full", "partial", "manual")


@dataclass(frozen=True)
class Fact:
    id: str
    project: str
    content: str
    source: str
    collected_at: str
    source_url: str | None = None
    official_url: str | None = None
    chain: str | None = None
    tags: tuple[str, ...] = ()
    expires_at: str | None = None


@dataclass(frozen=True)
class Step:
    action: str
    target: str


@dataclass(frozen=True)
class Recipe:
    project: str
    entry_url: str
    steps: tuple[Step, ...]
    chain: str | None = None
    signature_kind: str = "none"
    approve_unlimited: bool = False
    capital_required_usd: float = 0.0
    automatable: str = "manual"
    blockers: tuple[str, ...] = ()
    reconned_at: str = ""


@dataclass(frozen=True)
class Verdict:
    passed: bool
    issues: tuple[str, ...] = ()
    log: str = ""


def recipe_hash(recipe: Recipe) -> str:
    """entry_url + 정규화된 steps의 sha256. 레시피가 바뀌면 해시가 바뀐다."""
    payload = "\n".join(
        [recipe.entry_url, *(f"{s.action}:{s.target}" for s in recipe.steps)]
    )
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()
```

- [x] **Step 4: 테스트 통과 확인**

Run: `.venv/bin/pytest tests/test_models.py -v`
Expected: PASS (4 tests)

- [x] **Step 5: 커밋 (사용자 승인 후)**

```bash
git add src/airdropbot/models.py tests/test_models.py
git commit -m "feat(models): Fact/Step/Recipe/Verdict + recipe_hash"
```

---

### Task 2: llm.py — LLM 클라이언트 추상화

**Files:**
- Create: `src/airdropbot/llm.py`
- Test: `tests/test_llm.py`

**Interfaces:**
- Produces: `LLMClient` Protocol (`complete(system, prompt) -> str`), `FakeLLM(responses)`, `ClaudeCliClient(timeout_sec=120)`.
- 이후 모든 LLM 사용 모듈은 `LLMClient`만 의존한다.

- [x] **Step 1: 실패하는 테스트 작성**

```python
import pytest

from airdropbot.llm import ClaudeCliClient, FakeLLM


def test_fake_llm_returns_scripted_replies_in_order():
    llm = FakeLLM(["first", "second"])
    assert llm.complete("sys", "a") == "first"
    assert llm.complete("sys", "b") == "second"
    assert llm.calls == [("sys", "a"), ("sys", "b")]


def test_fake_llm_raises_when_exhausted():
    llm = FakeLLM([])
    with pytest.raises(AssertionError):
        llm.complete("sys", "a")


def test_claude_cli_client_passes_prompt_on_stdin(monkeypatch):
    seen = {}

    class _Done:
        returncode = 0
        stdout = "hello\n"
        stderr = ""

    def _fake_run(cmd, **kwargs):
        seen["cmd"] = cmd
        seen["input"] = kwargs["input"]
        return _Done()

    monkeypatch.setattr("airdropbot.llm.subprocess.run", _fake_run)
    out = ClaudeCliClient().complete("SYSTEM", "PROMPT")

    assert out == "hello"
    assert seen["cmd"][0] == "claude"
    assert "SYSTEM" in seen["input"] and "PROMPT" in seen["input"]


def test_claude_cli_client_raises_on_nonzero_exit(monkeypatch):
    class _Done:
        returncode = 1
        stdout = ""
        stderr = "boom"

    monkeypatch.setattr("airdropbot.llm.subprocess.run", lambda cmd, **kw: _Done())
    with pytest.raises(RuntimeError):
        ClaudeCliClient().complete("s", "p")
```

- [x] **Step 2: 실패 확인** — Run: `.venv/bin/pytest tests/test_llm.py -v` → FAIL (모듈 없음)

- [x] **Step 3: 최소 구현**

```python
"""LLM 클라이언트 추상화.

생성·검증 단은 ``LLMClient`` Protocol에만 의존하므로 ``FakeLLM``으로
네트워크 없이 단위테스트된다. 런타임 구현은 claude CLI subprocess —
autoinsta의 AnthropicClient(유료 API)와 달리 구독 기반이라 LLM 비용이 0이다.
"""
from __future__ import annotations

import subprocess
from typing import Protocol

DEFAULT_TIMEOUT_SEC = 120


class LLMClient(Protocol):
    def complete(self, system: str, prompt: str) -> str:
        """(system, prompt)에 대한 모델 텍스트 응답을 반환."""
        ...


class FakeLLM:
    """스크립트된 응답을 순서대로 반환하는 테스트 더블."""

    def __init__(self, responses: list[str]):
        self._responses = list(responses)
        self.calls: list[tuple[str, str]] = []

    def complete(self, system: str, prompt: str) -> str:
        self.calls.append((system, prompt))
        if not self._responses:
            raise AssertionError("FakeLLM ran out of scripted responses")
        return self._responses.pop(0)


class ClaudeCliClient:
    """claude CLI subprocess 래퍼. prompt는 stdin으로 전달(대형 인자 deadlock 회피)."""

    def __init__(self, timeout_sec: int = DEFAULT_TIMEOUT_SEC):
        self.timeout_sec = timeout_sec

    def complete(self, system: str, prompt: str) -> str:
        cmd = ["claude", "--print", "--dangerously-skip-permissions"]
        completed = subprocess.run(
            cmd,
            input=f"{system}\n\n---\n\n{prompt}",
            capture_output=True,
            text=True,
            timeout=self.timeout_sec,
        )
        if completed.returncode != 0:
            raise RuntimeError(
                f"claude exit={completed.returncode} stderr={completed.stderr[:300]}"
            )
        return completed.stdout.strip()
```

- [x] **Step 4: 통과 확인** — Run: `.venv/bin/pytest tests/test_llm.py -v` → PASS (4 tests)

- [x] **Step 5: 커밋 (승인 후)** — `feat(llm): LLMClient Protocol + FakeLLM + ClaudeCliClient`

---

### Task 3: kb/store.py — 팩트 저장소 + official_url 합의

**Files:**
- Create: `src/airdropbot/kb/__init__.py`, `src/airdropbot/kb/store.py`
- Test: `tests/test_kb_store.py`

**Interfaces:**
- Consumes: `Fact` (Task 1)
- Produces: `registrable_domain(url) -> str | None`, `resolve_official_urls(facts) -> list[Fact]`, `FactStore` (`put`, `query(now=..., tags=None)`, `all()`, `save(path)`, `load(path)` classmethod)

**핵심 규칙:** `official_url`은 **서로 다른 2개 이상 소스에서 등록 도메인이 일치**할 때만 채워진다.

- [x] **Step 1: 실패하는 테스트 작성**

```python
from airdropbot.kb.store import FactStore, registrable_domain, resolve_official_urls
from airdropbot.models import Fact


def _f(**kw) -> Fact:
    base = dict(
        id="x", project="P", content="c", source="airdrops.io", collected_at="2026-07-28"
    )
    base.update(kw)
    return Fact(**base)


def test_registrable_domain_strips_subdomain():
    assert registrable_domain("https://app.citrea.xyz/faucet") == "citrea.xyz"


def test_registrable_domain_handles_multipart_suffix():
    assert registrable_domain("https://foo.example.co.uk/a") == "example.co.uk"


def test_registrable_domain_returns_none_for_garbage():
    assert registrable_domain("not-a-url") is None


def test_official_url_requires_two_distinct_sources():
    facts = [
        _f(id="a", source="airdrops.io", source_url="https://citrea.xyz"),
        _f(id="b", source="icodrops.com", source_url="https://citrea.xyz/app"),
    ]
    out = {f.id: f for f in resolve_official_urls(facts)}
    assert out["a"].official_url == "https://citrea.xyz"
    assert out["b"].official_url == "https://citrea.xyz"


def test_official_url_stays_none_for_single_source():
    facts = [_f(id="a", source="airdrops.io", source_url="https://citrea.xyz")]
    assert resolve_official_urls(facts)[0].official_url is None


def test_official_url_stays_none_when_same_source_repeats():
    facts = [
        _f(id="a", source="airdrops.io", source_url="https://citrea.xyz"),
        _f(id="b", source="airdrops.io", source_url="https://citrea.xyz/app"),
    ]
    assert all(f.official_url is None for f in resolve_official_urls(facts))


def test_query_excludes_expired_facts():
    store = FactStore([_f(id="old", expires_at="2026-07-01"), _f(id="live")])
    ids = [f.id for f in store.query(now="2026-07-28")]
    assert ids == ["live"]


def test_query_filters_by_tag():
    store = FactStore([_f(id="a", tags=("testnet",)), _f(id="b", tags=("mainnet",))])
    assert [f.id for f in store.query(now="2026-07-28", tags=["testnet"])] == ["a"]


def test_put_upserts_by_id():
    store = FactStore([_f(id="a", content="old")])
    store.put(_f(id="a", content="new"))
    assert len(store.all()) == 1
    assert store.all()[0].content == "new"


def test_save_load_roundtrip(tmp_path):
    path = tmp_path / "kb.yaml"
    FactStore([_f(id="a", tags=("t",), expires_at="2026-09-01")]).save(path)
    loaded = FactStore.load(path)
    assert loaded.all()[0].tags == ("t",)
    assert loaded.all()[0].expires_at == "2026-09-01"


def test_load_missing_file_returns_empty_store(tmp_path):
    assert FactStore.load(tmp_path / "nope.yaml").all() == []
```

- [x] **Step 2: 실패 확인** — `.venv/bin/pytest tests/test_kb_store.py -v` → FAIL

- [x] **Step 3: 최소 구현**

`registrable_domain`은 외부 의존성 없이 구현한다: 호스트를 소문자화하고 `www.` 제거 후, 마지막 두 라벨을 취하되 다중 파트 접미사 집합(`co.uk`, `com.br` 등)에 걸리면 세 라벨을 취한다.

`FactStore.save`는 `daily.py`의 `_atomic_write`와 동일한 tmp→rename 방식을 쓴다.

```python
"""팩트 KB — 저장/조회/만료 + 교차소스 official_url 합의."""
from __future__ import annotations

import os
from collections import defaultdict
from dataclasses import asdict, replace
from pathlib import Path
from urllib.parse import urlparse

import yaml

from airdropbot.models import Fact

_MULTIPART_SUFFIXES = frozenset(
    {"co.uk", "co.kr", "com.br", "com.au", "co.jp", "co.in", "com.cn", "co.za"}
)
_MIN_SOURCES_FOR_OFFICIAL = 2


def registrable_domain(url: str | None) -> str | None:
    """등록 도메인(eTLD+1)을 반환. 판정 불가 시 None."""
    if not url:
        return None
    parsed = urlparse(url if "//" in url else f"//{url}")
    host = (parsed.hostname or "").lower().removeprefix("www.")
    if not host or "." not in host:
        return None
    labels = host.split(".")
    if len(labels) >= 3 and ".".join(labels[-2:]) in _MULTIPART_SUFFIXES:
        return ".".join(labels[-3:])
    return ".".join(labels[-2:])


def resolve_official_urls(facts: list[Fact]) -> list[Fact]:
    """서로 다른 2개 이상 소스가 동의한 도메인만 official_url로 승격."""
    by_project: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    for fact in facts:
        domain = registrable_domain(fact.source_url)
        if domain:
            by_project[fact.project][domain].add(fact.source)

    out: list[Fact] = []
    for fact in facts:
        domain = registrable_domain(fact.source_url)
        agreed = (
            domain
            and len(by_project[fact.project][domain]) >= _MIN_SOURCES_FOR_OFFICIAL
        )
        out.append(replace(fact, official_url=fact.source_url if agreed else None))
    return out


class FactStore:
    """팩트 저장소. id 기준 upsert, 만료 팩트는 query에서 제외."""

    def __init__(self, facts: list[Fact] | None = None):
        self._facts: dict[str, Fact] = {f.id: f for f in (facts or [])}

    def put(self, fact: Fact) -> None:
        self._facts[fact.id] = fact

    def all(self) -> list[Fact]:
        return list(self._facts.values())

    def query(self, *, now: str, tags: list[str] | None = None) -> list[Fact]:
        wanted = set(tags or [])
        return [
            f
            for f in self._facts.values()
            if not (f.expires_at and f.expires_at < now)
            and (not wanted or wanted & set(f.tags))
        ]

    def save(self, path: str | Path) -> None:
        path = Path(path)
        payload = {"facts": [_fact_to_dict(f) for f in self._facts.values()]}
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(
            yaml.safe_dump(payload, allow_unicode=True, sort_keys=False), encoding="utf-8"
        )
        os.replace(str(tmp), str(path))

    @classmethod
    def load(cls, path: str | Path) -> FactStore:
        path = Path(path)
        if not path.exists():
            return cls([])
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return cls([_fact_from_dict(d) for d in raw.get("facts") or []])


def _fact_to_dict(fact: Fact) -> dict:
    data = asdict(fact)
    data["tags"] = list(fact.tags)
    return data


def _fact_from_dict(data: dict) -> Fact:
    data = dict(data)
    data["tags"] = tuple(data.get("tags") or ())
    return Fact(**data)
```

- [x] **Step 4: 통과 확인** — 11 tests PASS

- [x] **Step 5: 커밋 (승인 후)** — `feat(kb): FactStore + 교차소스 official_url 합의`

---

### Task 4: collectors — Playwright 렌더 + 팩트 추출

**Files:**
- Create: `src/airdropbot/collectors/__init__.py`, `browser.py`, `extract.py`
- Test: `tests/test_collectors.py`

**Interfaces:**
- Produces: `RenderedPage(url, title, text, links)`, `render(url, *, timeout_ms=30000, headless=True) -> RenderedPage`, `render_all(urls, **kw) -> list[RenderedPage]`, `extract_facts(page, llm, *, now) -> list[Fact]`

**설계 근거:** 6개 사이트를 결정적 셀렉터로 파싱하면 개편 때마다 깨진다. `browser.py`는 **렌더된 텍스트 + 링크**만 뽑는 얇은 층으로 두고, 구조화는 소스당 LLM 1회 호출이 담당한다. 후보별 호출이 아니므로 비용이 선형으로 늘지 않는다.

- [x] **Step 1: 실패하는 테스트 작성**

```python
from airdropbot.collectors.browser import RenderedPage
from airdropbot.collectors.extract import extract_facts
from airdropbot.llm import FakeLLM

_PAGE = RenderedPage(
    url="https://airdrops.io",
    title="Airdrops",
    text="Citrea testnet bridge, ends 2026-08-15",
    links=(("Citrea", "https://citrea.xyz"),),
)

_GOOD = """```json
[{"project": "Citrea", "content": "Citrea 테스트넷 브리지",
  "source_url": "https://citrea.xyz", "chain": "citrea-testnet",
  "tags": ["testnet"], "expires_at": "2026-08-15"}]
```"""


def test_extract_facts_parses_json_and_stamps_source():
    facts = extract_facts(_PAGE, FakeLLM([_GOOD]), now="2026-07-28")
    assert len(facts) == 1
    assert facts[0].project == "Citrea"
    assert facts[0].source == "airdrops.io"
    assert facts[0].collected_at == "2026-07-28"
    assert facts[0].tags == ("testnet",)


def test_extract_facts_generates_stable_ids():
    a = extract_facts(_PAGE, FakeLLM([_GOOD]), now="2026-07-28")[0]
    b = extract_facts(_PAGE, FakeLLM([_GOOD]), now="2026-07-28")[0]
    assert a.id == b.id


def test_extract_facts_returns_empty_on_unparseable_output():
    assert extract_facts(_PAGE, FakeLLM(["I could not find anything"]), now="x") == []


def test_extract_facts_returns_empty_on_llm_error():
    class _Boom:
        def complete(self, system, prompt):
            raise RuntimeError("down")

    assert extract_facts(_PAGE, _Boom(), now="x") == []


def test_extract_facts_skips_entries_without_project():
    llm = FakeLLM(['[{"content": "no project"}]'])
    assert extract_facts(_PAGE, llm, now="x") == []
```

- [x] **Step 2: 실패 확인** — FAIL (모듈 없음)

- [x] **Step 3: 최소 구현**

`browser.py` — Playwright import는 함수 안에서 lazy하게(패키지가 playwright 없이도 import되도록):

```python
"""Playwright 렌더링 — 페이지를 텍스트 + 링크로 환원하는 얇은 층."""
from __future__ import annotations

from dataclasses import dataclass

DEFAULT_TIMEOUT_MS = 30_000
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
            page.wait_for_timeout(2_000)
            title = page.title()
            text = page.inner_text("body")[:MAX_TEXT_CHARS]
            links = page.eval_on_selector_all(
                "a[href]",
                "els => els.map(e => [e.innerText.trim(), e.href])",
            )[:MAX_LINKS]
        finally:
            browser.close()

    return RenderedPage(
        url=url, title=title, text=text, links=tuple((t, h) for t, h in links)
    )


def render_all(urls: list[str], **kwargs) -> list[RenderedPage]:
    """여러 URL을 순차 렌더링. 개별 실패는 건너뛴다(소스 다운 내성)."""
    pages: list[RenderedPage] = []
    for url in urls:
        try:
            pages.append(render(url, **kwargs))
        except Exception:
            continue
    return pages
```

`extract.py` — LLM에 렌더 결과를 주고 JSON 배열을 받는다. 파싱 실패·예외는 빈 목록(수집 실패가 파이프라인을 죽이지 않는다):

```python
"""렌더된 페이지 → 구조화된 Fact 목록 (LLM 1회 호출)."""
from __future__ import annotations

import hashlib
import json
import re

from airdropbot.collectors.browser import RenderedPage
from airdropbot.kb.store import registrable_domain
from airdropbot.llm import LLMClient
from airdropbot.models import Fact

MAX_LINKS_IN_PROMPT = 80

_SYSTEM = (
    "You extract airdrop opportunities from a rendered web page. "
    "Return STRICT JSON only: an array of objects with keys "
    '"project", "content", "source_url", "chain", "tags", "expires_at". '
    '"content" is a one-line Korean summary. "source_url" must be the project\'s '
    "own site taken from the provided links (not the aggregator's URL); use null if "
    'absent. "expires_at" is YYYY-MM-DD or null. "tags" is a string array. '
    "Output nothing except the JSON array (a ```json fence is tolerated)."
)


def extract_facts(page: RenderedPage, llm: LLMClient, *, now: str) -> list[Fact]:
    """페이지에서 Fact 목록을 추출. 실패는 빈 목록으로 흡수한다."""
    source = registrable_domain(page.url) or page.url
    links = "\n".join(f"- {t}: {h}" for t, h in page.links[:MAX_LINKS_IN_PROMPT])
    prompt = f"URL: {page.url}\nTITLE: {page.title}\n\nTEXT:\n{page.text}\n\nLINKS:\n{links}"

    try:
        raw = llm.complete(_SYSTEM, prompt)
    except Exception:
        return []

    entries = _parse_json_array(raw)
    facts: list[Fact] = []
    for entry in entries:
        project = (entry.get("project") or "").strip()
        if not project:
            continue
        facts.append(
            Fact(
                id=_fact_id(source, project, entry.get("content") or ""),
                project=project,
                content=(entry.get("content") or "").strip(),
                source=source,
                collected_at=now,
                source_url=entry.get("source_url") or None,
                chain=entry.get("chain") or None,
                tags=tuple(entry.get("tags") or ()),
                expires_at=entry.get("expires_at") or None,
            )
        )
    return facts


def _parse_json_array(raw: str) -> list[dict]:
    text = _strip_fence(raw)
    try:
        data = json.loads(text)
    except (ValueError, TypeError):
        return []
    return [d for d in data if isinstance(d, dict)] if isinstance(data, list) else []


def _strip_fence(text: str) -> str:
    s = text.strip()
    if s.startswith("```"):
        s = re.sub(r"^```[a-zA-Z]*\n?", "", s)
        s = re.sub(r"\n?```$", "", s)
    return s.strip()


def _fact_id(source: str, project: str, content: str) -> str:
    digest = hashlib.sha256(f"{source}|{project}|{content}".encode()).hexdigest()[:12]
    slug = re.sub(r"[^a-z0-9]+", "-", project.lower()).strip("-")
    return f"{slug}-{digest}"
```

- [x] **Step 4: 통과 확인** — 5 tests PASS

- [x] **Step 5: 커밋 (승인 후)** — `feat(collectors): Playwright 렌더 + LLM 팩트 추출`

---

### Task 5: selection.py — 정찰 대상 선정

**Files:**
- Create: `src/airdropbot/selection.py`
- Test: `tests/test_selection.py`

**Interfaces:**
- Produces: `select_targets(facts, *, now, limit=10) -> list[Fact]`

**정렬 규칙:** ① `official_url` 있는 것 우선(신뢰 앵커 확보분) ② 마감 임박순(`expires_at` 있는 것이 없는 것보다 앞) ③ 프로젝트명 사전순(결정적 tie-break). 만료분 제외.

- [x] **Step 1: 실패하는 테스트 작성**

```python
from airdropbot.models import Fact
from airdropbot.selection import select_targets


def _f(**kw) -> Fact:
    base = dict(id="x", project="P", content="c", source="s", collected_at="2026-07-28")
    base.update(kw)
    return Fact(**base)


def test_prefers_facts_with_official_url():
    anchored = _f(id="a", project="A", official_url="https://a.io")
    plain = _f(id="b", project="B")
    assert [f.id for f in select_targets([plain, anchored], now="2026-07-28")] == ["a", "b"]


def test_orders_by_imminent_deadline_within_same_anchor_state():
    soon = _f(id="soon", project="S", official_url="https://s.io", expires_at="2026-08-01")
    later = _f(id="later", project="L", official_url="https://l.io", expires_at="2026-09-01")
    picked = select_targets([later, soon], now="2026-07-28")
    assert [f.id for f in picked] == ["soon", "later"]


def test_facts_without_deadline_come_after_dated_ones():
    dated = _f(id="d", project="D", expires_at="2026-09-01")
    undated = _f(id="u", project="U")
    assert [f.id for f in select_targets([undated, dated], now="2026-07-28")] == ["d", "u"]


def test_excludes_expired_facts():
    assert select_targets([_f(id="old", expires_at="2026-07-01")], now="2026-07-28") == []


def test_respects_limit():
    facts = [_f(id=str(i), project=f"P{i}") for i in range(5)]
    assert len(select_targets(facts, now="2026-07-28", limit=2)) == 2


def test_is_deterministic_for_equal_ranking():
    facts = [_f(id="b", project="B"), _f(id="a", project="A")]
    assert [f.id for f in select_targets(facts, now="2026-07-28")] == ["a", "b"]
```

- [x] **Step 2: 실패 확인** — FAIL

- [x] **Step 3: 최소 구현**

```python
"""오늘 정찰할 대상 선정."""
from __future__ import annotations

from airdropbot.models import Fact

DEFAULT_LIMIT = 10
_NO_DEADLINE = "9999-12-31"


def select_targets(facts: list[Fact], *, now: str, limit: int = DEFAULT_LIMIT) -> list[Fact]:
    """만료분을 제외하고 신뢰 앵커·마감 임박 순으로 상위 limit개를 고른다."""
    live = [f for f in facts if not (f.expires_at and f.expires_at < now)]
    ranked = sorted(
        live,
        key=lambda f: (
            0 if f.official_url else 1,
            f.expires_at or _NO_DEADLINE,
            f.project,
        ),
    )
    return ranked[:limit]
```

- [x] **Step 4: 통과 확인** — 6 tests PASS

- [x] **Step 5: 커밋 (승인 후)** — `feat(selection): 신뢰 앵커·마감 임박 기준 정찰 대상 선정`

---

### Task 6: recon — 액션 레시피 정찰 + actions.yaml 영속화

**Files:**
- Create: `src/airdropbot/recon/__init__.py`, `scout.py`, `store.py`
- Test: `tests/test_recon.py`

**Interfaces:**
- Consumes: `Fact`, `Recipe`, `Step`, `RenderedPage`, `LLMClient`
- Produces: `scout_recipe(fact, page, llm, *, now) -> Recipe | None`, `load_recipes(path) -> list[Recipe]`, `save_recipes(path, recipes) -> None`

**안전 기본값:** LLM이 `signature_kind`/`automatable`에 enum 밖 값을 주면 **가장 보수적인 값**(`"approve"` 대신 `"none"`이 아니라 — 위험도 판정은 보수적으로 `"approve"`, 자동화 가능성은 `"manual"`)으로 강제한다. 알 수 없는 `action`이 섞이면 그 스텝을 버리지 않고 레시피 전체를 `automatable="manual"`로 낮춘다.

- [x] **Step 1: 실패하는 테스트 작성**

```python
from airdropbot.collectors.browser import RenderedPage
from airdropbot.llm import FakeLLM
from airdropbot.models import Fact, Recipe, Step
from airdropbot.recon.scout import scout_recipe
from airdropbot.recon.store import load_recipes, save_recipes

_FACT = Fact(
    id="citrea", project="Citrea", content="브리지", source="airdrops.io",
    collected_at="2026-07-28", official_url="https://citrea.xyz",
)
_PAGE = RenderedPage(url="https://citrea.xyz", title="Citrea", text="Faucet", links=())

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


def test_recipes_roundtrip(tmp_path):
    path = tmp_path / "actions.yaml"
    recipe = Recipe(
        project="Citrea", entry_url="https://citrea.xyz/faucet",
        steps=(Step("goto", "https://citrea.xyz/faucet"),), automatable="full",
    )
    save_recipes(path, [recipe])
    loaded = load_recipes(path)
    assert loaded[0].steps == (Step("goto", "https://citrea.xyz/faucet"),)
    assert loaded[0].automatable == "full"


def test_load_recipes_missing_file_returns_empty(tmp_path):
    assert load_recipes(tmp_path / "nope.yaml") == []


def test_save_recipes_writes_recipe_hash(tmp_path):
    path = tmp_path / "actions.yaml"
    save_recipes(path, [Recipe(project="P", entry_url="https://p.io", steps=())])
    assert "recipe_hash" in path.read_text(encoding="utf-8")
```

- [x] **Step 2: 실패 확인** — FAIL

- [x] **Step 3: 최소 구현** — `scout.py`

```python
"""활동 페이지 정찰 → 액션 레시피 추출."""
from __future__ import annotations

import json
import re

from airdropbot.collectors.browser import RenderedPage
from airdropbot.llm import LLMClient
from airdropbot.models import ACTIONS, AUTOMATABLE, SIGNATURE_KINDS, Fact, Recipe, Step

_MOST_DANGEROUS_SIGNATURE = "approve"
_LEAST_AUTOMATABLE = "manual"

_SYSTEM = (
    "You inspect a project's page and describe the exact steps a user must perform "
    "to complete its airdrop activity. Return STRICT JSON only, one object with keys: "
    '"entry_url" (string), "chain" (string|null), "signature_kind" '
    '(one of "none","message","tx","approve"), "approve_unlimited" (bool), '
    '"capital_required_usd" (number), "automatable" (one of "full","partial","manual"), '
    '"blockers" (string array), "steps" (array of {"action","target"}). '
    'Allowed actions: goto, click, fill, wait, wallet_connect, wallet_approve, '
    "wallet_sign. Be conservative: if unsure whether a wallet signature is needed, "
    'say "approve". Output nothing except the JSON object.'
)


def scout_recipe(
    fact: Fact, page: RenderedPage, llm: LLMClient, *, now: str
) -> Recipe | None:
    """페이지에서 액션 레시피를 뽑는다. 실패하면 None."""
    prompt = (
        f"PROJECT: {fact.project}\nOFFICIAL_URL: {fact.official_url}\n"
        f"KNOWN: {fact.content}\n\nPAGE_URL: {page.url}\nTITLE: {page.title}\n\n"
        f"TEXT:\n{page.text}"
    )
    try:
        raw = llm.complete(_SYSTEM, prompt)
    except Exception:
        return None

    data = _parse_json_object(raw)
    entry_url = (data.get("entry_url") or "").strip()
    if not entry_url:
        return None

    steps, saw_unknown_action = _parse_steps(data.get("steps") or [])
    automatable = data.get("automatable")
    if automatable not in AUTOMATABLE or saw_unknown_action:
        automatable = _LEAST_AUTOMATABLE

    signature_kind = data.get("signature_kind")
    if signature_kind not in SIGNATURE_KINDS:
        signature_kind = _MOST_DANGEROUS_SIGNATURE

    return Recipe(
        project=fact.project,
        entry_url=entry_url,
        steps=steps,
        chain=data.get("chain") or fact.chain,
        signature_kind=signature_kind,
        approve_unlimited=bool(data.get("approve_unlimited")),
        capital_required_usd=float(data.get("capital_required_usd") or 0),
        automatable=automatable,
        blockers=tuple(data.get("blockers") or ()),
        reconned_at=now,
    )


def _parse_steps(raw_steps: list) -> tuple[tuple[Step, ...], bool]:
    steps: list[Step] = []
    saw_unknown = False
    for item in raw_steps:
        if not isinstance(item, dict):
            saw_unknown = True
            continue
        action = (item.get("action") or "").strip()
        if action not in ACTIONS:
            saw_unknown = True
        steps.append(Step(action=action, target=(item.get("target") or "").strip()))
    return tuple(steps), saw_unknown


def _parse_json_object(raw: str) -> dict:
    s = raw.strip()
    if s.startswith("```"):
        s = re.sub(r"^```[a-zA-Z]*\n?", "", s)
        s = re.sub(r"\n?```$", "", s)
    try:
        data = json.loads(s.strip())
    except (ValueError, TypeError):
        return {}
    return data if isinstance(data, dict) else {}
```

`store.py` — `actions.yaml` 로드/저장. 저장 시 `recipe_hash`를 함께 기록하고, v1이므로 `verdict: null`을 명시한다:

```python
"""actions.yaml — 액션 레시피 영속화."""
from __future__ import annotations

import os
from pathlib import Path

import yaml

from airdropbot.models import Recipe, Step, recipe_hash


def load_recipes(path: str | Path) -> list[Recipe]:
    path = Path(path)
    if not path.exists():
        return []
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return [_recipe_from_dict(d) for d in raw.get("recipes") or []]


def save_recipes(path: str | Path, recipes: list[Recipe]) -> None:
    path = Path(path)
    payload = {"recipes": [_recipe_to_dict(r) for r in recipes]}
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        yaml.safe_dump(payload, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    os.replace(str(tmp), str(path))


def _recipe_to_dict(recipe: Recipe) -> dict:
    return {
        "project": recipe.project,
        "recipe_hash": recipe_hash(recipe),
        "entry_url": recipe.entry_url,
        "chain": recipe.chain,
        "signature_kind": recipe.signature_kind,
        "approve_unlimited": recipe.approve_unlimited,
        "capital_required_usd": recipe.capital_required_usd,
        "steps": [{"action": s.action, "target": s.target} for s in recipe.steps],
        "automatable": recipe.automatable,
        "blockers": list(recipe.blockers),
        "reconned_at": recipe.reconned_at,
        "verdict": None,
    }


def _recipe_from_dict(data: dict) -> Recipe:
    return Recipe(
        project=data["project"],
        entry_url=data["entry_url"],
        steps=tuple(
            Step(action=s.get("action", ""), target=s.get("target", ""))
            for s in data.get("steps") or []
        ),
        chain=data.get("chain"),
        signature_kind=data.get("signature_kind") or "none",
        approve_unlimited=bool(data.get("approve_unlimited")),
        capital_required_usd=float(data.get("capital_required_usd") or 0),
        automatable=data.get("automatable") or "manual",
        blockers=tuple(data.get("blockers") or ()),
        reconned_at=data.get("reconned_at") or "",
    )
```

- [x] **Step 4: 통과 확인** — 10 tests PASS

- [x] **Step 5: 커밋 (승인 후)** — `feat(recon): 액션 레시피 정찰 + actions.yaml 영속화`

---

### Task 7: verify — council (Refuter + Judge) + verdict 캐시

**Files:**
- Create: `src/airdropbot/verify/__init__.py`, `council.py`, `cache.py`
- Test: `tests/test_verify.py`

**Interfaces:**
- Produces: `verify_recipe(recipe, facts, llm) -> Verdict`, `load_verdicts(path) -> dict[str, Verdict]`, `save_verdicts(path, verdicts) -> None`

**fail-closed** — 파싱 실패·빈 응답·예외·`passed` 키 부재는 전부 `Verdict(passed=False)`.

- [x] **Step 1: 실패하는 테스트 작성**

```python
from airdropbot.llm import FakeLLM
from airdropbot.models import Fact, Recipe, Step, Verdict
from airdropbot.verify.cache import load_verdicts, save_verdicts
from airdropbot.verify.council import verify_recipe

_RECIPE = Recipe(
    project="Citrea", entry_url="https://citrea.xyz/faucet",
    steps=(Step("goto", "https://citrea.xyz/faucet"),), automatable="full",
)
_FACTS = [
    Fact(id="a", project="Citrea", content="브리지", source="airdrops.io",
         collected_at="2026-07-28", official_url="https://citrea.xyz")
]


def test_council_passes_when_judge_says_so():
    llm = FakeLLM(["refuter text", '{"passed": true, "issues": []}'])
    assert verify_recipe(_RECIPE, _FACTS, llm).passed is True


def test_council_runs_refuter_then_judge():
    llm = FakeLLM(["refuter text", '{"passed": true, "issues": []}'])
    verify_recipe(_RECIPE, _FACTS, llm)
    assert len(llm.calls) == 2
    assert "Refuter" in llm.calls[0][0]
    assert "Judge" in llm.calls[1][0]


def test_council_fails_and_keeps_issues():
    llm = FakeLLM(["refuter", '{"passed": false, "issues": ["도메인 위장"]}'])
    verdict = verify_recipe(_RECIPE, _FACTS, llm)
    assert verdict.passed is False
    assert verdict.issues == ("도메인 위장",)


def test_council_fails_closed_on_unparseable_judge():
    llm = FakeLLM(["refuter", "probably fine"])
    assert verify_recipe(_RECIPE, _FACTS, llm).passed is False


def test_council_fails_closed_on_missing_passed_key():
    llm = FakeLLM(["refuter", '{"issues": []}'])
    assert verify_recipe(_RECIPE, _FACTS, llm).passed is False


def test_council_fails_closed_on_llm_error():
    class _Boom:
        def complete(self, system, prompt):
            raise RuntimeError("down")

    assert verify_recipe(_RECIPE, _FACTS, _Boom()).passed is False


def test_council_tolerates_json_fence():
    llm = FakeLLM(["refuter", '```json\n{"passed": true, "issues": []}\n```'])
    assert verify_recipe(_RECIPE, _FACTS, llm).passed is True


def test_verdicts_roundtrip(tmp_path):
    path = tmp_path / "verdicts.yaml"
    save_verdicts(path, {"sha256:ab": Verdict(passed=False, issues=("bad",))})
    loaded = load_verdicts(path)
    assert loaded["sha256:ab"].passed is False
    assert loaded["sha256:ab"].issues == ("bad",)


def test_load_verdicts_missing_file_returns_empty(tmp_path):
    assert load_verdicts(tmp_path / "nope.yaml") == {}
```

- [x] **Step 2: 실패 확인** — FAIL

- [x] **Step 3: 최소 구현** — `council.py`

```python
"""서명 게이트 council — Refuter + Judge 2역할.

autoinsta의 3역할(Defender/Refuter/Judge)에서 Defender를 뺐다. 레시피가 반려돼도
비용이 0이므로(오늘 그 에어드랍을 건너뛰면 끝) 변호인이 필요 없고, 안전 게이트의
기본값은 "서명하지 않음"이어야 하기 때문이다.
"""
from __future__ import annotations

import json
import re

from airdropbot.llm import LLMClient
from airdropbot.models import Fact, Recipe, Verdict

_REFUTER_SYSTEM = (
    "You are the Refuter in a security council guarding a crypto wallet. Given an "
    "action recipe and the KB facts it came from, construct the strongest possible "
    "case that executing it would lose the user's assets. Attack: domain spoofing "
    "(typosquatting, lookalike TLDs), URLs absent from the KB facts, the scope of any "
    "token approval, unexpected signature prompts mid-flow, and weak source provenance. "
    "Be ruthless and concrete."
)

_JUDGE_SYSTEM = (
    "You are the Judge in a security council guarding a crypto wallet. Given the "
    "Refuter's argument, the recipe, and the KB facts, decide whether it is safe to "
    "execute with a real wallet. Return STRICT JSON only, of the exact shape "
    '{"passed": bool, "issues": [str, ...]}. Default to false when uncertain. '
    "Output nothing except the JSON object (a ```json fence is tolerated)."
)


def verify_recipe(recipe: Recipe, facts: list[Fact], llm: LLMClient) -> Verdict:
    """레시피 실행 안전성을 판정. 어떤 실패든 fail-closed."""
    context = f"{_render_recipe(recipe)}\n\nKB FACTS:\n{_render_facts(facts)}"
    try:
        refutation = llm.complete(_REFUTER_SYSTEM, context)
        judgement = llm.complete(
            _JUDGE_SYSTEM, f"{context}\n\nREFUTER:\n{refutation}"
        )
    except Exception as e:
        return Verdict(passed=False, issues=(f"council 실행 실패: {e}",))

    data = _parse_json_object(judgement)
    if not isinstance(data.get("passed"), bool):
        return Verdict(
            passed=False,
            issues=("Judge 응답을 파싱하지 못함 (fail-closed)",),
            log=refutation,
        )
    issues = tuple(str(i) for i in (data.get("issues") or []))
    return Verdict(passed=data["passed"], issues=issues, log=refutation)


def _render_recipe(recipe: Recipe) -> str:
    steps = "\n".join(f"  {i}. {s.action} -> {s.target}" for i, s in enumerate(recipe.steps, 1))
    return (
        f"RECIPE\nproject: {recipe.project}\nentry_url: {recipe.entry_url}\n"
        f"chain: {recipe.chain}\nsignature_kind: {recipe.signature_kind}\n"
        f"approve_unlimited: {recipe.approve_unlimited}\n"
        f"capital_required_usd: {recipe.capital_required_usd}\n"
        f"automatable: {recipe.automatable}\nblockers: {list(recipe.blockers)}\n"
        f"steps:\n{steps}"
    )


def _render_facts(facts: list[Fact]) -> str:
    if not facts:
        return "(no KB facts provided)"
    return "\n".join(
        f"- [{f.source}] {f.content} (official_url: {f.official_url})" for f in facts
    )


def _parse_json_object(raw: str) -> dict:
    s = raw.strip()
    if s.startswith("```"):
        s = re.sub(r"^```[a-zA-Z]*\n?", "", s)
        s = re.sub(r"\n?```$", "", s)
    try:
        data = json.loads(s.strip())
    except (ValueError, TypeError):
        return {}
    return data if isinstance(data, dict) else {}
```

`cache.py`:

```python
"""verdict 캐시 — recipe_hash가 바뀌면 자동 무효화되므로 별도 만료 로직이 없다."""
from __future__ import annotations

import os
from pathlib import Path

import yaml

from airdropbot.models import Verdict


def load_verdicts(path: str | Path) -> dict[str, Verdict]:
    path = Path(path)
    if not path.exists():
        return {}
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return {
        key: Verdict(
            passed=bool(value.get("passed")),
            issues=tuple(value.get("issues") or ()),
        )
        for key, value in (raw.get("verdicts") or {}).items()
    }


def save_verdicts(path: str | Path, verdicts: dict[str, Verdict]) -> None:
    path = Path(path)
    payload = {
        "verdicts": {
            key: {"passed": v.passed, "issues": list(v.issues)}
            for key, v in verdicts.items()
        }
    }
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        yaml.safe_dump(payload, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    os.replace(str(tmp), str(path))
```

- [x] **Step 4: 통과 확인** — 9 tests PASS

- [x] **Step 5: 커밋 (승인 후)** — `feat(verify): Refuter+Judge council (fail-closed) + verdict 캐시`

---

### Task 8: execute/guard.py — 결정적 프리필터

**Files:**
- Create: `src/airdropbot/execute/__init__.py`, `guard.py`
- Test: `tests/test_guard.py`

**Interfaces:**
- Produces: `Limits(capital_cap_usd=0.0, balance_cap_usd=50.0, chain_allowlist=None)`, `GuardResult(allowed, reason=None, pointing_only=False)`, `prefilter(recipe, facts, limits, *, wallet_balance_usd=0.0) -> GuardResult`

**규칙 순서** (spec §6): ① 도메인 불일치 ② 무제한 approve ③ 자본 초과 ④ 잔고 초과 ⑤ chain allowlist 밖(allowlist가 None이면 스킵) ⑥ `automatable != "full"` → `pointing_only`

- [x] **Step 1: 실패하는 테스트 작성 (악성 레시피 = 검증기의 검증)**

```python
from airdropbot.execute.guard import Limits, prefilter
from airdropbot.models import Fact, Recipe, Step

_FACTS = [
    Fact(id="a", project="Citrea", content="브리지", source="airdrops.io",
         collected_at="2026-07-28", official_url="https://citrea.xyz")
]


def _recipe(**kw) -> Recipe:
    base = dict(
        project="Citrea",
        entry_url="https://app.citrea.xyz/faucet",
        steps=(Step("goto", "https://app.citrea.xyz/faucet"),),
        automatable="full",
    )
    base.update(kw)
    return Recipe(**base)


def test_allows_clean_recipe_on_subdomain_of_official():
    assert prefilter(_recipe(), _FACTS, Limits()).allowed is True


def test_rejects_typosquatted_domain():
    result = prefilter(_recipe(entry_url="https://ctirea.xyz/faucet"), _FACTS, Limits())
    assert result.allowed is False
    assert "도메인" in result.reason


def test_rejects_lookalike_domain():
    result = prefilter(_recipe(entry_url="https://citrea-xyz.io/faucet"), _FACTS, Limits())
    assert result.allowed is False


def test_rejects_when_no_official_url_anchor():
    facts = [Fact(id="a", project="Citrea", content="c", source="s", collected_at="d")]
    assert prefilter(_recipe(), facts, Limits()).allowed is False


def test_rejects_unlimited_approve():
    recipe = _recipe(signature_kind="approve", approve_unlimited=True)
    result = prefilter(recipe, _FACTS, Limits())
    assert result.allowed is False
    assert "approve" in result.reason


def test_rejects_capital_over_cap():
    result = prefilter(_recipe(capital_required_usd=10.0), _FACTS, Limits(capital_cap_usd=0.0))
    assert result.allowed is False


def test_rejects_wallet_balance_over_cap():
    result = prefilter(
        _recipe(), _FACTS, Limits(balance_cap_usd=50.0), wallet_balance_usd=500.0
    )
    assert result.allowed is False
    assert "잔고" in result.reason


def test_rejects_chain_outside_allowlist():
    limits = Limits(chain_allowlist=("base",))
    result = prefilter(_recipe(chain="citrea-testnet"), _FACTS, limits)
    assert result.allowed is False


def test_skips_chain_rule_when_allowlist_absent():
    assert prefilter(_recipe(chain="anything"), _FACTS, Limits()).allowed is True


def test_marks_partial_recipe_as_pointing_only():
    result = prefilter(_recipe(automatable="partial"), _FACTS, Limits())
    assert result.allowed is False
    assert result.pointing_only is True


def test_domain_rule_is_evaluated_before_approve_rule():
    recipe = _recipe(entry_url="https://evil.io", signature_kind="approve", approve_unlimited=True)
    assert "도메인" in prefilter(recipe, _FACTS, Limits()).reason
```

- [x] **Step 2: 실패 확인** — FAIL

- [x] **Step 3: 최소 구현**

```python
"""서명 이전 결정적 프리필터. 거부의 대부분을 LLM 호출 없이 처리한다."""
from __future__ import annotations

from dataclasses import dataclass

from airdropbot.kb.store import registrable_domain
from airdropbot.models import Fact, Recipe


@dataclass(frozen=True)
class Limits:
    capital_cap_usd: float = 0.0
    balance_cap_usd: float = 50.0
    chain_allowlist: tuple[str, ...] | None = None


@dataclass(frozen=True)
class GuardResult:
    allowed: bool
    reason: str | None = None
    pointing_only: bool = False


def prefilter(
    recipe: Recipe,
    facts: list[Fact],
    limits: Limits,
    *,
    wallet_balance_usd: float = 0.0,
) -> GuardResult:
    """spec §6 규칙을 순서대로 평가. 하나라도 걸리면 즉시 거부."""
    entry_domain = registrable_domain(recipe.entry_url)
    official_domains = {
        d
        for d in (
            registrable_domain(f.official_url)
            for f in facts
            if f.project == recipe.project
        )
        if d
    }
    if not official_domains:
        return GuardResult(False, f"{recipe.project}: KB에 합의된 official_url 없음")
    if entry_domain not in official_domains:
        return GuardResult(
            False, f"entry_url 도메인({entry_domain})이 KB official_url과 불일치"
        )

    if recipe.signature_kind == "approve" and recipe.approve_unlimited:
        return GuardResult(False, "무제한 approve 서명 요구")

    if recipe.capital_required_usd > limits.capital_cap_usd:
        return GuardResult(
            False,
            f"요구 자본 ${recipe.capital_required_usd} > 상한 ${limits.capital_cap_usd}",
        )

    if wallet_balance_usd > limits.balance_cap_usd:
        return GuardResult(
            False, f"지갑 잔고 ${wallet_balance_usd} > 상한 ${limits.balance_cap_usd}"
        )

    if limits.chain_allowlist is not None and recipe.chain not in limits.chain_allowlist:
        return GuardResult(False, f"체인({recipe.chain})이 allowlist 밖")

    if recipe.automatable != "full":
        return GuardResult(
            False, f"자동화 불가({recipe.automatable}) — 포인팅만", pointing_only=True
        )

    return GuardResult(True)
```

- [x] **Step 4: 통과 확인** — 11 tests PASS

- [x] **Step 5: 커밋 (승인 후)** — `feat(guard): 서명 이전 결정적 프리필터`

---

### Task 9: execute — 지갑 세션 + dry-run 실행기

**Files:**
- Create: `src/airdropbot/execute/session.py`, `src/airdropbot/execute/runner.py`
- Test: `tests/test_runner.py`

**Interfaces:**
- Consumes: `Limits`, `GuardResult`, `prefilter`, `verify_recipe`, `Recipe`, `Fact`
- Produces: `wallet_page(user_data_dir, *, headless=False, ...)` 컨텍스트매니저, `run_recipe(recipe, facts, limits, *, llm=None, dry_run=True, page=None, wallet_balance_usd=0.0) -> dict`

**계약** (autoinsta `publish/instagram.py` 이식):
- `dry_run=True`(기본) → 브라우저를 구동하지 않고 plan 반환
- `dry_run=False` + `page is None` → `ValueError`
- guard 거부 → council 호출 없이 즉시 `rejected` / `pointing_only`
- guard 통과 + `dry_run=False` → council 통과해야만 실행

- [x] **Step 1: 실패하는 테스트 작성**

```python
import pytest

from airdropbot.execute.guard import Limits
from airdropbot.execute.runner import run_recipe
from airdropbot.llm import FakeLLM
from airdropbot.models import Fact, Recipe, Step

_FACTS = [
    Fact(id="a", project="Citrea", content="브리지", source="airdrops.io",
         collected_at="2026-07-28", official_url="https://citrea.xyz")
]
_RECIPE = Recipe(
    project="Citrea", entry_url="https://citrea.xyz/faucet",
    steps=(Step("goto", "https://citrea.xyz/faucet"), Step("click", "Request")),
    automatable="full",
)


class _FakePage:
    def __init__(self):
        self.actions = []

    def goto(self, url, **kw):
        self.actions.append(("goto", url))

    def click(self, selector, **kw):
        self.actions.append(("click", selector))

    def get_by_text(self, text):
        self.actions.append(("click", text))
        return self

    def first(self):
        return self

    def wait_for_timeout(self, ms):
        self.actions.append(("wait", str(ms)))


def test_dry_run_returns_plan_without_browser():
    result = run_recipe(_RECIPE, _FACTS, Limits())
    assert result["status"] == "dry_run"
    assert len(result["plan"]) == 2
    assert result["plan"][0] == "goto -> https://citrea.xyz/faucet"


def test_dry_run_reports_recipe_hash():
    assert run_recipe(_RECIPE, _FACTS, Limits())["recipe_hash"].startswith("sha256:")


def test_guard_rejection_short_circuits_before_council():
    bad = Recipe(project="Citrea", entry_url="https://evil.io", steps=(), automatable="full")
    llm = FakeLLM([])  # 호출되면 AssertionError
    result = run_recipe(bad, _FACTS, Limits(), llm=llm)
    assert result["status"] == "rejected"
    assert llm.calls == []


def test_pointing_only_status():
    manual = Recipe(
        project="Citrea", entry_url="https://citrea.xyz/faucet", steps=(),
        automatable="manual",
    )
    assert run_recipe(manual, _FACTS, Limits())["status"] == "pointing_only"


def test_live_run_without_page_raises():
    with pytest.raises(ValueError):
        run_recipe(_RECIPE, _FACTS, Limits(), llm=FakeLLM([]), dry_run=False)


def test_live_run_requires_llm():
    with pytest.raises(ValueError):
        run_recipe(_RECIPE, _FACTS, Limits(), dry_run=False, page=_FakePage())


def test_live_run_blocked_by_failed_council():
    llm = FakeLLM(["refuter", '{"passed": false, "issues": ["의심 도메인"]}'])
    result = run_recipe(_RECIPE, _FACTS, Limits(), llm=llm, dry_run=False, page=_FakePage())
    assert result["status"] == "rejected"
    assert result["issues"] == ["의심 도메인"]


def test_live_run_executes_steps_when_council_passes():
    page = _FakePage()
    llm = FakeLLM(["refuter", '{"passed": true, "issues": []}'])
    result = run_recipe(_RECIPE, _FACTS, Limits(), llm=llm, dry_run=False, page=page)
    assert result["status"] == "executed"
    assert ("goto", "https://citrea.xyz/faucet") in page.actions


def test_live_run_aborts_on_wallet_step_in_v1():
    recipe = Recipe(
        project="Citrea", entry_url="https://citrea.xyz/faucet",
        steps=(Step("wallet_sign", "confirm"),), automatable="full",
    )
    llm = FakeLLM(["refuter", '{"passed": true, "issues": []}'])
    result = run_recipe(recipe, _FACTS, Limits(), llm=llm, dry_run=False, page=_FakePage())
    assert result["status"] == "aborted"
```

- [x] **Step 2: 실패 확인** — FAIL

- [x] **Step 3: 최소 구현** — `session.py`

```python
"""지갑 브라우저 세션.

autoinsta ``publish/session.py`` 이식. 코드가 개인키·시드를 절대 만지지 않는다:
전용 프로필 디렉토리에 지갑 확장을 두고 최초 1회만 사람이 headful 창에서 직접
시드 입력·잠금해제하면, 세션이 디스크에 남아 이후 실행이 이를 재사용한다.

사용법::

    with wallet_page(".wallet_profile") as page:
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
        extension_path: 언팩된 지갑 확장 디렉토리. 지정 시 확장을 로드한다
            (확장 로딩은 headless에서 동작하지 않으므로 headless=False가 강제된다).
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
```

`runner.py`:

```python
"""액션 레시피 실행기. dry-run이 기본이며 서명 스텝은 v1에서 중단된다."""
from __future__ import annotations

from airdropbot.execute.guard import GuardResult, Limits, prefilter
from airdropbot.llm import LLMClient
from airdropbot.models import Fact, Recipe, Step, recipe_hash
from airdropbot.verify.council import verify_recipe

_WALLET_ACTIONS = frozenset({"wallet_connect", "wallet_approve", "wallet_sign"})
_STEP_WAIT_MS = 1_000


def run_recipe(
    recipe: Recipe,
    facts: list[Fact],
    limits: Limits,
    *,
    llm: LLMClient | None = None,
    dry_run: bool = True,
    page=None,
    wallet_balance_usd: float = 0.0,
) -> dict:
    """레시피를 실행한다. 기본은 dry-run으로 브라우저를 구동하지 않는다.

    Returns:
        ``{"status": "dry_run"|"rejected"|"pointing_only"|"executed"|"aborted", ...}``

    Raises:
        ValueError: ``dry_run=False``인데 ``page`` 또는 ``llm``이 없을 때.
    """
    guard = prefilter(recipe, facts, limits, wallet_balance_usd=wallet_balance_usd)
    base = {"project": recipe.project, "recipe_hash": recipe_hash(recipe)}

    if not guard.allowed:
        return {
            **base,
            "status": "pointing_only" if guard.pointing_only else "rejected",
            "reason": guard.reason,
        }

    if dry_run:
        return {**base, "status": "dry_run", "plan": _plan(recipe)}

    if page is None:
        raise ValueError(
            "live run requires an authenticated Playwright `page` "
            "(dry_run=False, page=<wallet_page(...)>)"
        )
    if llm is None:
        raise ValueError("live run requires an `llm` for the council gate")

    verdict = verify_recipe(recipe, facts, llm)
    if not verdict.passed:
        return {**base, "status": "rejected", "issues": list(verdict.issues)}

    return {**base, **_drive(page, recipe)}


def _plan(recipe: Recipe) -> list[str]:
    return [f"{s.action} -> {s.target}" for s in recipe.steps]


def _drive(page, recipe: Recipe) -> dict:
    """스텝을 순서대로 실행. 지갑 서명 스텝을 만나면 v1은 중단한다."""
    done: list[str] = []
    for step in recipe.steps:
        if step.action in _WALLET_ACTIONS:
            return {
                "status": "aborted",
                "reason": f"v1은 지갑 스텝을 실행하지 않음: {step.action}",
                "completed": done,
            }
        try:
            _apply(page, step)
        except Exception as e:
            return {"status": "aborted", "reason": f"{step.action} 실패: {e}", "completed": done}
        done.append(f"{step.action} -> {step.target}")
    return {"status": "executed", "completed": done}


def _apply(page, step: Step) -> None:
    if step.action == "goto":
        page.goto(step.target)
    elif step.action == "click":
        page.get_by_text(step.target).first().click()
    elif step.action == "fill":
        selector, _, value = step.target.partition("=")
        page.fill(selector.strip(), value.strip())
    elif step.action == "wait":
        page.wait_for_timeout(_STEP_WAIT_MS)
```

- [x] **Step 4: 통과 확인** — 9 tests PASS

- [x] **Step 5: 커밋 (승인 후)** — `feat(execute): 지갑 persistent 세션 + dry-run 실행기`

---

### Task 10: orchestrator + 배선 + 문서

**Files:**
- Create: `src/airdropbot/orchestrator.py`, `tests/test_orchestrator.py`
- Modify: `pyproject.toml`(playwright 의존성), `.gitignore`(지갑 프로필), `NEXT.md`

**Interfaces:**
- Produces: `run_pipeline(*, sources, kb_path, actions_path, llm, now, render_fn=..., limit=10, dry_run=True) -> dict`

- [x] **Step 1: 실패하는 테스트 작성**

```python
from airdropbot.collectors.browser import RenderedPage
from airdropbot.llm import FakeLLM
from airdropbot.orchestrator import run_pipeline

_LIST_PAGE = RenderedPage(
    url="https://airdrops.io", title="Airdrops", text="Citrea bridge",
    links=(("Citrea", "https://citrea.xyz"),),
)
_PROJECT_PAGE = RenderedPage(
    url="https://citrea.xyz", title="Citrea", text="Faucet", links=()
)

_FACT_JSON = (
    '[{"project": "Citrea", "content": "브리지", "source_url": "https://citrea.xyz",'
    ' "chain": "citrea-testnet", "tags": ["testnet"], "expires_at": "2026-12-01"}]'
)
_RECIPE_JSON = (
    '{"entry_url": "https://citrea.xyz/faucet", "chain": "citrea-testnet",'
    ' "signature_kind": "none", "approve_unlimited": false, "capital_required_usd": 0,'
    ' "automatable": "full", "blockers": [],'
    ' "steps": [{"action": "goto", "target": "https://citrea.xyz/faucet"}]}'
)


def _render_fn(url, **kw):
    return _LIST_PAGE if "airdrops.io" in url else _PROJECT_PAGE


def test_pipeline_persists_facts_and_recipes(tmp_path):
    kb_path, actions_path = tmp_path / "kb.yaml", tmp_path / "actions.yaml"
    llm = FakeLLM([_FACT_JSON, _FACT_JSON, _RECIPE_JSON])

    result = run_pipeline(
        sources=["https://airdrops.io", "https://icodrops.com"],
        kb_path=kb_path, actions_path=actions_path, llm=llm,
        now="2026-07-28", render_fn=_render_fn,
    )

    assert result["facts"] == 2
    assert result["recipes"] == 1
    assert kb_path.exists() and actions_path.exists()


def test_pipeline_promotes_official_url_on_two_source_agreement(tmp_path):
    llm = FakeLLM([_FACT_JSON, _FACT_JSON, _RECIPE_JSON])
    result = run_pipeline(
        sources=["https://airdrops.io", "https://icodrops.com"],
        kb_path=tmp_path / "kb.yaml", actions_path=tmp_path / "actions.yaml",
        llm=llm, now="2026-07-28", render_fn=_render_fn,
    )
    assert result["anchored"] == 2


def test_pipeline_is_dry_run_by_default(tmp_path):
    llm = FakeLLM([_FACT_JSON, _FACT_JSON, _RECIPE_JSON])
    result = run_pipeline(
        sources=["https://airdrops.io", "https://icodrops.com"],
        kb_path=tmp_path / "kb.yaml", actions_path=tmp_path / "actions.yaml",
        llm=llm, now="2026-07-28", render_fn=_render_fn,
    )
    assert all(r["status"] in {"dry_run", "pointing_only", "rejected"} for r in result["runs"])


def test_pipeline_survives_a_dead_source(tmp_path):
    def _flaky(url, **kw):
        if "icodrops" in url:
            raise RuntimeError("source down")
        return _render_fn(url)

    llm = FakeLLM([_FACT_JSON, _RECIPE_JSON])
    result = run_pipeline(
        sources=["https://airdrops.io", "https://icodrops.com"],
        kb_path=tmp_path / "kb.yaml", actions_path=tmp_path / "actions.yaml",
        llm=llm, now="2026-07-28", render_fn=_flaky,
    )
    assert result["facts"] == 1
```

- [x] **Step 2: 실패 확인** — FAIL

- [x] **Step 3: 최소 구현**

```python
"""전 구간 오케스트레이션: 수집 → KB → 선정 → 정찰 → 실행 게이트(dry-run)."""
from __future__ import annotations

from pathlib import Path

from airdropbot.collectors.browser import render
from airdropbot.collectors.extract import extract_facts
from airdropbot.execute.guard import Limits
from airdropbot.execute.runner import run_recipe
from airdropbot.kb.store import FactStore, resolve_official_urls
from airdropbot.llm import LLMClient
from airdropbot.recon.scout import scout_recipe
from airdropbot.recon.store import load_recipes, save_recipes
from airdropbot.selection import select_targets


def run_pipeline(
    *,
    sources: list[str],
    kb_path: str | Path,
    actions_path: str | Path,
    llm: LLMClient,
    now: str,
    render_fn=render,
    limit: int = 10,
    dry_run: bool = True,
    limits: Limits | None = None,
) -> dict:
    """하루치 파이프라인을 1회 실행하고 요약 dict를 반환한다."""
    limits = limits or Limits()

    collected = []
    for url in sources:
        try:
            page = render_fn(url)
        except Exception:
            continue
        collected.extend(extract_facts(page, llm, now=now))

    anchored = resolve_official_urls(collected)
    store = FactStore.load(kb_path)
    for fact in anchored:
        store.put(fact)
    store.save(kb_path)

    targets = select_targets(store.query(now=now), now=now, limit=limit)

    recipes = {r.entry_url: r for r in load_recipes(actions_path)}
    runs = []
    for fact in targets:
        if not fact.official_url:
            continue
        try:
            page = render_fn(fact.official_url)
        except Exception:
            continue
        recipe = scout_recipe(fact, page, llm, now=now)
        if recipe is None:
            continue
        recipes[recipe.entry_url] = recipe
        runs.append(
            run_recipe(recipe, store.all(), limits, llm=llm, dry_run=dry_run)
        )

    save_recipes(actions_path, list(recipes.values()))

    return {
        "facts": len(anchored),
        "anchored": sum(1 for f in anchored if f.official_url),
        "targets": len(targets),
        "recipes": len(recipes),
        "runs": runs,
    }
```

- [x] **Step 4: 통과 확인** — 4 tests PASS, 전체 스위트 통과

Run: `.venv/bin/pytest -q && .venv/bin/ruff check .`

- [x] **Step 5: 의존성 + gitignore + 문서**

`pyproject.toml`의 `dependencies`에 `"playwright>=1.49"` 추가.
`.gitignore`에 지갑 프로필·캐시 추가:

```
.wallet_profile/
cache/kb.yaml
cache/verdicts.yaml
```

`NEXT.md`에 v1.0 섹션 추가 (구현 완료 범위 + v2 승격 조건).

- [x] **Step 6: 커밋 (승인 후)** — `feat(pipeline): Playwright 수집→정찰→dry-run 게이트 오케스트레이션`

---

---

### Task 11: 2-pass detail enrichment (라이브 검증 후 추가)

**Files:**
- Create: `src/airdropbot/collectors/enrich.py`, `tests/test_enrich.py`
- Modify: `src/airdropbot/models.py`(`Fact.detail_url`), `collectors/extract.py`(프롬프트에 `detail_url`),
  `collectors/browser.py`(`resolve_redirect`), `kb/store.py`(`project_key`),
  `execute/guard.py`(정규화 매칭), `orchestrator.py`(2국면 enrichment)

**왜 추가됐나:** 라이브 스모크에서 airdrops.io 수집분 46개 전부 `source_url=null`이었다. 리스팅 페이지 링크가 전부 집계 사이트 자체 페이지였고, 프로젝트 실제 주소는 `airdrops.io/visit/<code>/` 리다이렉트 뒤에 있었다. spec §4.1 참조.

**Interfaces:**
- Produces: `resolve_redirect(url) -> str`, `enrich_source_url(fact, llm, *, render_fn, resolve_fn) -> Fact`, `project_key(project) -> str`

- [x] **Step 1: `Fact.detail_url` 추가 + extract 프롬프트에 `detail_url` 요구**
- [x] **Step 2: `browser.resolve_redirect` — goto 후 최종 `page.url` 반환**
- [x] **Step 3: `enrich_source_url` — 상세 페이지 렌더 → LLM이 프로젝트 URL 지목 → 집계 도메인이면 리다이렉트 해소 → 소셜 도메인 거부**
- [x] **Step 4: `project_key` 정규화를 앵커 합의·guard 매칭에 적용**
- [x] **Step 5: orchestrator 2국면 enrichment (앵커 후보 / 선정 대상) + 정찰은 앵커 불요**
- [x] **Step 6: 테스트 통과 확인** — `.venv/bin/python -m pytest -q` → 147 passed, ruff clean

---

## 실측 검증 기록 (2026-07-28)

| 검증 | 결과 |
|---|---|
| `render()` 라이브 (airdrops.io) | 통과 — 17,842자 텍스트, 175 링크 |
| 6개 소스 렌더 | 6/6 성공 (cryptorank·coinmarketcap 포함) |
| 수집 팩트 / 고유 프로젝트 / 앵커 후보 | 177 / 163 / **12** |
| enrichment 전 파이프라인 | `facts=46, anchored=0, recipes=0` — 레시피 0건 |
| enrichment 후 파이프라인 | `facts=34, anchored=0, recipes=2` — 레시피 생성됨 |
| 생성 레시피 품질 | `signature_kind=approve`, `capital_required_usd=100`, `automatable=manual`, blockers 기록 — 보수적 분류 정상 |
| 실행 게이트 | 앵커 없는 레시피 2건 모두 `rejected` ("KB에 합의된 official_url 없음") |
| 전체 스위트 | 147 passed, ruff clean |

2소스만으로는 앵커 후보가 0~1개라 앵커링이 성립하지 않는다. **6개 소스 전량이 전제 조건**이다.

## Self-Review

**1. Spec coverage**

| spec 섹션 | 담당 Task |
|---|---|
| §2.1 ClaudeCliClient (LLM $0) | Task 2 |
| §2.2 council 배치 = 서명 게이트 | Task 7, 9 |
| §4 컴포넌트 경계 | Task 1–10 (File Structure 표) |
| §5.1 KB 팩트 + 2소스 합의 | Task 3 |
| §5.2 액션 레시피 + recipe_hash | Task 1, 6 |
| §5.3 verdict 캐시 | Task 7 |
| §6 코드 프리필터 6규칙 | Task 8 |
| §7 Refuter+Judge, fail-closed | Task 7 |
| §8 dry-run 계약 + 지갑 세션 | Task 9 |
| §9 실패복구 (소스 다운/recon 실패/council fail/서명 중단) | Task 4(render_all), 6, 9, 10 |
| §10 테스트 전략 | 각 Task Step 1 |
| §11 v1 경계 (서명 미실행) | Task 9 `_drive` 중단 |
| §12 v2 승격 조건 | Task 10 Step 5 (NEXT.md) |

갭 없음.

**2. Placeholder scan** — "TBD"/"적절히 처리" 류 없음. 모든 코드 스텝에 실제 코드가 있다.

**3. Type consistency** — `Fact`/`Recipe`/`Step`/`Verdict` 필드명이 Task 1 정의와 이후 모든 Task에서 일치. `registrable_domain`은 Task 3에서 정의되어 Task 4(extract)·Task 8(guard)에서 재사용. `Limits`/`GuardResult`는 Task 8 정의를 Task 9·10이 소비. `run_recipe`의 반환 status 집합이 Task 9 테스트와 Task 10 테스트에서 일치.

---

## 실행 기록 (2026-07-29)

Task 1–11 전량 완료. 각 Task의 "Step 5: 커밋"은 **개별 커밋 대신 v1.0 단일 커밋으로
묶어서** 처리했다 (사용자 승인: 2026-07-29, spec/plan/구현 번들). 최종 상태:

- `.venv/bin/python -m pytest -q` → **147 passed**
- `.venv/bin/ruff check .` → **All checks passed**
