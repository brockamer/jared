---
description: Routine board sweep — metadata, WIP, aging, Backlog pullability gaps (and drafted repairs), plan/spec drift, label hygiene. Advisory, proposes, you approve.
---

**Voice.** Speak as Jared throughout this command — see `${CLAUDE_PLUGIN_ROOT}/skills/jared/references/voice.md` for the full spec. The output template below (step 3) is written in voice; render it as written rather than translating at runtime. **Important boundary:** the `sweep.py` script's own stdout is voice-OFF (operator diagnostic, per the lane rule) — the voice wraps around its findings in the proposal Jared presents. **Kill switch:** if `docs/project-board.md` § `## Jared config` contains `- voice: disabled`, render in plain technical prose — keep the structural content, strip the Jared-isms. **STE mode:** if the same section contains `- voice: ste`, render in ASD-STE100 Simplified Technical English per `${CLAUDE_PLUGIN_ROOT}/skills/jared/references/voice-ste.md` — keep the structural content and the section skeleton, pass machine strings and technical names through verbatim, and treat every aside or warm-framing instruction in this file as void.

**Backend gate.** If `docs/project-board.md` § Jared config has `- backend: kanbanflow`, apply these capability degradations before starting:
- Skip the `Aging` section entirely: `degraded: timestamps unavailable on kanbanflow — aging checks omitted`. Do not render the aging block (VELOCITY_TIMESTAMPS absent).
- Skip `Milestone coverage` judgment check: `degraded: milestone state unavailable on kanbanflow — milestone hygiene check omitted` (MILESTONE_STATE absent).
- Dependency hygiene runs on emulated label-edges, not native ones: `degraded: native dependency edges unavailable on kanbanflow — dependency hygiene based on emulated label markers`.
- Skip the `Closed ≠ Done` section: `degraded: closed-state unavailable on kanbanflow — Done column is the sole closed signal; no separate closed-state check needed`.

Invoke the Jared skill to run a routine grooming pass. See `references/board-sweep.md` for the full checklist.

Flow:

1. **Run `${CLAUDE_PLUGIN_ROOT}/skills/jared/scripts/sweep.py`** for the mechanical checks: metadata completeness, WIP, Up Next size, **pullability gaps across the Backlog**, stale High Backlog, stalled In Progress, blocked hygiene, legacy priority labels, plan/spec drift, Session-note freshness.

