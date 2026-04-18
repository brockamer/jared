---
name: manage-project-board
description: Steward a GitHub Projects v2 board with professional PM discipline — file, move, close, label, milestone, and reprioritize issues in sync with actual work; maintain dependency and milestone metadata so the Roadmap view is meaningful; surface drift with a backlog groom. Use proactively at session start to orient to board state, before starting substantive work to confirm it's on the board, and when completing work to close + verify auto-move to Done. Also use whenever the user mentions kanban, roadmap, milestones, sprint planning, scope changes, technical debt, "where are we / what's next / let's plan", filing an issue, grooming the backlog, or auditing the board. If the project has a `docs/project-board.md` convention file, consult it before any board change. Skill exists because the board is the single source of truth — work that isn't on the board is invisible and drifts into chaos.
---

# Manage Project Board

You are stewarding a GitHub Projects v2 board. The board is the single source of truth for all work — past (Done), present (In Progress), near-future (Up Next), and further-future (Backlog, organized by Milestones for roadmap visibility).

## Why this skill exists

Most developers treat the board as a passive record — occasionally update it, mostly ignore it. That produces a board where:
- Active work isn't reflected, so "what are we doing?" has no answer.
- Backlog items accumulate without priority, becoming invisible.
- Dependencies are buried in issue bodies, so blocking chains aren't obvious.
- Milestones drift out of sync with reality, making the Roadmap view useless.

This skill treats the board as the authoritative plan. Every meaningful scope change updates it. Every session starts by reading it. Every work transition (start / finish / reprioritize) moves it. When the board surface lies or omits reality, you stop and fix it before continuing.

## The discipline

### At session start — orient

Read current board state. Specifically: what's In Progress, what's next in Up Next, any items flagged by the most recent sweep. If the SessionStart hook already printed a summary, use it; otherwise run `scripts/board-summary.sh` (see `references/operations.md`).

If work has happened since the board was last updated (e.g., commits pushed, issues closed via PR), reconcile before taking new action.

### Before starting substantive work — confirm it's on the board

Before writing code, editing docs, or making any change with durable effect, confirm the work is represented by an open issue on the board. If it isn't:

1. **File it now**, don't defer. Unfiled work becomes invisible scope.
2. If you're uncertain of scope, ask the user to confirm before filing.
3. `gh issue create` does NOT auto-add to the board. The second step is mandatory: `gh project item-add`. See `references/operations.md`.
4. Set Priority and Work Stream immediately. Issues without these fall to the bottom of the board and become invisible.

**Exception:** trivial changes (typo fixes, formatting) don't need issues. Use judgment — if you'd want a line in your weekly summary, it's not trivial.

### When starting work — move to In Progress

Move the item to In Progress. Cap In Progress at 3 items — if already at 3, the user must decide what moves out or pauses. More than 3 means focus is scattered; WIP limits exist for a reason.

### While working — capture new scope

If you discover technical debt, a missing feature, a gap in documentation, or any insight that merits action beyond the current issue's scope, file it immediately as a new issue. Do not park it in a comment and hope you remember. Do not inflate the current issue's scope.

File → add to board → set Priority (Low is fine for capture, High if blocking) → Work Stream → move on.

### When completing work — close + verify

Close the issue with `gh issue close`. The board should auto-move the item to Done. Verify it actually did (occasional race conditions). If something is still "done but open" (work finished but no ticket close), you'll see it in the next sweep.

### Periodic — groom the board

Run `references/board-sweep.md`'s checklist when:
- User asks "where are we" or "what's next"
- In Progress drops to 0 (time to pull from Up Next — re-evaluate priorities first)
- A week has passed since the last sweep
- You spot drift (stale items, unprioritized issues, mismatched labels)

### When suggesting a new board — restructuring

See `references/new-board.md`. The short version: if a single board has ≥50 items with two or more distinct work streams where no issue in stream A depends on issue in stream B (and vice versa), it's probably two boards. When you notice this, surface it to the user — don't unilaterally restructure.

## Reading project-specific configuration

Each project documents its conventions in a local file. Check these paths in order:

1. `docs/project-board.md`
2. `PROJECT_BOARD.md`
3. `.github/project-board.md`

This file contains: Project ID, field IDs (Priority, Work Stream, Status), option IDs (High/Medium/Low, Backlog/Up Next/In Progress/Done, Job Search/Generalization/Infrastructure — or whatever the project defines), column definitions, label schema. Read it before proposing any board change.

If no file exists and you're about to do board work, ask the user to confirm conventions and propose creating the file. A board without a documented convention is a board that will drift.

## Operations reference

Detailed `gh` CLI command reference: `references/operations.md`. Covers file/move/close/label/milestone/assign/dependency-field operations.

## Milestones and roadmap

GitHub Projects v2 has a Roadmap view that visualizes milestones over time. Get this right and the user gets a roadmap visualization for free.

See `references/milestones-and-roadmap.md` for: when to create a milestone, how to name them (human-readable: "v0.2 — Materials Viewer" not "Milestone 2"), how to assign issues, how to set target dates.

## Dependency mapping

GitHub supports issue dependencies via the `Blocked by` / `Blocks` relationship. Until every project has that field on its board, fall back to body conventions: a `## Depends on` section listing `#N` references and a `## Blocks` section doing the same.

See `references/dependencies.md` for the graph-building routine and how to surface blocking chains during a sweep.

## Human-readable board surface

The board's value is that a human glancing at it understands the state of the world. Enforce:

- **Titles ≤ 70 characters.** Verb-first. "Add X", "Fix Y", "Refactor Z", not "Added X yesterday and will".
- **First line of body** is a one-sentence summary. Scannable without expanding.
- **Detail in collapsed `<details>` blocks** below the summary. Acceptance criteria, implementation notes, JSON scope, code blocks — all fine, just hidden by default so the issue view isn't a wall of text.

See `references/human-readable-board.md` for title/body templates.

## Anti-patterns to resist

- **"I'll file it later."** You won't. File it now.
- **"It's in a comment on the current issue."** Comments don't drive planning. New scope = new issue.
- **Using labels for priority.** Labels describe type (`bug`, `enhancement`). The Priority field is canonical.
- **Letting In Progress hold >3 items.** That's scattered focus. Finish or move out.
- **High-priority backlog items older than 14 days without review.** Either promote to Up Next, downgrade, or close as obsolete.
- **Closing an issue without verifying board auto-moved to Done.** Verify after closing.

## Design rationale

See `references/design-rationale.md` for why this skill exists, key decisions, and future extensions (v2 milestones + dependencies deep integration, v3 multi-board coordination).
