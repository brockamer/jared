# KanbanFlow event-history client + `recently_closed` — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give `KanbanFlowProvider.recently_closed()` real data by reading the `GET /board/events` history for `columnId`→Done transitions, replacing today's `return []` stub.

**Architecture:** Add a `KfEvent` dataclass family + parser and a `get_board_events()` method to the stdlib KanbanFlow client (mirroring the existing `KfRelation`/`get_relations` and `list_tasks`-paging idioms), then rewrite the provider's `recently_closed` to scan events for moves into the Done column (resolved via the Status column map) and map each to a `ClosedItem`. A final task live-verifies on board `p9vK6cR`.

**Tech Stack:** Python 3 (stdlib-only client), pytest, the `_raw_http`/`patch_kf` test seam, `mypy --strict`, `ruff`.

---

## Scope (read first)

This is **Phase 1a** of epic #357 (see `docs/superpowers/specs/2026-06-11-kanbanflow-parity-design.md`). It is a complete, testable deliverable on its own: `recently_closed` returns real data, which populates `jared next-session-prompt`'s "Recently closed" section on a KanbanFlow board.

**Explicitly NOT in this plan** (each planned separately when pulled):
- **Phase 1b — CLOSED_STATE flip** (`find_orphaned` via Done-membership). Touches `dependency-graph.py` and may add a `@runtime_checkable BoardProvider` method → the atomic-coupling constraint (both provider impls in one commit).
- **Phase 1c — VELOCITY_TIMESTAMPS flag decision.** Needs per-task `createdAt`/activity reconstruction across all open items **and** the event-retention ceiling (Task 4 records the first observation). The `VELOCITY_TIMESTAMPS` flag is **not** flipped in this plan; `recently_closed` returning data is independent of the flag (no surface gates `recently_closed` on it — verified by grep: the five gates are all created-at/activity surfaces).

**Per-capability outcome of this plan:** no `_OMITTED_CAPABILITIES` change. `recently_closed` ships real data; the capability declaration is untouched.

## File Structure

| File | Change | Responsibility |
|---|---|---|
| `skills/jared/scripts/lib/kanbanflow_client.py` | Modify | Add `KfChangedProperty`/`KfDetailedEvent`/`KfEvent` dataclasses, their `_parse_*` functions, and `get_board_events()` |
| `skills/jared/scripts/lib/kanbanflow_provider.py` | Modify | Add `get_board_events` to the `KanbanFlowClientLike` Protocol; import `KfEvent`; rewrite `recently_closed` |
| `tests/fake_kanbanflow.py` | Modify | Add `board_events` attribute + `get_board_events()` to `FakeKanbanFlowClient` |
| `tests/test_kanbanflow_client.py` | Modify | Tests for `_parse_event` and `get_board_events` (single call + paging) |
| `tests/test_kanbanflow_provider.py` | Modify | Replace `test_recently_closed_is_empty_degraded` with real-data tests |

---

### Task 1: `KfEvent` dataclass family + parsers (client)

**Files:**
- Modify: `skills/jared/scripts/lib/kanbanflow_client.py` (dataclass block ~L176-188; parser block ~L265-277)
- Test: `tests/test_kanbanflow_client.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_kanbanflow_client.py` (and add `_parse_event` + `KfEvent` to the existing `from ...kanbanflow_client import (...)` block at the top):