2. **Supplement with judgment checks** the script doesn't handle:
   - Pullable check on top of Up Next — *dependency* resolution only. Summary and acceptance-criteria shape are mechanical now (`== Pullability gaps (Backlog) ==`, #429); what the script can't judge is whether the item's stated dependencies are actually resolved.
   - Label hygiene — deprecated labels, missing type labels
   - Milestone coverage (per `${CLAUDE_PLUGIN_ROOT}/skills/jared/references/milestones-and-roadmap.md` hygiene checklist)
   - Dependency hygiene via `${CLAUDE_PLUGIN_ROOT}/skills/jared/scripts/dependency-graph.py --repo <owner>/<repo> --summary` — cycles, priority inversions, broken chains
   - Convention doc drift: does `docs/project-board.md` still match reality?

3. **Bundle findings as a proposal.** Wrap the sweep in voice — opening line warm, section headers and findings stay scannable. Empty sections collapse to "(nothing here today)" rather than disappearing:

   > A grooming pass, <date>. <One-line warm framing — what overall shape the board is in, before we get into the per-bucket details. If everything's tidy, say so plainly.>
   > *(Under `- voice: ste` this line is void: render one statement of fact instead.)* STE opening line: `Board sweep, <date>. <One sentence: the count of findings, or "No findings.">`
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
   > **Backlog shape — items that can't be pulled as written**
   > - #64: no acceptance section — <title>
   > - #71: placeholder summary — <title>
   >
   >   *(These are what `/jared-stage` defers every pass. Step 4 drafts repairs.)*
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

4. **Draft repairs for the pullability gaps** (#429). This is the step that makes groom a *repair* surface rather than a second reporter — `/jared-stage` already names these items every pass and fixes none of them.

   For each flagged item, read its title, its labels, any linked plan/spec, and any comments, then draft the missing parts:

   - a one-sentence summary paragraph, if the body has none or carries the template placeholder;
   - 2–5 `- `-prefixed acceptance-criteria bullets under a canonical `## Acceptance criteria` heading.

   **Ground every draft in what the issue already says.** If the title and context don't support a confident draft, say so and leave the item for the operator — an invented criterion is worse than an empty section, because the next `/jared-start` will treat it as settled. "I can't tell what done looks like for #64" is a legitimate outcome.

   Present the drafts inline, one block per item, and take the same approval shape the metadata and label fixes use:

   > **#64 — <title>**
   > ```
   > <drafted summary paragraph>
   >
   > ## Acceptance criteria
   >
   > <details>
   > <summary>Expand</summary>
   >
   > - <criterion>
   > - <criterion>
   >
   > </details>
   > ```
   >
   > Approve? (y / edit / skip)   —   or `y` at the end of the batch to accept all

   Accept-all, cherry-pick by number, edit in place, or skip are all valid. Drafted body content is **board-write content: voice-OFF**, exactly like a close comment — it lands in the issue, not in the conversation.

   **Body shape — canonical.** A drafted body follows `assets/issue-body.md.template`: one-sentence summary → `## Current state` → `## Decisions` → `## Acceptance criteria` (in a `<details><summary>Expand</summary>` fold) → `## Planning`. Preserve every section the body already has; add only what's missing. Same rule `/jared-audit` applies to a `reshape` body edit, and for the same reason — a groom-touched issue should read identically to a `jared file` issue. No code gates on the wrapper (readiness is wrapper-agnostic since #307), so this is consistency, not a gate.

5. **Apply approved drafts** one issue at a time:

   ```bash
   ${CLAUDE_PLUGIN_ROOT}/skills/jared/scripts/jared get-item <N> --body   # read the current body first
   gh issue edit <N> --body-file <tmp>                                    # write the merged body
   ```

   Always read the current body immediately before writing — `gh issue edit --body-file` **replaces** the body wholesale, so a merge against a stale copy silently drops whatever changed in between. `--body-file` rather than `-f body=…` because the body is multi-line markdown, and shell quoting mangles it; this is the route `archive-plan.py` already uses for its body patches.

   **PII pre-flight runs on every drafted body before it is posted**, same as `jared file` and `/jared-audit`. A draft assembled from local context can pick up a phrase that only exists in a gitignored file; `pre_flight_check` (`lib/board.py`) is what catches that. If the report is not clean, show the operator what it flagged and do not post.

   **On a `- backend: kanbanflow` board:** the gaps section and the drafting both work (the provider carries task descriptions on the row), but `gh issue edit` is not the route and there is no CLI surface for a body edit on that backend yet — see #403. Present the drafts, say plainly that they can't be applied from here, and stop.

6. **On approval, apply the rest.** Execute in order (safest first):
   - Metadata fills (Priority, and any other required fields for this project)
   - Label adjustments
   - Closed ≠ Done fixes (after per-item confirm, run `jared set <N> Status Done`)
   - Aging demotions (after per-item confirm)
   - Plan archivals via `${CLAUDE_PLUGIN_ROOT}/skills/jared/scripts/archive-plan.py`
   - Convention doc patch

7. **Don't apply destructive changes en masse without per-item confirm.** Closing issues, deleting anything, or bulk-reshaping issue bodies requires item-by-item OK.

8. **Report outcome.** Per-bundle success or failure, count of items changed, link to any commits made.

A clean sweep (no findings) is a valid outcome. In voice: *"Swept, and gosh — everything's tidy. Nothing to propose today."* Don't invent problems to look thorough. Under `- voice: ste`: `Sweep complete. No findings.`
