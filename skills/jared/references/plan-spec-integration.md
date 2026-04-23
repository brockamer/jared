# Plans, Specs, and Issues

Plans and specs (Superpowers-style `docs/superpowers/plans/` and `docs/superpowers/specs/`, or any equivalent planning-doc system) are **working artifacts**. They serve during brainstorming and execution, then become historical. The issue is the permanent record.

## The three roles

- **Spec** — What and why. Design and decision-log from brainstorming. Describes the desired end state and the rationale. One per feature, roughly.
- **Plan** — How. Concrete tasks with verifications. The bridge from spec to commits. Prescriptive enough that a fresh session can execute without re-reading the spec.
- **Issue** — The permanent record. Summarizes, points to the spec/plan, captures decisions made during implementation, receives Session notes.

A spec without a plan can't be executed. A plan without a spec usually means the design wasn't really thought through. Both without an issue means the work is invisible to the board — and Jared treats that as drift.

## The three rules

### 1. Every plan and spec cites an issue

Every plan document has an `## Issue` section near the top referencing the issue it implements:

```markdown
## Issue
#14 — Add excluded_employers config + prefilter enforcement
```

Every spec document, likewise:

```markdown
## Issue(s)
- #14 — primary implementation
- #23 — discovered scope, filed during design
```

A plan or spec without this section is orphaned and gets flagged during grooming.

### 2. Issues reverse-link to their planning artifacts

The issue body has a `## Planning` section pointing back:

```markdown
## Planning
- Spec: [docs/superpowers/specs/2026-04-17-generalize-prefilter-config-design.md](../blob/main/docs/superpowers/specs/2026-04-17-generalize-prefilter-config-design.md)
- Plan: [docs/superpowers/plans/2026-04-17-generalize-prefilter-config.md](../blob/main/docs/superpowers/plans/2026-04-17-generalize-prefilter-config.md)
```

Use GitHub-relative links so they resolve whether viewed on github.com or a local checkout.

### 3. Plans and specs archive on ship

When all issues a plan/spec references are closed:

1. Move the file to `docs/superpowers/plans/archived/YYYY-MM/` (or `specs/archived/YYYY-MM/`) — YYYY-MM is the month the issue(s) closed.
2. Prepend a header to the file:
   ```markdown
   ---
   **Shipped in #14 on 2026-04-19. Final decisions captured in issue body.**
   ---
   ```
3. Update the issue's `## Planning` section to point at the archived path.

This kills the "stale plan doc misleads future Claude" failure mode. A future search for "prefilter" finds the issue (current) *and* the archived plan (frozen, labeled as such) — and it's obvious which is which.

## Decisions made during implementation

The plan file is NOT where to record decisions made while executing. That content goes on the issue body's `## Decisions` section (see `references/context-capture.md` and `references/human-readable-board.md`).

Why not the plan? The plan is frozen at approval time. If you start editing it with decisions made later, the plan stops being an approvable artifact — it becomes a running log, which is what the issue already is.

When you want to amend the plan with a material change to the plan itself (not a decision about implementation, but a change to what the plan says to do), either:

- Update the plan with a `## Amendments` section at the bottom, dated; or
- Capture the amendment as a Decision on the issue and note in the plan "amended — see #14 Decision 2026-04-19."

## The lifecycle

```
1. Spec is written (in docs/superpowers/specs/)
     ↓ (brainstorming, design, decision-log)
2. Issue filed, spec's ## Issue(s) section cites it
     ↓
3. Issue's ## Planning section links to the spec
     ↓
4. Plan is written (in docs/superpowers/plans/), cites the issue
     ↓
5. Issue's ## Planning section updated to include the plan link
     ↓
6. Execution begins (work moves through In Progress)
     ↓
   ← Decisions made during execution: captured on issue ## Decisions
   ← Scope discovered: filed as new issues (may get their own specs/plans)
   ← Current state updated as work progresses
   ← Session notes appended each session
     ↓
7. Issue closes, PR merges
     ↓
8. Plan and spec archive to archived/YYYY-MM/
     ↓
9. Issue stays as permanent record. Plan and spec are historical artifacts linked from the issue.
```

## Grooming checks

`references/board-sweep.md` flags:

- Active plans (not in `archived/`) with no `## Issue` section.
- Active plans whose referenced issues/PRs have all shipped (issues CLOSED, PRs MERGED) — propose archival.
- Active plans whose referenced issues are stale (>30 days no update) — flag for review.
- Active specs with no `## Issue(s)` section.
- Issues with a `## Planning` section pointing to a non-existent file (plan was moved/deleted without updating).

## The archival script

```bash
# Archive a single plan (assumes all referenced issues/PRs have shipped: CLOSED or MERGED)
scripts/archive-plan.py --plan docs/superpowers/plans/2026-04-17-feature.md

# Batch — find all plans whose issues are closed, propose archival
scripts/archive-plan.py --scan --dry-run
scripts/archive-plan.py --scan  # apply after review
```

The script:

1. Parses the `## Issue` section.
2. Queries each referenced issue's state.
3. If all closed, moves the file to `archived/YYYY-MM/` (month of latest close).
4. Prepends the archival header.
5. Updates the issue's `## Planning` section to point at the new path.
6. Commits with a standardized message.

## When the project doesn't use plans/specs

Not every project wants this overhead. For small projects, solo hacks, or non-software work (renovation, event planning), issues alone are fine. Jared's plan/spec integration activates only when:

- `docs/plan-conventions.md` exists, or
- `docs/superpowers/plans/` or `docs/superpowers/specs/` directories exist, or
- The user explicitly asks Jared to set up planning artifacts

If none of these are true, Jared skips all plan/spec checks and behaves as a pure board-steward.

## For findajob specifically

The existing `plan-conventions.md` describes the sections a plan must contain. Jared's version (shipped at `assets/plan-conventions.md.template`) adds:

- An `## Issue` requirement (was missing)
- A "Documentation Impact" item asking explicitly for the issue reference
- A new "After the plan ships" section covering the archival routine

When `/jared-init` runs against findajob, it will detect the existing `plan-conventions.md` and offer to patch it with these additions rather than overwriting it.
