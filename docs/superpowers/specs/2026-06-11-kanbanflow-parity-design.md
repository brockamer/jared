# KanbanFlow → GitHub capability parity — design (Phase 0 brainstorm output)

- **Issue:** #357 (epic) — "Bring KanbanFlow backend to capability parity with GitHub Projects"
- **Date:** 2026-06-11
- **Status:** design approved; per-phase plans to follow (one spec/plan/PR each, per the epic body)
- **Successor to:** epic #313 (closed) — which shipped KanbanFlow as a deliberately *reduced* backend

## 1. What this is

Epic #313 made jared board-backend-agnostic and shipped `KanbanFlowProvider` with the
**entire** `Capability` set in `_OMITTED_CAPABILITIES` ("KF supports only the core board
loop"). Every `degraded:` gate in jared's prose and CLI fires on a KanbanFlow board today.

This epic systematically closes that gap. The operator's chosen posture (Phase-0 decision):
**treat KanbanFlow as a backend a marketplace user could genuinely run day-to-day — close
every *feasibly*-closable gap; document only the true limits as non-goals.** This is the
build-mode reading, aligned with the in-scope marketplace-ship goal (epic #348), not the
"document non-goals and close" reading.

## 2. Governing principle — what a capability *means*

A `Capability` flag means **"no jared surface degrades on this backend for lack of it."**
That is already the flag's operational job: it gates `degraded_or_none` (`lib/capabilities.py`).
From this definition every flip/keep decision derives, rather than being argued case by case:

- **Flip a flag to present only when every consumer that gates on it stops degrading.** Not
  "the feature now half-works" — every gated surface must be satisfied.
- **A partial improvement ships, but keeps the flag omitted and *refines the `degraded:`
  note*** to describe the precise residual loss. Honesty over optimism: a still-degrading
  surface keeps its (now sharper) note.
- **Do not split the `Capability` enum into finer flags unless a real consumer branches
  differently on the halves.** Splitting a flag no surface reads is the dead-field
  anti-pattern (CLAUDE.md: "reach for parsing only when a CLI surface gates on the value").
- **Every phase live-verifies on the `p9vK6cR` test board before merge.** Verification is
  folded into the producing phase, never deferred (`feedback_deferred_verification_drift`).

## 3. How feasibility was established (and its limits)

KanbanFlow's v1 REST API **does not self-describe** — no OpenAPI/Swagger spec, no discovery
endpoint, no `OPTIONS` affordance listing. So truth comes from docs + probing, graded by
source strength (strongest → weakest):

1. **jared's shipped client/provider code** — encodes a read contract live-confirmed in the
   #318/#319 runs. Ground truth, but only for the slice the client already exercises.
2. **Primary non-KF sources** — npm registry JSON, GitHub API JSON (the MCP-server verdict).
3. **KanbanFlow doc sub-pages** (re-fetched by an adversarial verifier) — good for *what
   exists*, weak for *what does not*.
4. **Third-party integrations** (Pipedream "Task Moved" trigger) — corroboration, not proof.
5. **Doc inference** — "the example shows `color`, so `columnId` works the same way." Weakest.

The feasibility pass was a 15-agent workflow (1 API-surface map + 7 classifiers + 7
adversarial verifiers). The verifiers earned their keep: they **overturned** the
VELOCITY_TIMESTAMPS verdict (classifier said "true parity"; verifier downgraded it to
"feasible pending a live probe" because the load-bearing `columnId`-in-events mechanism is
*never shown* in any KF doc example — only inferred). That single correction motivated the
live probe below.

> **Discipline for implementers:** the read contract is live-confirmed below, but
> `feedback_kanbanflow_fake_masks_live_contract` is about **write** contracts — the fake
> returns full objects while real create/update return `{taskId}`/`null`. Each build phase
> must live-verify its **writes** on `p9vK6cR` before merge, not trust the fake.

## 4. Live probe findings (read-only, run 2026-06-11 on `p9vK6cR`)

A read-only `GET /board/events` probe (same Bearer/`/api/v1` protocol as the production
client) resolved the gated uncertainty. **No write was needed** — the board's existing
history already contained a column move into Done. Findings — these are ground truth the
build phases inherit, not to be re-derived:

- **`GET /board/events` exists** (200) and returns **`{eventsLimited, events}`** — an
  envelope object, **not** the bare list the research assumed. `eventsLimited` is the
  pagination signal.
- **`columnId` transitions are in the stream** — observed `{columnId: 3, groupingDate: 1}`
  across `detailedEvents[].changedProperties[]`. The inference is now a fact.
- **A move into Done is timestamped** — `2026-06-05T13:20:56Z  Doing Now → Done`. The #313
  "settled" premise ("KanbanFlow exposes no reliable moved-to-Done timestamp") is
  **empirically false**.
- **`columnId` value == the column's `uniqueId`** (`get_board`) — so Done resolves cleanly,
  **through the `### Status column map`** (the test board uses GTD column names; "Done"
  matched only by coincidence — implementers must resolve Done via the map, not a literal).
- **`groupingDate` changes are tracked** — the zero-extra-call, day-granularity closed-date
  fallback is real.
- **Retention caveat (open):** events reach back to the board's oldest activity (~6 days on
  this young board), which covers `recently_closed(14d)` comfortably. The **deep-history
  retention ceiling is unprobed** — the board is too young to show it, and there is no
  `_dateCreated` on the task object, so on KanbanFlow **created-at is reconstructable only
  from the event log**. This is the load-bearing contingency for §6.

## 5. Per-capability verdicts (verified) + consumer analysis

| Capability | Verified verdict | Real consumers (grepped) |
|---|---|---|
| VELOCITY_TIMESTAMPS | feasible for `recently_closed`; **flag flip contingent** | 5 gates, **all created-at/activity-based**: sweep stale-High-Backlog, stalled-In-Progress, Blocked-aging; `board.py` audit-window sort; `stage.py` Backlog-age tiebreaker. **None consume `recently_closed`.** |
| CLOSED_STATE | partial overall, but **flag flips cleanly** | 1 gate: `find_orphaned` (dependency-graph.py) — needs only *closed-or-not*, which Done-membership answers. Orthogonal-closed flag is unused. |
| NATIVE_DEPENDENCIES | partial — read closeable, **write impossible** | `get_relations` exists in the client but is **dead** (never called). `dependsOn`/`requiredBy` readable; no relations write endpoint exists (confirmed 3 ways). |
| MARKDOWN_BODY | partial | KF **does** render bold/italic/links/lists/code (the #313 "plain text" premise was wrong). `##` headings + `<details>` do **not** render — those are exactly jared's body-template scaffolding. |
| MILESTONE_STATE | partial — state derivable, **due a non-goal** | State = all-swimlane-tasks-in-Done (reuses shipped logic). No native container due date; per-task `dates[]` is the wrong granularity. |
| MCP_TIER | feasible-but-declined → **build a shim** (operator ruling) | A third-party server exists but is frozen + bypasses the atomic `file` invariant. Build a thin shim over provider methods instead. |
| SUB_ISSUES | **non-goal** | KF subtasks are checklist lines (no `#N`/status). jared consumes sub-issues **nowhere — even on GitHub**; the `epic` label is the hierarchy primitive. A `parent:<N>` marker would be dead code. |

## 6. Capability outcomes (grep-grounded — corrected from first draft)

- **CLOSED_STATE → flips (clean, cheap, not retention-dependent).** Its only consumer,
  `find_orphaned`, needs closed-or-not; route that through Done-membership on KanbanFlow.
  The impossible orthogonal-closed flag stays a documented, *unused* limit.
- **VELOCITY_TIMESTAMPS → `recently_closed` ships real data; flag flip is CONTINGENT.**
  Building `recently_closed` delivers value (next-session-prompt "Recently closed";
  velocity inputs) but clears **none** of the five gated surfaces — they need per-task
  `createdAt`/activity reconstructed from the event log, which is (a) more build and (b)
  retention-ceiling-dependent. The flag flips **only if** a retention probe confirms the
  ceiling covers the aging windows (sweep default 14d; audit default-staleness clamp
  `[14,60]`). **If retention is insufficient, `recently_closed` value still ships, the flag
  stays omitted, and its note is refined** — the epic does *not* promise this flip.
- **NATIVE_DEPENDENCIES → stays omitted; note refined.** Read wired (native
  `dependsOn`/`requiredBy` merged + reconciled vs `blocked-by:<N>` labels); writes remain
  label-only (no API). New note: *blocked-by writes are label markers; native relations are
  read.*
- **MARKDOWN_BODY → stays omitted; note refined + corrected.** Inline formatting renders;
  block structure (headings, `<details>`) is downgraded. The current note **overstates** the
  loss and must be corrected.
- **MILESTONE_STATE → stays omitted; note refined.** State derived; due is a documented
  non-goal. **Not** splitting the enum (no consumer branches state-vs-due today).
- **MCP_TIER → flips** once the shim ships.
- **SUB_ISSUES → non-goal** (formalized; already in the spec/inventory/migrate.py loss msg).

## 7. Phase plan

Phases 2/3/4 are mutually independent (no probe dependency) — parallelizable. Phase 1 is the
value anchor; Phase 5 (MCP) is the heaviest and gets its own sub-spec.

- **Phase 0 ✅ — Live events probe** (this session). Findings in §4. Gate resolved.
- **Phase 1 — Events + closed-state.**
  - `KanbanFlowClient.get_board_events(...)` + `get_task_events(...)`, a `KfEvent` dataclass
    + parser; handle the `{eventsLimited, events}` envelope and `from/to/limit≤100/order`
    windowed paging (no cursor); respect the 1000/hr · 5000/day budget.
  - Rewrite `KanbanFlowProvider.recently_closed` from `return []` to an event scan for
    `columnId`→Done (Done resolved via the Status column map), emitting `ClosedItem`.
  - Route `find_orphaned`'s closed-detection through the provider (Done-membership) →
    **flip CLOSED_STATE.**
  - **Retention sub-probe** + per-task `createdAt`/activity reconstruction: decide whether
    **VELOCITY_TIMESTAMPS flips** or stays omitted-with-refined-note. Do **not** assume the
    flip.
  - Live-verify on `p9vK6cR` (reads *and* any new write paths).
- **Phase 2 — Native dependency reads.** Wire the dead `get_relations` into the provider edge
  fetch; map `dependsOn`→`Edge(dependent,blocker)`, `requiredBy`→inverse, drop `relatesTo`;
  reconcile/dedup vs `blocked-by:<N>` labels (surface divergence as a groom/audit finding).
  Refine the NATIVE_DEPENDENCIES note; flag stays omitted (write impossible).
- **Phase 3 — Markdown downgrade.** A one-way GFM→KF-subset transform at the KanbanFlow
  provider's `set_body` boundary: `## Heading`→`**Heading**`, `<details><summary>X</summary>…`
  → `**X**` + visible list (content preserved, collapsibility lost), leave bold/lists/code/
  links as-is. No new client methods. Correct + refine the MARKDOWN_BODY note.
- **Phase 4 — Milestone state.** Derive milestone closed = all tasks in that swimlane in Done
  (reuses `_status_by_column_id` + swimlane maps; zero new client methods). Suppress state for
  empty swimlanes (avoid a misleading "closed"). Due = explicit non-goal. Refine the
  MILESTONE_STATE note.
- **Phase 5 — MCP shim (own sub-spec).** A thin MCP server over the **provider** methods
  (`file`/`move`/`close`/`comment`), preserving the atomic `file` invariant — **not** the
  third-party server's raw `create-task`/`update-task` CRUD. Flips MCP_TIER. Sequenced last;
  different build domain (its own design + plan).
- **Phase 6 — Document + reconcile + close.** Formalize SUB_ISSUES (and milestone-due,
  orthogonal-closed, native-write) as rationale-backed non-goals; finalize
  `_OMITTED_CAPABILITIES`; assert **every still-firing `degraded:` note is accurate** (none
  overstates the loss); update the convention-doc capability prose; close the epic.

## 8. Constraints for implementers

- **`runtime_checkable` atomic-coupling (`reference_runtime_checkable_protocol_atomic_coupling`,
  #318).** Prefer folding into **existing** `BoardProvider` methods (`recently_closed`,
  `fetch_blocked_by_edges`, `set_body`, `list_milestones`) and adding new methods only on
  `KanbanFlowClient` (safe — not the Protocol). If a phase genuinely needs a **new**
  `@runtime_checkable` `BoardProvider` method (e.g. a closed-state or created-at lookup for
  `find_orphaned`/aging), it must land in **both** provider impls in **one commit** —
  `isinstance()` + `mypy --strict` break with no green intermediate otherwise.
- **Done is resolved via the Status column map**, never a literal "Done" match (the live
  board uses GTD column names).
- **Rate budget:** 1000 req/hr/board, 5000/day token-lock. Event scans use `from/to`
  windows, not unbounded crawls. The relations read has no bulk endpoint (one GET per task) —
  budget it (lazy/on-demand vs full-board sweep).
- **`GH_TOKEN`/auth:** unrelated to KF, but the GitHub-side surfaces still follow
  `project_gh_token_pat_shadows_oauth_flaky_project_scope`.

## 9. Acceptance criteria (epic)

1. Every member of `_OMITTED_CAPABILITIES` is either (a) removed at true parity, (b) retained
   with a precise residual-loss note, or (c) a rationale-backed non-goal — and
   `kanbanflow_provider.py`'s capability declaration reflects the outcome.
2. **No `degraded:` note overstates the actual loss** (asserted in Phase 6; the MARKDOWN_BODY
   correction is the canonical example).
3. `recently_closed()` returns real data on KanbanFlow, **live-verified on `p9vK6cR`**;
   next-session-prompt's "Recently closed" is populated.
4. CLOSED_STATE flips: `find_orphaned` works on KanbanFlow via Done-membership.
5. Native `dependsOn`/`requiredBy` relations are read into the dependency graph and reconciled
   against label markers.
6. KanbanFlow issue bodies render jared's section structure acceptably (content never lost).
7. The MCP shim preserves the atomic `file` invariant (no raw task CRUD).
8. Each phase's writes are live-verified on `p9vK6cR` before merge.

> Deliberately **not** an acceptance criterion: "VELOCITY_TIMESTAMPS flips." That is
> contingent on the retention probe (§6) and would overstate parity if promised.

## 10. Non-goals (rationale-backed)

- **SUB_ISSUES** — no consumer on either backend; the `epic` label is the hierarchy
  primitive; a `parent:<N>` marker would be dead code.
- **Milestone due dates** — no native container date; a non-live config registry fights "the
  board is the single source of truth." Ship the derived *state* half only.
- **Orthogonal closed state** (a closed flag independent of the Done column) — genuine KF
  platform limit; unused by jared (Done == closed).
- **Native blocked-by *writes*** — no relations write endpoint exists; writes stay label-only.
- **Markdown block structure** (headings, `<details>`, tables) on KF — renderer doesn't
  support it; downgraded with content preserved.

## 11. Open questions / contingencies

- **Event retention ceiling** (§4, §6) — gates the VELOCITY_TIMESTAMPS flag flip. Probe in
  Phase 1; cannot be answered by the young test board's history alone.
- **Events endpoint tier-gating** — docs silent on whether `/board/events` is premium-only;
  confirm on `p9vK6cR` (it returned 200 there, so at minimum the current token has it).
- **`groupingDate`** as a zero-call day-granularity closed-date fallback — confirm it is
  populated for Done tasks by default vs only when date-grouping is enabled.
- **Optional absence-probe** (not yet run): `POST /tasks/<id>/relations` → expect `404/405`
  to harden the NATIVE_DEPENDENCIES write-impossible verdict beyond doc-absence. Low-risk
  (a 404 mutates nothing); offer before Phase 2.
