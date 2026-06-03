# KanbanFlow REST client (#315, Phase 2) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a stdlib-only KanbanFlow REST client (`lib/kanbanflow_client.py`) that the Phase-3 `KanbanFlowProvider` (#316) will sit on — Bearer auth, quota-aware throttling, typed resources, typed errors — fully unit-testable offline.

**Architecture:** All network I/O funnels through one module-level seam `_raw_http`; everything above it (auth header, JSON, quota budget, retry/backoff, error mapping) is pure logic. Typed per-resource methods return KanbanFlow-internal dataclasses carrying KF `_id`s — no semantic mapping (that is #316). Tests monkeypatch `_raw_http`/`_sleep`/`_now` and assert on the calls, exactly as `test_github_provider.py` fakes `gh`.

**Tech Stack:** Python 3 stdlib only (`urllib.request`, `urllib.error`, `json`, `time`, `os`, `dataclasses`); pytest; ruff; mypy --strict. Zero third-party runtime dependencies.

**Spec:** `docs/superpowers/specs/2026-06-02-kanbanflow-rest-client-design.md` (Appendix B is the verified wire reference).

**Working location:** session-2 worktree `~/Code/jared-315` on branch `feature/315-build-kanbanflow-rest-api-client-phase-2`. Run all commands from there.

**Import-path note (from CLAUDE.md):** tests import `from skills.jared.scripts.lib.kanbanflow_client import …`. Because `_raw_http`/`_sleep`/`_now` are *module-level* functions and the client calls them by bare name, monkeypatching `skills.jared.scripts.lib.kanbanflow_client._raw_http` in a test intercepts every call — no dual-import hazard (unlike patching a method *on* a class).

---

## File structure

- **Create `skills/jared/scripts/lib/kanbanflow_client.py`** — the whole client: module seams (`_raw_http`, `_sleep`, `_now`), exception hierarchy, KF dataclasses, `KanbanFlowClient`.
- **Create `tests/test_kanbanflow_client.py`** — the offline unit suite.
- **Modify `tests/conftest.py`** — add `patch_kf` / `patch_kf_by_url` helpers (analogues of `patch_gh` / `patch_gh_by_arg`).
- **Modify `docs/superpowers/specs/2026-06-02-board-provider-abstraction-design.md`** — annotate Appendix A with the verified corrections (Task 12).

No CLI files, no provider, no `Board` changes — those are later phases.

---

### Task 1: Seam, exceptions, request core + test harness

**Files:**
- Create: `skills/jared/scripts/lib/kanbanflow_client.py`
- Modify: `tests/conftest.py`
- Test: `tests/test_kanbanflow_client.py`

- [ ] **Step 1: Add the `patch_kf` helpers to `tests/conftest.py`**

Append near the existing `patch_gh` helpers:

```python
def patch_kf(monkeypatch, *, status=200, headers=None, body="{}"):
    """Patch the KanbanFlow transport seam with a single canned response.

    Returns a list of recorded calls; each is a dict with method/url/headers/data.
    Also no-ops _sleep so retry/backoff tests never wait, and pins _now to a
    fixed epoch so budget-gate math is deterministic.
    """
    import skills.jared.scripts.lib.kanbanflow_client as kf

    calls: list[dict[str, object]] = []

    def fake(method: str, url: str, hdrs: dict, data):
        calls.append({"method": method, "url": url, "headers": hdrs, "data": data})
        b = body.encode() if isinstance(body, str) else body
        return status, headers or {}, b

    monkeypatch.setattr(kf, "_raw_http", fake)
    monkeypatch.setattr(kf, "_sleep", lambda _s: None)
    monkeypatch.setattr(kf, "_now", lambda: 1_000_000)
    return calls


def patch_kf_by_url(monkeypatch, routes):
    """Route canned responses by substring match on the request URL.

    `routes`: dict mapping a URL substring -> either a body str, or a
    (status, headers, body) tuple. First matching key wins. Unmatched -> 200 "{}".
    Returns the recorded-calls list.
    """
    import skills.jared.scripts.lib.kanbanflow_client as kf

    calls: list[dict[str, object]] = []

    def fake(method: str, url: str, hdrs: dict, data):
        calls.append({"method": method, "url": url, "headers": hdrs, "data": data})
        for needle, resp in routes.items():
            if needle in url:
                if isinstance(resp, tuple):
                    status, hdr, body = resp
                else:
                    status, hdr, body = 200, {}, resp
                return status, hdr, body.encode() if isinstance(body, str) else body
        return 200, {}, b"{}"

    monkeypatch.setattr(kf, "_raw_http", fake)
    monkeypatch.setattr(kf, "_sleep", lambda _s: None)
    monkeypatch.setattr(kf, "_now", lambda: 1_000_000)
    return calls
```

- [ ] **Step 2: Write the failing test for the seam + error mapping**

Create `tests/test_kanbanflow_client.py`:

```python
from __future__ import annotations

import json

import pytest

from skills.jared.scripts.lib.kanbanflow_client import (
    KanbanFlowAuthError,
    KanbanFlowClient,
    KanbanFlowForbiddenError,
    KanbanFlowNotFoundError,
    KanbanFlowServerError,
)
from tests.conftest import patch_kf


def _client() -> KanbanFlowClient:
    return KanbanFlowClient(token="tok", base_url="https://kanbanflow.com/api/v1")


def test_request_sends_bearer_header_and_returns_parsed_json(monkeypatch) -> None:
    calls = patch_kf(monkeypatch, status=200, body=json.dumps({"_id": "B1", "name": "Board"}))
    result = _client()._request("GET", "/board")
    assert result == {"_id": "B1", "name": "Board"}
    assert calls[0]["headers"]["Authorization"] == "Bearer tok"
    assert calls[0]["url"] == "https://kanbanflow.com/api/v1/board"
    assert calls[0]["method"] == "GET"


@pytest.mark.parametrize(
    "status,exc",
    [
        (401, KanbanFlowAuthError),
        (403, KanbanFlowForbiddenError),
        (404, KanbanFlowNotFoundError),
        (500, KanbanFlowServerError),
    ],
)
def test_request_maps_status_to_typed_exception_with_message(monkeypatch, status, exc) -> None:
    patch_kf(monkeypatch, status=status, body=json.dumps({"errors": [{"message": "boom"}]}))
    with pytest.raises(exc, match="boom"):
        _client()._request("GET", "/board")
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `cd ~/Code/jared-315 && python -m pytest tests/test_kanbanflow_client.py -q`
Expected: collection error / ImportError — `kanbanflow_client` does not exist yet.

- [ ] **Step 4: Write the module foundation**

Create `skills/jared/scripts/lib/kanbanflow_client.py`:

```python
"""Wire-level KanbanFlow REST client (epic #313, Phase 2 / #315).

Pure transport: auth, quota policy, typed resources, error mapping. No semantic
board mapping — that is the KanbanFlowProvider's job (#316). Stdlib only.

All network I/O flows through the module-level `_raw_http` seam; `_sleep` and
`_now` are the other two seams. Tests monkeypatch these three. See the design
spec's Appendix B for the verified API surface.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field

# --------------------------------------------------------------------------- #
# Module-level seams (the only impure functions; monkeypatched in tests)      #
# --------------------------------------------------------------------------- #


def _raw_http(
    method: str, url: str, headers: dict[str, str], data: bytes | None
) -> tuple[int, dict[str, str], bytes]:
    """Perform one HTTP request. Returns (status, response_headers, body_bytes).

    Non-2xx responses (urllib raises HTTPError) are captured and returned like
    any other response, so `_request` maps them uniformly. Connection-level
    failures (URLError that is not HTTPError) propagate to the caller.
    """
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status, dict(resp.headers.items()), resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, dict(exc.headers.items()), exc.read()


def _sleep(seconds: float) -> None:
    time.sleep(seconds)


def _now() -> float:
    return time.time()


# --------------------------------------------------------------------------- #
# Typed exceptions                                                            #
# --------------------------------------------------------------------------- #


class KanbanFlowError(Exception):
    """Base for all client errors (also transport/JSON failures)."""


class KanbanFlowAuthError(KanbanFlowError):
    """401 — missing or invalid token."""


class KanbanFlowForbiddenError(KanbanFlowError):
    """403 — refused; validation failures surface here, not 400/422."""


class KanbanFlowNotFoundError(KanbanFlowError):
    """404 — resource not found."""


class KanbanFlowRateLimitError(KanbanFlowError):
    """429 or local budget exhaustion."""


class KanbanFlowServerError(KanbanFlowError):
    """500 — server error."""


_EXCEPTION_FOR_STATUS: dict[int, type[KanbanFlowError]] = {
    401: KanbanFlowAuthError,
    403: KanbanFlowForbiddenError,
    404: KanbanFlowNotFoundError,
    429: KanbanFlowRateLimitError,
    500: KanbanFlowServerError,
}


def _parse_error(body: bytes) -> str:
    """Extract the human message from {"errors":[{"message":"..."}]}."""
    try:
        payload = json.loads(body)
        errors = payload.get("errors") or []
        if errors and isinstance(errors, list):
            return str(errors[0].get("message", "")) or "unknown error"
    except (ValueError, AttributeError):
        pass
    return body.decode(errors="replace") or "unknown error"


class KanbanFlowClient:
    """Typed, quota-aware KanbanFlow REST client."""

    def __init__(
        self,
        token: str,
        base_url: str = "https://kanbanflow.com/api/v1",
        *,
        request_floor: int = 50,
        daily_ceiling: int = 4000,
        max_retries: int = 3,
    ) -> None:
        self._token = token
        self._base_url = base_url.rstrip("/")
        self._request_floor = request_floor
        self._daily_ceiling = daily_ceiling
        self._max_retries = max_retries
        # quota state, updated from response headers
        self._remaining: int | None = None
        self._reset: int | None = None
        self._daily_count = 0

    def _build_url(self, path: str, params: dict[str, object] | None) -> str:
        url = f"{self._base_url}/{path.lstrip('/')}"
        if params:
            clean = {k: str(v) for k, v in params.items() if v is not None}
            if clean:
                url = f"{url}?{urllib.parse.urlencode(clean)}"
        return url

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, object] | None = None,
        body: dict[str, object] | None = None,
    ) -> object:
        for attempt in range(self._max_retries + 1):
            self._budget_gate()
            url = self._build_url(path, params)
            headers = {"Authorization": f"Bearer {self._token}"}
            data: bytes | None = None
            if body is not None:
                data = json.dumps(body).encode()
                headers["Content-Type"] = "application/json"
            try:
                status, resp_headers, resp_body = _raw_http(method, url, headers, data)
            except urllib.error.URLError as exc:
                if attempt < self._max_retries:
                    _sleep(self._backoff(attempt))
                    continue
                raise KanbanFlowError(f"transport error: {exc}") from exc

            self._record_quota(resp_headers)

            if 200 <= status < 300:
                return json.loads(resp_body) if resp_body else None

            message = _parse_error(resp_body)
            if status == 429 and attempt < self._max_retries:
                _sleep(self._retry_delay(resp_headers))
                continue
            if status >= 500 and attempt < self._max_retries:
                _sleep(self._backoff(attempt))
                continue
            raise _EXCEPTION_FOR_STATUS.get(status, KanbanFlowError)(message)

        raise KanbanFlowRateLimitError("request retries exhausted")

    # quota helpers filled in Task 3 — minimal stubs so Task 1 tests pass
    def _budget_gate(self) -> None:
        self._daily_count += 1

    def _record_quota(self, headers: dict[str, str]) -> None:
        return None

    def _retry_delay(self, headers: dict[str, str]) -> float:
        return 0.0

    def _backoff(self, attempt: int) -> float:
        return 0.0
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd ~/Code/jared-315 && python -m pytest tests/test_kanbanflow_client.py -q`
Expected: 5 passed (1 + 4 parametrized).

- [ ] **Step 6: Commit**

```bash
cd ~/Code/jared-315
git add skills/jared/scripts/lib/kanbanflow_client.py tests/test_kanbanflow_client.py tests/conftest.py
git commit -m "feat(315): KanbanFlow client seam + request core + typed errors (Phase 2.1)" \
  -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Auth config + `from_env`

**Files:**
- Modify: `skills/jared/scripts/lib/kanbanflow_client.py`
- Test: `tests/test_kanbanflow_client.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_kanbanflow_client.py`:

```python
def test_from_env_reads_token(monkeypatch) -> None:
    monkeypatch.setenv("KANBANFLOW_API_TOKEN", "envtok")
    client = KanbanFlowClient.from_env()
    calls = patch_kf(monkeypatch, body="{}")
    client._request("GET", "/board")
    assert calls[0]["headers"]["Authorization"] == "Bearer envtok"


def test_from_env_raises_clear_error_when_unset(monkeypatch) -> None:
    monkeypatch.delenv("KANBANFLOW_API_TOKEN", raising=False)
    with pytest.raises(KanbanFlowError, match="KANBANFLOW_API_TOKEN"):
        KanbanFlowClient.from_env()
```

- [ ] **Step 2: Run to verify failure**

Run: `cd ~/Code/jared-315 && python -m pytest tests/test_kanbanflow_client.py -k from_env -q`
Expected: FAIL — `from_env` not defined.

- [ ] **Step 3: Add the classmethod**

In `KanbanFlowClient`, after `__init__`:

```python
    @classmethod
    def from_env(cls, **kwargs: object) -> "KanbanFlowClient":
        token = os.environ.get("KANBANFLOW_API_TOKEN")
        if not token:
            raise KanbanFlowError(
                "KANBANFLOW_API_TOKEN is not set. Create an API token in a premium "
                "KanbanFlow board (Settings -> API & Webhooks) and export it as "
                "KANBANFLOW_API_TOKEN."
            )
        return cls(token, **kwargs)  # type: ignore[arg-type]
```

- [ ] **Step 4: Run to verify pass**

Run: `cd ~/Code/jared-315 && python -m pytest tests/test_kanbanflow_client.py -k from_env -q`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
cd ~/Code/jared-315
git add -A && git commit -m "feat(315): KanbanFlowClient.from_env with clear token diagnostic (Phase 2.2)" \
  -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Quota budget gate + retry/backoff

**Files:**
- Modify: `skills/jared/scripts/lib/kanbanflow_client.py`
- Test: `tests/test_kanbanflow_client.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_kanbanflow_client.py`:

```python
import skills.jared.scripts.lib.kanbanflow_client as kf
from skills.jared.scripts.lib.kanbanflow_client import KanbanFlowRateLimitError


def test_proactive_gate_sleeps_until_reset_when_remaining_low(monkeypatch) -> None:
    sleeps: list[float] = []
    monkeypatch.setattr(kf, "_sleep", lambda s: sleeps.append(s))
    monkeypatch.setattr(kf, "_now", lambda: 1_000_000)
    monkeypatch.setattr(
        kf,
        "_raw_http",
        lambda m, u, h, d: (200, {}, b"{}"),
    )
    client = _client()
    client._remaining = 5  # below the default floor of 50
    client._reset = 1_000_030  # 30s in the future
    client._request("GET", "/board")
    assert sleeps == [30]


def test_daily_ceiling_refuses_before_lock(monkeypatch) -> None:
    patch_kf(monkeypatch, body="{}")
    client = KanbanFlowClient(token="t", daily_ceiling=2)
    client._request("GET", "/board")
    client._request("GET", "/board")
    with pytest.raises(KanbanFlowRateLimitError, match="daily request ceiling"):
        client._request("GET", "/board")


def test_429_then_success_retries_off_reset(monkeypatch) -> None:
    seq = [
        (429, {"X-RateLimit-Reset": "1000010"}, b'{"errors":[{"message":"slow down"}]}'),
        (200, {}, b'{"ok": true}'),
    ]
    monkeypatch.setattr(kf, "_now", lambda: 1_000_000)
    sleeps: list[float] = []
    monkeypatch.setattr(kf, "_sleep", lambda s: sleeps.append(s))
    monkeypatch.setattr(kf, "_raw_http", lambda m, u, h, d: seq.pop(0))
    result = _client()._request("GET", "/board")
    assert result == {"ok": True}
    assert sleeps == [10]
```

- [ ] **Step 2: Run to verify failure**

Run: `cd ~/Code/jared-315 && python -m pytest tests/test_kanbanflow_client.py -k "gate or ceiling or 429" -q`
Expected: FAIL — stubs return 0/None; the gate does not sleep or refuse yet.

- [ ] **Step 3: Replace the quota stubs with real logic**

Replace the four stub methods at the end of `KanbanFlowClient`:

```python
    def _budget_gate(self) -> None:
        if self._daily_count >= self._daily_ceiling:
            raise KanbanFlowRateLimitError(
                f"daily request ceiling ({self._daily_ceiling}) reached; refusing to "
                "risk a KanbanFlow token lock (5000/day)"
            )
        if (
            self._remaining is not None
            and self._remaining <= self._request_floor
            and self._reset is not None
        ):
            wait = self._reset - _now()
            if wait > 0:
                _sleep(wait)
        self._daily_count += 1

    def _record_quota(self, headers: dict[str, str]) -> None:
        rem = headers.get("X-RateLimit-Remaining")
        rst = headers.get("X-RateLimit-Reset")
        if rem is not None:
            try:
                self._remaining = int(rem)
            except ValueError:
                pass
        if rst is not None:
            try:
                self._reset = int(rst)
            except ValueError:
                pass

    def _retry_delay(self, headers: dict[str, str]) -> float:
        rst = headers.get("X-RateLimit-Reset")
        if rst is not None:
            try:
                wait = int(rst) - _now()
                return float(min(max(wait, 0.0), 60.0))
            except ValueError:
                pass
        return 1.0

    def _backoff(self, attempt: int) -> float:
        return float(min(2**attempt, 30))
```

- [ ] **Step 4: Run to verify pass**

Run: `cd ~/Code/jared-315 && python -m pytest tests/test_kanbanflow_client.py -k "gate or ceiling or 429" -q`
Expected: 3 passed.

- [ ] **Step 5: Run the whole file**

Run: `cd ~/Code/jared-315 && python -m pytest tests/test_kanbanflow_client.py -q`
Expected: all green so far.

- [ ] **Step 6: Commit**

```bash
cd ~/Code/jared-315
git add -A && git commit -m "feat(315): proactive quota budget + 429/5xx retry (Phase 2.3)" \
  -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: KF dataclasses + parsers

**Files:**
- Modify: `skills/jared/scripts/lib/kanbanflow_client.py`
- Test: `tests/test_kanbanflow_client.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_kanbanflow_client.py`:

```python
from skills.jared.scripts.lib.kanbanflow_client import (
    KfCustomFieldValue,
    KfLabel,
    KfTask,
    _parse_task,
)


def test_parse_task_maps_all_fields() -> None:
    raw = {
        "_id": "T1",
        "name": "Do thing",
        "description": "body",
        "color": "red",
        "columnId": "C1",
        "swimlaneId": "S1",
        "position": 0,
        "number": {"value": 42, "prefix": "BUG-"},
        "responsibleUserId": "U1",
        "collaborators": [{"userId": "U2"}, {"userId": "U3"}],
        "labels": [{"name": "Priority", "pinned": True}],
        "customFields": [{"customFieldId": "F1", "value": {"text": "High"}}],
    }
    task = _parse_task(raw)
    assert isinstance(task, KfTask)
    assert task.id == "T1"
    assert task.number_value == 42
    assert task.number_prefix == "BUG-"
    assert task.column_id == "C1"
    assert task.responsible_user_id == "U1"
    assert task.collaborators == ["U2", "U3"]
    assert task.labels == [KfLabel(name="Priority", pinned=True)]
    assert task.custom_fields == [KfCustomFieldValue(custom_field_id="F1", value="High")]


def test_parse_task_handles_missing_optional_arrays() -> None:
    task = _parse_task({"_id": "T2", "name": "Bare", "columnId": "C1"})
    assert task.number_value is None
    assert task.labels == []
    assert task.collaborators == []
    assert task.custom_fields == []
```

- [ ] **Step 2: Run to verify failure**

Run: `cd ~/Code/jared-315 && python -m pytest tests/test_kanbanflow_client.py -k parse_task -q`
Expected: FAIL — dataclasses/`_parse_task` not defined.

- [ ] **Step 3: Add dataclasses + parsers**

Insert after the exception block (before `class KanbanFlowClient`):

```python
@dataclass
class KfColumn:
    unique_id: str
    name: str
    description: str = ""


@dataclass
class KfSwimlane:
    unique_id: str
    name: str
    description: str = ""


@dataclass
class KfBoard:
    id: str
    name: str
    columns: list[KfColumn] = field(default_factory=list)
    swimlanes: list[KfSwimlane] = field(default_factory=list)


@dataclass
class KfCustomFieldDef:
    id: str
    name: str
    field_type: str
    dropdown_options: list[str] = field(default_factory=list)
    number_prefix: str | None = None


@dataclass
class KfLabel:
    name: str
    pinned: bool = False


@dataclass
class KfCustomFieldValue:
    custom_field_id: str
    value: str | float


@dataclass
class KfTask:
    id: str
    name: str
    description: str = ""
    color: str | None = None
    column_id: str | None = None
    swimlane_id: str | None = None
    position: int | None = None
    number_value: int | None = None
    number_prefix: str | None = None
    responsible_user_id: str | None = None
    collaborators: list[str] = field(default_factory=list)
    labels: list[KfLabel] = field(default_factory=list)
    custom_fields: list[KfCustomFieldValue] = field(default_factory=list)


@dataclass
class KfComment:
    id: str
    text: str
    created_timestamp: str
    author_user_id: str = ""


@dataclass
class KfRelation:
    relation_type: str
    related_task_id: str
    related_task_name: str = ""
    related_task_board_id: str | None = None


@dataclass
class KfUser:
    id: str
    name: str = ""


def _parse_label(raw: dict) -> KfLabel:
    return KfLabel(name=raw["name"], pinned=bool(raw.get("pinned", False)))


def _parse_custom_field_value(raw: dict) -> KfCustomFieldValue:
    value_obj = raw.get("value") or {}
    value = value_obj.get("text", value_obj.get("number"))
    return KfCustomFieldValue(custom_field_id=raw["customFieldId"], value=value)


def _parse_task(raw: dict) -> KfTask:
    number = raw.get("number") or {}
    return KfTask(
        id=raw["_id"],
        name=raw.get("name", ""),
        description=raw.get("description", ""),
        color=raw.get("color"),
        column_id=raw.get("columnId"),
        swimlane_id=raw.get("swimlaneId"),
        position=raw.get("position"),
        number_value=number.get("value"),
        number_prefix=number.get("prefix"),
        responsible_user_id=raw.get("responsibleUserId"),
        collaborators=[c["userId"] for c in raw.get("collaborators", [])],
        labels=[_parse_label(label) for label in raw.get("labels", [])],
        custom_fields=[_parse_custom_field_value(cf) for cf in raw.get("customFields", [])],
    )


def _parse_board(raw: dict) -> KfBoard:
    return KfBoard(
        id=raw["_id"],
        name=raw.get("name", ""),
        columns=[
            KfColumn(unique_id=c["uniqueId"], name=c.get("name", ""), description=c.get("description", ""))
            for c in raw.get("columns", [])
        ],
        swimlanes=[
            KfSwimlane(unique_id=s["uniqueId"], name=s.get("name", ""), description=s.get("description", ""))
            for s in raw.get("swimlanes", [])
        ],
    )


def _parse_custom_field_def(raw: dict) -> KfCustomFieldDef:
    return KfCustomFieldDef(
        id=raw["_id"],
        name=raw.get("name", ""),
        field_type=raw.get("fieldType", ""),
        dropdown_options=[o["text"] for o in raw.get("dropdownOptions", [])],
        number_prefix=(raw.get("numberSettings") or {}).get("prefix"),
    )


def _parse_comment(raw: dict) -> KfComment:
    return KfComment(
        id=raw["_id"],
        text=raw.get("text", ""),
        created_timestamp=raw.get("createdTimestamp", ""),
        author_user_id=raw.get("authorUserId", ""),
    )


def _parse_relation(raw: dict) -> KfRelation:
    return KfRelation(
        relation_type=raw.get("relationType", ""),
        related_task_id=raw.get("relatedTaskId", ""),
        related_task_name=raw.get("relatedTaskName", ""),
        related_task_board_id=raw.get("relatedTaskBoardId"),
    )


def _parse_user(raw: dict) -> KfUser:
    return KfUser(id=raw["_id"], name=raw.get("name", ""))
```

- [ ] **Step 4: Run to verify pass**

Run: `cd ~/Code/jared-315 && python -m pytest tests/test_kanbanflow_client.py -k parse_task -q`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
cd ~/Code/jared-315
git add -A && git commit -m "feat(315): KF-internal dataclasses + JSON parsers (Phase 2.4)" \
  -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: Structure reads + caching

**Files:**
- Modify: `skills/jared/scripts/lib/kanbanflow_client.py`
- Test: `tests/test_kanbanflow_client.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_get_board_parses_structure(monkeypatch) -> None:
    patch_kf(
        monkeypatch,
        body=json.dumps(
            {
                "_id": "B1",
                "name": "Board",
                "columns": [{"uniqueId": "C1", "name": "To-do"}],
                "swimlanes": [{"uniqueId": "S1", "name": "Team A", "description": "d"}],
            }
        ),
    )
    board = _client().get_board()
    assert board.id == "B1"
    assert board.columns[0].unique_id == "C1"
    assert board.swimlanes[0].description == "d"


def test_get_board_is_cached(monkeypatch) -> None:
    calls = patch_kf(monkeypatch, body=json.dumps({"_id": "B1", "name": "B"}))
    client = _client()
    client.get_board()
    client.get_board()
    board_calls = [c for c in calls if c["url"].endswith("/board")]
    assert len(board_calls) == 1, "second get_board must hit the per-process cache"


def test_jared_no_cache_bypasses_cache(monkeypatch) -> None:
    monkeypatch.setenv("JARED_NO_CACHE", "1")
    calls = patch_kf(monkeypatch, body=json.dumps({"_id": "B1", "name": "B"}))
    client = _client()
    client.get_board()
    client.get_board()
    board_calls = [c for c in calls if c["url"].endswith("/board")]
    assert len(board_calls) == 2, "JARED_NO_CACHE=1 must defeat caching"
```

- [ ] **Step 2: Run to verify failure**

Run: `cd ~/Code/jared-315 && python -m pytest tests/test_kanbanflow_client.py -k "board" -q`
Expected: FAIL — `get_board` not defined.

- [ ] **Step 3: Add a cache helper + the structure reads**

In `__init__`, add the cache dict at the end:

```python
        self._cache: dict[str, object] = {}
```

Add to `KanbanFlowClient` (after `_request`):

```python
    def _cached_get(self, key: str, path: str):
        if os.environ.get("JARED_NO_CACHE") != "1" and key in self._cache:
            return self._cache[key]
        raw = self._request("GET", path)
        self._cache[key] = raw
        return raw

    def get_board(self) -> KfBoard:
        return _parse_board(self._cached_get("board", "/board"))  # type: ignore[arg-type]

    def list_custom_field_defs(self) -> list[KfCustomFieldDef]:
        raw = self._cached_get("custom-fields", "/custom-fields")
        return [_parse_custom_field_def(d) for d in raw]  # type: ignore[union-attr]

    def list_users(self) -> list[KfUser]:
        raw = self._cached_get("users", "/users")
        return [_parse_user(u) for u in raw]  # type: ignore[union-attr]
```

- [ ] **Step 4: Run to verify pass**

Run: `cd ~/Code/jared-315 && python -m pytest tests/test_kanbanflow_client.py -k "board" -q`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
cd ~/Code/jared-315
git add -A && git commit -m "feat(315): cached structure reads (board/custom-fields/users) (Phase 2.5)" \
  -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: Task reads (list + pagination cursor + get)

**Files:**
- Modify: `skills/jared/scripts/lib/kanbanflow_client.py`
- Test: `tests/test_kanbanflow_client.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_list_tasks_unwraps_column_groups(monkeypatch) -> None:
    patch_kf(
        monkeypatch,
        body=json.dumps(
            [{"columnId": "C1", "columnName": "To-do", "tasksLimited": False,
              "tasks": [{"_id": "T1", "name": "a", "columnId": "C1"},
                        {"_id": "T2", "name": "b", "columnId": "C1"}]}]
        ),
    )
    tasks = _client().list_tasks(column_id="C1")
    assert [t.id for t in tasks] == ["T1", "T2"]


def test_list_tasks_follows_date_grouped_cursor(monkeypatch) -> None:
    page1 = json.dumps(
        [{"columnId": "C1", "tasksLimited": True, "nextTaskId": "T2",
          "tasks": [{"_id": "T1", "name": "a", "columnId": "C1"}]}]
    )
    page2 = json.dumps(
        [{"columnId": "C1", "tasksLimited": False,
          "tasks": [{"_id": "T2", "name": "b", "columnId": "C1"}]}]
    )
    pages = [page1.encode(), page2.encode()]
    monkeypatch.setattr(kf, "_sleep", lambda _s: None)
    monkeypatch.setattr(kf, "_now", lambda: 1_000_000)
    seen: list[str] = []

    def fake(method, url, headers, data):
        seen.append(url)
        return 200, {}, pages.pop(0)

    monkeypatch.setattr(kf, "_raw_http", fake)
    tasks = _client().list_tasks(column_id="C1")
    assert [t.id for t in tasks] == ["T1", "T2"]
    assert any("startTaskId=T2" in u for u in seen), "must page using nextTaskId -> startTaskId"


def test_get_task_returns_single(monkeypatch) -> None:
    patch_kf(monkeypatch, body=json.dumps({"_id": "T9", "name": "solo", "columnId": "C1"}))
    task = _client().get_task("T9")
    assert task.id == "T9"
    assert task.name == "solo"
```

- [ ] **Step 2: Run to verify failure**

Run: `cd ~/Code/jared-315 && python -m pytest tests/test_kanbanflow_client.py -k "list_tasks or get_task" -q`
Expected: FAIL — methods not defined.

- [ ] **Step 3: Add the task reads**

```python
    def list_tasks(
        self,
        *,
        column_id: str | None = None,
        column_name: str | None = None,
        swimlane_id: str | None = None,
        limit: int | None = None,
        start_task_id: str | None = None,
        order: str | None = None,
    ) -> list[KfTask]:
        params: dict[str, object] = {
            "columnId": column_id,
            "columnName": column_name,
            "swimlaneId": swimlane_id,
            "limit": limit,
            "order": order,
        }
        tasks: list[KfTask] = []
        cursor = start_task_id
        while True:
            params["startTaskId"] = cursor
            groups = self._request("GET", "/tasks", params=params)
            next_cursor: str | None = None
            for group in groups or []:
                for raw in group.get("tasks", []):
                    tasks.append(_parse_task(raw))
                if group.get("tasksLimited") and group.get("nextTaskId"):
                    next_cursor = group["nextTaskId"]
            if not next_cursor:
                break
            cursor = next_cursor
        return tasks

    def iter_all_tasks(self) -> list[KfTask]:
        board = self.get_board()
        tasks: list[KfTask] = []
        for column in board.columns:
            tasks.extend(self.list_tasks(column_id=column.unique_id))
        return tasks

    def get_task(self, task_id: str) -> KfTask:
        raw = self._request("GET", f"/tasks/{task_id}")
        return _parse_task(raw)  # type: ignore[arg-type]
```

- [ ] **Step 4: Run to verify pass**

Run: `cd ~/Code/jared-315 && python -m pytest tests/test_kanbanflow_client.py -k "list_tasks or get_task" -q`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
cd ~/Code/jared-315
git add -A && git commit -m "feat(315): task reads with date-grouped pagination cursor (Phase 2.6)" \
  -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 7: Task writes (create always-explicit-number, update, delete)

**Files:**
- Modify: `skills/jared/scripts/lib/kanbanflow_client.py`
- Test: `tests/test_kanbanflow_client.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_create_task_always_sends_explicit_number(monkeypatch) -> None:
    calls = patch_kf(monkeypatch, body=json.dumps({"_id": "T1", "name": "n", "columnId": "C1",
                                                    "number": {"value": 7}}))
    task = _client().create_task(name="n", column_id="C1", number_value=7)
    sent = json.loads(calls[0]["data"])
    assert sent["number"] == {"value": 7}, "create_task must always send number.value explicitly"
    assert calls[0]["method"] == "POST"
    assert task.number_value == 7


def test_update_task_uses_post_and_includes_only_given_fields(monkeypatch) -> None:
    calls = patch_kf(monkeypatch, body=json.dumps({"_id": "T1", "name": "renamed", "columnId": "C2"}))
    _client().update_task("T1", name="renamed", column_id="C2")
    assert calls[0]["method"] == "POST"
    assert calls[0]["url"].endswith("/tasks/T1")
    sent = json.loads(calls[0]["data"])
    assert sent == {"name": "renamed", "columnId": "C2"}


def test_delete_task_issues_delete(monkeypatch) -> None:
    calls = patch_kf(monkeypatch, body="")
    _client().delete_task("T1")
    assert calls[0]["method"] == "DELETE"
    assert calls[0]["url"].endswith("/tasks/T1")
```

- [ ] **Step 2: Run to verify failure**

Run: `cd ~/Code/jared-315 && python -m pytest tests/test_kanbanflow_client.py -k "create_task or update_task or delete_task" -q`
Expected: FAIL — methods not defined.

- [ ] **Step 3: Add the writes**

```python
    def create_task(
        self,
        *,
        name: str,
        column_id: str,
        number_value: int,
        swimlane_id: str | None = None,
        description: str | None = None,
        color: str | None = None,
        responsible_user_id: str | None = None,
        labels: list[KfLabel] | None = None,
    ) -> KfTask:
        body: dict[str, object] = {
            "name": name,
            "columnId": column_id,
            "number": {"value": number_value},
        }
        if swimlane_id is not None:
            body["swimlaneId"] = swimlane_id
        if description is not None:
            body["description"] = description
        if color is not None:
            body["color"] = color
        if responsible_user_id is not None:
            body["responsibleUserId"] = responsible_user_id
        if labels:
            body["labels"] = [{"name": label.name, "pinned": label.pinned} for label in labels]
        raw = self._request("POST", "/tasks", body=body)
        return _parse_task(raw)  # type: ignore[arg-type]

    def update_task(
        self,
        task_id: str,
        *,
        name: str | None = None,
        column_id: str | None = None,
        number_value: int | None = None,
        description: str | None = None,
        color: str | None = None,
        responsible_user_id: str | None = None,
    ) -> KfTask:
        body: dict[str, object] = {}
        if name is not None:
            body["name"] = name
        if column_id is not None:
            body["columnId"] = column_id
        if number_value is not None:
            body["number"] = {"value": number_value}
        if description is not None:
            body["description"] = description
        if color is not None:
            body["color"] = color
        if responsible_user_id is not None:
            body["responsibleUserId"] = responsible_user_id
        raw = self._request("POST", f"/tasks/{task_id}", body=body)
        return _parse_task(raw)  # type: ignore[arg-type]

    def delete_task(self, task_id: str) -> None:
        self._request("DELETE", f"/tasks/{task_id}")
```

- [ ] **Step 4: Run to verify pass**

Run: `cd ~/Code/jared-315 && python -m pytest tests/test_kanbanflow_client.py -k "create_task or update_task or delete_task" -q`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
cd ~/Code/jared-315
git add -A && git commit -m "feat(315): task create/update/delete; create forces explicit number (Phase 2.7)" \
  -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 8: Custom-field values (get + set upsert)

**Files:**
- Modify: `skills/jared/scripts/lib/kanbanflow_client.py`
- Test: `tests/test_kanbanflow_client.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_get_task_custom_fields_parses_values(monkeypatch) -> None:
    patch_kf(monkeypatch, body=json.dumps(
        [{"customFieldId": "F1", "value": {"text": "High"}},
         {"customFieldId": "F2", "value": {"number": 12.5}}]))
    values = _client().get_task_custom_fields("T1")
    assert values[0] == KfCustomFieldValue(custom_field_id="F1", value="High")
    assert values[1] == KfCustomFieldValue(custom_field_id="F2", value=12.5)


def test_set_task_custom_field_text_posts_to_field_url(monkeypatch) -> None:
    calls = patch_kf(monkeypatch, body="{}")
    _client().set_task_custom_field("T1", "F1", "High")
    assert calls[0]["method"] == "POST"
    assert calls[0]["url"].endswith("/tasks/T1/custom-fields/F1")
    assert json.loads(calls[0]["data"]) == {"value": {"text": "High"}}


def test_set_task_custom_field_number_uses_number_key(monkeypatch) -> None:
    calls = patch_kf(monkeypatch, body="{}")
    _client().set_task_custom_field("T1", "F2", 12.5)
    assert json.loads(calls[0]["data"]) == {"value": {"number": 12.5}}
```

- [ ] **Step 2: Run to verify failure**

Run: `cd ~/Code/jared-315 && python -m pytest tests/test_kanbanflow_client.py -k "custom_field" -q`
Expected: FAIL — methods not defined.

- [ ] **Step 3: Add the methods**

```python
    def get_task_custom_fields(self, task_id: str) -> list[KfCustomFieldValue]:
        raw = self._request("GET", f"/tasks/{task_id}/custom-fields")
        return [_parse_custom_field_value(cf) for cf in raw]  # type: ignore[union-attr]

    def set_task_custom_field(
        self, task_id: str, custom_field_id: str, value: str | float
    ) -> None:
        key = "number" if isinstance(value, (int, float)) and not isinstance(value, bool) else "text"
        self._request(
            "POST",
            f"/tasks/{task_id}/custom-fields/{custom_field_id}",
            body={"value": {key: value}},
        )
```

- [ ] **Step 4: Run to verify pass**

Run: `cd ~/Code/jared-315 && python -m pytest tests/test_kanbanflow_client.py -k "custom_field" -q`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
cd ~/Code/jared-315
git add -A && git commit -m "feat(315): custom-field value get + upsert (text/number) (Phase 2.8)" \
  -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 9: Comments (list + add, backdatable)

**Files:**
- Modify: `skills/jared/scripts/lib/kanbanflow_client.py`
- Test: `tests/test_kanbanflow_client.py`

- [ ] **Step 1: Write the failing tests**

```python
from skills.jared.scripts.lib.kanbanflow_client import KfComment


def test_list_comments_parses(monkeypatch) -> None:
    patch_kf(monkeypatch, body=json.dumps(
        [{"_id": "C1", "text": "hi", "createdTimestamp": "2026-01-01T00:00:00Z", "authorUserId": "U1"}]))
    comments = _client().list_comments("T1")
    assert comments == [KfComment(id="C1", text="hi",
                                  created_timestamp="2026-01-01T00:00:00Z", author_user_id="U1")]


def test_add_comment_posts_text_and_returns_id(monkeypatch) -> None:
    calls = patch_kf(monkeypatch, body=json.dumps({"taskCommentId": "C9"}))
    cid = _client().add_comment("T1", "a note")
    assert cid == "C9"
    assert calls[0]["method"] == "POST"
    assert calls[0]["url"].endswith("/tasks/T1/comments")
    assert json.loads(calls[0]["data"]) == {"text": "a note"}


def test_add_comment_backdates_with_created_timestamp(monkeypatch) -> None:
    calls = patch_kf(monkeypatch, body=json.dumps({"taskCommentId": "C9"}))
    _client().add_comment("T1", "old note", created_timestamp="2025-01-01T00:00:00Z",
                          author_user_id="U2")
    sent = json.loads(calls[0]["data"])
    assert sent["createdTimestamp"] == "2025-01-01T00:00:00Z"
    assert sent["authorUserId"] == "U2"
```

- [ ] **Step 2: Run to verify failure**

Run: `cd ~/Code/jared-315 && python -m pytest tests/test_kanbanflow_client.py -k "comment" -q`
Expected: FAIL — methods not defined.

- [ ] **Step 3: Add the methods**

```python
    def list_comments(self, task_id: str) -> list[KfComment]:
        raw = self._request("GET", f"/tasks/{task_id}/comments")
        return [_parse_comment(c) for c in raw]  # type: ignore[union-attr]

    def add_comment(
        self,
        task_id: str,
        text: str,
        *,
        created_timestamp: str | None = None,
        author_user_id: str | None = None,
    ) -> str:
        body: dict[str, object] = {"text": text}
        if created_timestamp is not None:
            body["createdTimestamp"] = created_timestamp
        if author_user_id is not None:
            body["authorUserId"] = author_user_id
        raw = self._request("POST", f"/tasks/{task_id}/comments", body=body)
        return str(raw.get("taskCommentId", ""))  # type: ignore[union-attr]
```

- [ ] **Step 4: Run to verify pass**

Run: `cd ~/Code/jared-315 && python -m pytest tests/test_kanbanflow_client.py -k "comment" -q`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
cd ~/Code/jared-315
git add -A && git commit -m "feat(315): comment list + add (backdatable) (Phase 2.9)" \
  -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 10: Labels (list + add + remove by-name)

**Files:**
- Modify: `skills/jared/scripts/lib/kanbanflow_client.py`
- Test: `tests/test_kanbanflow_client.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_list_labels_parses(monkeypatch) -> None:
    patch_kf(monkeypatch, body=json.dumps([{"name": "Priority", "pinned": True}, {"name": "X"}]))
    labels = _client().list_labels("T1")
    assert labels == [KfLabel(name="Priority", pinned=True), KfLabel(name="X", pinned=False)]


def test_add_label_posts_name_and_pinned(monkeypatch) -> None:
    calls = patch_kf(monkeypatch, body=json.dumps({"insertIndex": 0}))
    _client().add_label("T1", "blocked-by:42", pinned=False)
    assert calls[0]["method"] == "POST"
    assert calls[0]["url"].endswith("/tasks/T1/labels")
    assert json.loads(calls[0]["data"]) == {"name": "blocked-by:42", "pinned": False}


def test_remove_label_deletes_by_name(monkeypatch) -> None:
    calls = patch_kf(monkeypatch, body="{}")
    _client().remove_label("T1", "blocked-by:42")
    assert calls[0]["method"] == "DELETE"
    assert calls[0]["url"].endswith("/tasks/T1/labels/by-name/blocked-by%3A42"), (
        "label name must be URL-encoded in the path"
    )
```

- [ ] **Step 2: Run to verify failure**

Run: `cd ~/Code/jared-315 && python -m pytest tests/test_kanbanflow_client.py -k "label" -q`
Expected: FAIL — methods not defined.

- [ ] **Step 3: Add the methods**

```python
    def list_labels(self, task_id: str) -> list[KfLabel]:
        raw = self._request("GET", f"/tasks/{task_id}/labels")
        return [_parse_label(label) for label in raw]  # type: ignore[union-attr]

    def add_label(self, task_id: str, name: str, *, pinned: bool = False) -> None:
        self._request("POST", f"/tasks/{task_id}/labels", body={"name": name, "pinned": pinned})

    def remove_label(self, task_id: str, name: str) -> None:
        encoded = urllib.parse.quote(name, safe="")
        self._request("DELETE", f"/tasks/{task_id}/labels/by-name/{encoded}")
```

- [ ] **Step 4: Run to verify pass**

Run: `cd ~/Code/jared-315 && python -m pytest tests/test_kanbanflow_client.py -k "label" -q`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
cd ~/Code/jared-315
git add -A && git commit -m "feat(315): label list/add/remove-by-name (URL-encoded) (Phase 2.10)" \
  -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 11: Relations (read-only)

**Files:**
- Modify: `skills/jared/scripts/lib/kanbanflow_client.py`
- Test: `tests/test_kanbanflow_client.py`

- [ ] **Step 1: Write the failing test**

```python
from skills.jared.scripts.lib.kanbanflow_client import KfRelation


def test_get_relations_parses(monkeypatch) -> None:
    patch_kf(monkeypatch, body=json.dumps(
        [{"relationType": "dependsOn", "relatedTaskId": "T2", "relatedTaskName": "dep"}]))
    rels = _client().get_relations("T1")
    assert rels == [KfRelation(relation_type="dependsOn", related_task_id="T2",
                               related_task_name="dep", related_task_board_id=None)]
```

- [ ] **Step 2: Run to verify failure**

Run: `cd ~/Code/jared-315 && python -m pytest tests/test_kanbanflow_client.py -k "relations" -q`
Expected: FAIL — method not defined.

- [ ] **Step 3: Add the method**

```python
    def get_relations(self, task_id: str) -> list[KfRelation]:
        raw = self._request("GET", f"/tasks/{task_id}/relations")
        return [_parse_relation(r) for r in raw]  # type: ignore[union-attr]
```

- [ ] **Step 4: Run to verify pass**

Run: `cd ~/Code/jared-315 && python -m pytest tests/test_kanbanflow_client.py -k "relations" -q`
Expected: 1 passed.

- [ ] **Step 5: Commit**

```bash
cd ~/Code/jared-315
git add -A && git commit -m "feat(315): read-only task relations (Phase 2.11)" \
  -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 12: Propagate the verified corrections into the Phase-1 spec's Appendix A

**Files:**
- Modify: `docs/superpowers/specs/2026-06-02-board-provider-abstraction-design.md`

This stops #316 ("Map per Appendix A of the design spec") from inheriting the stale claims. Do **not** rewrite Appendix A's intent — annotate the corrected lines and point at the Phase-2 spec.

- [ ] **Step 1: Edit Appendix A's concept-mapping + constraints**

In the `**blocked-by**` / number / labels rows and the "Two correctness/quota constraints" section, append a correction note. Concretely, under the Appendix A heading insert this admonition block immediately after the "Frozen from the 2026-06-02 API + product research." line:

```markdown
> **Corrected 2026-06-02 (Phase-2 wire verification, see
> `2026-06-02-kanbanflow-rest-client-design.md` § "Corrections to Appendix A"):**
> (1) KanbanFlow **does** auto-assign `number` when the field is omitted on a
> numbering-enabled board — jared must always send an explicit `number.value`.
> (2) Labels are objects `{name, pinned}` via per-task endpoints (case-sensitive),
> not a bare string array. (3) Custom-field values cannot be set inline on task
> create — they require a separate per-field POST. (4) Board structure
> (columns/swimlanes) is **read-only** via the API; it must pre-exist in the KF UI.
> (5) Update is POST (not PUT); validation errors surface as 403. Auth is confirmed
> Bearer (not Basic).
```

- [ ] **Step 2: Verify the doc still reads coherently**

Run: `cd ~/Code/jared-315 && grep -n "Corrected 2026-06-02" docs/superpowers/specs/2026-06-02-board-provider-abstraction-design.md`
Expected: one match inside Appendix A.

- [ ] **Step 3: Commit**

```bash
cd ~/Code/jared-315
git add -A && git commit -m "docs(314): correct Appendix A KanbanFlow constraints from Phase-2 research (#315)" \
  -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 13: Full verification gate

**Files:** none (verification only)

- [ ] **Step 1: Full unit suite (offline)**

Run: `cd ~/Code/jared-315 && python -m pytest -m 'not integration' -q`
Expected: all green, including the existing suite (the new module adds tests, changes nothing else).

- [ ] **Step 2: Lint + format check**

Run: `cd ~/Code/jared-315 && ruff check . && ruff format --check .`
Expected: no errors. (If `ruff format --check` reports diffs, run `ruff format .`, re-run the suite, and amend.)

- [ ] **Step 3: Strict type check**

Run: `cd ~/Code/jared-315 && mypy`
Expected: `Success: no issues found`. Resolve any `kanbanflow_client.py` finding before proceeding (the `# type: ignore` comments above are scoped to JSON-shape narrowing; tighten if mypy flags a real gap).

- [ ] **Step 4: Confirm the seam invariant (no stray urllib calls)**

Run: `cd ~/Code/jared-315 && grep -rn "urllib" skills/jared/scripts/lib/kanbanflow_client.py | grep -v "^.*_raw_http\|import urllib\|urllib.parse\|urllib.error\|urllib.request.Request\|urllib.request.urlopen"`
Expected: only the `_raw_http` body and `urllib.parse.quote`/`urlencode` usages appear — no `urlopen` call outside `_raw_http`.

- [ ] **Step 5: Push the branch and open the PR**

```bash
cd ~/Code/jared-315
git push -u origin feature/315-build-kanbanflow-rest-api-client-phase-2
gh pr create --title "feat(315): KanbanFlow REST client (Phase 2)" \
  --body "Implements #315 per docs/superpowers/specs/2026-06-02-kanbanflow-rest-client-design.md.

Wire-level stdlib client for KanbanFlow: Bearer auth, proactive quota budget + 429/5xx
retry, typed resources + exceptions, offline test suite (monkeypatched _raw_http seam).
No provider, no semantic mapping (deferred to #316). Also corrects the Phase-1 spec's
Appendix A from verified Phase-2 research.

🤖 Generated with [Claude Code](https://claude.com/claude-code)"
```

---

## Self-Review

**Spec coverage** (each spec section → task):
- Module layout + `_raw_http` seam → Task 1. ✓
- Typed exceptions → Task 1. ✓
- Auth / `from_env` / Bearer → Task 2. ✓
- Quota budget + 429/5xx retry + injectable sleep → Task 3. ✓
- KF dataclasses + parsers → Task 4. ✓
- Cached structure reads + `JARED_NO_CACHE` → Task 5. ✓
- Task reads + date-grouped pagination cursor → Task 6. ✓
- Task writes + always-explicit-number → Task 7. ✓
- Custom-field values (dropdown by text / number) → Task 8. ✓
- Comments (backdatable) → Task 9. ✓
- Labels (object shape, by-name remove, case-sensitive) → Task 10. ✓
- Relations read-only → Task 11. ✓
- Appendix A corrections land in this PR → Task 12. ✓
- AC verification (`pytest -m 'not integration'`, ruff, mypy, seam invariant) → Task 13. ✓
- Non-goals (no provider, no number↔_id index, no subtasks, no CLI) → respected; nothing builds them.

**Placeholder scan:** none — every code/test step shows complete code.

**Type/name consistency:** `_raw_http(method,url,headers,data)->(status,headers,bytes)`, `_request(method,path,*,params,body)`, `_sleep`/`_now` seams, `_cached_get(key,path)`, dataclass field names (`unique_id`, `number_value`, `custom_field_id`, `created_timestamp`), and method names are used identically across Tasks 1–13. `patch_kf`/`patch_kf_by_url` signatures match their call sites.

**Deferred (correctly out of scope):** opt-in live integration test (needs premium board + token), provider/semantic mapping, `init`/`migrate`, capability enforcement.
