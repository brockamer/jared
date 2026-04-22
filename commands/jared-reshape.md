---
description: Structural review of the board — shape, phasing, milestones, dependencies, long-horizon arc. Replaces the board-stewardship-kickoff.md pattern.
---

Invoke the Jared skill to run a full structural review of the project board. This is heavier than `/jared-groom` — a 10,000-foot pass that may propose substantive changes: new milestones, possible board splits, dependency graph rebuilds, strategic issues. Plan for a longer session.

Follow the Seven Questions in `references/structural-review.md`:

1. **Shape** — one coherent project, or would 2+ boards serve better? See `references/new-board.md` for split criteria.
2. **Phasing** — items correctly tied to phases/releases? Orphans? Implicit phases not yet named?
3. **Milestones** — exist, dated, meaningful names, Roadmap view renders? See `references/milestones-and-roadmap.md`.
4. **Dependencies** — build graph via `${CLAUDE_PLUGIN_ROOT}/skills/jared/scripts/dependency-graph.py --repo <owner>/<repo>`. Cycles? Inversions? Long fragile chains?
5. **Metadata drift** — sweep findings classified: real drift vs. noise.
6. **Deliverables** — each milestone has a one-sentence deliverable proving it's done?
7. **Future arc** — what's the next 6–12 months beyond the current horizon?

Context to load before starting:

1. `docs/project-board.md` — current conventions
2. Top-level strategic issues (usually 1–3 long-lived issues describing the roadmap)
3. Milestone inventory: `gh api repos/<owner>/<repo>/milestones --jq '.[] | {title, state, open_issues, closed_issues, due_on}'`
4. Current git state (branch, uncommitted work — reshape mid-stream is a red flag)

Produce a review proposal:

```
Structural review <date>:

Shape: <findings>

Phasing: <findings + proposed changes>

Milestones:
  - <name>: <target date>, <deliverable sentence>, <N open / M closed>
  - Proposed new: <name> — <why>
  - Proposed retire: <name> — <why>

Dependencies: <graph summary, proposed fixes>

Metadata drift: <bulk fixes>

Deliverables (one-sentence each milestone): <list>

Future arc: <strategic issues to file, long-horizon items>

Open questions:
  - <user decides>
  - <user decides>

Approve which bundles? (1–7 / cherry-pick / discuss first)
```

Wait for the user to approve. A structural review that silently reshapes a board is indistinguishable from chaos.

Execute approved bundles in order:

1. Fix cycles and hard bugs in dependencies.
2. File new strategic issues and milestones.
3. Assign issues to milestones.
4. Fix metadata drift in bulk.
5. Close obsolete items with explanatory comments.
6. Migrate if splitting (see `references/new-board.md`).
7. Update `docs/project-board.md` if conventions changed.

Close with a handoff summary — a Session note on the most-strategic open issue, or a new issue if none exists.

When to use:

- After a major release ships
- When routine sweeps keep flagging foundational issues
- When the user asks "what's the shape of this project?" or "are we working on the right things?"
- Quarterly for active projects
- When the board passes ~50 open items and tactical grooming can't address shape

Not weekly, not on a schedule. When the project calls for it.
