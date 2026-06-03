---
**Shipped in #316 on 2026-06-03. Final decisions captured in issue body.**
---

# KanbanFlowProvider (Phase 3) Implementation Plan

## Issue

- #316

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement `KanbanFlowProvider`, satisfying the `BoardProvider` contract (Phase 1) over the KanbanFlow REST client (Phase 2), so a project can be stewarded on KanbanFlow.

**Architecture:** A new `lib/kanbanflow_provider.py` maps every semantic `BoardProvider` method onto `KanbanFlowClient`. A small disk-backed `lib/kf_number_index.py` resolves the stable `#N` handle to KanbanFlow's internal `_id` (no get-by-number endpoint exists) and allocates new numbers. `Board.provider` gains a `kanbanflow` branch. The client gets one small extension (`update_task` learns `swimlane_id`). Tests inject a faked in-memory client.

**Tech Stack:** Python 3, `dataclasses`, `typing.Protocol`, pytest, `mypy --strict`, ruff. No new deps.

**Design of record:** `docs/superpowers/specs/2026-06-03-kanbanflow-provider-design.md`. Read it before starting — this plan implements it verbatim.

---

## Environment

All work happens in the worktree `/home/brockamer/Code/jared-316` (branch `feature/316-implement-kanbanflowprovider-phase-3`). The worktree has **no `.venv` of its own** — use the main repo's venv binaries but run from the worktree root so `pythonpath = ["."]` resolves to the worktree's code:

```bash
cd /home/brockamer/Code/jared-316
VENV=/home/brockamer/Code/jared/.venv/bin
# tests:  $VENV/python -m pytest <args>
# lint:   $VENV/ruff check . && $VENV/ruff format .
# types:  $VENV/mypy
```

Every `Run:` command below assumes `cd /home/brockamer/Code/jared-316` first and `$VENV` as above.

## File Structure

| File | Responsibility |
|---|---|
| Create `skills/jared/scripts/lib/kf_number_index.py` | `KfNumberIndex` — disk-backed `number → _id` store + `next_number()`. Pure storage; no client. |
| Create `skills/jared/scripts/lib/kanbanflow_provider.py` | `KanbanFlowProvider` — implements `BoardProvider` over `KanbanFlowClient` + `KfNumberIndex`. |
| Modify `skills/jared/scripts/lib/kanbanflow_client.py` | `update_task` gains a `swimlane_id` parameter. |
| Modify `skills/jared/scripts/lib/board.py` | `provider` property gains the `kanbanflow` branch; `_provider` field + return type widened to `BoardProvider`. |
| Create `tests/fake_kanbanflow.py` | `FakeKanbanFlowClient` — in-memory test double mirroring the client's public surface. |
| Create `tests/test_kf_number_index.py` | Unit tests for the index. |
| Create `tests/test_kanbanflow_provider.py` | Unit tests for the provider (one per contract method + invariants). |
| Modify `tests/test_kanbanflow_client.py` | Add the `update_task` swimlane test. |
| Modify `tests/test_board.py` | Update `test_board_provider_unknown_backend_raises` (kanbanflow now returns a provider). |

---

## Task 1: `KfNumberIndex` — disk-backed number↔_id store

