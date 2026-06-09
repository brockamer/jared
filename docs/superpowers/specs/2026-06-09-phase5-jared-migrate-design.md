# `jared migrate` between backends — Phase 5: migration command (design)

**Issue:** #318 (Phase 5). Parent epic: #313.
**Date:** 2026-06-09
**Status:** Design — not yet started. Drafted during the 2026-06-09 structural review; **open design questions below are unresolved and must be settled (with the operator) before a plan is written.**
**Related references:** `skills/jared/scripts/lib/board_provider.py`, `lib/github_provider.py`, `lib/kanbanflow_provider.py`, `docs/superpowers/specs/archived/2026-06/2026-06-02-board-provider-abstraction-design.md` (§ "Appendix A — Migration fidelity"), `docs/project-board.md`.

## Context — the larger feature

Epic #313 makes jared's board backend pluggable. Phases 1–4 shipped: the backend-neutral `BoardProvider` contract (#314), the KanbanFlow REST client (#315), `KanbanFlowProvider` (#316), and init-time backend selection persisted in the convention doc (#317). With Phase 4 landed, a project can be *stood up* on either GitHub Projects v2 or KanbanFlow — but it cannot yet *move* from one to the other.

Phase 5 adds `jared migrate`: a one-shot, operator-confirmed command that reads a project's board from its current backend and re-creates it on the other, surfacing the **named, accepted lossiness** of that specific direction before it writes anything. Phase 5 and Phase 6 (#319) are independent and run in parallel after Phase 4.

## Problem

The two backends are not symmetric, and the asymmetries are exactly where a naïve copy loses data silently. The migration must make every loss explicit and confirmed *before* the first write. The constraints are frozen in Appendix A of the Phase 1 spec; restated here as the problem surface:

- **`#N` is settable on KanbanFlow but auto-assigned on GitHub.** GitHub→KF can preserve every issue number exactly. KF→GitHub **cannot** — GitHub assigns its own numbers, so that direction *renumbers*, breaking every `#N` cross-reference in bodies, comments, and session history unless they are rewritten against an old→new map.
- **blocked-by representation differs.** GitHub stores native relation edges; KanbanFlow relations are read-only via API, so jared emulates them with `blocked-by:<N>` labels + the Blocked column. Migration must translate the representation in both directions — and a translated edge is only correct once the *target* numbers exist, so edge re-establishment is a second pass after item creation.
- **Closed-state asymmetry.** GitHub has a real closed state; KanbanFlow has only a Done column (`CLOSED_STATE` capability absent). Migrating history (every Done/closed item) is both expensive under KF's quota and of questionable value.
- **Milestones vs swimlanes.** GitHub milestones carry name + description + open/close state + due date; KanbanFlow swimlanes carry only name + description. GH→KF drops milestone state and due dates; KF→GitHub loses any swimlane structure not mapped back to a milestone.
- **Markdown vs plain text.** GitHub bodies are markdown; KanbanFlow `description` is plain text. jared's `## section` parsing round-trips (it is text-based), but rendering is lost — a representation loss, not a data loss.
- **Board structure is read-only on KanbanFlow.** Columns, swimlanes, and custom-field *definitions* must pre-exist in the KanbanFlow UI before a GH→KF migration can write into them (the same Phase-4 `init` prerequisite). Migration validates the target's structure up front and refuses with a clear list if it is missing.
- **KanbanFlow write amplification + quota.** `file` is ≥2 calls (task create, then per-field custom-field POST, then per-comment POST), against a 1,000 req/hr / token-locks-at-5,000-day budget. A whole-board migration of a real project can approach or exceed that — so throttling, batching, and (open question) resumability are first-class concerns, not afterthoughts.

## Goals