```python
def test_parse_event_maps_nested_shape() -> None:
    raw = {
        "_id": "Nn1Xdp",
        "timestamp": "2026-06-05T13:20:56.216Z",
        "userId": "u-1",
        "detailedEvents": [
            {
                "eventType": "taskChanged",
                "taskId": "1eTJRipf",
                "changedProperties": [
                    {"property": "columnId", "oldValue": "col-inprog", "newValue": "col-done"}
                ],
            }
        ],
    }
    ev = kf._parse_event(raw)
    assert ev.id == "Nn1Xdp"
    assert ev.timestamp == "2026-06-05T13:20:56.216Z"
    assert ev.user_id == "u-1"
    assert len(ev.detailed_events) == 1
    de = ev.detailed_events[0]
    assert de.event_type == "taskChanged"
    assert de.task_id == "1eTJRipf"
    assert de.changed_properties[0].property == "columnId"
    assert de.changed_properties[0].old_value == "col-inprog"
    assert de.changed_properties[0].new_value == "col-done"


def test_parse_event_taskcreated_has_no_changed_properties() -> None:
    ev = kf._parse_event(
        {"_id": "e2", "timestamp": "t", "detailedEvents": [{"eventType": "taskCreated", "taskId": "x"}]}
    )
    assert ev.detailed_events[0].changed_properties == []
    assert ev.user_id == ""
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_kanbanflow_client.py::test_parse_event_maps_nested_shape -v`
Expected: FAIL — `AttributeError: module ... has no attribute '_parse_event'` (and the import line fails to resolve `KfEvent`/`_parse_event`).

- [ ] **Step 3: Write minimal implementation**

In `kanbanflow_client.py`, add the dataclasses after `KfUser` (~L188):

```python
@dataclass
class KfChangedProperty:
    property: str
    old_value: str | None = None
    new_value: str | None = None


@dataclass
class KfDetailedEvent:
    event_type: str
    task_id: str | None = None
    changed_properties: list[KfChangedProperty] = field(default_factory=list)


@dataclass
class KfEvent:
    id: str
    timestamp: str
    user_id: str = ""
    detailed_events: list[KfDetailedEvent] = field(default_factory=list)
```

And add the parsers after `_parse_user` (~L277):

```python
def _parse_changed_property(raw: dict[str, Any]) -> KfChangedProperty:
    return KfChangedProperty(
        property=str(raw.get("property", "")),
        old_value=str(raw["oldValue"]) if raw.get("oldValue") is not None else None,
        new_value=str(raw["newValue"]) if raw.get("newValue") is not None else None,
    )


def _parse_detailed_event(raw: dict[str, Any]) -> KfDetailedEvent:
    return KfDetailedEvent(
        event_type=str(raw.get("eventType", "")),
        task_id=str(raw["taskId"]) if raw.get("taskId") is not None else None,
        changed_properties=[
            _parse_changed_property(cp) for cp in raw.get("changedProperties", [])
        ],
    )


def _parse_event(raw: dict[str, Any]) -> KfEvent:
    return KfEvent(
        id=str(raw.get("_id", "")),
        timestamp=str(raw.get("timestamp", "")),
        user_id=str(raw.get("userId", "")),
        detailed_events=[_parse_detailed_event(de) for de in raw.get("detailedEvents", [])],
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_kanbanflow_client.py -k parse_event -v`
Expected: PASS (both tests).

- [ ] **Step 5: Commit**

```bash
git add skills/jared/scripts/lib/kanbanflow_client.py tests/test_kanbanflow_client.py
git commit -m "feat(jared): add KfEvent dataclasses + parser (Phase 1a.1)"
```

---

### Task 2: `get_board_events()` client method (single call + windowed paging)

