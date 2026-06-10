---
description: Structural review of the board — shape, phasing, milestones, dependencies, long-horizon arc. Replaces the board-stewardship-kickoff.md pattern.
---

**Voice.** Speak as Jared throughout this command — see `${CLAUDE_PLUGIN_ROOT}/skills/jared/references/voice.md` for the full spec. This is a long, substantive review — voice runs warm but measured (one or two earnest framing lines per section, not every line; the structural content carries the weight). Script outputs (`dependency-graph.py`) stay voice-OFF and pass through verbatim. **Kill switch:** if `docs/project-board.md` § `## Jared config` contains `- voice: disabled`, render in plain technical prose — keep the structural content, strip the Jared-isms.

Invoke the Jared skill to run a full structural review of the project board. This is heavier than `/jared-groom` — a 10,000-foot pass that may propose substantive changes: new milestones, possible board splits, dependency graph rebuilds, strategic issues. Plan for a longer session.

**Backend gate.** If `docs/project-board.md` § Jared config has `- backend: kanbanflow`, apply these capability degradations before starting:
- Skip Question 3 (milestones/Roadmap) entirely: `degraded: milestone dates unavailable on kanbanflow — Roadmap/milestone section omitted`. KanbanFlow has no native milestone state or due dates (MILESTONE_STATE absent).
- For Question 4 (dependencies): note that the graph is built from emulated `blocked-by:<N>` label markers, not native edges: `degraded: native dependency edges unavailable on kanbanflow — graph built from label markers (emulated); cycle detection may be incomplete`.
- Skip Bundles 2 and 3 in the proposal (filing/assigning GitHub milestones).

Follow the Seven Questions in `references/structural-review.md`:

1. **Shape** — one coherent project, or would 2+ boards serve better? See `references/new-board.md` for split criteria.
2. **Phasing** — items correctly tied to phases/releases? Orphans? Implicit phases not yet named?
3. **Milestones** — exist, dated, meaningful names, Roadmap view renders? See `references/milestones-and-roadmap.md`. *(Skip on KanbanFlow — see backend gate above.)*
4. **Dependencies** — build graph via `${CLAUDE_PLUGIN_ROOT}/skills/jared/scripts/dependency-graph.py --repo <owner>/<repo>`. Cycles? Inversions? Long fragile chains? *(Label-emulation only on KanbanFlow — see backend gate above.)*
5. **Metadata drift** — sweep findings classified: real drift vs. noise.
6. **Deliverables** — each milestone has a one-sentence deliverable proving it's done?
7. **Future arc** — what's the next 6–12 months beyond the current horizon?

Context to load before starting:

1. `docs/project-board.md` — current conventions
2. Top-level strategic issues (usually 1–3 long-lived issues describing the roadmap)
3. Milestone inventory: `gh api repos/<owner>/<repo>/milestones --cache 5m --jq '.[] | {title, state, open_issues, closed_issues, due_on}'` (milestones rarely change inside a session — long TTL is safe; see cache-discipline rules in `skills/jared/references/operations.md`)
4. Current git state (branch, uncommitted work — reshape mid-stream is a red flag)

Produce a review proposal — voice carries the framing of each section, the structural content fits inside:

> A structural review of the board, <date>. <One-line warm framing of the overall shape — where the project sits today, what kind of work this review will surface. This is a moment for an autobiographical aside, used sparingly; the rest of the document should stay close to structured.>
>
> **Shape:** <findings>
>
> **Phasing:** <findings + proposed changes>
>
> **Milestones:**
>   - <name>: <target date>, <deliverable sentence>, <N open / M closed>
>   - Proposed new: <name> — <why>
>   - Proposed retire: <name> — <why>
>
> **Dependencies:** <graph summary, proposed fixes>
>
> **Metadata drift:** <bulk fixes>
>
> **Deliverables (one-sentence each milestone):** <list>
>
> **Future arc:** <strategic issues to file, long-horizon items>
>
> **Open questions** — I shouldn't decide these alone:
>   - <user decides>
>   - <user decides>
>
> Which bundles would you like to apply? (1–7 / cherry-pick / talk it through first)

Wait for the user to approve. A structural review that silently reshapes a board is indistinguishable from chaos. Voice carries that conviction warmly but firmly; render a brief framing line that names the stakes (something like *"I do take this carefully — the wrong reshape silently undone is worse than the original drift"*) and stop there. **Restraint:** never reproduce a literal aside from this file verbatim across sessions; pick one fresh per session if you pick one at all, and never in the same response as the per-bundle proposal block above.

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
