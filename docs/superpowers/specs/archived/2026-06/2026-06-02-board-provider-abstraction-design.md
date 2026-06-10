---
**Shipped in #313, #314 on 2026-06-10. Final decisions captured in issue body.**
---

# Board provider abstraction — Phase 1: interface extraction

**Issue:** #314 (Phase 1). Parent epic: #313.
**Date:** 2026-06-02
**Status:** Design — not yet started.
**Related references:** `skills/jared/scripts/lib/board.py`, `tests/conftest.py`, `CLAUDE.md` (§ "Dual import path", § "The `Board` helper"), `docs/project-board.md`.

## Context — the larger feature

The operator wants jared to steward **either** a GitHub Projects v2 board **or** a KanbanFlow board, selected per-project at `jared init`, with a clean migration path between them at any time. "Single source of truth" is preserved — it becomes *one* board per project, with a pluggable backend.

That feature decomposes into independent sub-projects, each with its own spec → plan → implementation cycle:

1. KanbanFlow API spike — *done* (findings frozen into Appendix A of this doc).
2. **Provider interface extraction ← THIS SPEC.** Behavior-preserving; GitHub as the first and only implementation; existing test suite as the safety net.
3. `KanbanFlowProvider` — implement the interface against a new REST client.
4. Init-time backend selection — `jared init` picks and persists the backend.
5. Migration command — `jared migrate`, with named, accepted lossiness.
6. Capability declaration + graceful degradation across slash-command/skill surfaces.

This spec covers **only Phase 2.** The KanbanFlow mapping (Appendix A) is included as a *constraints catalog* — it shapes the interface so it does not thrash when Phase 3 hits the live API — but no KanbanFlow implementation is designed here. The migration-fidelity and number-counter notes (Appendix A) are forward constraints, not Phase-1 deliverables.

## Problem

`skills/jared/scripts/lib/board.py` (~2,000 lines) is a GitHub-Projects passthrough, and the ~12 board subcommands in `skills/jared/scripts/jared` reach **straight through** it to `gh`/GraphQL, assembling GitHub-specific mutations inline. The real consumer surface, measured across the CLI and batch scripts, is dominated by low-level methods:

```
5  board.run_gh(          4  board.option_id(       4  board.field_id(
3  board.run_gh_raw(      3  board.open_items(      2  board.fetch_open_issues_for_ties(
2  board.add_existing_to_board(   1  board.run_graphql(   1  board.find_item_id(  …
```

There is **no semantic board interface** — only a thin gh passthrough plus ID lookups. A second backend cannot be slotted under something that does not exist. So Phase 1's job is to *create* that seam for the GitHub path we already have, changing **no behavior**.

## Goals

- Define a `BoardProvider` contract stated in **backend-neutral** terms, derived from what the subcommands actually *do* — not from GitHub's wire shape.
- Refactor today's `board.py` internals into a `GitHubProjectsProvider` that implements the contract, with `gh`/GraphQL/`field_id`/`option_id`/caching as **private** members.
- Make `Board` a thin facade: parse the convention doc → instantiate the configured provider → expose it.
- Introduce a `Capability` enum so commands can branch on backend feature-support instead of assuming GitHub.
- Keep `IssueRef` = the stable human integer (`#N`); the provider owns integer → internal-ID resolution.
- **Preserve every existing test** (`pytest -m 'not integration'` green throughout) — this is the de-risking premise and the extend-vs-fork evidence.

## Non-goals (Phase 1)

- **No KanbanFlow code.** No REST client, no `KanbanFlowProvider`. Appendix A is a constraints catalog only.
- **No `jared init` backend selection, no `jared migrate`.** Later phases.
- **No change to the repo/git axis.** PRs, worktrees, session locks, the wrap state-machine, plan archival, doc-sync/changelog gates are backend-independent and are **not** touched. They stay on git/GitHub regardless of board backend. (This axis split is the single biggest scope reducer — it roughly halves the surface.)
- **No new behavior, no new CLI flags, no doctrine changes.** Pure internal restructuring proven equivalent by the existing tests.
- **No capability *enforcement* yet** — the enum is defined and `GitHubProjectsProvider` advertises its full set, but command-level degradation logic lands in Phase 6.

