# KanbanFlowProvider — Phase 3: implement the BoardProvider contract over KanbanFlow

**Issue:** #316 (Phase 3). Parent epic: #313.
**Date:** 2026-06-03
**Status:** Design — approved, not yet started.
**Related references:** `skills/jared/scripts/lib/board_provider.py` (the contract), `skills/jared/scripts/lib/kanbanflow_client.py` (Phase 2, #315), `skills/jared/scripts/lib/github_provider.py` (the sibling implementation), `skills/jared/scripts/lib/board.py` (the facade — § "provider" property), `skills/jared/scripts/lib/cache.py` (disk-persistence idiom), `tests/test_github_provider.py` / `tests/test_kanbanflow_client.py` (test precedents), `docs/superpowers/specs/2026-06-02-board-provider-abstraction-design.md` (Phase 1 — Appendix A forward constraints), `docs/superpowers/specs/2026-06-02-kanbanflow-rest-client-design.md` (Phase 2 — § "Corrections to Appendix A").

## Context

Epic #313 makes jared's board backend pluggable (GitHub Projects v2 **or** KanbanFlow) behind the backend-neutral `BoardProvider` contract extracted in Phase 1 (#314), over the wire-level REST client built in Phase 2 (#315). Phase 3 is where the two meet: a `KanbanFlowProvider` that *implements* the contract by mapping each semantic board operation onto the Phase-2 client.

This is the keystone of the epic — every later phase depends on it. Phase 4 (#317, init-time backend selection) needs a provider to select; Phase 5 (#318, `jared migrate`) needs a provider to migrate *to*; Phase 6 (#319, capability degradation) needs a provider that *advertises* a reduced capability set. None of those are in scope here.

### What Phases 1 and 2 already settled

- **Phase 1** defined the contract (`board_provider.py`): `BoardProvider` Protocol, the neutral dataclasses (`BoardItem`, `Edge`, `Milestone`, `ClosedItem`), the `Capability` enum, and `IssueRef = int` (the stable human handle; the provider owns integer → internal-ID resolution). It made `Board` a facade whose `provider` property (`board.py:394`) instantiates the configured backend — and **currently raises for any backend other than `github`**. That raise is Phase 3's extension point.
- **Phase 2** built `KanbanFlowClient`: Bearer auth, quota/rate-limit gating (1000 req/hr, 5000/day token-lock guard), typed `Kf*` dataclasses, typed exceptions, and the per-resource methods this provider sits on. Its research **corrected** several Appendix-A claims (numbering, labels-as-objects, custom-fields-not-inline-on-create, read-only board structure, POST-not-PUT, 403-on-validation, Bearer auth). This spec is written against the *corrected* reality.

## Scope & boundary

**In scope:** one new module, `lib/kanbanflow_provider.py`, with `class KanbanFlowProvider` implementing every `BoardProvider` method; the `kanbanflow` branch of `Board.provider`; a small disk-backed `number ↔ _id` index; and one small extension to the Phase-2 client (`update_task` gains `swimlane_id` — see § "Client extension required").

**Out of scope (later phases):** `jared init` backend selection (#317), `jared migrate` (#318), capability *enforcement* across slash-command/skill surfaces (#319). This provider *advertises* its capability set; no caller branches on it yet. No batch-script (`sweep.py`, etc.) migration — those still use `Board`'s GitHub methods directly (the Phase-1 boundary), untouched here.

## Architecture

### Construction & wiring (mirror the GitHub side)

`GitHubProjectsProvider.__init__` takes keyword config parsed from `project-board.md` and reaches the wire via the module-level `run_gh*` seam. The KanbanFlow client is an **OO object** (`KanbanFlowClient.from_env()`), so `KanbanFlowProvider` takes its collaborators by **constructor dependency-injection**:

```python
KanbanFlowProvider(
    *,
    client: KanbanFlowClientLike,         # structural Protocol — see below
    board: KfBoard,                       # columns + swimlanes (read-only structure)
    field_defs: list[KfCustomFieldDef],   # custom-field definitions (Priority, Work Stream, …)
    index: KfNumberIndex,                 # number ↔ _id store (below)
)
```

`Board.provider` gains a `kanbanflow` branch: build the client via `from_env()`, call `get_board()` + `list_custom_field_defs()` once to resolve structure, construct the index, and cache the provider (same lazy-singleton shape as the GitHub branch).

DI is deliberate: it makes the unit-test seam a **faked in-memory client** (see § "Testing") rather than HTTP-level patching, and keeps the provider's logic — pure mapping — testable in isolation. The `client` parameter is typed against `KanbanFlowClientLike` — a **consumer-owned `typing.Protocol`** (defined in `kanbanflow_provider.py`) declaring only the ~11 client methods the provider calls. Both the production `KanbanFlowClient` and the in-memory test fake satisfy it structurally, so the fake injection type-checks under `mypy --strict` without any nominal base class. (Interface segregation: the provider depends on the narrow surface it uses, not the whole client.)

### Name → internal-ID resolution (resolved once, cached in-process)

The interface speaks names (`"In Progress"`, `"High"`, a milestone name); KanbanFlow speaks IDs. The provider builds three lookup maps at construction from the already-fetched structure:

| jared name | resolves to | source |
|---|---|---|
| Status column (`Backlog`/`Up Next`/`In Progress`/`Blocked`/`Done`) | `KfColumn.unique_id` | `board.columns` |
| Priority / Work Stream / custom single-select | `KfCustomFieldDef.id` + option `text` | `field_defs` (option is matched by `text`; KF dropdown options have no id) |
| Milestone | `KfSwimlane.unique_id` | `board.swimlanes` |

Unknown name → raise the same typed errors the GitHub provider raises (`FieldNotFound` / `OptionNotFound` analogues), so the CLI's existing catch-and-exit behavior is preserved across backends. The KF board's columns/swimlanes/custom-fields **must pre-exist** with the canonical names (board structure is read-only via the API — a Phase-4 `init` prerequisite, surfaced here, not built here).

### The number ↔ _id index (`KfNumberIndex`)

KanbanFlow has **no get-task-by-number endpoint** (confirmed in Phase-2 research), and `create_task` **requires** an explicit `number_value`. So jared owns `#N` allocation and must persist a `number → _id` map for resolution. Because the `jared` CLI runs as **one-shot processes** (the reason `cache.py` exists as a cross-process disk layer), this map must live on disk — an in-memory map would rebuild via a full board scan on every invocation, the exact per-call quota hit Appendix A warns against.

**Storage.** JSON at `<cache_dir>/kf-index-<board_id>.json`, written with the `cache.py` atomic-rename idiom (`.tmp` sibling + `os.replace`). Keyed by KanbanFlow **board id** (KF has no GitHub `project_number`). Payload: `{ "numbers": { "<N>": "<task_id>", … } }`.

**Operations.**
- `resolve(N) -> task_id | None` — map lookup; on miss, **reseed via a full `iter_all_tasks()` scan** (each `KfTask` carries `number_value`), persist, retry. The index is therefore *rebuildable* — a lost or corrupt file costs one scan, not correctness.
- `next_number() -> int` — `max(existing numbers, default 0) + 1`, scanning once to seed if the index is empty/cold.
- `record(N, task_id)` — persist a new mapping after a successful `create_task`.

**Concurrency — document-and-accept (operator decision, 2026-06-03).** Two concurrent `jared file` calls could both compute `max+1` and assign the same `#N` (last-writer-wins on the index). This is a vanishingly thin race on a solo, single-host tool, and a reseed scan + manual renumber repairs it. No file locking. This is a documented, accepted lossiness — *not* an oversight.

### Method-by-method mapping

Every `BoardProvider` method, its KanbanFlow realization, and call count:

| Contract method | KanbanFlow realization |
|---|---|
| `get_item(ref)` | `index.resolve(ref)` → `client.get_task(id)`; `KfTask` already carries labels/custom-fields/swimlane/description, so **one call**. `blocked_by` parsed from `blocked-by:<N>` labels (no relations call). `priority`/`fields` mapped from `custom_fields` via `field_defs`. Returns `BoardItem(provider_ref=task_id)`. Missing → `None`. |
| `list_open_items()` | `client.iter_all_tasks()` minus the Done column ("open" = not in Done). Each `KfTask` → `BoardItem`. |
| `get_body(ref)` | resolve → `get_task().description`. |
| `fetch_blocked_by_edges()` | `iter_all_tasks()`; for each task parse `blocked-by:<N>` labels → `Edge(dependent=task.number_value, blocker=N)`. |
| `recently_closed(days)` | **`[]`.** KF exposes no reliable moved-to-Done timestamp (`VELOCITY_TIMESTAMPS` omitted). Documented degradation; Phase 6 gates callers on the capability. |
| `validate_fields(priority, status, fields)` | check `status` ∈ columns, `priority` ∈ Priority options, each `(field, value)` ∈ defs; raise on miss. |
| `file(title, body, priority, status, labels, milestone, fields)` | `index.next_number()`; resolve status → `columnId` and milestone → swimlane `uniqueId` (via § "Name → internal-ID resolution"); `client.create_task(name=title, column_id=<resolved status>, number_value=N, swimlane_id=<resolved milestone>, description=body, labels=…)` → per-field `client.set_task_custom_field(...)` for Priority + Work Stream + each `fields` entry → `index.record(N, id)`. **On any post-create failure: `client.delete_task(id)` then re-raise** (preserve "no half-filed item"). Returns `BoardItem`. |
| `add_to_board(ref, …)` | KanbanFlow has no off-board tasks (a task *is* on a board). Semantics: ensure the existing task carries the given status/priority/fields/labels — i.e. `move` + `set_field`(s) + label adds. |
| `set_field(ref, field, value)` | **`field == "Status"` → delegate to `move` (structural column change).** The CLI drives Status changes through `set_field` — `jared move` → `_cmd_move` → `_cmd_set` → `set_field(ref, "Status", …)`, and the advertised `jared set N Status` — mirroring the GitHub provider where `move()` *is* `set_field("Status")`. Any other field → resolve → `customFieldId`, value → option `text`; `client.set_task_custom_field(id, customFieldId, value)`. |
| `move(ref, status)` | resolve status → `columnId`; `client.update_task(id, column_id=…)`. (Also the target of `set_field`'s `"Status"` branch above.) |
| `close(ref, comment=None)` | if `comment`: `client.add_comment(id, comment)`; then `client.update_task(id, column_id=Done)`. ("Closed" = in Done; `CLOSED_STATE` omitted.) |
| `set_body(ref, text)` | `client.update_task(id, description=text)`. |
| `comment(ref, body)` | `client.add_comment(id, body)` → returns the comment id (the client already returns `str`). |
| `add_label(ref, name)` / `remove_label(ref, name)` | `client.add_label` / `client.remove_label` (case-sensitive by name). |
| `add_blocked_by(ref, blocker)` / `remove_blocked_by(ref, blocker)` | add / remove the `blocked-by:<blocker>` label (KF relations are read-only via API → label-marker emulation). Status stays a separate `move()` to Blocked. |
| `set_milestone(ref, name)` | resolve name → swimlane `uniqueId`; `client.update_task(id, swimlane_id=…)`. **Requires the client extension below.** |
| `list_milestones()` | `board.swimlanes` → `Milestone(name, description, state=None, due=None)` (no swimlane state/dates; `MILESTONE_STATE` omitted). |
| `capabilities()` | the reduced frozenset (below). |

### Client extension required

`KanbanFlowClient.update_task` (Phase 2, `kanbanflow_client.py:461`) accepts `name`/`column_id`/`number_value`/`description`/`color`/`responsible_user_id` but **not `swimlane_id`**. `set_milestone` cannot move a task between swimlanes without it. Phase 3 extends `update_task` with a `swimlane_id: str | None = None` parameter (mapped to the `swimlaneId` body field), with a unit test. This is a small, justified addition — the provider is the client's first real consumer, and the contract demands swimlane assignment. No other client change is needed.

### Capabilities advertised

`GitHubProjectsProvider` advertises the full `Capability` set. `KanbanFlowProvider` advertises the full set **minus** the six Appendix-A omissions — `NATIVE_DEPENDENCIES`, `MILESTONE_STATE`, `VELOCITY_TIMESTAMPS`, `MARKDOWN_BODY`, `CLOSED_STATE`, `MCP_TIER` — **and also `SUB_ISSUES`** (KF `subTasks` are checklist items, not numbered sub-issues with their own `#N`; advertising native sub-issue support would be misleading). The result is **`frozenset()`** — KanbanFlow supports only the core board loop, with every richer feature degrading gracefully. This is the data Phase 6 will branch on; Phase 3 only declares it.

### Error mapping

The client raises typed `KanbanFlow*` exceptions (`KanbanFlowAuthError`, `KanbanFlowForbiddenError` for 403/validation, `KanbanFlowNotFoundError`, `KanbanFlowRateLimitError`, `KanbanFlowServerError`). The provider lets these propagate where the contract is silent, and converts to the contract's neutral exceptions (`ItemNotFound`, `FieldNotFound`, `OptionNotFound` analogues) where a CLI subcommand catches them — so the CLI's existing "catch → non-zero exit + human-readable stderr" behavior is identical across backends. No `Kf*` exception type crosses the contract boundary into `_cmd_*` code.

## Testing & verification ceiling

**Unit tests** (`tests/test_kanbanflow_provider.py`): a **faked in-memory `KanbanFlowClient`** injected via the constructor, holding tasks/labels/custom-fields/comments in dicts. Tests mirror `tests/test_github_provider.py`'s structure — one test per contract method plus the cross-cutting invariants (`file` rollback-on-failure, `#N` allocation + index round-trip, `blocked-by` label emulation, capability set, status-vs-field distinction for `move`). `KfNumberIndex` gets its own tests against a `tmp_path` cache dir (round-trip, scan-on-miss reseed, next-number).

**Verification ceiling (stated, not papered over).** No live KanbanFlow testbed exists — `tests/testbed.env` targets a real GitHub project only. Phase 3 is therefore verified **offline**: faked-client unit tests, `mypy --strict` structural conformance to the `BoardProvider` Protocol (`runtime_checkable` + an explicit isinstance/typed assignment test), and `ruff`. **Live-API verification is explicitly deferred** to the first real KanbanFlow board / Phase-4 `init` — it is *not* claimed here. This matches the ceiling Phase 2 shipped under and respects the deferred-verification-as-drift discipline: the gap is named in the acceptance criteria, not implied-then-skipped.

## Acceptance criteria

- `lib/kanbanflow_provider.py` defines `KanbanFlowProvider` implementing **every** `BoardProvider` method; `mypy --strict` confirms structural conformance (the Protocol is `runtime_checkable`; a typed-assignment/isinstance test asserts it).
- `Board.provider` returns a `KanbanFlowProvider` when `backend: kanbanflow`, constructed via `KanbanFlowClient.from_env()` + resolved board structure; the GitHub branch is unchanged.
- `KfNumberIndex` persists `number ↔ _id` on disk (atomic-rename, keyed by board id), with scan-on-miss reseed and `next_number()`; the concurrent-`file` race is document-and-accept (no locking).
- `file()` is best-effort-atomic: on any post-`create_task` failure the orphan task is `delete_task`d and the error re-raised.
- `KanbanFlowClient.update_task` accepts `swimlane_id`, with a unit test.
- `capabilities()` returns `frozenset()` (the six Appendix-A omissions plus `SUB_ISSUES`).
- Degradations are explicit and tested: `recently_closed` → `[]`; `list_milestones` → `state`/`due` `None`; `blocked_by` via `blocked-by:<N>` labels.
- `tests/test_kanbanflow_provider.py` passes against a faked client; full `pytest -m 'not integration'` stays green. **One existing test must change:** `tests/test_board.py::test_board_provider_unknown_backend_raises` currently uses `backend: kanbanflow` as its "unimplemented backend" case and asserts `board.provider` raises `BoardConfigError` — Phase 3 makes that case *return* a `KanbanFlowProvider`, so the test is updated (assert a `KanbanFlowProvider` is returned, and/or re-point the raise-assertion at a still-unimplemented backend value). **Conftest signatures are unchanged** (the KF provider's test seam is constructor-injected — a faked in-memory client — not the module-level `run_gh` seam the GitHub side patches; `patch_kf` already exists). `ruff check .`, `ruff format .`, `mypy` all clean.
- **Verification ceiling acknowledged in the PR:** offline only (faked-client + `mypy --strict`); live-API verification deferred to the first real KanbanFlow board / Phase-4 `init`.

## Non-goals (Phase 3)

- No `jared init` backend selection (#317) and no creation/editing of KanbanFlow board structure (read-only via API — a Phase-4 prerequisite).
- No `jared migrate` (#318); no `number`-preserving cross-backend mechanics beyond what `file` needs locally.
- No capability *enforcement* — no `_cmd_*` or batch script branches on `capabilities()` yet (#319).
- No batch-script (`sweep.py`/`stage.py`/ties) migration off `Board`'s GitHub methods — the Phase-1 boundary stands.
- No change to the repo/git axis (PRs, worktrees, session locks, wrap state-machine, plan archival).
