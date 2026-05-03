# Board Sweep — Grooming Checklist

Routine grooming, distinct from structural review. Run when the user asks "where are we / what's next," when In Progress drops to 0, when a week has passed, or when you spot drift.

## Goals

1. Every open item has complete metadata.
2. In Progress reflects reality — no abandoned or stalled items faking active status.
3. Up Next is ordered and the top item is pullable.
4. Backlog is prioritized so the next grooming knows what's next.
5. Milestones render a credible Roadmap view.
6. Dependencies are visible.
7. Plans and specs align with their issues (neither orphaned nor stale).
8. Issue bodies don't contradict the project roadmap doc (phase ordering, cross-issue decisions).

## The checks

Run in order. Each flag is a *proposal* to the user, not a unilateral fix.

### 1. Metadata completeness

Every open item needs **Status** and **Priority**, plus any categorical fields the project has defined (see `docs/project-board.md` for the canonical field list). Items without required field values sort to the bottom and disappear.

Status in particular is easy to miss: GitHub's auto-add-to-project workflow adds issues to the board without populating Status, so items can land with Priority set (because `jared-file` sets it explicitly) but Status=None. `scripts/sweep.py` flags both gaps.

`scripts/sweep.py` also flags **closed items whose Status ≠ Done** — GitHub's auto-move on close sometimes fails, and stale board state accumulates. Move them to Done manually during the sweep.

### 2. WIP

- In Progress > cap? Focus is scattered. Propose: finish one, move one back to Up Next, or pause one.
- In Progress = 0? Pull the top of Up Next after a priority check.
- In Progress item with no activity in 7 days? Stale. Propose: finish, punt to Up Next, or close.

### 3. Up Next queue and pullable check

- More than 3 items in Up Next? Overstocked. Propose moving lower items back to Backlog.
- Is the top item **pullable**? Specifically: does it have (a) a clear next action stated in the body, (b) acceptance criteria, (c) all dependencies unblocked? If not, propose reshaping it or pulling the next pullable item instead.
- Up Next items without Priority set — fix.

### 4. Blocked-status items

Every item currently in the **Blocked Status column** needs a `## Blocked by` section in its body naming the unblock owner and what specifically is being waited on. If a Blocked-status item lacks this section, flag for fix.

Also flag items that have been in Blocked status for more than 7 days — propose unblocking, punting back to Backlog, or breaking the blocker into a smaller issue.

(The old `blocked` label is retired. A `blockedBy` edge alone does not put an issue in the Blocked column. Items move to Blocked only when actively stuck after being pulled to In Progress.)

### 5. Aging

- High-priority Backlog items >14 days old: propose promote / downgrade / close.
- Any Backlog item >60 days old without activity: propose closing as obsolete unless the user has specific plans for it.

### 6. Done hygiene

Issues in Done since before the last release — fine to leave, but glance for anything that should have been closed differently (closed as "won't fix" but with no explanatory comment). Add a `wontfix` or `obsolete` label if appropriate.

### 6b. Off-board issues (ghost detection)

Open issues in the repo that have no project item — `gh issue create` ran somewhere outside `jared file` / `jared add-to-board` and the issue never landed on the kanban. The operator can't see it; Status and Priority are null; it sorts to the bottom and disappears.

`sweep.py`'s `check_off_board_issues` intersects `gh issue list --state open` against `gh project item-list` and flags any difference. Each finding renders a `jared add-to-board <N> --priority Medium` recovery line — adjust priority before pasting.