## Architecture

### The two axes

Every jared concern is either **BOARD** (the kanban board itself) or **REPO/GIT** (the code repo). Only BOARD concerns get a provider; REPO/GIT is untouched.

- **BOARD → provider:** Status columns, Priority/Work-Stream/custom single-selects, issue body text, comments (session notes), labels, milestones, blocked-by, assignees, the open/closed notion, board reads (summary, ties, next-session-prompt, audit-fetch, dependency edges).
- **REPO/GIT → untouched:** branch/commit/PR/merge workflow, worktrees, `session-*.lock` files, `wrap-state`, `propose-partition`, plan/spec archival, PII pre-flight, token scrubbing.

### The `BoardProvider` contract

A `typing.Protocol` (structural, mypy-checked). Method set is derived from the real subcommand behaviors plus the read paths the research proved necessary (body read-modify-write, comment reads, label add/remove, milestone assignment, bulk edge fetch — all of which my first sketch omitted):

**Reads**
- `get_item(ref) -> BoardItem | None`
- `list_open_items() -> list[BoardItem]` — "open" is provider-defined (GitHub: open issue on board; KF: task not in Done column)
- `get_body(ref) -> str` / `list_comments(ref) -> list[Comment]`
- `fetch_ties(*, include_bodies) -> list[TieCandidate]`
- `fetch_blocked_by_edges() -> list[Edge]` — bulk, for the dependency graph and ties

**Writes (semantic, atomic where the subcommand guarantees atomicity)**
- `file(*, title, body, priority, status, labels, milestone, fields) -> BoardItem`
- `set_field(ref, field, value)` — Priority / Work Stream / custom single-selects
- `move(ref, status)` — distinct from `set_field`: Status is a *field* on GitHub but *structural* (the column) on KF, so it gets its own method
- `close(ref, *, comment=None)` — provider decides semantics (GitHub: close issue + verify Done; KF: move to Done column)
- `set_body(ref, text)` — for `capture-context.py`'s read-modify-write of `## Current state` / `## Decisions`
- `comment(ref, body)`
- `add_label(ref, name)` / `remove_label(ref, name)` — for the `session-N` lifecycle, applied long after filing
- `add_blocked_by(ref, blocker)` / `remove_blocked_by(ref, blocker)`
- `set_milestone(ref, name)` / `list_milestones() -> list[Milestone]`

**Introspection**
- `capabilities() -> frozenset[Capability]`

### Backend-neutral data types

Dataclasses that carry *only* portable data — never `PVTI_…` node-IDs or KF `_id`s:

- `IssueRef` — the stable integer handle (`#N`). The interface speaks this exclusively; the provider resolves it to its internal ID.
- `BoardItem` — `number`, `title`, `status`, `priority`, `body`, `labels`, `milestone`, `blocked_by`, `assignee`, plus a `fields: dict[str, str]` for custom single-selects.
- `Comment` — `body`, `author`, `created_at`.
- `Edge` — `(dependent: int, blocker: int)`.
- `Milestone` — `name`, `description`, `state`, `due` (last two may be empty on backends without the concept).
- `TieCandidate` — the fields the six analyzers consume (number, title, body, labels, milestone).

### `IssueRef` = integer; provider owns resolution

On GitHub, `#N` is the issue number → resolved to `node_id`. On KanbanFlow (Phase 3), `#N` is the task `number.value` → resolved to `_id` via a cached `number ↔ _id` index. Both already-hidden patterns: jared hides GitHub node-IDs behind `#N` today; KF is a second implementation of the same hiding. **No internal ID ever crosses the interface boundary.**

### `Capability` enum

Defined in Phase 1; advertised in full by `GitHubProjectsProvider`. Members anticipated from the research (Appendix A):

