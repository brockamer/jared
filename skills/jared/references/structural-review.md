# Structural Review — The Seven Questions

Use this when the board may have drifted from the project's actual trajectory — after a major release, a pivot, a new strategic horizon opening up, or when a routine sweep (`references/board-sweep.md`) keeps turning up issues that feel more foundational than tactical. Also the routine invoked by `/jared-reshape`.

This is heavier than a sweep. It's the 10,000-foot pass. Plan for 30–60 minutes and expect to propose substantive changes: new milestones, possible board splits, dependency graph rebuilds, strategic issues to file.

## The Seven Questions

Work through these in order. Each question has a one-line goal and concrete checks.

### 1. Shape — one board or many?

*Goal: confirm the board's scope is coherent.*

- Is every open issue plausibly something the operator would want to see today?
- Are there two or more work streams with no cross-dependencies between them?
- Is the board >100 open items and growing?
- Do different audiences need different surfaces?

If multiple yeses, consider a split. See `references/new-board.md` for criteria and mechanics. Don't split on weak signals ("the board is getting long") — split on clear orthogonality.

### 2. Phasing — are items tied to their phase?

*Goal: every backlog item knows which phase or release it belongs to.*

- Does the project have a phase/release/horizon concept? (Often a strategic issue like "GA roadmap" or a milestone set.)
- Are items correctly assigned to their phase via milestone?
- Orphans — items not tied to any phase?
- Implicit phases — is there a bucket of work that clearly belongs to a future phase you haven't named yet?

Propose: name missing phases, tie orphans to their phase, file strategic issues for implicit phases.

### 3. Milestones — do they render a useful Roadmap view?

*Goal: the Roadmap view shows a credible sequence of near-term releases.*

For each milestone:

- Does it have a target date?
- Is the name human-meaningful (`v0.2 — Materials Viewer`, not `Milestone 2`)?
- Does every open issue in the milestone have Priority and any other required field (e.g., Work Stream, if the project defines one)?
- Is the open/closed ratio realistic for the date?
- Is there a one-sentence deliverable that proves the milestone is done?

See `references/milestones-and-roadmap.md` for the full milestone hygiene checklist.

### 4. Dependencies — is the blocking graph visible?

*Goal: blocking chains are explicit, not buried.*

- Build (or refresh) the dependency graph via `scripts/dependency-graph.py`.
- Cycles? These are hard bugs — fix immediately.
- Priority inversions (High depending on Medium/Low)? Either the dependency is actually more important than labeled, or the dependent doesn't really need it.
- Chains of length >3? Fragile — any slip cascades. Consider parallelizing or cutting scope.
- Orphaned dependents referencing closed issues? Clean up.

### 5. Metadata drift — what's the sweep telling you?

*Goal: triage sweep findings into "real drift" vs. "noise."*

Run `scripts/sweep.py`. Classify findings:

- Missing Priority or other required field (project-dependent) — triage each. Often closed-PR noise on the board; sometimes real.
- Legacy priority labels — strip or reconcile.
- Stale High in Backlog — promote, downgrade, or close.
- In Progress with no recent activity — finish, punt, or close.

Propose fixes in bulk where the pattern is the same across many items; propose individually where each is a judgment call.

### 6. Deliverables — what proves each milestone is done?

*Goal: a shipped milestone is recognizable.*

For each open milestone, write a one-sentence deliverable — the thing that, when true, means the milestone ships. Not a list of issues. One sentence.

Examples:

- `v0.2 — Materials Viewer` — "The user can browse, filter, and preview their materials library from a single page without leaving the app."
- `v1.0 — GA` — "External users can install, configure, and run the pipeline on their own data without operator support."

If you can't write the sentence, the milestone is a bag of issues, not a release.

### 7. Future arc — what's next after the current horizon?

*Goal: the board shows something beyond the next release.*

Beyond the current milestone or strategic issue, what's the next 6–12 months?

- Is there a strategic issue capturing the longer-term arc? If not, propose filing one.
- Are there distant-horizon items that should exist as "someday" issues so they're not forgotten?
- Major shifts coming — open-source launch, hosted service, platform expansion — that need a placeholder to grow into?

Distant-horizon items are allowed to be vague. They exist so that when someone later says "remember when we thought about X?", the answer is "yes, #N, go look."

## After the review — propose, don't apply

Bundle findings into a proposal document:

```
Structural review YYYY-MM-DD:

Shape: [findings]
Phasing: [findings + proposed changes]
Milestones: [list, with proposed dates and deliverables]
Dependencies: [graph summary, proposed fixes]
Metadata: [bulk fixes proposed]
Deliverables: [per-milestone one-sentence]
Future arc: [strategic issues proposed]

Open questions for user:
- ...
- ...

Approve which bundles?
```

Wait for the user to approve before executing bulk changes. A structural review that silently reshapes a board is indistinguishable from chaos.

## Executing approved changes

Once approved, execute in order:

1. Fix cycles and hard bugs in dependencies.
2. File new strategic issues and milestones.
3. Assign issues to milestones.
4. Fix metadata drift in bulk.
5. Close obsolete items with explanatory comments.
6. Migrate if splitting (see `references/new-board.md`).
7. Update `docs/project-board.md` if conventions changed.
8. Close with a handoff summary — a Session note on the most-strategic open issue, or a new issue if none exists.

## When to run a structural review

- After a major release ships and the next phase's shape isn't obvious
- When routine sweeps keep flagging issues that feel foundational
- When the user asks "what's the shape of this project?" or "are we working on the right things?"
- Once a quarter for active projects, just to keep the mirror honest
- When the board reaches a size (50+ open items) where tactical grooming can't address shape

Not every week. Not on a schedule. When the project calls for it.
