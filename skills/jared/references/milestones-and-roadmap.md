# Milestones and the Roadmap View

GitHub Projects v2 has a **Roadmap view** that visualizes issues on a time axis by milestone. Used well, it gives you a roadmap visualization for free — no Gantt tool, no separate PM app. Used poorly, milestones are noise.

## When to create a milestone

Create when there is a **coherent cut of work** with:

- A **target date** (approximate is fine — set it and revise as you learn)
- A **human-meaningful name** describing what ships
- **At least 3 issues** that belong to it
- A **one-sentence deliverable** that proves it's done

Don't create for:

- A single issue (the issue itself is the unit)
- "Things I might do someday" (that's the Backlog)
- Arbitrary sprints with no shipping boundary

## Naming convention

**Good:**
- `v0.1 — Containerized Deploy`
- `v0.2 — Materials Viewer (retires rclone)`
- `v1.0 — General Availability`
- `2026-Q2 — Generalization Foundations`
- `Phase 1 — Demo` (for a house-renovation board)

**Bad:**
- `Milestone 1`, `Milestone 2` (what ships?)
- `Cleanup` (what kind?)
- `TBD` (then file it when you know)

A reader glancing at the Roadmap view should understand what each milestone delivers without clicking in.

## The deliverable sentence

Every milestone has a one-sentence deliverable in its description field. Not a task list — one sentence describing the state of the world when it ships.

- `v0.2 — Materials Viewer` → "The user can browse, filter, and preview their materials library from a single page without leaving the app."
- `Phase 1 — Demo` (renovation) → "All walls and flooring removed, studs exposed, ready for rough-in."

If you can't write the sentence, the milestone is a bag of issues, not a release. Either write it or delete the milestone.

## Target dates

Set a date even if uncertain. A rough date ("end of May") beats no date — the Roadmap view uses dates to lay things out, and un-dated items bunch or hide.

Revise as you learn. Milestones are plans, not promises. Sliding a date is normal; leaving it blank is the failure mode.

```bash
gh api --method PATCH repos/<owner>/<repo>/milestones/<number> \
  -f due_on="2026-05-15T00:00:00Z"
```

## Assigning issues

Every issue in a near-term milestone should know it. Every milestone issue should:

- Have Priority (High = must ship, Medium = should ship, Low = stretch)
- Have any other required fields the project defines (e.g., Work Stream if it's in use)
- Reference its milestone via the GitHub milestone field (not via body convention — the field is canonical)

```bash
gh issue edit <number> --repo <owner>/<repo> --milestone "v0.2 — Materials Viewer"
```

## Setting up the Roadmap view

On the GitHub Project board:

1. Go to `github.com/users/<owner>/projects/<N>` (or `/orgs/<owner>/projects/<N>`)
2. Click the `+` next to existing views
3. Pick **Roadmap**
4. Configure:
   - **Layout:** Horizontal (time axis)
   - **Field for dates:** `Milestone due date`
   - **Group by:** Work Stream or Priority
   - **Color by:** Priority
5. Save the view

Every milestoned, dated issue appears. Unmilestoned or undated issues don't — that's the nudge.

## Hygiene during a sweep

- [ ] Every near-term milestone (next 1–2) has a target date.
- [ ] Every near-term milestone has a one-sentence deliverable.
- [ ] Every open issue in a near-term milestone has Priority and any other fields the project requires (e.g., Work Stream, if defined).
- [ ] Open/closed ratio is credible for the date.
- [ ] No issue in a shipped milestone is still open.
- [ ] The Roadmap view renders without gaps — if empty, issues aren't properly milestoned.

## Closing a milestone

When all issues are closed and the release shipped:

```bash
gh api --method PATCH repos/<owner>/<repo>/milestones/<number> -f state="closed"
```

Don't reopen closed milestones. If a post-ship bug needs tracking, file in the next milestone.

## When a milestone slips

Milestones slip. Handle it:

1. **Acknowledge in a comment** on the strategic issue (or on the milestone's top issue). Don't slide the date silently.
2. **Update the target date** to a realistic estimate.
3. **If the slip is large (>2 weeks or >50% of original duration)**, re-evaluate scope: can anything move to a later milestone to ship this one faster?
4. **If structural** (the milestone was always too ambitious), that's a signal — flag it to the user.
