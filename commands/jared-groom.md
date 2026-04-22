---
description: Routine board sweep — metadata, WIP, aging, pullable check, plan/spec drift, label hygiene. Advisory, proposes, you approve.
---

Invoke the Jared skill to run a routine grooming pass. See `references/board-sweep.md` for the full checklist.

Flow:

1. **Run `${CLAUDE_PLUGIN_ROOT}/skills/jared/scripts/sweep.py`** for the mechanical checks: metadata completeness, WIP, Up Next size, stale High Backlog, stalled In Progress, blocked hygiene, legacy priority labels, plan/spec drift, Session-note freshness.

2. **Supplement with judgment checks** the script doesn't handle:
   - Pullable check on top of Up Next (does it have clear acceptance criteria, resolved dependencies?)
   - Label hygiene — deprecated labels, missing type labels
   - Milestone coverage (per `${CLAUDE_PLUGIN_ROOT}/skills/jared/references/milestones-and-roadmap.md` hygiene checklist)
   - Dependency hygiene via `${CLAUDE_PLUGIN_ROOT}/skills/jared/scripts/dependency-graph.py --repo <owner>/<repo> --summary` — cycles, priority inversions, broken chains
   - Convention doc drift: does `docs/project-board.md` still match reality?

3. **Bundle findings as a proposal.** Format:

   ```
   Sweep <date>:

   == Metadata ==
   - #47, #52 missing Priority. Propose: Medium.

   == WIP ==
   - In Progress = 2/3 (healthy).

   == Up Next pullable check ==
   - Top is #31 but missing acceptance criteria. Propose reshaping.

   == Aging ==
   - #18 in High Backlog since <date> (26d). Propose downgrade to Medium.

   == Plan/spec drift ==
   - docs/superpowers/plans/2026-04-10-feature.md references only closed issues. Propose archiving via ${CLAUDE_PLUGIN_ROOT}/skills/jared/scripts/archive-plan.py.
   - docs/superpowers/specs/2026-04-02-xyz.md has no ## Issue(s) section. Propose filing or deleting.

   == Dependencies ==
   - Priority inversion: #82 (High) depends on #13 (Medium, closed OK) — note, not action.
   - No cycles.

   == Label hygiene ==
   - #14 has no type label. Propose: enhancement.

   == Convention doc ==
   - Board has new "Design" Work Stream option; docs/project-board.md missing it. Propose update.

   Approve? (y / cherry-pick / skip)
   ```

4. **On approval, apply.** Execute in order (safest first):
   - Metadata fills (Priority, and any other required fields for this project)
   - Label adjustments
   - Aging demotions (after per-item confirm)
   - Plan archivals via `${CLAUDE_PLUGIN_ROOT}/skills/jared/scripts/archive-plan.py`
   - Convention doc patch

5. **Don't apply destructive changes en masse without per-item confirm.** Closing issues, deleting anything, or bulk-reshaping issue bodies requires item-by-item OK.

6. **Report outcome.** Per-bundle success or failure, count of items changed, link to any commits made.

A clean sweep (no findings) is a valid outcome. Say "Swept, all clear" — don't invent problems.
