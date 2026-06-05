# Phase 4 — Init-time backend selection (design)

Epic #313 ("Make jared board-backend-agnostic"), Phase 4 of 6. Issue #317.

Predecessors (shipped): Phase 1 (#314, `BoardProvider` extraction), Phase 2 (#315,
KanbanFlow REST client), Phase 3 (#316, `KanbanFlowProvider`). This phase makes the
backend **selectable at init** and makes a KanbanFlow-backed `docs/project-board.md`
**parse**. Phases 5 (#318, `jared migrate`) and 6 (#319, capability declaration) are
unblocked by this one and run in parallel after it lands.

## Problem

The plumbing to steward a KanbanFlow board exists end-to-end (verified this session:
the Phase 2/3 client reads the operator's live board `Jared Test` / `p9vK6cR`
cleanly). But there is **no way to choose KanbanFlow**, and two concrete blockers
stand between "the provider works" and "a project runs on it":

1. **`jared init` is GitHub-only.** `bootstrap-project.py` requires `--url` (a GitHub
   Project URL) and its `main()` immediately calls `parse_url()` then GraphQL field
   introspection. There is no `--backend` switch and no KanbanFlow bootstrap path.

2. **A KanbanFlow doc cannot parse — chicken-and-egg.** `Board._parse`
   (`lib/board.py`) reads the `backend` selector at the **end** (line ~195), *after*
   it hard-requires the GitHub fields `Project URL / Project ID / Project number /
   Owner` (line ~180). So a doc that says `- backend: kanbanflow` and omits the
   GitHub Project identifiers raises `BoardConfigError` before `backend` is ever read.

3. **Real boards don't use jared's column names.** The provider maps Status → column
   by **exact name** (`{column.name: column.unique_id}`), but the operator's board has
   GTD-style columns (`Maybe Never?`, `Planned One Day`, `Planned This Week`, `Will
   Do Today`, `Doing Now`, `Blocked`, `Done`). Only `Blocked` and `Done` match
   canonical. Forcing a rename is hostile; the board structure is also **read-only via
   the API** (Phase-1 Appendix A, frozen 2026-06-02), so jared cannot create/rename
   columns even if it wanted to. The board must be adapted to via a **mapping**, not a
   mutation.

## Goals

- Add `--backend github|kanbanflow` to `bootstrap-project.py` (default `github`), with
  an interactive prompt fallback, mirroring the `--yes`/`--work-streams` non-interactive
  pattern from #268. `/jared-init` selects/asks.
- Give the KanbanFlow path a **read-only bootstrap**: connect via env token, fetch the
  live columns + custom-field defs, **auto-map** exact name matches, **interview** the
  operator for the rest, **warn** on what can't be mapped (unmapped columns, missing
  `Priority` field, absent swimlanes), and write a slim KanbanFlow-shaped doc.
- Make `Board._parse` **backend-aware**: read `backend` first, then apply
  backend-specific required-field validation. KanbanFlow requires `Repo` + a Status
  column map; not the GitHub Project identifiers.
- Teach `KanbanFlowProvider` a `status_column_map` (canonical Status → board column
  name), defaulting to identity so a canonically-named board needs no map.
- Preserve every existing GitHub-doc test green; add KanbanFlow-doc parse/provider tests.
- Verify end-to-end against the operator's live board.

## Non-goals (Phase 4)

- **No board-structure creation.** Columns and swimlanes are read-only via the API
  (Appendix A). Missing structure is **validated and guided**, never created. The user's
  "offer to create" intent is honored only where the API allows it — which, for board
  structure, is nowhere. Mapping replaces creation.
- **No Priority-field creation, no Priority name/value mapping.** A `Priority` dropdown
  with `High/Medium/Low` is *validated*; if absent or mis-optioned, bootstrap guides the
  operator to fix it in the KanbanFlow UI. The field must be named `Priority` with
  canonical options (the provider resolves it by exact name and validates the option).
  Mapping a differently-named Priority field is a deliberate future extension, not this
  phase.
- **No swimlane / milestone mapping.** The board has no swimlanes; `MILESTONE_STATE` is
  an already-declared KanbanFlow degradation. Bootstrap notes it; milestone-on-KF support
  is out of scope here.
- **No number-index work.** `KanbanFlowProvider` self-seeds the `number ↔ _id` index
  lazily (`_ensure_seeded`/`_reseed_index`, persisted to `cache_dir/kf-index-<board>.json`
  outside the repo). Bootstrap touches none of it.
- **No migration** (`jared migrate` is Phase 5 / #318) and **no capability enforcement**
  across slash-command surfaces (Phase 6 / #319). The KanbanFlow provider already
  advertises its reduced capability set; Phase 4 only makes the board selectable and
  parseable.
- **No change to the repo/git axis.** PRs, worktrees, session locks, wrap-state, plan
  archival are backend-independent and untouched (Phase-1 axis split).

## Architecture

### Piece A — init-time selection

`bootstrap-project.py`:

- Add `--backend {github,kanbanflow}` (default `github`). When omitted and the session is
  interactive, prompt (`prompt_*` machinery, like `prompt_work_streams`); `--yes` defaults
  to `github` for non-interactive runs.
- Make `--url` **conditionally required**: required for `github`; passing it with
  `--backend kanbanflow` is a hard argparse error (a KanbanFlow board has no GitHub
  Project URL — it's selected by the board-scoped token), not a silent no-op. `--repo`
  stays **required for both** (the git/PR axis is backend-independent).
- Branch `main()` at the top: `github` keeps today's GraphQL-introspection path verbatim;
  `kanbanflow` enters the new bootstrap path below and never calls `parse_url`/`fetch_fields`.

`/jared-init` stub (`commands/jared-init.md`): ask which backend on a fresh project (voice
ON for the question, per the stub's first-impression rule), then invoke
`bootstrap-project.py --backend <choice> --repo <owner>/<repo> [--url <project-url>]`.
Script output stays voice-OFF / verbatim, including the interview prompts.

### Piece B — KanbanFlow bootstrap (read-only)

New path in `bootstrap-project.py`, all reads (no board writes):

1. **Connect.** `KanbanFlowClient.from_env()` (reads `KANBANFLOW_API_TOKEN`; errors with
   guidance if unset). The token is board-scoped, so the token *is* the board selector.
2. **Fetch** `client.get_board()` (columns, swimlanes, board id/name) and
   `client.list_custom_field_defs()`.
3. **Auto-map** canonical Status → column where the column name matches exactly
   (`Blocked`, `Done` on this board).
4. **Interview** for each unmapped canonical Status, offering the board's remaining
   columns as choices:
   > `Which column is "Up Next"?  [1] Maybe Never?  [2] Planned One Day  [3] Planned This Week  [4] Will Do Today  [5] Doing Now`
   Each canonical Status maps to **exactly one** column (the write target). `--yes`
   short-circuits the interview only when every Status auto-mapped; otherwise a
   non-interactive run with unmapped Statuses fails with the list of what needs mapping.
5. **Warn** (precise, actionable — the "guide the user" intent):
   - Leftover columns not chosen for any Status:
     `NOTE: columns not mapped to a jared Status — items there are invisible to jared: Maybe Never?, Will Do Today`
   - Missing/mis-optioned Priority field (validated by reading the field def's
     `dropdown_options: list[str]` — the same attribute the provider's `_check_option`
     enforces at write time, so bootstrap validates exactly what the provider requires):
     `WARNING: no 'Priority' custom field with options High, Medium, Low. jared requires it. Create a dropdown custom field named 'Priority' (options: High, Medium, Low) at https://kanbanflow.com/board/<id> → Settings → Custom fields, then re-run.`
   - Absent swimlanes:
     `NOTE: no swimlanes on this board — milestones (which map to swimlanes) are unavailable; jared's dateless milestone convention degrades gracefully.`
6. **Write** the slim doc (see *Doc format* below). Missing Priority is a **hard stop**
   (exit non-zero, no doc written) because jared requires Priority; unmapped leftover
   columns and absent swimlanes are **soft** (doc still written).

### Piece C — backend-aware parse + provider

**`Board._parse` reordering (correctness-critical, test-guarded):**

- Parse `backend` from `## Jared config` **before** the required-field gate.
- Split required-field validation by backend:
  - `github` (default): unchanged — `Project URL / ID / number / Owner / Repo`.
  - `kanbanflow`: require `Repo` and a non-empty Status column map; derive `owner` from
    `repo.split("/")[0]`; `Project URL / ID / number` are **not** required (left `None`/
    unused — they are GitHub-provider construction args only).
- Parse the Status column map (new `### Status column map` block) into a
  `status_column_map: dict[str, str]` field on `Board`. A dedicated parser
  (`_parse_status_column_map`) reads it; the generic `_parse_field_blocks` tolerates the
  block's presence (it is only consulted for the GitHub provider's field/option IDs, which
  a KanbanFlow doc does not carry).
- Record board identity for KanbanFlow: `Board ID`, `Board name`, `Board URL` bullets
  (human reference + safety check below).

**`KanbanFlowProvider` — route *all* status↔column translation through the map.**

The constructor gains `status_column_map: dict[str, str] | None = None` (canonical Status →
board column name). The map must be applied **at construction**, not bolted onto one or two
methods — every place the provider translates between a Status name and a column is a site,
and missing one silently breaks open/closed detection. Today's lookup dicts are keyed by raw
board column name (`{c.name: c.unique_id}`); rebuild them **canonical-Status-keyed** so all
existing call sites become map-aware for free:

- `_column_id_by_status = {status: column_unique_id}` — built by resolving each canonical
  Status through the map (identity fallback) to its board column. `_column_id(status)` and
  the default-`"Backlog"` write path (line ~284) read this.
- `_status_by_column_id = {column_unique_id: status}` — the inverse, used by `_item_from_task`
  (line ~172) to report a task's Status. A task in an **unmapped** column (e.g. `Maybe
  Never?`) has no entry → reports `None` Status, which is exactly why bootstrap warns those
  items are invisible.

**Enumerated sites that must use the map-applied dicts** (grep `kanbanflow_provider.py`):
`__init__` dict construction (105–106); `_column_id` (118–123); `_item_from_task` Status
report (172); **`list_open_items` Done-detection (224) — currently a hardcoded
`_column_id_by_name.get("Done")` that bypasses any map**; the default-`"Backlog"` write
(284); `close()` → `_column_id("Done")` (351). All resolve correctly once the dicts are
Status-keyed. Swimlane dicts (107–108, 176) are **not** remapped — milestones are out of
scope this phase (no swimlanes on the board).

- `Board.provider` passes the parsed `status_column_map` into the constructor.
- **Board-identity soft verify:** `Board._parse` records the doc's `Board ID`;
  `Board.provider` passes it to the constructor as `expected_board_id`. On construction
  the provider compares the live `board.id` to `expected_board_id`; on mismatch it emits a
  warning (the token points at a different board than the doc describes — a real footgun)
  but does not hard-fail (the token is authoritative; the doc may be stale). When
  `expected_board_id` is absent (e.g. a hand-written doc) the check is skipped.

### Doc format (KanbanFlow)

Concrete shape for the operator's board (machine-readable bullets first, narrative after,
mirroring the GitHub doc's contract):

```markdown
# Project Board — How It Works

- Backend: kanbanflow
- Board URL: https://kanbanflow.com/board/p9vK6cR
- Board ID: p9vK6cR
- Board name: Jared Test
- Repo: brockamer/jared

### Status column map
- Backlog: Planned One Day
- Up Next: Planned This Week
- In Progress: Doing Now
- Blocked: Blocked
- Done: Done

### Priority
- Field name: Priority
- Options: High, Medium, Low

## Jared config
- backend: kanbanflow
- voice: enabled
```

Notes:
- The token is **never** written to the doc. Auth is via `KANBANFLOW_API_TOKEN` in the
  environment; the doc carries a one-line reminder of this in its narrative section.
- `- backend: kanbanflow` appears under `## Jared config` (where `Board._parse` reads it
  today). The top-of-file `- Backend:` bullet is human-facing redundancy; the parsed
  source of truth is the `## Jared config` bullet, unchanged from Phase 1.
- The GitHub field/option-ID blocks (`### Status` with `OPTION_…`, `### Priority` with
  option ids) are **absent** — a KanbanFlow board resolves columns and field options live.
- The `### Priority` block shown above is **human-facing documentation only** — it is *not*
  machine-parsed in Phase 4 (the provider resolves the field by the hardcoded name
  `Priority` and validates the option live). It is included so a person reading the doc
  knows the board contract; per CLAUDE.md's "don't parse a field nothing reads" rule, no
  parser consumes it. If a future phase adds Priority name-mapping, this block becomes its
  source of truth.

## Data flow

```
/jared-init  ──asks──▶  bootstrap-project.py --backend kanbanflow --repo o/r
                              │
                              ├─ KanbanFlowClient.from_env()  (KANBANFLOW_API_TOKEN)
                              ├─ get_board() + list_custom_field_defs()
                              ├─ auto-map exact + interview operator
                              ├─ validate Priority (hard) / warn unmapped+swimlanes (soft)
                              └─ write docs/project-board.md  (slim KF shape)

jared <any board cmd>  ──▶  Board.from_default()
                              ├─ _parse: read backend FIRST
                              ├─ backend==kanbanflow → require Repo + status map
                              ├─ parse status_column_map
                              └─ .provider → KanbanFlowProvider(status_column_map=…)
                                              └─ _column_id(status)=map→name→id
```

## Testing & verification

**Unit (offline, must stay the default suite):**
- `Board._parse` backend-aware gate: a KanbanFlow doc (no GitHub Project fields) parses;
  a KanbanFlow doc missing `Repo` or the Status map fails with a clear message; **every
  existing GitHub-doc test stays green, no conftest signature change** (Phase-1 gate — if
  a GitHub test must change, that is a regression to surface, not absorb).
- `_parse_status_column_map`: round-trips the example block; tolerates `Blocked`/`Done`
  identity rows; rejects a malformed/empty map.
- `KanbanFlowProvider` with a `status_column_map` via `FakeKanbanFlowClient`, using a
  **non-identity Done mapping** (e.g. a fake board where `Done` maps from a column named
  `Complete`): `move` writes the mapped column id; `get_item` reports the mapped Status;
  **`list_open_items` correctly excludes tasks in the mapped Done column** (this is the
  regression guard — an identity `Done`→`Done` fake would pass even with the map unwired,
  so the test *must* use a renamed Done); an item in an unmapped column reports `None`
  Status. Also cover the default-identity construction (no map) to prove canonically-named
  boards are unaffected.
- Bootstrap KanbanFlow path with `FakeKanbanFlowClient` + mocked `input()`: auto-maps
  exact matches, interviews for the rest, hard-stops on missing Priority, writes the
  expected doc; board-id mismatch warns.

**Live end-to-end (operator's board, token available this session):**
- Run bootstrap against `p9vK6cR`, complete the interview, write the doc.
- Run a real `jared file → move → summary → close` cycle against the live board; confirm
  the task lands in the mapped columns and `#N` numbering works.
- **Cleanup:** delete the test task afterward; note the `cache_dir/kf-index-p9vK6cR.json`
  index file is created outside the repo (no commit).
- **Worktree caveat:** run the **worktree-resident** `jared` script
  (`/home/brockamer/Code/jared-317/skills/jared/scripts/jared`), not the main-repo one —
  the main script always imports the main repo's `lib/board.py` regardless of CWD.

## Acceptance criteria

- `bootstrap-project.py --backend kanbanflow --repo <o/r>` connects via the env token,
  maps Status columns (auto + interview), validates Priority (hard-stop if absent), warns
  on unmapped columns + absent swimlanes, and writes a KanbanFlow-shaped
  `docs/project-board.md`. `--backend github` is unchanged and default.
- `Board.from_default()` parses a KanbanFlow doc: `backend` read before validation;
  `Repo` + Status map required, GitHub Project identifiers not; `status_column_map`
  populated; `owner` derived from `repo`.
- `KanbanFlowProvider` honors `status_column_map` for both write (`move`) and read
  (Status reporting); defaults to identity without a map; warns on board-id mismatch.
- A real `file → move → summary → close` cycle succeeds against the live board.
- `pytest -m 'not integration'` green with **no GitHub-doc test changes and no conftest
  signature change**; new KanbanFlow tests added. `ruff check .`, `ruff format .`,
  `mypy --strict` clean.
- `/jared-init` asks the backend and dispatches correctly; docs updated:
  `commands/jared-init.md` documents both invocations, `CLAUDE.md` notes the KanbanFlow
  doc shape, and `render_kanbanflow_doc` is the source of truth for the doc's shape. (No
  KanbanFlow section is added to jared's own `docs/project-board.md` — that board is
  GitHub-backed; a KF section there would be incongruous.)

## Open questions / deferred

- **Priority field name mapping.** Deferred — Phase 4 requires the field be named
  `Priority`. Revisit if a real board can't accommodate that.
- **Pre-populated boards.** A board with tasks created in the KF UI (no jared `number`)
  has invisible items by design (`list_open_items` skips un-numbered tasks). jared assumes
  it owns numbering on its board; mixed-use boards are out of scope.
- **Many-to-one read mapping.** Rejected for Phase 4 (operator chose 1:1 + warn). The
  `status_column_map` shape (Status → one column) does not preclude a future inverse
  multi-map if needed.