- A `jared migrate` subcommand that moves a board from its current backend to the other, expressed **entirely** through `BoardProvider` semantic methods on both sides — no GitHub node-id or KanbanFlow `_id` crosses the command. The command instantiates a *source* provider (the project's configured backend) and a *target* provider, and copies item-by-item.
- **Lossiness is surfaced and confirmed before any write.** The command computes a direction- and dataset-specific lossiness report ("N native edges → label-markers; M items will be renumbered; K closed items will/won't migrate; milestone due-dates dropped") and requires explicit operator confirmation. **Dry-run is the default**; writing requires an explicit `--apply`.
- **GitHub→KanbanFlow preserves `#N` exactly.** **KanbanFlow→GitHub emits an authoritative old→new number map** as a durable artifact of the run.
- **blocked-by edges are semantically preserved** across the renumber, in both representations.
- The migration is **safe to abort and re-run**: a partially-applied migration leaves the target in a state the next run can reconcile rather than duplicate (mechanism is an open question — see below).
- Existing tests stay green; new tests cover the lossiness report and the translation passes against a capability-restricted fake — **plus a live round-trip against a real KanbanFlow board** (see Acceptance).

## Non-goals (Phase 5)

- **No continuous / two-way sync.** `migrate` is a one-shot directional copy, not a mirror. There is no ongoing reconciliation daemon.
- **No board-structure creation on KanbanFlow.** Columns / swimlanes / custom-field definitions must pre-exist; `migrate` validates and refuses if absent, it does not create them (the API can't).
- **No change to the repo/git axis.** Branches, PRs, worktrees, session locks, wrap-state, plan archival are backend-independent and untouched — a migrated board points at the same repo.
- **No capability-degradation logic** — that is Phase 6 (#319). Phase 5 may *consume* `capabilities()` to compute the lossiness report, but it does not wire command-surface degradation.

## Architecture

### Shape of the command

```
jared migrate --to <github|kanbanflow> [--apply] [--include-closed] [--out <map.json>]
```

- The **source** is the project's currently-configured backend (parsed from `docs/project-board.md`); `--to` names the target. Refuse if `--to` equals the current backend.
- How the **target board identity** is supplied (a second convention doc? inline flags? a pre-seeded target `docs/project-board.md`?) is an **open question** — see below.
- Default run is a **dry-run**: it reads the source, validates the target structure, computes the lossiness report, prints it, and stops. `--apply` performs the writes after confirmation.

### Pipeline (read source → report → confirm → write target)

1. **Read the full source board** via the provider: `list_open_items()` (+ closed items only under `--include-closed`), `get_body()`, `fetch_blocked_by_edges()`, `list_milestones()`. **Contract gap:** the shipped `BoardProvider` has no comment-*read* method — `comment()` is write-only, and the `list_comments()` the Phase 1 spec sketched did **not** ship. Porting session-note history therefore requires extending the contract first (see Open question 7).
2. **Validate the target** (KanbanFlow target: columns for every Status, dropdown custom fields for Priority/Work-Stream/custom selects, swimlanes for every milestone). Refuse with a precise missing-structure list.
3. **Compute the lossiness report** for this direction + dataset, driven by the *difference* between source and target `capabilities()` plus the structural mappings.
4. **Surface and confirm.** Print the report; require `--apply` + an interactive confirmation (or `--yes`) to proceed.
5. **Write the target in dependency-safe order:**
   a. Create every item (`file(...)`), preserving `#N` on GH→KF / accumulating an old→new map on KF→GH.
   b. Apply Status (`move`), Priority/fields (`set_field`), milestone (`set_milestone`).
   c. **Second pass:** re-establish blocked-by edges (`add_blocked_by`) now that all target numbers exist, translating through the number map.
   d. Port comments / session notes — **gated on the contract gaining a comment-read method** (Open question 7); when available, write via `comment()`, backdating where the target supports it.
6. **Emit the run artifact:** the old→new number map and a human-readable migration report (what moved, what was lost), written to `--out` (default a timestamped file).

### The number map is the spine

Every later pass keys off the old→new map produced in 5a. On GH→KF it is the identity map (numbers preserved) and exists only to make edge/cross-ref translation uniform. On KF→GitHub it is the load-bearing artifact: edges, and (open question) in-body / in-comment `#N` cross-references, are rewritten through it.

### Quota-aware writes (KanbanFlow target)

Writes batch and throttle to respect the 1,000 req/hr budget; the command estimates total calls up front (items × per-item call count + edges + comments) and includes that estimate in the dry-run report so the operator knows whether a run fits the window. Resumability under quota exhaustion is an open question.

## Open design questions — settle before writing the plan

1. **Migrate closed/Done history, or the live board only?** Default to live-board-only (cheap, high-value) with `--include-closed` opt-in (expensive, lossy on KF where there is no closed state)? Or the reverse?
2. **KF→GitHub cross-reference rewriting.** When renumbering, do we *automatically rewrite* `#N` references inside bodies and comments via the number map, or only emit the map and warn that prose cross-refs now point at the old numbers? Auto-rewrite is correct-but-risky (false positives on `#N` that isn't an issue ref); warn-only is safe-but-leaves-rot.
3. **Resumability.** For boards large enough to exceed the KF hourly quota mid-run, do we checkpoint (a resume file mapping completed items) so a re-run continues, or document a hard size ceiling and refuse above it?
4. **Does `migrate` flip `docs/project-board.md`'s backend selector** to the target on success, or leave the convention doc to the operator (so the source board stays authoritative until they switch)?
5. **How is the target board identified?** Inline flags vs a pre-seeded target convention doc vs an interactive `init`-style interview for the target. This couples to Phase 4's `init` flow.
6. **Comment author attribution.** KanbanFlow comments are authored by the API token's user, so GH→KF loses original authorship. Accept as a named loss, or prepend `(originally @author)` into the comment text?
7. **Comment/session-note portage needs a contract extension.** The provider can *write* comments (`comment()`) but cannot *read* them — there is no `list_comments()` in the shipped contract (Phase 1 proposed it; it did not ship). Phase 5 must either add a comment-read method to `BoardProvider` + both providers (a prerequisite sub-task) or scope session-note migration out of v1 as a named loss. Given how much jared invests in session continuity, migrating a board *without* its note history is a material fidelity loss — lean toward the contract extension.

## Acceptance criteria

- `jared migrate` reads the source and writes the target **only** through `BoardProvider` methods; a grep proves no `gh`/GraphQL/`field_id`/`option_id`/KanbanFlow `_id` in the command file.
- Dry-run is the default; no write occurs without `--apply` **and** confirmation. The dry-run prints the full lossiness report and a KanbanFlow call-count estimate.
- GH→KF preserves every `#N`; KF→GitHub emits a complete old→new number map artifact.
- blocked-by edges are semantically preserved across the renumber (verified by re-reading the target's edges and comparing the dependency graph to the source's).
- Each named loss from Appendix A is itemized in the report before writing.
- **Live verification (required, not fake-only):** a real GitHub↔KanbanFlow round-trip is exercised against a **real KanbanFlow board**, not just `FakeKanbanFlowClient`. The fake returns full task objects where the live API returns `{taskId}` on create / `null` on update, so a fake-only green run hides the real write contract — this is the lesson from #317 / PR #334 and the reason migration's write path must be confirmed live.
- `pytest -m 'not integration'` green (new unit tests for the report + translation passes via a capability-restricted fake provider); `ruff check .`, `ruff format .`, `mypy` clean.

## Documentation Impact

- `docs/project-board.md` — document backend-switching via `jared migrate` and the named lossiness per direction; note the KanbanFlow target-structure prerequisite.
- `CLAUDE.md` — add `migrate` to the CLI surface inventory (the "~18 subcommands" count) and the three-tier operations note.
- `skills/jared/references/operations.md` — the `migrate` operation, dry-run/apply discipline, and quota guidance.
- `CHANGELOG.md` + GitHub Release — at ship, under **Features**.
- A new implementation plan in `docs/superpowers/plans/` at activation, citing `## Issue: #318`.
