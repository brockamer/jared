# KanbanFlow REST client — Phase 2 (#315)

**Issue:** #315 (Phase 2). Parent epic: #313. Consumed by: #316 (`KanbanFlowProvider`).
**Date:** 2026-06-02
**Status:** Design — approved; implementation in progress (session-2 worktree).
**Related references:** `docs/superpowers/specs/2026-06-02-board-provider-abstraction-design.md` (Phase 1 — see § "Corrections to Appendix A" below), `skills/jared/scripts/lib/board_provider.py`, `skills/jared/scripts/lib/github_provider.py`, `tests/test_github_provider.py`, `tests/conftest.py`, `CLAUDE.md` (§ "Dual import path", § "The `Board` helper").

## Context

Epic #313 makes jared's board backend pluggable (GitHub Projects v2 **or** KanbanFlow) behind the backend-neutral `BoardProvider` contract extracted in Phase 1 (#314). Every jared concern is either a **BOARD** concern (gets a provider) or a **REPO/GIT** concern (untouched). This phase lives entirely on the BOARD axis, *below* the provider.

This spec covers **only Phase 2: the KanbanFlow REST client** — the wire-level HTTP layer (auth, quota policy, typed resources, error mapping) that the Phase-3 `KanbanFlowProvider` (#316) will sit on. No semantic mapping is designed here; that is #316's job. The split is deliberate and mirrors the wire-vs-semantic boundary the Phase-1 spec drew.

The KanbanFlow API surface was verified by live research on 2026-06-02 (see § "Appendix B — Verified API reference"). That research **corrected several claims** frozen in the Phase-1 spec's Appendix A; those corrections are itemized below and must be propagated so #316 (whose body says *"Map per Appendix A of the design spec"*) does not inherit the errors.

## Scope & boundary

**In scope (Phase 2):**
- A stdlib-only (`urllib`) HTTP client, `KanbanFlowClient`, wrapping the verified KanbanFlow REST surface.
- Bearer authentication, a proactive request-quota budget + reactive `429` backoff, typed exceptions, JSON encode/decode.
- Typed per-resource methods returning **KanbanFlow-internal** dataclasses (carrying KF `_id`s).
- Per-process caching of quasi-static reads (`/board`, `/custom-fields`, `/users`).
- An offline unit-test suite that monkeypatches a single transport seam.

**Out of scope (→ #316, the provider):** all semantic mapping (columns→Status, dropdown custom field→Priority, swimlanes→milestones), the `number ↔ _id` index/counter, `blocked-by` label-marker emulation, the `BoardProvider` contract, capability declaration.

**Out of scope (→ later phases / non-goals):** `jared init` backend selection (#317), `jared migrate` (#318), capability enforcement (#319); any CLI wiring; KanbanFlow **subtasks** (the endpoints exist and are writable, but jared's board model does not use them); a live integration test as a *deliverable* (a deferred, opt-in integration test is described under Testing but is not required to close #315).

## Goals

- Give #316 a typed, quota-safe, fully unit-tested client so the provider can be written against a stable in-process surface, never against raw `urllib`.
- Keep jared's **zero-runtime-dependency** property: stdlib `urllib` only, no third-party HTTP library (the client runs under ambient Python at runtime; the `.venv` is dev-tooling only).
- Make every documented endpoint the provider will need reachable through one typed method, with KF `_id`s contained inside KF-internal dataclasses (no internal IDs leak to callers as bare values — they travel on typed objects).
- Be **offline-testable by construction**: the acceptance gate is `pytest -m 'not integration'` green with no network and no credential.

## Non-goals (Phase 2)

- No `KanbanFlowProvider`, no `BoardProvider` implementation, no neutral-dataclass mapping.
- No `number ↔ _id` index, no authoritative number counter, no `blocked-by` emulation — those are #316 semantic concerns.
- No CLI subcommand changes, no `init`/`migrate`, no capability enforcement.
- No subtasks wrapper.
- No live integration test as a closing requirement.

## Architecture

### Module layout

- **`skills/jared/scripts/lib/kanbanflow_client.py`** — the entire client: KF-internal dataclasses, the `KanbanFlowClient` class, the typed exception hierarchy, and the policy core.
- **One module-level transport seam:** `_raw_http(method: str, url: str, headers: dict[str, str], data: bytes | None) -> tuple[int, dict[str, str], bytes]` returning `(status, response_headers, body_bytes)`. This is the *only* code that calls `urllib.request.urlopen`. Everything else (auth header, JSON, budget, retry/backoff, error mapping) is pure logic above it.

This mirrors `board.py`'s module-level `run_gh`/`run_graphql` seam: tests monkeypatch the one function (here `_raw_http`, plus an injectable `_sleep`), exactly as the GitHub provider tests monkeypatch `subprocess.run` via `patch_gh`. No third-party imports anywhere in the module.

### Components — typed surface

**KF-internal dataclasses** (carry KanbanFlow `_id`s; they are *not* the neutral `BoardItem`/`Comment`/… types — the provider maps between them in #316):

- `KfBoard(id, name, columns: list[KfColumn], swimlanes: list[KfSwimlane])`
- `KfColumn(unique_id, name, description)`
- `KfSwimlane(unique_id, name, description)`
- `KfCustomFieldDef(id, name, field_type, dropdown_options: list[str], number_prefix: str | None)`  *(field_type ∈ {text, number, dropdown})*
- `KfTask(id, name, description, column_id, swimlane_id, number_value, number_prefix, responsible_user_id, collaborators: list[str], labels: list[KfLabel], custom_fields: list[KfCustomFieldValue], color, position)`
- `KfLabel(name, pinned)`
- `KfCustomFieldValue(custom_field_id, value: str | float)`
- `KfComment(id, text, created_timestamp, author_user_id)`
- `KfRelation(relation_type, related_task_id, related_task_name, related_task_board_id)`  *(relation_type ∈ {relatesTo, dependsOn, requiredBy}; read-only)*
- `KfUser(id, name)`

**Resource methods** (each maps to a verified endpoint — see Appendix B):

- *Structure (read-only, cached):* `get_board()`, `list_custom_field_defs()`, `list_users()`.
- *Tasks:* `list_tasks(*, column_id=None, column_name=None, swimlane_id=None, limit=None, start_task_id=None, order=None)` — unwraps the column-grouped response and follows the date-grouped `nextTaskId` cursor; `iter_all_tasks()` — paginate across columns; `get_task(task_id)`; `create_task(...)`; `update_task(task_id, **fields)` *(POST, not PUT)*; `delete_task(task_id)`.
- *Custom-field values:* `get_task_custom_fields(task_id)`; `set_task_custom_field(task_id, custom_field_id, value)` *(separate upsert; not settable inline on create)*.
- *Comments:* `list_comments(task_id)`; `add_comment(task_id, text, *, created_timestamp=None, author_user_id=None)` *(createdTimestamp backdatable)*.
- *Labels:* `list_labels(task_id)`; `add_label(task_id, name, *, pinned=False)`; `remove_label(task_id, name)` *(by-name, case-sensitive)*.
- *Relations (read-only):* `get_relations(task_id)`.

### Quota & retry policy (load-bearing)

KanbanFlow allows **1000 requests/hour per board** and **locks the API token after 5000 requests/day**. A token-lock is catastrophic — it removes the board for the rest of the day — so the policy is conservative by design:

- **Proactive budget gate** (mirrors the GraphQL budget gate from #49): track `X-RateLimit-Remaining` from each response. Before issuing a request, if the last-seen remaining is below a configurable floor, sleep until `X-RateLimit-Reset` (UTC epoch seconds). Track a per-process daily counter and **refuse with a typed error before approaching the 5000/day ceiling** rather than gamble against the lock.
- **Reactive `429` backoff:** on `429`, read `X-RateLimit-Reset`, sleep until then (capped), retry a bounded number of times, then raise `KanbanFlowRateLimitError`. (No `Retry-After` is documented; `X-RateLimit-Reset` is the only timing signal.)
- **Transient retry:** bounded exponential backoff on `500` / connection errors (the #112 retry ethos).
- **All sleeps go through an injectable `_sleep` hook** so tests never wait.

### Auth, config, caching

- `KanbanFlowClient(token: str, base_url: str = "https://kanbanflow.com/api/v1")`. Classmethod `from_env()` reads `KANBANFLOW_API_TOKEN` (a **jared-side convention**, not a KanbanFlow doc fact) and raises a clear typed error when unset, mirroring the gh token-scope diagnostics. Every request sends `Authorization: Bearer <token>`.
- Per-process cache for `/board`, `/custom-fields`, `/users` (quasi-static and quota-precious), with a `JARED_NO_CACHE` bypass — the same env switch the GitHub provider already honors. Task reads and all writes are never cached.

### Error handling — typed hierarchy

Mirrors `board.py`'s typed-exception convention. All parse the verified error body `{"errors":[{"message": "..."}]}` and surface the message:

- `KanbanFlowError` (base; also transport/JSON failures)
- `KanbanFlowAuthError` (`401` — missing/invalid token)
- `KanbanFlowForbiddenError` (`403` — refused; **validation failures surface here**, not 400/422)
- `KanbanFlowNotFoundError` (`404`)
- `KanbanFlowRateLimitError` (`429` / budget exhaustion)
- `KanbanFlowServerError` (`500`)

The provider (#316) / CLI will catch these and convert to non-zero exits with a human-readable stderr line, exactly as the gh side does today.

### Data flow

`KanbanFlowProvider` (#316, future) → `KanbanFlowClient` typed method → `_request(method, path, params, body)` *(auth + budget + retry + error mapping + JSON)* → `_raw_http` *(urllib)* → KanbanFlow API. Responses are parsed into KF dataclasses; the provider maps KF dataclasses ↔ neutral `BoardProvider` types.

### Test seam (load-bearing)

The unit suite is **offline by construction**, mirroring `tests/test_github_provider.py`:

- A `patch_kf` conftest helper (analog of `patch_gh`) monkeypatches the module-level `_raw_http` with a fake that returns canned `(status, headers, body)` and **records calls**; `_sleep` is patched to a no-op recorder.
- Tests assert on *which* endpoint/verb/body fired and on the returned dataclass shapes — never on a live response. Coverage includes: Bearer header present; budget gate sleeps when `Remaining` is low (assert `_sleep` called with the right delay); `429` → backoff → retry; each documented status → its typed exception (parsing `{"errors":[…]}`); date-grouped pagination cursor followed; `create_task`/`update_task` always send an explicit `number.value`; dropdown value written as `{value:{text}}`; labels via the per-task object endpoints; relations read-only.
- **Deferred, opt-in integration test (NOT a Phase-2 deliverable):** an analog of the existing `pytest -m integration` pattern (which hits `jared-testbed` via untracked `tests/testbed.env`) would exercise the client against a real board. It requires a **premium** KanbanFlow board and an API token supplied via env / an untracked file — **never committed** (this repo is public with secret scanning enabled). Tracked as a non-goal here; revisit at #316 or a full bake.

## Acceptance criteria

- `skills/jared/scripts/lib/kanbanflow_client.py` exists, **stdlib-only** (zero third-party imports), exposing the KF-internal dataclasses and `KanbanFlowClient` methods above.
- **All** network I/O flows through the single module-level `_raw_http` seam; no other call site imports or calls `urllib`.
- `from_env()` raises a clear typed error when `KANBANFLOW_API_TOKEN` is unset; every request carries `Authorization: Bearer <token>`.
- A proactive budget gate honors `X-RateLimit-Remaining`/`X-RateLimit-Reset` and refuses before the 5000/day ceiling; reactive `429` backoff retries off `X-RateLimit-Reset`; all sleeps are injectable.
- A typed exception exists for each documented status (`401/403/404/429/500`), each parsing `{"errors":[{"message"}]}`.
- `create_task` and `update_task` always send an explicit `number.value`; dropdown custom-field values are written by option **text**; labels go through the per-task `{name, pinned}` endpoints; relations are read-only.
- Static reads (`/board`, `/custom-fields`, `/users`) are cached per-process with a `JARED_NO_CACHE` bypass.
- Offline unit tests cover all of the above (monkeypatched `_raw_http`, patched `_sleep`, zero network); `pytest -m 'not integration'`, `ruff check .`, `ruff format .`, and `mypy --strict` are all clean.
- **Non-goals respected:** no `KanbanFlowProvider`, no semantic mapping, no `number ↔ _id` index, no CLI/init wiring, no subtasks wrapper.
- The Phase-1 spec's Appendix A is corrected (see below) **in this PR**.

## Corrections to Appendix A (Phase-1 spec) — MUST land in this PR

The 2026-06-02 wire research disproved or sharpened several frozen claims. Because #316's body says *"Map per Appendix A of the design spec,"* these corrections are propagated to the Phase-1 spec's Appendix A (patched, or annotated with a pointer to this spec) as part of this PR, so the provider phase does not inherit the errors:

1. **Task numbering — corrected.** Appendix A says "KF does NOT auto-increment." Reality: KanbanFlow **auto-assigns** a number when the `number` property is omitted *and* board numbering is enabled. jared must therefore **always send an explicit `number.value`** (or disable board numbering) to retain control. ("No get-task-by-number endpoint" is **confirmed** — number→task still needs a scan + index in #316.)
2. **Labels — corrected.** Not a free-text string array: labels are **objects `{name, pinned}`** managed via per-task endpoints (`GET/POST /tasks/<id>/labels`, `DELETE /tasks/<id>/labels/by-name/<NAME>`); names are **case-sensitive** (confirmed via the delete-by-name endpoint).
3. **Custom fields not inline on create — new constraint.** A task's custom-field values **cannot** be set on `create_task`; they require a separate `POST /tasks/<id>/custom-fields/<customFieldId>` (upsert). Any "atomic file" the provider replicates is therefore ≥2 calls.
4. **Board structure is read-only via API — new constraint.** Columns/swimlanes/board cannot be created or edited via the API; they must pre-exist in the KanbanFlow UI. (A `jared init` prerequisite for #317.)
5. **Naming & verbs — sharpened.** Update is **POST** `/tasks/<id>` (not PUT); validation failures surface as **403** (not 400/422); a custom-field **definition** is keyed `_id` while a task **value** references `customFieldId` (same value); the discriminator is `fieldType` (not `type`); dropdown options have **no id** — option `text` is the sole identifier (renaming an option orphans stored values); board structure calls the id `uniqueId` while tasks call it `columnId`/`swimlaneId`.
6. **Auth — confirmed (suspicion refuted).** Appendix A's "Bearer auth" is **correct**; the wire check (unauthenticated `401` carries no `WWW-Authenticate: Basic`) refutes any HTTP-Basic theory. (The server also accepts `?apiToken=` and a POST value, but Bearer header is canonical.)

## Appendix B — Verified KanbanFlow API reference (2026-06-02 research)

Source: <https://kanbanflow.com/api-docs> and sub-pages, plus a live unauthenticated wire check. High confidence unless a gap is noted.

- **Base URL / transport:** `https://kanbanflow.com/api/v1/`, HTTPS. One token = one board.
- **Auth:** `Authorization: Bearer <token>`. Token minted in a **premium** board → Settings → API & Webhooks.
- **Rate limits:** 1000 req/hr/board; **>5000/day locks the token**. Response headers `X-RateLimit-Limit`, `X-RateLimit-Remaining`, `X-RateLimit-Reset` (UTC epoch seconds). Throttle status `429`; **no `Retry-After`** documented.
- **Status codes:** `200`, `401` (bad/missing token), `403` (refused; validation errors land here), `404`, `429`, `500`. **Error body:** `{"errors":[{"message":"..."}]}`, `Content-Type: application/json`.
- **Board (read-only):** `GET /board` → `{_id, name, columns[], swimlanes[], colors[]}`; each column/swimlane `{name, uniqueId, description?}`.
- **Custom field definitions:** `GET /custom-fields` → `[{_id, name, fieldType: text|number|dropdown, dropdownOptions:[{text}], numberSettings:{prefix}}]`. (Definitions are writable via create/update/delete endpoints — not needed in Phase 2.)
- **Tasks:**
  - List: `GET /tasks?columnId=|columnName=|columnIndex=` (one required) `[&swimlaneId=…]` → array of column groups `{columnId, columnName, tasksLimited, tasks:[…]}`.
  - Get one: `GET /tasks/<id>`. **No get-by-number endpoint.**
  - Create: `POST /tasks`. Update: `POST /tasks/<id>`. Delete: `DELETE /tasks/<id>`.
  - Task fields: `_id, name, description, color, columnId, swimlaneId, position, number{value,prefix?}, responsibleUserId, collaborators[], totalSeconds*, pointsEstimate, groupingDate, dates[], subTasks[], labels[], customFields[], timeline`. Nested arrays are **omitted when empty**.
  - `number`: `{value, prefix?}`; settable on create/update; KF auto-assigns when omitted (numbering-enabled boards) — always send explicit `value`; `null` clears.
- **Custom-field values on a task:** `GET /tasks/<id>/custom-fields` → `[{customFieldId, value:{text}|{number}}]`; write `POST /tasks/<id>/custom-fields/<customFieldId>` body `{value:{text:"…"}}` (upsert). Dropdown matched by option **text**.
- **Comments:** `GET/POST /tasks/<id>/comments`; update `POST /tasks/<id>/comments/<id>`. `{_id, text, createdTimestamp (ISO-8601 UTC), authorUserId}`. `createdTimestamp` and `authorUserId` settable (backdatable; author overridable). Create returns `{taskCommentId}`.
- **Labels:** `GET/POST /tasks/<id>/labels`; `DELETE /tasks/<id>/labels/by-name/<NAME>` (case-sensitive). Label `{name, pinned}`; optional `insertIndex` ordering.
- **Relations (read-only):** `GET /tasks/<id>/relations` → `[{relationType: relatesTo|dependsOn|requiredBy, relatedTaskId, relatedTaskName, relatedTaskBoardId?}]`. No write endpoint.
- **Assignee:** `responsibleUserId` (single) + `collaborators[]` (array of `{userId}`); users via `GET /users`.
- **Pagination:** cursor-based, **only for date-grouped columns** (`tasksLimited`, `nextTaskId` → feed back as `startTaskId`; `limit` max 100 default 20; `order` asc/desc). Non-date-grouped columns return the whole column in one response.
- **Dates:** ISO-8601/RFC-3339; UTC `…Z` paired with `…Local` (offset); grouping dates `YYYY-MM-DD`.

**Open risks / gaps (flag in implementation):**
- Token-lock recovery (auto daily reset vs manual) is undocumented → treat 5000/day as a hard ceiling never to approach.
- Whether `429` responses carry the `X-RateLimit-*` headers / any `Retry-After` was not wire-confirmed → key backoff off `X-RateLimit-Reset` and degrade gracefully if absent.
- Whether `GET /tasks` inlines populated custom-field **values** per task, or only requires the per-task `/custom-fields` call, was not nailed down → the provider may need a per-task custom-fields fetch (call amplification to budget for).
- Label case-sensitivity is confirmed only on the delete endpoint; treat names as case-sensitive end-to-end.