**Files:**
- Modify: `skills/jared/scripts/lib/kanbanflow_client.py` (add method after `get_relations`, ~L544)
- Test: `tests/test_kanbanflow_client.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_get_board_events_single_call_returns_parsed_events(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    body = json.dumps(
        {
            "eventsLimited": False,
            "events": [
                {
                    "_id": "e1",
                    "timestamp": "2026-06-05T13:20:56.216Z",
                    "detailedEvents": [
                        {
                            "eventType": "taskChanged",
                            "taskId": "t1",
                            "changedProperties": [
                                {"property": "columnId", "oldValue": "a", "newValue": "b"}
                            ],
                        }
                    ],
                }
            ],
        }
    )
    calls = patch_kf(monkeypatch, status=200, body=body)
    events = _client().get_board_events(limit=100, order="descending")
    assert len(events) == 1
    assert events[0].id == "e1"
    assert events[0].detailed_events[0].changed_properties[0].new_value == "b"
    assert "/board/events" in cast(str, calls[0]["url"])
    assert "limit=100" in cast(str, calls[0]["url"])
    assert "order=descending" in cast(str, calls[0]["url"])


def test_get_board_events_pages_backward_when_limited(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seq = [
        (
            200,
            {},
            json.dumps(
                {
                    "eventsLimited": True,
                    "events": [
                        {"_id": "e2", "timestamp": "2026-06-05T13:00:00.000Z", "detailedEvents": []},
                        {"_id": "e1", "timestamp": "2026-06-05T12:00:00.000Z", "detailedEvents": []},
                    ],
                }
            ).encode(),
        ),
        (
            200,
            {},
            json.dumps(
                {
                    "eventsLimited": False,
                    "events": [
                        {"_id": "e0", "timestamp": "2026-06-05T11:00:00.000Z", "detailedEvents": []}
                    ],
                }
            ).encode(),
        ),
    ]
    urls: list[str] = []

    def fake(method: str, url: str, headers: dict[str, str], data: bytes | None):
        urls.append(url)
        return seq.pop(0)

    monkeypatch.setattr(kf, "_raw_http", fake)
    events = _client().get_board_events(order="descending")
    assert [e.id for e in events] == ["e2", "e1", "e0"]
    assert len(urls) == 2
    # Second window ends just before the oldest event of the first batch.
    assert "to=2026-06-05T12%3A00%3A00.000Z" in urls[1] or "to=2026-06-05T12:00:00.000Z" in urls[1]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_kanbanflow_client.py -k get_board_events -v`
Expected: FAIL — `AttributeError: 'KanbanFlowClient' object has no attribute 'get_board_events'`.

- [ ] **Step 3: Write minimal implementation**

In `kanbanflow_client.py`, add after `get_relations` (~L544):

```python
def get_board_events(
    self,
    *,
    from_ts: str | None = None,
    to_ts: str | None = None,
    limit: int = 100,
    order: str = "descending",
    max_pages: int = 20,
) -> list[KfEvent]:
    """Read board event history (GET /board/events).

    Returns events newest-first (order='descending'). The endpoint has no
    cursor — when the response sets `eventsLimited`, this walks the time
    window backward by setting `to` to the oldest event seen, bounded by
    `from_ts` (server-side floor) and `max_pages` (safety cap). The
    `{eventsLimited, events}` envelope shape is confirmed live on p9vK6cR.
    """
    out: list[KfEvent] = []
    window_to = to_ts
    for _ in range(max_pages):
        params: dict[str, object] = {
            "from": from_ts,
            "to": window_to,
            "limit": limit,
            "order": order,
        }
        raw = self._request("GET", "/board/events", params=params)
        if not isinstance(raw, dict):
            break
        batch = [_parse_event(e) for e in (raw.get("events") or [])]
        out.extend(batch)
        if not raw.get("eventsLimited") or not batch:
            break
        oldest = min((e.timestamp for e in batch if e.timestamp), default=None)
        if oldest is None or oldest == window_to:
            break
        window_to = oldest
    return out
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_kanbanflow_client.py -k get_board_events -v`
Expected: PASS (both tests).

- [ ] **Step 5: Commit**

```bash
git add skills/jared/scripts/lib/kanbanflow_client.py tests/test_kanbanflow_client.py
git commit -m "feat(jared): add get_board_events with windowed paging (Phase 1a.2)"
```

---

### Task 3: Rewrite `recently_closed` to scan events for moves into Done

**Files:**
- Modify: `tests/fake_kanbanflow.py` (add `board_events` + `get_board_events` to the fake)
- Modify: `skills/jared/scripts/lib/kanbanflow_provider.py` (Protocol L65-101; import L20-28; `recently_closed` L287-291)
- Test: `tests/test_kanbanflow_provider.py` (replace `test_recently_closed_is_empty_degraded`, L106-109)

- [ ] **Step 1: Extend the fake client**

In `tests/fake_kanbanflow.py`: add `KfEvent` to the import from `kanbanflow_client` (L13-24), add `self.board_events: list[KfEvent] = []` in `__init__` (after L67 `self.users = []`), and add this method (after `iter_all_tasks`, ~L82):