`MILESTONE_STATE` (open/close + due dates), `VELOCITY_TIMESTAMPS` (created/closed/transition times for velocity + aging), `NATIVE_DEPENDENCIES` (a real relation edge vs. a label-marker emulation), `MARKDOWN_BODY`, `CLOSED_STATE`, `MCP_TIER`, `SUB_ISSUES`.

`GitHubProjectsProvider` returns all of them. KanbanFlow (later) will omit several — see Appendix A.

### `Board` becomes a facade

`Board.from_default()` keeps its signature. Internally it parses the convention doc, reads the (Phase-4) backend selector — defaulting to `github` when absent, so existing boards are unaffected — and instantiates the matching provider. All the GitHub machinery (`run_gh*`, `run_graphql`, `field_id`, `option_id`, `board_items`, `invalidate_*`, ETag/REST, `graphql_budget`) moves **into** `GitHubProjectsProvider` as private members.

### Test-seam preservation (load-bearing)

"Existing tests stay green" is the entire de-risking premise — but it is **not free**, because of two facts recorded in `CLAUDE.md` and `tests/conftest.py`:

1. **Dual import path.** `from skills.jared.scripts.lib.board import Board` (tests) and `from lib.board import Board` (CLI) produce two distinct module objects. Patching anything defined *on* a class requires patching both, or refactoring so the sides converge.
2. **conftest patch targets.** `patch_gh`, `patch_gh_by_arg`, and `import_cli` monkeypatch specific functions. The module-level `run_gh`/`run_gh_raw`/`run_graphql` (which the helpers patch) currently live at module scope in `board.py`.

**Requirement:** the refactor keeps the module-level `run_gh`/`run_gh_raw`/`run_graphql` functions as the single subprocess seam, and `GitHubProjectsProvider` calls *through* them (as the current `Board` methods already delegate — see `board.py:385-393, 821-824`). Monkeypatching `subprocess.run` (what `patch_gh` ultimately leans on via the shared global `subprocess`) therefore keeps working unchanged. Any provider method that consumes `field_id`/`option_id` resolves them internally, but the *gh call itself* still flows through the module-level seam the tests patch. The spec's acceptance gate is: **`patch_gh` / `patch_gh_by_arg` / `import_cli` need no signature change, and the full unit suite passes untouched.** If a test *must* change, that is a behavior change in disguise — stop and surface it.

### The extend-vs-fork decision gate

If every `_cmd_*` rewrites to call only `BoardProvider` semantic methods with **zero** `gh`/GraphQL leakage, extend is vindicated and Phase 3 proceeds. If some command cannot be expressed without GitHub leaking through the interface, *that specific spot* is the documented, objective reason to reconsider a fork. Either outcome is a win; the refactor is the probe.

## Acceptance criteria

- A `BoardProvider` Protocol exists with the method set above; `GitHubProjectsProvider` implements it; `mypy --strict` passes.
- All GitHub-specific machinery is private to `GitHubProjectsProvider`; no `_cmd_*` references `run_gh`/`field_id`/`option_id`/`run_graphql` directly (grep proves zero leakage, or each remaining leak is itemized as fork-signal evidence).
- `Board` is a facade defaulting to the GitHub provider; existing call sites unchanged.
- `Capability` enum defined; GitHub provider advertises the full set. No enforcement yet.
- `pytest -m 'not integration'` passes with **no test-file changes** and **no conftest signature changes**.
- `ruff check .`, `ruff format .`, `mypy` all clean.

---

## Appendix A — KanbanFlow mapping (forward constraints, NOT Phase-1 work)

Frozen from the 2026-06-02 API + product research. These shape the interface so Phase 3 doesn't force a redesign. Source: <https://kanbanflow.com/api-docs> and sub-pages.