This is the durable backstop for the "any opaque `jared file` failure → fall back to raw `gh issue create` → orphan" pattern (issue #100). Detection is automatic; remediation is per-item with explicit operator approval.

### 7. Label hygiene

- Deprecated labels (e.g., legacy `priority:` labels when the Priority field is canonical) — strip.
- Labels on one issue but missing on similar issues — standardize.
- Issues with no type label (no `bug`, `enhancement`, `refactor`, etc.) — triage.

### 8. Milestone coverage

For each near-term milestone:

- Target date set?
- Open/closed ratio realistic?
- All open issues have Priority and any other required field (e.g., Work Stream, if defined)?
- No shipped-milestone issues still open (close or reassign)?

### 9. Dependency hygiene

For each open issue with native `blockedBy` edges:

- Referenced blocker still exists and is open? Edges pointing at closed issues should be removed.
- Dependent's Priority higher than or equal to its blockers' Priority? (Priority inversions are red flags.)
- Any circular dependencies? Fix hard.
- Chains >3 deep? Fragile — slip cascades. Consider parallelizing or cutting scope.

`## Depends on` body sections (if present) are prose context only and are not parsed.

Run `scripts/dependency-graph.py --summary` for a compact view.

### 10. Plan/spec alignment

Scan `docs/superpowers/plans/` (or the project's equivalent):

- Active plans (not in `archived/`) with no `## Issue: #N` section — propose filing an issue or deleting the plan.
- Active plans whose referenced issues/PRs have **all shipped** (issues CLOSED, PRs MERGED) — propose archiving to `archived/YYYY-MM/` with a header pointing to them.
- Active plans whose referenced issues are stale (>30 days no update) — flag for review.

Same check for `specs/` directory.

See `references/plan-spec-integration.md` for archival mechanics.

### 11. Session-note freshness

For every In Progress issue:

- Is there a Session note from within the last 3 working days?
- If not, propose running `/jared-wrap` or asking the user what's going on.

Stale In Progress with no Session note usually means work was started and abandoned — reconcile.

### 12. Convention doc drift

Read `docs/project-board.md` and verify its IDs and conventions match the actual board. Any board changes (new columns, new priority options, new work streams, new fields) must be reflected in the doc. If drifted, fix the doc in the same grooming session.

### 13. Roadmap drift

If the project has a `docs/roadmap.md` (or equivalent phase-narrative doc), scan open issue bodies for language that could contradict it. The goal is **issue bodies reference the roadmap, not restate it.**

Flag any issue body that:

- Asserts phase ordering (e.g., "Phase 4 runs before Phase 3", "this is blocked on Phase 5 finishing") that contradicts the roadmap's phase arc.
- Restates a numbered decision from the roadmap (decision 7, etc.) with different wording — restating is how prose and canonical fact drift apart.
- Names milestone-level acceptance criteria that don't match the roadmap.
- References a phase / decision / milestone that no longer exists in the roadmap.

How to scan:

1. Read `docs/roadmap.md`. Note the phase names, the active milestone's acceptance criteria, and any decision subject lines.
2. For each open issue body, `grep`-style scan for: `Phase \d`, `Milestone \d`, `decision \d`, or the active milestone's name.
3. For any hit, compare against the roadmap. If it matches: fine. If it paraphrases or contradicts: flag.

Fixes are narrow — change the issue body to *link* (`see Phase N in roadmap.md`) rather than restate. The roadmap itself is only updated if the conflict reveals the roadmap is wrong, which is rare and should prompt a conversation with the user.

## Output of a sweep

Present as a proposal:

```
Sweep YYYY-MM-DD:

== Metadata ==
- #47, #52, #61 missing Priority. Propose: Medium unless you say otherwise.

== WIP ==
- In Progress = 2 (healthy).
- #27 has no activity in 10 days. Propose: close or move back to Up Next.

== Pullable check ==
- Top of Up Next is #31 but missing acceptance criteria. Propose reshaping before pulling.

== Aging ==
- #18 in High Backlog since 2026-03-25 (26d). Propose downgrading to Medium.

== Plan/spec ==
- `docs/superpowers/plans/2026-04-10-feed-expansion.md` references #14 (closed 2026-04-12). Propose archiving.
- `docs/superpowers/specs/2026-04-02-scorer-v2.md` has no issue. Propose filing one or deleting.

== Convention doc ==
- Board has a new "Design" work stream option; project-board.md doesn't list it. Propose adding.

Approve? (y / cherry-pick / skip)
```

Wait for sign-off before bulk changes. The sweep is advisory.

## When the sweep finds nothing

Say so. "Swept, all clear" is a valid outcome and the user trusts you more for reporting it honestly than for inventing findings.
