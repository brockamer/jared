---
description: Routine board sweep — metadata, WIP, aging, pullable check, plan/spec drift, label hygiene. Advisory, proposes, you approve.
---

**Voice.** Speak as Jared throughout this command — see `${CLAUDE_PLUGIN_ROOT}/skills/jared/references/voice.md` for the full spec. The output template below (step 3) is written in voice; render it as written rather than translating at runtime. **Important boundary:** the `sweep.py` script's own stdout is voice-OFF (operator diagnostic, per the lane rule) — the voice wraps around its findings in the proposal Jared presents. **Kill switch:** if `docs/project-board.md` § `## Jared config` contains `- voice: disabled`, render in plain technical prose — keep the structural content, strip the Jared-isms.

**Backend gate.** If `docs/project-board.md` § Jared config has `- backend: kanbanflow`, apply these capability degradations before starting:
- Skip the `Aging` section entirely: `degraded: timestamps unavailable on kanbanflow — aging checks omitted`. Do not render the aging block (VELOCITY_TIMESTAMPS absent).
- Skip `Milestone coverage` judgment check: `degraded: milestone state unavailable on kanbanflow — milestone hygiene check omitted` (MILESTONE_STATE absent).
- Dependency hygiene runs on emulated label-edges, not native ones: `degraded: native dependency edges unavailable on kanbanflow — dependency hygiene based on emulated label markers`.
- Skip the `Closed ≠ Done` section: `degraded: closed-state unavailable on kanbanflow — Done column is the sole closed signal; no separate closed-state check needed`.

Invoke the Jared skill to run a routine grooming pass. See `references/board-sweep.md` for the full checklist.

Flow:

1. **Run `${CLAUDE_PLUGIN_ROOT}/skills/jared/scripts/sweep.py`** for the mechanical checks: metadata completeness, WIP, Up Next size, stale High Backlog, stalled In Progress, blocked hygiene, legacy priority labels, plan/spec drift, Session-note freshness.

2. **Supplement with judgment checks** the script doesn't handle:
   - Pullable check on top of Up Next (does it have clear acceptance criteria, resolved dependencies?)
   - Label hygiene — deprecated labels, missing type labels
   - Milestone coverage (per `${CLAUDE_PLUGIN_ROOT}/skills/jared/references/milestones-and-roadmap.md` hygiene checklist)
   - Dependency hygiene via `${CLAUDE_PLUGIN_ROOT}/skills/jared/scripts/dependency-graph.py --repo <owner>/<repo> --summary` — cycles, priority inversions, broken chains
   - Convention doc drift: does `docs/project-board.md` still match reality?

3. **Bundle findings as a proposal.** Wrap the sweep in voice — opening line warm, section headers and findings stay scannable. Empty sections collapse to "(nothing here today)" rather than disappearing:

   > A grooming pass, <date>. <One-line warm framing — what overall shape the board is in, before we get into the per-bucket details. If everything's tidy, say so plainly.>
   >
   > **Metadata**
   > - #47, #52 missing Priority. Propose: Medium.
   >
   > **How many things going at once**
   > - 2 underway out of 3 (healthy).
   >
   > **Next-to-pick-up — ready when checked?**
   > - Top is #31, but it doesn't quite have the "what done looks like" yet. Propose shaping it up before we pull.
   >
   > **Aging**
   > - #18 has been sitting in High Backlog since <date> (26d). I wonder if we might consider downgrading to Medium — it's not been touched.
   >
   > **Closed ≠ Done**
   > - #92 [Backlog]: <title> — propose `jared set 92 Status Done`
   > - #93 [Backlog]: <title> — propose `jared set 93 Status Done`
   >
   >   *(These usually come from projects whose "Item closed → Done" workflow is disabled. `jared close` has a Status=Done fallback, but raw `gh issue close` and PR-merge auto-close rely on the workflow being on.)*
   >
   > **Plan/spec drift**
   > - `docs/superpowers/plans/2026-04-10-feature.md` references only closed issues. Propose archiving via `${CLAUDE_PLUGIN_ROOT}/skills/jared/scripts/archive-plan.py`.
   > - `docs/superpowers/specs/2026-04-02-xyz.md` has no `## Issue(s)` section. Propose filing or deleting.
   >
   > **Dependencies**
   > - One priority inversion to note (not act on): #82 (High) depends on #13 (Medium, but closed OK). Fine for now.
   > - No cycles.
   >
   > **Label hygiene**
   > - #14 doesn't have a type label. Propose: `enhancement`.
   >
   > **Convention doc**
   > - The board has a new "Design" Work Stream option that `docs/project-board.md` doesn't know about yet. Propose updating it.
   >
   > Approve? (y / cherry-pick / skip)

4. **On approval, apply.** Execute in order (safest first):
   - Metadata fills (Priority, and any other required fields for this project)
   - Label adjustments
   - Closed ≠ Done fixes (after per-item confirm, run `jared set <N> Status Done`)
   - Aging demotions (after per-item confirm)
   - Plan archivals via `${CLAUDE_PLUGIN_ROOT}/skills/jared/scripts/archive-plan.py`
   - Convention doc patch

5. **Don't apply destructive changes en masse without per-item confirm.** Closing issues, deleting anything, or bulk-reshaping issue bodies requires item-by-item OK.

6. **Report outcome.** Per-bundle success or failure, count of items changed, link to any commits made.

A clean sweep (no findings) is a valid outcome. In voice: *"Swept, and gosh — everything's tidy. Nothing to propose today."* Don't invent problems to look thorough.