> **Corrected 2026-06-02 (Phase-2 wire verification — see
> `2026-06-02-kanbanflow-rest-client-design.md` § "Corrections to Appendix A"):**
> (1) KanbanFlow **does** auto-assign `number` when the field is omitted on a
> numbering-enabled board — so jared must *always* send an explicit `number.value`
> ("KF does not auto-increment" below is wrong; "no get-by-number endpoint" is confirmed).
> (2) Labels are objects `{name, pinned}` via per-task endpoints (case-sensitive),
> not a bare free-text string array.
> (3) Custom-field values **cannot** be set inline on task create — they need a
> separate per-field `POST /tasks/<id>/custom-fields/<id>` (so an "atomic file" is ≥2 calls).
> (4) Board structure (columns/swimlanes) is **read-only** via the API — it must pre-exist
> in the KanbanFlow UI (a Phase-4 `init` prerequisite).
> (5) Task update is `POST` (not PUT); validation errors surface as `403`; a custom-field
> *definition* is keyed `_id` while a task *value* references `customFieldId`; dropdown
> options have no id (option `text` is the key). Auth is confirmed **Bearer** (not Basic).

### Concept mapping

| jared concept | KanbanFlow representation |
|---|---|
| Status (5 columns) | board **columns** (`columnId`) — *structural*; `move()` not `set_field` |
| Priority / Work Stream / custom selects | **dropdown custom fields** (`customFieldId`, `dropdownOptions[].text`) |
| Issue body + `## sections` | task **`description`** (plain text; jared's section-parsing is text-based, round-trips) |
| Title | task **`name`** |
| Session notes | task **comments** (`text`, backdatable `createdTimestamp`) |
| Labels | task **`labels[]`** (free text, no registry, multi, case-sensitive by-name) |
| **Milestone** (theme-based) | **swimlane** (`uniqueId`, `name`, `description`); description = deliverable sentence. **Decision: milestone owns the swimlane axis; Work Stream → dropdown custom field.** |
| **blocked-by** | **label-marker emulation** `blocked-by:<N>` on the dependent + Blocked column. KF relations are **read-only via API** — native relations cannot be written. The dependency graph / cycle / inversion checks parse these labels via the number→id index. **Decision: operator-approved 2026-06-02.** |
| Assignee | `responsibleUserId` (single) + `collaborators[]` (multi); user-ID indirection |
| `#N` handle | task **`number.value`** — jared-assigned (KF does *not* auto-increment) |

### Capabilities KanbanFlow will omit (degrade gracefully under capability-based parity)

- `NATIVE_DEPENDENCIES` — emulated via labels (above).
- `MILESTONE_STATE` — swimlanes have no open/closed state or due date. jared's *dateless* milestone convention actually fits KF better than GitHub; the loss is milestone-close and date anchoring (used by `/jared-audit`, `/jared-reshape`).
- `VELOCITY_TIMESTAMPS` — the task object exposes no reliable created / moved-to-Done timestamp, so velocity, cycle-time, and aging flags degrade on KF.
- `MARKDOWN_BODY` — `description` is plain text; sections parse but don't render.
- `CLOSED_STATE` — no closed state; `close()` = move to Done column; "open" = not in Done.
- `MCP_TIER` — KanbanFlow is single-tier REST; the MCP-first guidance is GitHub-only.

### Two correctness/quota constraints for Phase 3

- **`#N` needs an authoritative counter, not a board scan.** KF has no "get task by number" endpoint and no auto-increment, so naïve "max existing + 1" means paginating every task in every column (including Done) on every `file` — against a **1,000 req/hr, token-locks-at-5,000/day** budget. Persist the counter in the `number ↔ _id` index (seeded once, maintained on create), and re-check uniqueness on create with retry-on-collision (the thin two-sessions-file-at-once race).
- **Call amplification.** The task object embeds `subTasks`/`labels`/`customFields`/`dates` (one `GET tasks?columnId=` returns most data), but **relations and comments are separate per-task calls**. A full board read must batch hard to stay inside the quota.

### Migration fidelity (Phase 5 forward note)

Because `number` is settable, **GitHub → KanbanFlow migration preserves `#N`** — `#312` stays `#312`, so cross-references, session history, and muscle memory survive. **KanbanFlow → GitHub cannot** (GitHub auto-assigns), so that direction renumbers — a named, documented lossiness. Other named losses: GitHub→KF drops native relation edges (→ label-markers) and the closed-state; KF→GitHub drops swimlane structure if not mapped back to milestones.