**Files:**
- Create: `skills/jared/scripts/lib/kf_number_index.py`
- Test: `tests/test_kf_number_index.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_kf_number_index.py
"""Unit tests for KfNumberIndex (disk-backed number -> KanbanFlow _id store)."""

from __future__ import annotations

from pathlib import Path

from skills.jared.scripts.lib.kf_number_index import KfNumberIndex


def test_put_get_roundtrip_persists_across_instances(tmp_path: Path) -> None:
    path = tmp_path / "kf-index-B1.json"
    idx = KfNumberIndex(path)
    idx.put(312, "task-abc")
    # A fresh instance reads the same file.
    reloaded = KfNumberIndex(path)
    assert reloaded.get(312) == "task-abc"


def test_get_missing_returns_none(tmp_path: Path) -> None:
    idx = KfNumberIndex(tmp_path / "kf-index-B1.json")
    assert idx.get(999) is None


def test_max_number_empty_is_zero(tmp_path: Path) -> None:
    idx = KfNumberIndex(tmp_path / "kf-index-B1.json")
    assert idx.is_empty() is True
    assert idx.max_number() == 0


def test_max_number_returns_highest_key(tmp_path: Path) -> None:
    idx = KfNumberIndex(tmp_path / "kf-index-B1.json")
    idx.put(3, "c")
    idx.put(11, "k")
    idx.put(7, "g")
    assert idx.max_number() == 11
    assert idx.is_empty() is False


def test_replace_overwrites_whole_map(tmp_path: Path) -> None:
    idx = KfNumberIndex(tmp_path / "kf-index-B1.json")
    idx.put(1, "a")
    idx.replace({5: "e", 6: "f"})
    assert idx.get(1) is None
    assert idx.get(5) == "e"
    assert idx.max_number() == 6


def test_for_board_uses_cache_dir_and_board_id(tmp_path: Path) -> None:
    idx = KfNumberIndex.for_board("BOARD9", cache_dir=tmp_path)
    idx.put(2, "b")
    assert (tmp_path / "kf-index-BOARD9.json").exists()


def test_corrupt_file_is_treated_as_empty(tmp_path: Path) -> None:
    path = tmp_path / "kf-index-B1.json"
    path.write_text("{ not json")
    idx = KfNumberIndex(path)
    assert idx.is_empty() is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `$VENV/python -m pytest tests/test_kf_number_index.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'skills.jared.scripts.lib.kf_number_index'`

- [ ] **Step 3: Write the implementation**

```python
# skills/jared/scripts/lib/kf_number_index.py
"""Disk-backed number <-> KanbanFlow _id index (#316, Phase 3).

KanbanFlow has no get-task-by-number endpoint, and create_task requires an
explicit number. So jared owns #N allocation and persists a number -> _id map
for resolution. Because the jared CLI runs as one-shot processes, this map
lives on disk (the same reason cache.py exists). It is rebuildable: a lost or
corrupt file costs one full board scan to reseed, never correctness.

Stored as {"numbers": {"<N>": "<task_id>"}}. Writes use atomic-rename
(os.replace on a .tmp sibling), matching cache.py.

Concurrency: document-and-accept (operator decision 2026-06-03). Two concurrent
`jared file` calls may both pick max+1 and collide (last-writer-wins on the
index); a reseed scan + manual renumber repairs it. No locking.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from . import cache


class KfNumberIndex:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._map: dict[int, str] = self._load()

    @classmethod
    def for_board(cls, board_id: str, *, cache_dir: Path | None = None) -> KfNumberIndex:
        base = cache_dir if cache_dir is not None else cache._default_cache_dir()
        return cls(base / f"kf-index-{board_id}.json")

    def _load(self) -> dict[int, str]:
        if not self._path.exists():
            return {}
        try:
            payload = json.loads(self._path.read_text())
            numbers = payload["numbers"]
            return {int(k): str(v) for k, v in numbers.items()}
        except (OSError, json.JSONDecodeError, KeyError, AttributeError, ValueError, TypeError):
            return {}

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"numbers": {str(k): v for k, v in self._map.items()}}
        tmp = self._path.with_suffix(self._path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload))
        os.replace(tmp, self._path)

    def get(self, number: int) -> str | None:
        return self._map.get(number)

    def put(self, number: int, task_id: str) -> None:
        self._map[number] = task_id
        self._save()

    def replace(self, mapping: dict[int, str]) -> None:
        self._map = dict(mapping)
        self._save()

    def is_empty(self) -> bool:
        return not self._map

    def max_number(self) -> int:
        return max(self._map, default=0)
```

(`_load` swallows a missing or corrupt file by returning `{}` via the bare `try/except` — no `contextlib` is needed here, unlike cache.py which suppresses `FileNotFoundError` on `unlink`.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `$VENV/python -m pytest tests/test_kf_number_index.py -v`
Expected: PASS (7 passed)

- [ ] **Step 5: Lint + type-check + commit**

Run: `$VENV/ruff check skills/jared/scripts/lib/kf_number_index.py tests/test_kf_number_index.py && $VENV/ruff format skills/jared/scripts/lib/kf_number_index.py tests/test_kf_number_index.py && $VENV/mypy`
Expected: all clean

```bash
git add skills/jared/scripts/lib/kf_number_index.py tests/test_kf_number_index.py
git commit -m "feat(316): KfNumberIndex disk-backed number<->_id store (Phase 3.1)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: Extend `KanbanFlowClient.update_task` with `swimlane_id`

The provider's `set_milestone` moves a task between swimlanes, but `update_task` (kanbanflow_client.py:461) has no `swimlane_id` parameter. Add it.

**Files:**
- Modify: `skills/jared/scripts/lib/kanbanflow_client.py:461-486`
- Test: `tests/test_kanbanflow_client.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_kanbanflow_client.py` (use the file's existing `patch_kf` / `_client` helpers — check the top of the file for their exact names and signatures, and mirror an existing `update_task` test):

```python
def test_update_task_sends_swimlane_id(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = patch_kf(monkeypatch, status=200, body=json.dumps({"_id": "T1", "name": "x"}))
    _client().update_task("T1", swimlane_id="SW2")
    # The POST body must carry swimlaneId.
    sent = json.loads(calls[-1].body)  # adapt to how patch_kf records the request body
    assert sent["swimlaneId"] == "SW2"
```

> If `patch_kf`'s recorded-call shape differs (it may capture `(method, url, headers, data)` tuples), adapt the assertion to read the request body from whatever structure `patch_kf` returns — match the existing client tests in this file exactly.

- [ ] **Step 2: Run test to verify it fails**

Run: `$VENV/python -m pytest tests/test_kanbanflow_client.py::test_update_task_sends_swimlane_id -v`
Expected: FAIL — `TypeError: update_task() got an unexpected keyword argument 'swimlane_id'`

- [ ] **Step 3: Add the parameter**

In `skills/jared/scripts/lib/kanbanflow_client.py`, add `swimlane_id` to `update_task`'s signature and body assembly:

```python
    def update_task(
        self,
        task_id: str,
        *,
        name: str | None = None,
        column_id: str | None = None,
        swimlane_id: str | None = None,
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
        if swimlane_id is not None:
            body["swimlaneId"] = swimlane_id
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `$VENV/python -m pytest tests/test_kanbanflow_client.py -v`
Expected: PASS (all client tests, including the new one)

- [ ] **Step 5: Lint + type-check + commit**

Run: `$VENV/ruff check . && $VENV/mypy`
Expected: clean

```bash
git add skills/jared/scripts/lib/kanbanflow_client.py tests/test_kanbanflow_client.py
git commit -m "feat(316): update_task accepts swimlane_id (Phase 3.2)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: `FakeKanbanFlowClient` in-memory test double

The provider takes a client by DI; provider tests inject this fake instead of patching HTTP. It mirrors the public methods the provider calls, holding state in dicts.

**Files:**
- Create: `tests/fake_kanbanflow.py`
- Test: `tests/test_kanbanflow_provider.py` (a couple of sanity tests for the fake itself)

- [ ] **Step 1: Write the fake + sanity tests**

```python
# tests/fake_kanbanflow.py
"""In-memory test double for KanbanFlowClient (Phase 3, #316).

Mirrors only the public methods KanbanFlowProvider calls. Holds tasks/comments
in dicts. `fail_set_custom_field` forces set_task_custom_field to raise, for
exercising file()'s rollback path.
"""

from __future__ import annotations

from skills.jared.scripts.lib.kanbanflow_client import (
    KanbanFlowNotFoundError,
    KfBoard,
    KfColumn,
    KfComment,
    KfCustomFieldDef,
    KfCustomFieldValue,
    KfLabel,
    KfSwimlane,
    KfTask,
)


class FakeKanbanFlowClient:
    def __init__(
        self,
        *,
        board: KfBoard | None = None,
        field_defs: list[KfCustomFieldDef] | None = None,
    ) -> None:
        self.board = board or KfBoard(
            id="B1",
            name="Test",
            columns=[
                KfColumn(unique_id="col-backlog", name="Backlog"),
                KfColumn(unique_id="col-upnext", name="Up Next"),
                KfColumn(unique_id="col-inprog", name="In Progress"),
                KfColumn(unique_id="col-blocked", name="Blocked"),
                KfColumn(unique_id="col-done", name="Done"),
            ],
            swimlanes=[
                KfSwimlane(unique_id="sw-default", name="Default", description=""),
                KfSwimlane(unique_id="sw-v1", name="v1.0", description="First release"),
            ],
        )
        self.field_defs = field_defs or [
            KfCustomFieldDef(
                id="cf-priority", name="Priority", field_type="dropdown",
                dropdown_options=["High", "Medium", "Low"],
            ),
            KfCustomFieldDef(
                id="cf-ws", name="Work Stream", field_type="dropdown",
                dropdown_options=["alpha", "beta"],
            ),
        ]
        self.tasks: dict[str, KfTask] = {}
        self.comments: dict[str, list[KfComment]] = {}
        self._next_id = 0
        self.fail_set_custom_field = False

    # --- reads ---
    def get_board(self) -> KfBoard:
        return self.board

    def list_custom_field_defs(self) -> list[KfCustomFieldDef]:
        return self.field_defs

    def list_tasks(self, *, column_id: str | None = None, **_: object) -> list[KfTask]:
        return [t for t in self.tasks.values() if column_id is None or t.column_id == column_id]

    def iter_all_tasks(self) -> list[KfTask]:
        return list(self.tasks.values())

    def get_task(self, task_id: str) -> KfTask:
        if task_id not in self.tasks:
            raise KanbanFlowNotFoundError(f"no task {task_id}")
        return self.tasks[task_id]

    # --- writes ---
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
        self._next_id += 1
        task_id = f"task-{self._next_id}"
        task = KfTask(
            id=task_id, name=name, description=description or "", column_id=column_id,
            swimlane_id=swimlane_id, number_value=number_value,
            responsible_user_id=responsible_user_id, labels=list(labels or []),
        )
        self.tasks[task_id] = task
        return task

    def update_task(
        self,
        task_id: str,
        *,
        name: str | None = None,
        column_id: str | None = None,
        swimlane_id: str | None = None,
        number_value: int | None = None,
        description: str | None = None,
        color: str | None = None,
        responsible_user_id: str | None = None,
    ) -> KfTask:
        t = self.get_task(task_id)
        if name is not None:
            t.name = name
        if column_id is not None:
            t.column_id = column_id
        if swimlane_id is not None:
            t.swimlane_id = swimlane_id
        if number_value is not None:
            t.number_value = number_value
        if description is not None:
            t.description = description
        return t

    def delete_task(self, task_id: str) -> None:
        self.tasks.pop(task_id, None)

    def get_task_custom_fields(self, task_id: str) -> list[KfCustomFieldValue]:
        return self.get_task(task_id).custom_fields

    def set_task_custom_field(self, task_id: str, custom_field_id: str, value: str | float) -> None:
        if self.fail_set_custom_field:
            raise RuntimeError("forced custom-field failure")
        t = self.get_task(task_id)
        for cf in t.custom_fields:
            if cf.custom_field_id == custom_field_id:
                cf.value = value
                return
        t.custom_fields.append(KfCustomFieldValue(custom_field_id=custom_field_id, value=value))

    def add_comment(self, task_id: str, text: str, **_: object) -> str:
        self.get_task(task_id)
        bucket = self.comments.setdefault(task_id, [])
        cid = f"c-{len(bucket) + 1}"
        bucket.append(KfComment(id=cid, text=text, created_timestamp="t"))
        return cid

    def list_comments(self, task_id: str) -> list[KfComment]:
        return self.comments.get(task_id, [])

    def add_label(self, task_id: str, name: str, *, pinned: bool = False) -> None:
        t = self.get_task(task_id)
        if not any(label.name == name for label in t.labels):
            t.labels.append(KfLabel(name=name, pinned=pinned))

    def remove_label(self, task_id: str, name: str) -> None:
        t = self.get_task(task_id)
        t.labels = [label for label in t.labels if label.name != name]

    def list_labels(self, task_id: str) -> list[KfLabel]:
        return self.get_task(task_id).labels
```

```python
# tests/test_kanbanflow_provider.py  (start the file with fake sanity checks)
"""Unit tests for KanbanFlowProvider (Phase 3, #316). Faked client, no network."""

from __future__ import annotations

from pathlib import Path

import pytest

from skills.jared.scripts.lib.board_provider import BoardProvider
from skills.jared.scripts.lib.kf_number_index import KfNumberIndex
from skills.jared.scripts.lib.kanbanflow_provider import KanbanFlowProvider
from tests.fake_kanbanflow import FakeKanbanFlowClient


def _provider(tmp_path: Path) -> tuple[KanbanFlowProvider, FakeKanbanFlowClient]:
    client = FakeKanbanFlowClient()
    index = KfNumberIndex(tmp_path / "kf-index-B1.json")
    provider = KanbanFlowProvider(
        client=client, board=client.board, field_defs=client.field_defs, index=index
    )
    return provider, client


def test_fake_create_and_get_roundtrip() -> None:
    client = FakeKanbanFlowClient()
    t = client.create_task(name="hi", column_id="col-backlog", number_value=1)
    assert client.get_task(t.id).name == "hi"


def test_fake_get_missing_raises() -> None:
    from skills.jared.scripts.lib.kanbanflow_client import KanbanFlowNotFoundError

    client = FakeKanbanFlowClient()
    with pytest.raises(KanbanFlowNotFoundError):
        client.get_task("nope")
```

- [ ] **Step 2: Run sanity tests — they should fail on the provider import**

Run: `$VENV/python -m pytest tests/test_kanbanflow_provider.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'skills.jared.scripts.lib.kanbanflow_provider'` (the fake itself is fine; the import of the not-yet-written provider fails collection)

- [ ] **Step 3: (Provider is written in Task 4.)** No implementation here — the fake is the deliverable; its sanity tests pass once Task 4 lands the provider module. Proceed to Task 4, then return is unnecessary — Task 4's run will green these.

- [ ] **Step 4: Commit the fake (test infra)**

```bash
git add tests/fake_kanbanflow.py
git commit -m "test(316): FakeKanbanFlowClient in-memory test double (Phase 3.3)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

(Do not commit `tests/test_kanbanflow_provider.py` yet — it grows through Tasks 4–12 and is committed with Task 4.)

---

## Task 4: `KanbanFlowProvider` skeleton — construction, resolution maps, capabilities

**Files:**
- Create: `skills/jared/scripts/lib/kanbanflow_provider.py`
- Test: `tests/test_kanbanflow_provider.py`

- [ ] **Step 1: Add failing tests**

Append to `tests/test_kanbanflow_provider.py`:

```python
def test_provider_satisfies_protocol(tmp_path: Path) -> None:
    provider, _ = _provider(tmp_path)
    assert isinstance(provider, BoardProvider)


def test_capabilities_is_empty_frozenset(tmp_path: Path) -> None:
    provider, _ = _provider(tmp_path)
    assert provider.capabilities() == frozenset()
```

- [ ] **Step 2: Run to verify failure**

Run: `$VENV/python -m pytest tests/test_kanbanflow_provider.py -v`
Expected: FAIL — module not found

- [ ] **Step 3: Write the skeleton**

```python
# skills/jared/scripts/lib/kanbanflow_provider.py
"""KanbanFlowProvider — BoardProvider over the KanbanFlow REST client (#316).

All KanbanFlow ids (_id, columnId, swimlaneId, customFieldId) stay private here;
the interface speaks only IssueRef (#N) and the neutral dataclasses. #N is
resolved to the internal task _id via KfNumberIndex (no get-by-number endpoint).

Capability set is reduced: KanbanFlow supports only the core board loop. See the
design spec for the per-capability rationale.
"""

from __future__ import annotations

import contextlib
from typing import Protocol

from .board import FieldNotFound, ItemNotFound, OptionNotFound
from .board_provider import BoardItem, Capability, IssueRef
from .kanbanflow_client import KfBoard, KfCustomFieldDef, KfLabel, KfTask
from .kf_number_index import KfNumberIndex

# NOTE: later tasks add imports as they first use them — KanbanFlowNotFoundError
# (Task 5), Edge + ClosedItem (Task 6), Milestone (Task 12). Each task keeps its
# own ruff/mypy gate green; do not front-load these here (they would be unused
# until their task and trip ruff F401).

_BLOCKED_BY_PREFIX = "blocked-by:"

# KanbanFlow advertises the full Capability set MINUS these. The remainder is
# empty: KF supports only the core board loop. See the design spec.
_OMITTED_CAPABILITIES = frozenset(
    {
        Capability.NATIVE_DEPENDENCIES,
        Capability.MILESTONE_STATE,
        Capability.VELOCITY_TIMESTAMPS,
        Capability.MARKDOWN_BODY,
        Capability.CLOSED_STATE,
        Capability.MCP_TIER,
        Capability.SUB_ISSUES,
    }
)


class KanbanFlowClientLike(Protocol):
    """The exact KanbanFlowClient surface KanbanFlowProvider depends on.

    A consumer-owned structural interface (interface segregation): the real
    KanbanFlowClient and the test FakeKanbanFlowClient both satisfy it without a
    nominal base class, so the provider type-checks under `mypy --strict` whether
    constructed with the production client or the in-memory fake. Declares only
    the ~11 methods the provider actually calls.
    """

    def get_board(self) -> KfBoard: ...
    def list_custom_field_defs(self) -> list[KfCustomFieldDef]: ...
    def iter_all_tasks(self) -> list[KfTask]: ...
    def get_task(self, task_id: str) -> KfTask: ...
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
    ) -> KfTask: ...
    def update_task(
        self,
        task_id: str,
        *,
        name: str | None = None,
        column_id: str | None = None,
        swimlane_id: str | None = None,
        number_value: int | None = None,
        description: str | None = None,
        color: str | None = None,
        responsible_user_id: str | None = None,
    ) -> KfTask: ...
    def delete_task(self, task_id: str) -> None: ...
    def set_task_custom_field(
        self, task_id: str, custom_field_id: str, value: str | float
    ) -> None: ...
    def add_comment(self, task_id: str, text: str) -> str: ...
    def add_label(self, task_id: str, name: str) -> None: ...
    def remove_label(self, task_id: str, name: str) -> None: ...


class KanbanFlowProvider:
    _CAPABILITIES = frozenset(Capability) - _OMITTED_CAPABILITIES  # == frozenset()

    def __init__(
        self,
        *,
        client: KanbanFlowClientLike,
        board: KfBoard,
        field_defs: list[KfCustomFieldDef],
        index: KfNumberIndex,
    ) -> None:
        self._client = client
        self._board = board
        self._index = index
        self._column_id_by_name = {c.name: c.unique_id for c in board.columns}
        self._column_name_by_id = {c.unique_id: c.name for c in board.columns}
        self._swimlane_id_by_name = {s.name: s.unique_id for s in board.swimlanes}
        self._swimlane_name_by_id = {s.unique_id: s.name for s in board.swimlanes}
        self._field_def_by_name = {d.name: d for d in field_defs}
        self._field_name_by_id = {d.id: d.name for d in field_defs}

    # --- introspection ---
    def capabilities(self) -> frozenset[Capability]:
        return self._CAPABILITIES

    # --- private resolution helpers ---
    def _column_id(self, status: str) -> str:
        if status not in self._column_id_by_name:
            available = ", ".join(sorted(self._column_id_by_name)) or "(none)"
            raise FieldNotFound(f"Status column '{status}' not on the board. Available: {available}")
        return self._column_id_by_name[status]

    def _swimlane_id(self, name: str) -> str:
        if name not in self._swimlane_id_by_name:
            available = ", ".join(sorted(self._swimlane_id_by_name)) or "(none)"
            raise FieldNotFound(f"Milestone (swimlane) '{name}' not on the board. Available: {available}")
        return self._swimlane_id_by_name[name]

    def _field_def(self, name: str) -> KfCustomFieldDef:
        if name not in self._field_def_by_name:
            available = ", ".join(sorted(self._field_def_by_name)) or "(none)"
            raise FieldNotFound(f"Field '{name}' not on the board. Available: {available}")
        return self._field_def_by_name[name]

    def _check_option(self, field_name: str, value: str) -> KfCustomFieldDef:
        definition = self._field_def(field_name)
        if value not in definition.dropdown_options:
            available = ", ".join(definition.dropdown_options) or "(none)"
            raise OptionNotFound(
                f"Option '{value}' not valid for field '{field_name}'. Available: {available}"
            )
        return definition

    @staticmethod
    def _parse_blocked_by(label_names: list[str]) -> list[int]:
        out: list[int] = []
        for name in label_names:
            if name.startswith(_BLOCKED_BY_PREFIX):
                with contextlib.suppress(ValueError):
                    out.append(int(name[len(_BLOCKED_BY_PREFIX) :]))
        return out

    def _item_from_task(self, task: KfTask) -> BoardItem:
        label_names = [label.name for label in task.labels]
        priority: str | None = None
        fields: dict[str, str] = {}
        for cf in task.custom_fields:
            field_name = self._field_name_by_id.get(cf.custom_field_id)
            if field_name is None:
                continue
            if field_name == "Priority":
                priority = str(cf.value)
            else:
                fields[field_name] = str(cf.value)
        return BoardItem(
            number=task.number_value or 0,
            title=task.name,
            status=self._column_name_by_id.get(task.column_id) if task.column_id else None,
            priority=priority,
            body=task.description,
            labels=[n for n in label_names if not n.startswith(_BLOCKED_BY_PREFIX)],
            milestone=self._swimlane_name_by_id.get(task.swimlane_id) if task.swimlane_id else None,
            blocked_by=sorted(self._parse_blocked_by(label_names)),
            assignee=task.responsible_user_id,
            fields=fields,
            provider_ref=task.id,
        )

    # --- index plumbing ---
    def _reseed_index(self) -> None:
        mapping = {
            t.number_value: t.id
            for t in self._client.iter_all_tasks()
            if t.number_value is not None
        }
        self._index.replace(mapping)

    def _ensure_seeded(self) -> None:
        if self._index.is_empty():
            self._reseed_index()

    def _resolve_id(self, ref: IssueRef) -> str:
        task_id = self._index.get(ref)
        if task_id is None:
            self._reseed_index()
            task_id = self._index.get(ref)
        if task_id is None:
            raise ItemNotFound(f"#{ref} not found on the KanbanFlow board")
        return task_id

    def _set_custom_field(self, field_name: str, value: str, task_id: str) -> None:
        definition = self._check_option(field_name, value)
        self._client.set_task_custom_field(task_id, definition.id, value)
```

The remaining contract methods are added by Tasks 5–12. Until then `mypy` will report `KanbanFlowProvider` does not satisfy `BoardProvider` only at the `isinstance` test site — that test is expected to PASS at runtime (Protocol `runtime_checkable` checks method *names*, which we add incrementally) but **may fail until all methods exist**. To keep the suite green per task, mark the protocol test with a skip until Task 12:

```python
@pytest.mark.skip(reason="enable in Task 12 once all BoardProvider methods exist")
def test_provider_satisfies_protocol(tmp_path: Path) -> None:
    ...
```

> Remove the skip in Task 12. `test_capabilities_is_empty_frozenset` is not skipped and must pass now.

- [ ] **Step 4: Run to verify capabilities test passes**

Run: `$VENV/python -m pytest tests/test_kanbanflow_provider.py -v`
Expected: PASS for the fake sanity tests + `test_capabilities_is_empty_frozenset`; `test_provider_satisfies_protocol` SKIPPED

- [ ] **Step 5: Lint + type-check + commit**

Run: `$VENV/ruff check skills/jared/scripts/lib/kanbanflow_provider.py tests/test_kanbanflow_provider.py && $VENV/ruff format skills/jared/scripts/lib/kanbanflow_provider.py tests/test_kanbanflow_provider.py && $VENV/mypy`
Expected: clean. mypy passes because the test's `FakeKanbanFlowClient` satisfies the `KanbanFlowClientLike` Protocol *structurally* (the ctor takes `KanbanFlowClientLike`, not the concrete client — this is what keeps the fake-injection type-clean from here on). `BoardProvider` conformance is asserted only at the skipped `test_provider_satisfies_protocol`, enabled in Task 12.

```bash
git add skills/jared/scripts/lib/kanbanflow_provider.py tests/test_kanbanflow_provider.py
git commit -m "feat(316): KanbanFlowProvider skeleton — construction + capabilities (Phase 3.4)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: Reads — `get_item`, `list_open_items`, `get_body`

**Files:**
- Modify: `skills/jared/scripts/lib/kanbanflow_provider.py`
- Test: `tests/test_kanbanflow_provider.py`

- [ ] **Step 1: Add failing tests**

```python
def test_get_item_maps_task_to_boarditem(tmp_path: Path) -> None:
    provider, client = _provider(tmp_path)
    task = client.create_task(
        name="Do the thing", column_id="col-inprog", number_value=42,
        swimlane_id="sw-v1", description="## Summary\nbody",
    )
    client.set_task_custom_field(task.id, "cf-priority", "High")
    client.add_label(task.id, "session-2")
    client.add_label(task.id, "blocked-by:7")
    provider._index.put(42, task.id)

    item = provider.get_item(42)
    assert item is not None
    assert item.number == 42
    assert item.title == "Do the thing"
    assert item.status == "In Progress"
    assert item.priority == "High"
    assert item.milestone == "v1.0"
    assert item.body == "## Summary\nbody"
    assert item.labels == ["session-2"]          # blocked-by markers stripped
    assert item.blocked_by == [7]
    assert item.provider_ref == task.id


def test_get_item_missing_returns_none(tmp_path: Path) -> None:
    provider, _ = _provider(tmp_path)
    assert provider.get_item(999) is None


def test_list_open_items_excludes_done(tmp_path: Path) -> None:
    provider, client = _provider(tmp_path)
    client.create_task(name="open", column_id="col-upnext", number_value=1)
    client.create_task(name="closed", column_id="col-done", number_value=2)
    items = provider.list_open_items()
    assert sorted(i.title for i in items) == ["open"]


def test_get_body_returns_description(tmp_path: Path) -> None:
    provider, client = _provider(tmp_path)
    t = client.create_task(name="x", column_id="col-backlog", number_value=5, description="hello")
    provider._index.put(5, t.id)
    assert provider.get_body(5) == "hello"
```

- [ ] **Step 2: Run to verify failure**

Run: `$VENV/python -m pytest tests/test_kanbanflow_provider.py -k "get_item or list_open or get_body" -v`
Expected: FAIL — `AttributeError: 'KanbanFlowProvider' object has no attribute 'get_item'`

- [ ] **Step 3: Implement the reads**

First, add `KanbanFlowNotFoundError` to the client import (it's used by `get_item`):

```python
from .kanbanflow_client import KanbanFlowNotFoundError, KfBoard, KfCustomFieldDef, KfLabel, KfTask
```

Then add to `KanbanFlowProvider`:

```python
    # --- reads ---
    def get_item(self, ref: IssueRef) -> BoardItem | None:
        task_id = self._index.get(ref)
        if task_id is None:
            self._reseed_index()
            task_id = self._index.get(ref)
        if task_id is None:
            return None
        try:
            task = self._client.get_task(task_id)
        except KanbanFlowNotFoundError:
            return None
        return self._item_from_task(task)

    def list_open_items(self) -> list[BoardItem]:
        done_id = self._column_id_by_name.get("Done")
        return [
            self._item_from_task(t)
            for t in self._client.iter_all_tasks()
            if t.column_id != done_id
        ]

    def get_body(self, ref: IssueRef) -> str:
        return self._client.get_task(self._resolve_id(ref)).description
```

- [ ] **Step 4: Run to verify pass**

Run: `$VENV/python -m pytest tests/test_kanbanflow_provider.py -v`
Expected: PASS (skeleton + read tests)

- [ ] **Step 5: Lint + type-check + commit**

Run: `$VENV/ruff check . && $VENV/mypy`

```bash
git add skills/jared/scripts/lib/kanbanflow_provider.py tests/test_kanbanflow_provider.py
git commit -m "feat(316): KanbanFlowProvider reads — get_item/list_open_items/get_body (Phase 3.5)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 6: `fetch_blocked_by_edges` + `recently_closed`

**Files:**
- Modify: `skills/jared/scripts/lib/kanbanflow_provider.py`
- Test: `tests/test_kanbanflow_provider.py`

- [ ] **Step 1: Add failing tests**

```python
def test_fetch_blocked_by_edges_parses_labels(tmp_path: Path) -> None:
    provider, client = _provider(tmp_path)
    a = client.create_task(name="a", column_id="col-upnext", number_value=10)
    client.add_label(a.id, "blocked-by:3")
    client.add_label(a.id, "blocked-by:4")
    client.create_task(name="b", column_id="col-upnext", number_value=11)  # no blockers
    edges = provider.fetch_blocked_by_edges()
    assert sorted((e.dependent, e.blocker) for e in edges) == [(10, 3), (10, 4)]


def test_recently_closed_is_empty_degraded(tmp_path: Path) -> None:
    provider, client = _provider(tmp_path)
    client.create_task(name="done", column_id="col-done", number_value=1)
    assert provider.recently_closed(days=7) == []
```

- [ ] **Step 2: Run to verify failure**

Run: `$VENV/python -m pytest tests/test_kanbanflow_provider.py -k "blocked_by_edges or recently_closed" -v`
Expected: FAIL — attributes missing

- [ ] **Step 3: Implement**

First, add `ClosedItem` and `Edge` to the board_provider import (used by these two methods):

```python
from .board_provider import BoardItem, Capability, ClosedItem, Edge, IssueRef
```

Then add to `KanbanFlowProvider`:

```python
    def fetch_blocked_by_edges(self) -> list[Edge]:
        edges: list[Edge] = []
        for task in self._client.iter_all_tasks():
            if task.number_value is None:
                continue
            for blocker in self._parse_blocked_by([label.name for label in task.labels]):
                edges.append(Edge(dependent=task.number_value, blocker=blocker))
        return edges

    def recently_closed(self, *, days: int) -> list[ClosedItem]:
        # KanbanFlow exposes no reliable moved-to-Done timestamp
        # (VELOCITY_TIMESTAMPS omitted). Degrade to empty; Phase 6 gates callers
        # on the capability.
        return []
```

- [ ] **Step 4: Run to verify pass**

Run: `$VENV/python -m pytest tests/test_kanbanflow_provider.py -v`
Expected: PASS

- [ ] **Step 5: Lint + type-check + commit**

Run: `$VENV/ruff check . && $VENV/mypy`

```bash
git add skills/jared/scripts/lib/kanbanflow_provider.py tests/test_kanbanflow_provider.py
git commit -m "feat(316): blocked-by edges + recently_closed degradation (Phase 3.6)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 7: `validate_fields`

**Files:**
- Modify: `skills/jared/scripts/lib/kanbanflow_provider.py`
- Test: `tests/test_kanbanflow_provider.py`

- [ ] **Step 1: Add failing tests**

```python
def test_validate_fields_passes_for_valid(tmp_path: Path) -> None:
    provider, _ = _provider(tmp_path)
    provider.validate_fields(priority="High", status="Backlog", fields=[("Work Stream", "alpha")])


def test_validate_fields_raises_on_bad_status(tmp_path: Path) -> None:
    provider, _ = _provider(tmp_path)
    with pytest.raises(FieldNotFound):
        provider.validate_fields(priority="High", status="Nonexistent")


def test_validate_fields_raises_on_bad_priority_option(tmp_path: Path) -> None:
    provider, _ = _provider(tmp_path)
    with pytest.raises(OptionNotFound):
        provider.validate_fields(priority="Critical", status="Backlog")
```

Add to the imports at the top of the test file:

```python
from skills.jared.scripts.lib.board import FieldNotFound, OptionNotFound
```

- [ ] **Step 2: Run to verify failure**

Run: `$VENV/python -m pytest tests/test_kanbanflow_provider.py -k validate_fields -v`
Expected: FAIL — attribute missing

- [ ] **Step 3: Implement**

```python
    # --- writes ---
    def validate_fields(
        self,
        *,
        priority: str,
        status: str,
        fields: list[tuple[str, str]] | None = None,
    ) -> None:
        """Fail-before-mutate fence: resolve Status column + Priority option +
        extra field options, raising FieldNotFound/OptionNotFound on any miss."""
        self._column_id(status)
        self._check_option("Priority", priority)
        for name, value in fields or []:
            self._check_option(name, value)
```

- [ ] **Step 4: Run to verify pass**

Run: `$VENV/python -m pytest tests/test_kanbanflow_provider.py -v`
Expected: PASS

- [ ] **Step 5: Lint + type-check + commit**

Run: `$VENV/ruff check . && $VENV/mypy`

```bash
git add skills/jared/scripts/lib/kanbanflow_provider.py tests/test_kanbanflow_provider.py
git commit -m "feat(316): validate_fields fail-before-mutate fence (Phase 3.7)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 8: `file()` — create + set fields + rollback + index

**Files:**
- Modify: `skills/jared/scripts/lib/kanbanflow_provider.py`
- Test: `tests/test_kanbanflow_provider.py`

- [ ] **Step 1: Add failing tests**

```python
def test_file_creates_task_with_status_priority_and_indexes(tmp_path: Path) -> None:
    provider, client = _provider(tmp_path)
    item = provider.file(
        title="New work", body="## Summary\nx", priority="High", status="Backlog",
        labels=["session-2"], milestone="v1.0", fields=[("Work Stream", "alpha")],
    )
    assert item.number == 1                       # first allocation
    assert item.status == "Backlog"
    assert item.priority == "High"
    assert item.milestone == "v1.0"
    assert item.fields == {"Work Stream": "alpha"}
    assert "session-2" in item.labels
    assert provider._index.get(1) == item.provider_ref


def test_file_allocates_sequential_numbers(tmp_path: Path) -> None:
    provider, _ = _provider(tmp_path)
    a = provider.file(title="a", body="", priority="Low", status="Backlog")
    b = provider.file(title="b", body="", priority="Low", status="Backlog")
    assert (a.number, b.number) == (1, 2)


def test_file_seeds_next_number_from_existing_tasks(tmp_path: Path) -> None:
    provider, client = _provider(tmp_path)
    client.create_task(name="old", column_id="col-backlog", number_value=50)  # pre-existing
    item = provider.file(title="new", body="", priority="Low", status="Backlog")
    assert item.number == 51                       # max existing + 1, via scan-on-seed


def test_file_rolls_back_orphan_on_field_failure(tmp_path: Path) -> None:
    provider, client = _provider(tmp_path)
    client.fail_set_custom_field = True
    with pytest.raises(RuntimeError):
        provider.file(title="doomed", body="", priority="High", status="Backlog")
    assert client.tasks == {}                       # orphan deleted
    assert provider._index.get(1) is None           # not recorded
```

- [ ] **Step 2: Run to verify failure**

Run: `$VENV/python -m pytest tests/test_kanbanflow_provider.py -k "file_" -v`
Expected: FAIL — `file` missing

- [ ] **Step 3: Implement**

```python
    def _next_number(self) -> int:
        self._ensure_seeded()
        return self._index.max_number() + 1

    def file(
        self,
        *,
        title: str,
        body: str,
        priority: str,
        status: str,
        labels: list[str] | None = None,
        milestone: str | None = None,
        fields: list[tuple[str, str]] | None = None,
    ) -> BoardItem:
        effective_status = status or "Backlog"
        self.validate_fields(priority=priority, status=effective_status, fields=fields)
        column_id = self._column_id(effective_status)
        swimlane_id = self._swimlane_id(milestone) if milestone else None
        number = self._next_number()
        kf_labels = [KfLabel(name=n) for n in (labels or [])]
        task = self._client.create_task(
            name=title,
            column_id=column_id,
            number_value=number,
            swimlane_id=swimlane_id,
            description=body,
            labels=kf_labels or None,
        )
        try:
            self._set_custom_field("Priority", priority, task.id)
            for name, value in fields or []:
                self._set_custom_field(name, value, task.id)
        except Exception:
            with contextlib.suppress(Exception):
                self._client.delete_task(task.id)
            raise
        self._index.put(number, task.id)
        return self._item_from_task(self._client.get_task(task.id))
```

- [ ] **Step 4: Run to verify pass**

Run: `$VENV/python -m pytest tests/test_kanbanflow_provider.py -v`
Expected: PASS

- [ ] **Step 5: Lint + type-check + commit**

Run: `$VENV/ruff check . && $VENV/mypy`

```bash
git add skills/jared/scripts/lib/kanbanflow_provider.py tests/test_kanbanflow_provider.py
git commit -m "feat(316): file() — create + fields + rollback + index (Phase 3.8)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 9: `add_to_board`

KanbanFlow has no off-board tasks; `add_to_board` ensures an existing task carries the given status/priority/fields/labels.

**Files:**
- Modify: `skills/jared/scripts/lib/kanbanflow_provider.py`
- Test: `tests/test_kanbanflow_provider.py`

- [ ] **Step 1: Add failing test**

```python
def test_add_to_board_applies_status_priority_fields_labels(tmp_path: Path) -> None:
    provider, client = _provider(tmp_path)
    t = client.create_task(name="bare", column_id="col-backlog", number_value=8)
    provider._index.put(8, t.id)
    provider.add_to_board(
        8, priority="Medium", status="Up Next",
        labels=["session-2"], fields=[("Work Stream", "beta")],
    )
    item = provider.get_item(8)
    assert item is not None
    assert item.status == "Up Next"
    assert item.priority == "Medium"
    assert item.fields == {"Work Stream": "beta"}
    assert "session-2" in item.labels
```

- [ ] **Step 2: Run to verify failure**

Run: `$VENV/python -m pytest tests/test_kanbanflow_provider.py -k add_to_board -v`
Expected: FAIL

- [ ] **Step 3: Implement**

```python
    def add_to_board(
        self,
        ref: IssueRef,
        *,
        priority: str,
        status: str,
        labels: list[str] | None = None,
        fields: list[tuple[str, str]] | None = None,
    ) -> None:
        task_id = self._resolve_id(ref)
        self.validate_fields(priority=priority, status=status, fields=fields)
        self._client.update_task(task_id, column_id=self._column_id(status))
        self._set_custom_field("Priority", priority, task_id)
        for name, value in fields or []:
            self._set_custom_field(name, value, task_id)
        for name in labels or []:
            self._client.add_label(task_id, name)
```

- [ ] **Step 4: Run to verify pass**

Run: `$VENV/python -m pytest tests/test_kanbanflow_provider.py -v`
Expected: PASS

- [ ] **Step 5: Lint + type-check + commit**

Run: `$VENV/ruff check . && $VENV/mypy`

```bash
git add skills/jared/scripts/lib/kanbanflow_provider.py tests/test_kanbanflow_provider.py
git commit -m "feat(316): add_to_board for existing tasks (Phase 3.9)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 10: Mutations — `set_field`, `move`, `set_body`, `comment`, `close`

**Files:**
- Modify: `skills/jared/scripts/lib/kanbanflow_provider.py`
- Test: `tests/test_kanbanflow_provider.py`

- [ ] **Step 1: Add failing tests**

```python
def _filed(provider: KanbanFlowProvider, **kw: object) -> int:
    item = provider.file(title="t", body="", priority="Low", status="Backlog", **kw)  # type: ignore[arg-type]
    return item.number


def test_set_field_updates_custom_field(tmp_path: Path) -> None:
    provider, _ = _provider(tmp_path)
    n = _filed(provider)
    provider.set_field(n, "Work Stream", "beta")
    assert provider.get_item(n).fields == {"Work Stream": "beta"}  # type: ignore[union-attr]


def test_move_changes_status_column(tmp_path: Path) -> None:
    provider, _ = _provider(tmp_path)
    n = _filed(provider)
    provider.move(n, "In Progress")
    assert provider.get_item(n).status == "In Progress"  # type: ignore[union-attr]


def test_set_body_updates_description(tmp_path: Path) -> None:
    provider, _ = _provider(tmp_path)
    n = _filed(provider)
    provider.set_body(n, "new body")
    assert provider.get_body(n) == "new body"


def test_comment_adds_and_returns_id(tmp_path: Path) -> None:
    provider, client = _provider(tmp_path)
    n = _filed(provider)
    cid = provider.comment(n, "a note")
    assert cid
    task_id = provider._index.get(n)
    assert client.list_comments(task_id)[-1].text == "a note"  # type: ignore[arg-type]


def test_close_comments_then_moves_to_done(tmp_path: Path) -> None:
    provider, client = _provider(tmp_path)
    n = _filed(provider)
    provider.close(n, comment="closing")
    assert provider.get_item(n).status == "Done"  # type: ignore[union-attr]
    task_id = provider._index.get(n)
    assert client.list_comments(task_id)[-1].text == "closing"  # type: ignore[arg-type]
```

- [ ] **Step 2: Run to verify failure**

Run: `$VENV/python -m pytest tests/test_kanbanflow_provider.py -k "set_field or test_move or set_body or comment or close" -v`
Expected: FAIL

- [ ] **Step 3: Implement**

```python
    def set_field(self, ref: IssueRef, field_name: str, value: str) -> None:
        # "Status" is a structural column on KanbanFlow, not a custom field. The
        # CLI drives Status changes through set_field (jared move -> _cmd_set ->
        # set_field, and `jared set N Status`), mirroring GitHub where move() IS
        # set_field("Status"). Route Status to the column move so both CLI paths
        # work. (Caught by the Phase-3 final review; add a CLI-dispatch test for
        # `jared move` on a KF backend, not just a direct provider.move() test.)
        if field_name == "Status":
            self.move(ref, value)
            return
        self._set_custom_field(field_name, value, self._resolve_id(ref))

    def move(self, ref: IssueRef, status: str) -> None:
        self._client.update_task(self._resolve_id(ref), column_id=self._column_id(status))

    def set_body(self, ref: IssueRef, text: str) -> None:
        self._client.update_task(self._resolve_id(ref), description=text)

    def comment(self, ref: IssueRef, body: str) -> str:
        return self._client.add_comment(self._resolve_id(ref), body)

    def close(self, ref: IssueRef, *, comment: str | None = None) -> None:
        task_id = self._resolve_id(ref)
        if comment:
            self._client.add_comment(task_id, comment)
        self._client.update_task(task_id, column_id=self._column_id("Done"))
```

- [ ] **Step 4: Run to verify pass**

Run: `$VENV/python -m pytest tests/test_kanbanflow_provider.py -v`
Expected: PASS

- [ ] **Step 5: Lint + type-check + commit**

Run: `$VENV/ruff check . && $VENV/mypy`

```bash
git add skills/jared/scripts/lib/kanbanflow_provider.py tests/test_kanbanflow_provider.py
git commit -m "feat(316): set_field/move/set_body/comment/close (Phase 3.10)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 11: Labels + blocked-by emulation

**Files:**
- Modify: `skills/jared/scripts/lib/kanbanflow_provider.py`
- Test: `tests/test_kanbanflow_provider.py`

- [ ] **Step 1: Add failing tests**

```python
def test_add_remove_label(tmp_path: Path) -> None:
    provider, _ = _provider(tmp_path)
    n = _filed(provider)
    provider.add_label(n, "session-2")
    assert "session-2" in provider.get_item(n).labels  # type: ignore[union-attr]
    provider.remove_label(n, "session-2")
    assert "session-2" not in provider.get_item(n).labels  # type: ignore[union-attr]


def test_add_remove_blocked_by_uses_label_marker(tmp_path: Path) -> None:
    provider, client = _provider(tmp_path)
    n = _filed(provider)
    provider.add_blocked_by(n, 99)
    task_id = provider._index.get(n)
    assert any(label.name == "blocked-by:99" for label in client.list_labels(task_id))  # type: ignore[arg-type]
    assert provider.get_item(n).blocked_by == [99]  # type: ignore[union-attr]
    provider.remove_blocked_by(n, 99)
    assert provider.get_item(n).blocked_by == []  # type: ignore[union-attr]
```

- [ ] **Step 2: Run to verify failure**

Run: `$VENV/python -m pytest tests/test_kanbanflow_provider.py -k "label or blocked_by" -v`
Expected: FAIL

- [ ] **Step 3: Implement**

```python
    def add_label(self, ref: IssueRef, name: str) -> None:
        self._client.add_label(self._resolve_id(ref), name)

    def remove_label(self, ref: IssueRef, name: str) -> None:
        self._client.remove_label(self._resolve_id(ref), name)

    def add_blocked_by(self, ref: IssueRef, blocker: IssueRef) -> None:
        self._client.add_label(self._resolve_id(ref), f"{_BLOCKED_BY_PREFIX}{blocker}")

    def remove_blocked_by(self, ref: IssueRef, blocker: IssueRef) -> None:
        self._client.remove_label(self._resolve_id(ref), f"{_BLOCKED_BY_PREFIX}{blocker}")
```

- [ ] **Step 4: Run to verify pass**

Run: `$VENV/python -m pytest tests/test_kanbanflow_provider.py -v`
Expected: PASS

- [ ] **Step 5: Lint + type-check + commit**

Run: `$VENV/ruff check . && $VENV/mypy`

```bash
git add skills/jared/scripts/lib/kanbanflow_provider.py tests/test_kanbanflow_provider.py
git commit -m "feat(316): labels + blocked-by label-marker emulation (Phase 3.11)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 12: Milestones — `set_milestone`, `list_milestones` + Protocol gate

**Files:**
- Modify: `skills/jared/scripts/lib/kanbanflow_provider.py`
- Test: `tests/test_kanbanflow_provider.py`

- [ ] **Step 1: Add failing tests + un-skip the Protocol test**

```python
def test_set_milestone_moves_swimlane(tmp_path: Path) -> None:
    provider, _ = _provider(tmp_path)
    n = _filed(provider)
    provider.set_milestone(n, "v1.0")
    assert provider.get_item(n).milestone == "v1.0"  # type: ignore[union-attr]


def test_set_milestone_bad_name_raises(tmp_path: Path) -> None:
    provider, _ = _provider(tmp_path)
    n = _filed(provider)
    with pytest.raises(FieldNotFound):
        provider.set_milestone(n, "nonexistent")


def test_list_milestones_from_swimlanes_dateless(tmp_path: Path) -> None:
    provider, _ = _provider(tmp_path)
    names = {m.name: m for m in provider.list_milestones()}
    assert "v1.0" in names
    assert names["v1.0"].state is None and names["v1.0"].due is None
    assert names["v1.0"].description == "First release"
```

Then **remove the `@pytest.mark.skip` decorator** from `test_provider_satisfies_protocol` (added in Task 4).

- [ ] **Step 2: Run to verify failure**

Run: `$VENV/python -m pytest tests/test_kanbanflow_provider.py -k "milestone or satisfies_protocol" -v`
Expected: FAIL — `set_milestone`/`list_milestones` missing; protocol test fails (methods incomplete until Step 3)

- [ ] **Step 3: Implement**

First, add `Milestone` to the board_provider import (used by `list_milestones`):

```python
from .board_provider import BoardItem, Capability, ClosedItem, Edge, IssueRef, Milestone
```

Then add to `KanbanFlowProvider`:

```python
    def set_milestone(self, ref: IssueRef, name: str) -> None:
        self._client.update_task(self._resolve_id(ref), swimlane_id=self._swimlane_id(name))

    def list_milestones(self) -> list[Milestone]:
        return [
            Milestone(name=s.name, description=s.description, state=None, due=None)
            for s in self._board.swimlanes
        ]
```

- [ ] **Step 4: Run to verify pass — including the now-active Protocol conformance test**

Run: `$VENV/python -m pytest tests/test_kanbanflow_provider.py -v`
Expected: PASS — `test_provider_satisfies_protocol` now passes (`isinstance(provider, BoardProvider)` is True; all methods exist)

- [ ] **Step 5: Lint + type-check + commit**

Run: `$VENV/ruff check . && $VENV/mypy`
Expected: clean. `mypy` now type-checks the full provider against all method signatures.

```bash
git add skills/jared/scripts/lib/kanbanflow_provider.py tests/test_kanbanflow_provider.py
git commit -m "feat(316): milestones + Protocol conformance gate (Phase 3.12)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 13: Wire `Board.provider` + update the existing test + full green

**Files:**
- Modify: `skills/jared/scripts/lib/board.py` (the `provider` property ~line 394, the `_provider` field ~line 85, imports)
- Modify: `tests/test_board.py` (`test_board_provider_unknown_backend_raises`, ~line 1545)

- [ ] **Step 1: Update the existing board test**

Replace `test_board_provider_unknown_backend_raises` in `tests/test_board.py`. It currently uses `backend: kanbanflow` as the "unimplemented" case — that case now returns a provider. Re-point the raise-assertion at a genuinely-unimplemented backend (`trello`):

```python
def test_board_provider_unknown_backend_raises(tmp_path: Path) -> None:
    """An unrecognized backend value raises BoardConfigError on .provider access.

    Also exercises the parse wiring: jared_config.get('backend') flows through
    _parse into Board.backend for non-default values."""
    from skills.jared.scripts.lib.board import Board, BoardConfigError

    board_md = tmp_path / "docs" / "project-board.md"
    board_md.parent.mkdir(parents=True)
    board_md.write_text(
        dedent("""\
        - Project URL: https://github.com/users/brockamer/projects/7
        - Project number: 7
        - Project ID: PVT_kwHO_xyz
        - Owner: brockamer
        - Repo: brockamer/findajob

        ## Jared config
        - backend: trello
        """)
    )

    board = Board.from_path(board_md)
    assert board.backend == "trello"
    with pytest.raises(BoardConfigError, match="trello"):
        _ = board.provider
```

- [ ] **Step 2: Run it — fails because `trello` currently also doesn't raise? (No — it DOES raise today, since the current code raises for anything != "github". This test passes now, but will break in Step 3 unless the new branch still raises for `trello`. Run it to confirm green baseline.)**

Run: `$VENV/python -m pytest tests/test_board.py::test_board_provider_unknown_backend_raises -v`
Expected: PASS (current code raises for any non-github backend, including `trello`)

- [ ] **Step 3: Add a failing test for the kanbanflow branch**

Add to `tests/test_board.py`:

```python
def test_board_provider_returns_kanbanflow_provider(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """backend: kanbanflow constructs a KanbanFlowProvider (not a raise)."""
    from skills.jared.scripts.lib.board import Board
    from skills.jared.scripts.lib.kanbanflow_provider import KanbanFlowProvider
    from tests.fake_kanbanflow import FakeKanbanFlowClient

    # Avoid real network: from_env returns a fake client.
    fake = FakeKanbanFlowClient()
    monkeypatch.setattr(
        "skills.jared.scripts.lib.kanbanflow_client.KanbanFlowClient.from_env",
        classmethod(lambda cls, **kw: fake),
    )
    monkeypatch.setenv("JARED_CACHE_DIR", str(tmp_path))

    board_md = tmp_path / "docs" / "project-board.md"
    board_md.parent.mkdir(parents=True)
    board_md.write_text(
        dedent("""\
        - Project URL: https://github.com/users/brockamer/projects/7
        - Project number: 7
        - Project ID: PVT_kwHO_xyz
        - Owner: brockamer
        - Repo: brockamer/findajob

        ## Jared config
        - backend: kanbanflow
        """)
    )
    board = Board.from_path(board_md)
    assert isinstance(board.provider, KanbanFlowProvider)
```

> **Dual-import caveat (see CLAUDE.md):** `from_env` is patched via the `skills.jared.scripts.lib.kanbanflow_client` path, which is what this test imports. The CLI's `from lib...` path is a different module object, but this is a unit test using the `skills.jared...` path throughout, so a single patch suffices. Verify by running the test.

Run: `$VENV/python -m pytest tests/test_board.py::test_board_provider_returns_kanbanflow_provider -v`
Expected: FAIL — `BoardConfigError: backend 'kanbanflow' has no provider yet`

- [ ] **Step 4: Implement the wiring**

In `skills/jared/scripts/lib/board.py`:

a) Widen the cached-provider field type (near line 85) and the lazy import at the top of the TYPE_CHECKING block (line ~20). Change:

```python
    _provider: GitHubProjectsProvider | None = field(default=None, repr=False)
```
to:
```python
    _provider: BoardProvider | None = field(default=None, repr=False)
```

And add to the imports at the top of `board.py` (alongside the existing `from .github_provider import GitHubProjectsProvider` under TYPE_CHECKING, or as a top-level import of the Protocol):

```python
from .board_provider import BoardProvider
```

> `BoardProvider` is a pure-types module (no gh imports), so a top-level import creates no cycle. If a cycle is detected at runtime, move it under `if TYPE_CHECKING:` and quote the annotations (`"BoardProvider"`).

b) Replace the `provider` property (line ~394):

```python
    @property
    def provider(self) -> BoardProvider:
        """Return the configured backend provider, lazily constructed."""
        if self.backend not in ("github", "kanbanflow"):
            raise BoardConfigError(
                f"backend '{self.backend}' has no provider (Phase 3+). "
                "Supported: 'github', 'kanbanflow'."
            )
        if self._provider is None:
            if self.backend == "github":
                from .github_provider import GitHubProjectsProvider

                self._provider = GitHubProjectsProvider(
                    project_number=self.project_number,
                    project_id=self.project_id,
                    owner=self.owner,
                    repo=self.repo,
                    field_ids=self._field_ids,
                    field_options=self._field_options,
                )
            else:  # kanbanflow
                from .kanbanflow_client import KanbanFlowClient
                from .kanbanflow_provider import KanbanFlowProvider
                from .kf_number_index import KfNumberIndex

                client = KanbanFlowClient.from_env()
                kf_board = client.get_board()
                field_defs = client.list_custom_field_defs()
                index = KfNumberIndex.for_board(kf_board.id)
                self._provider = KanbanFlowProvider(
                    client=client, board=kf_board, field_defs=field_defs, index=index
                )
        return self._provider
```

- [ ] **Step 5: Run both board tests + the full suite**

Run: `$VENV/python -m pytest tests/test_board.py -k "backend or kanbanflow_provider" -v`
Expected: PASS (both the `trello`-raises test and the `kanbanflow`-returns-provider test)

Run: `$VENV/python -m pytest -m "not integration"`
Expected: PASS — entire unit suite green, no other test changed.

- [ ] **Step 6: Full lint + type-check**

Run: `$VENV/ruff check . && $VENV/ruff format --check . && $VENV/mypy`
Expected: all clean.

- [ ] **Step 7: Commit**

```bash
git add skills/jared/scripts/lib/board.py tests/test_board.py
git commit -m "feat(316): wire Board.provider kanbanflow branch + retarget unknown-backend test (Phase 3.13)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Final verification (whole-plan gate)

- [ ] Run the full offline suite: `$VENV/python -m pytest -m "not integration" -q` → all green.
- [ ] `$VENV/ruff check . && $VENV/ruff format --check . && $VENV/mypy` → clean.
- [ ] Confirm `KanbanFlowProvider` satisfies `BoardProvider` (the `test_provider_satisfies_protocol` test is active and passing).
- [ ] Confirm no existing test other than `test_board_provider_unknown_backend_raises` was modified, and conftest signatures are unchanged (grep the diff).
- [ ] **Verification-ceiling honesty (state in the PR description):** Phase 3 is verified **offline only** — faked-client unit tests + `mypy --strict` structural conformance. **No live KanbanFlow board was exercised.** Live-API verification is deferred to the first real KanbanFlow board / Phase-4 `init`. Do not claim end-to-end KanbanFlow verification.
- [ ] PR note: merging #316 unblocks #317 (Phase 4), #318 (Phase 5), #319 (Phase 6).

## Self-review checklist (done while writing — recorded here for the executor)

- **Spec coverage:** every `BoardProvider` method (5 reads, validate_fields, file, add_to_board, 5 mutations, 4 label/blocked-by, 2 milestone, capabilities) has a task; the `update_task` swimlane extension (Task 2) and the disk index (Task 1) are covered; the offline ceiling is in the final gate.
- **Type consistency:** `_column_id`/`_swimlane_id`/`_field_def`/`_check_option`/`_set_custom_field`/`_resolve_id`/`_next_number`/`_reseed_index`/`_ensure_seeded`/`_item_from_task`/`_parse_blocked_by` are defined once (Tasks 1/4) and reused with identical names throughout. `KfNumberIndex` methods (`get`/`put`/`replace`/`is_empty`/`max_number`/`for_board`) match across Tasks 1, 4, 8, 13.
- **No placeholders:** every code step shows complete code; every `Run:` shows the expected result.