```python
    def get_board_events(
        self,
        *,
        from_ts: str | None = None,
        to_ts: str | None = None,
        limit: int = 100,
        order: str = "descending",
    ) -> list[KfEvent]:
        return list(self.board_events)
```

- [ ] **Step 2: Write the failing tests**

Replace `test_recently_closed_is_empty_degraded` (L106-109) in `tests/test_kanbanflow_provider.py` with these. They need helpers to build events and seed a Done task — add the imports `from skills.jared.scripts.lib.kanbanflow_client import KfChangedProperty, KfDetailedEvent, KfEvent, KfTask` at the top if not present:

```python
def _move_event(ev_id: str, ts: str, task_id: str, new_col: str) -> KfEvent:
    return KfEvent(
        id=ev_id,
        timestamp=ts,
        detailed_events=[
            KfDetailedEvent(
                event_type="taskChanged",
                task_id=task_id,
                changed_properties=[
                    KfChangedProperty(property="columnId", old_value="col-inprog", new_value=new_col)
                ],
            )
        ],
    )


def test_recently_closed_maps_columnid_into_done(tmp_path: Path) -> None:
    provider, client = _provider(tmp_path)  # see note below
    # A task currently in Done with number 7, and an event moving it there.
    client.tasks["task-A"] = KfTask(id="task-A", name="Closed thing", column_id="col-done", number_value=7)
    client.board_events = [_move_event("e1", "2026-06-05T13:20:56.216Z", "task-A", "col-done")]
    closed = provider.recently_closed(days=36500)  # wide window: exercise mapping, not cutoff
    assert len(closed) == 1
    assert closed[0].number == 7
    assert closed[0].title == "Closed thing"
    assert closed[0].closed_at == "2026-06-05T13:20:56.216Z"


def test_recently_closed_most_recent_move_wins(tmp_path: Path) -> None:
    provider, client = _provider(tmp_path)
    client.tasks["task-A"] = KfTask(id="task-A", name="T", column_id="col-done", number_value=7)
    # Descending order: newest first. Two moves into Done for the same task.
    client.board_events = [
        _move_event("e2", "2026-06-05T15:00:00.000Z", "task-A", "col-done"),
        _move_event("e1", "2026-06-05T13:00:00.000Z", "task-A", "col-done"),
    ]
    closed = provider.recently_closed(days=36500)
    assert len(closed) == 1
    assert closed[0].closed_at == "2026-06-05T15:00:00.000Z"


def test_recently_closed_skips_moves_into_non_done(tmp_path: Path) -> None:
    provider, client = _provider(tmp_path)
    client.tasks["task-A"] = KfTask(id="task-A", name="T", column_id="col-inprog", number_value=7)
    client.board_events = [_move_event("e1", "2026-06-05T13:00:00.000Z", "task-A", "col-inprog")]
    assert provider.recently_closed(days=36500) == []


def test_recently_closed_skips_unresolvable_task(tmp_path: Path) -> None:
    provider, client = _provider(tmp_path)
    # Event references a task that no longer exists (deleted after close).
    client.board_events = [_move_event("e1", "2026-06-05T13:00:00.000Z", "ghost", "col-done")]
    assert provider.recently_closed(days=36500) == []
```

Add this provider-builder helper near the top of `tests/test_kanbanflow_provider.py` if an equivalent does not already exist (the file already constructs providers inline at L19/L347 — reuse that exact shape):

```python
def _provider(tmp_path: Path) -> tuple[KanbanFlowProvider, FakeKanbanFlowClient]:
    client = FakeKanbanFlowClient()
    index = KfNumberIndex(tmp_path / "kf-index-B1.json")
    provider = KanbanFlowProvider(
        client=client, board=client.board, field_defs=client.field_defs, index=index
    )
    return provider, client
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `pytest tests/test_kanbanflow_provider.py -k recently_closed -v`
Expected: FAIL — `recently_closed` still returns `[]`, so the mapping/most-recent assertions fail.

- [ ] **Step 4: Add `get_board_events` to the Protocol + rewrite `recently_closed`**

In `kanbanflow_provider.py`, add `KfEvent` to the import from `.kanbanflow_client` (L20-28). Add to the `KanbanFlowClientLike` Protocol (after `iter_all_tasks`, ~L67):

```python
    def get_board_events(
        self,
        *,
        from_ts: str | None = None,
        to_ts: str | None = None,
        limit: int = 100,
        order: str = "descending",
    ) -> list[KfEvent]: ...
```

Add `from datetime import datetime, timedelta, timezone` to the imports at the top. Replace `recently_closed` (L287-291):

```python
    def recently_closed(self, *, days: int) -> list[ClosedItem]:
        """Closed items = tasks whose most recent event is a move into Done.

        Scans GET /board/events (descending) for changedProperties columnId
        transitions whose newValue is the Done column (resolved via the Status
        column map), within the `days` window. Maps each task's most-recent
        such move to a ClosedItem; the task's number/title come from the live
        task set, so a deleted task (history outlives the task) is skipped.
        """
        done_col_id = self._column_id_by_status.get("Done")
        if done_col_id is None:
            return []
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat().replace(
            "+00:00", "Z"
        )
        events = self._client.get_board_events(from_ts=cutoff, order="descending", limit=100)
        task_by_id = {t.id: t for t in self._client.iter_all_tasks()}
        seen: set[str] = set()
        out: list[ClosedItem] = []
        for ev in events:  # descending → first move per task is the most recent
            if ev.timestamp and ev.timestamp < cutoff:
                continue
            for de in ev.detailed_events:
                tid = de.task_id
                if not tid or tid in seen:
                    continue
                moved_to_done = any(
                    cp.property == "columnId" and cp.new_value == done_col_id
                    for cp in de.changed_properties
                )
                if not moved_to_done:
                    continue
                task = task_by_id.get(tid)
                if task is not None and task.number_value is not None:
                    out.append(
                        ClosedItem(number=task.number_value, title=task.name, closed_at=ev.timestamp)
                    )
                seen.add(tid)
        return out
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_kanbanflow_provider.py -k recently_closed -v`
Expected: PASS (all four tests).

- [ ] **Step 6: Run the full gate (suite + types + lint)**

Run: `pytest && mypy && ruff check .`
Expected: all pass. (mypy verifies `FakeKanbanFlowClient` and the real client both still satisfy `KanbanFlowClientLike` with the new method.)

- [ ] **Step 7: Commit**

```bash
git add skills/jared/scripts/lib/kanbanflow_provider.py tests/fake_kanbanflow.py tests/test_kanbanflow_provider.py
git commit -m "feat(jared): recently_closed reads board events for moves into Done (Phase 1a.3)"
```

---

### Task 4: Live verification on board `p9vK6cR` (verification folded into the phase)

This is a verification task, not TDD. It satisfies the spec's "each phase live-verifies on p9vK6cR before merge" and records the **event-retention** and **`from`/`to` format** observations that Phase 1c needs.

- [ ] **Step 1: Confirm `recently_closed` returns real data via the real client**

Run (token from `~/.secrets`, never printed):

```bash
source /home/brockamer/.secrets && python3 -c "
from skills.jared.scripts.lib.kanbanflow_client import KanbanFlowClient
from skills.jared.scripts.lib.kanbanflow_provider import KanbanFlowProvider
from skills.jared.scripts.lib.kf_number_index import KfNumberIndex
import tempfile, pathlib
c = KanbanFlowClient.from_env()
board = c.get_board()
# GTD column map for the test board (canonical Status -> board column name):
status_map = {'Backlog':'Planned One Day','Up Next':'Planned This Week','In Progress':'Doing Now','Blocked':'Blocked','Done':'Done'}
idx = KfNumberIndex(pathlib.Path(tempfile.mkdtemp())/'idx.json')
p = KanbanFlowProvider(client=c, board=board, field_defs=c.list_custom_field_defs(), index=idx, status_column_map=status_map)
print('recently_closed(60):', [(ci.number, ci.title, ci.closed_at) for ci in p.recently_closed(days=60)])
evs = c.get_board_events(limit=100, order='descending')
ts = sorted(e.timestamp for e in evs if e.timestamp)
print('event count:', len(evs), '| oldest:', ts[0] if ts else None, '| newest:', ts[-1] if ts else None)
"
```

Expected: a non-empty `recently_closed` list **iff** the board has a task that was moved into Done within 60 days (the probe saw `task=1eTJRipf` move `Doing Now → Done` on 2026-06-05). Record the oldest event timestamp as the **retention floor observation**.

- [ ] **Step 2: Confirm the `from`/`to` window format**

Run a windowed call and confirm server-side filtering works with ISO timestamps (the format `get_board_events` passes):

```bash
source /home/brockamer/.secrets && python3 -c "
from skills.jared.scripts.lib.kanbanflow_client import KanbanFlowClient
c = KanbanFlowClient.from_env()
narrow = c.get_board_events(from_ts='2026-06-05T13:20:00.000Z', to_ts='2026-06-05T13:21:30.000Z', order='descending')
print('windowed event count (expect a small subset):', len(narrow))
"
```

Expected: a strict subset of the full history. **If the count equals the full history**, the server ignores ISO `from`/`to` → record that `get_board_events` must rely on client-side timestamp filtering (already present in `recently_closed`) and note the format question for Phase 1c. **Either outcome is acceptable for this plan** — `recently_closed` already filters client-side defensively.

- [ ] **Step 3: Confirm the integration surface**

Run: `source /home/brockamer/.secrets && /home/brockamer/Code/jared/skills/jared/scripts/jared next-session-prompt` **against a KanbanFlow-backed `docs/project-board.md`** (the test board), and confirm the "Recently closed" section is now populated rather than empty.
Expected: at least the `1eTJRipf` close appears (or however the test board stands at run time).

- [ ] **Step 4: Record findings in the spec**

Append a short "Phase 1a live-verify (date)" note to `docs/superpowers/specs/2026-06-11-kanbanflow-parity-design.md` §11 capturing: the retention floor observed, whether ISO `from`/`to` filters server-side, and the next-session-prompt result. Commit:

```bash
git add docs/superpowers/specs/2026-06-11-kanbanflow-parity-design.md
git commit -m "docs(jared): record Phase 1a live-verify findings on p9vK6cR (Phase 1a.4)"
```

---

## Self-Review

**1. Spec coverage (against the §7 Phase 1 scope):**
- "events client method + `KfEvent`" → Tasks 1, 2. ✓
- "rewrite `recently_closed`" → Task 3. ✓
- "Done resolved via the Status column map" → Task 3 uses `_column_id_by_status['Done']`; Task 4 passes the GTD `status_map`. ✓
- "`{eventsLimited, events}` envelope + windowed paging" → Task 2. ✓
- "live-verify on p9vK6cR" → Task 4. ✓
- CLOSED_STATE flip, per-task createdAt/VELOCITY flip → **deliberately deferred** to Phase 1b/1c (stated in Scope). Not a gap — a scoping decision.

**2. Placeholder scan:** No "TBD"/"handle edge cases"/"similar to". Every code step shows complete code. `_provider`/`_move_event` helpers are defined inline. ✓

**3. Type consistency:** `get_board_events` signature is identical across the real client (Task 2), the `KanbanFlowClientLike` Protocol (Task 3), and `FakeKanbanFlowClient` (Task 3). `KfEvent`/`KfDetailedEvent`/`KfChangedProperty` field names (`property`, `old_value`, `new_value`, `task_id`, `detailed_events`, `timestamp`) are used consistently in parser, provider scan, and tests. `ClosedItem(number, title, closed_at)` matches `board_provider.py`. ✓

**Constraint check:** No new `@runtime_checkable BoardProvider` method is added (the atomic-coupling trap is avoided) — `recently_closed` already exists on the Protocol; only `KanbanFlowClient` gains a method (safe). ✓
