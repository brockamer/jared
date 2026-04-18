# Milestones and the Roadmap View

GitHub Projects v2 has a **Roadmap view** that visualizes issues on a time axis by milestone. Used well, this gives you a roadmap visualization for free — no Gantt tool, no separate product-management app. Used poorly, milestones are noise.

## When to create a milestone

Create a milestone when there is a **coherent cut of work** with:
- A **target date** (approximate is fine — set it and revise as you learn)
- A **human-meaningful name** describing what ships (`v0.2 — Materials Viewer` is good; `Milestone 2` is not)
- **At least 3 issues** that belong to it

Don't create a milestone for:
- A single issue (the issue itself is the unit)
- "Things I might do someday" (that's the Backlog)
- Arbitrary sprints with no shipping boundary

## Naming convention

**Good milestone names:**
- `v0.1 — Containerized Deploy`
- `v0.2 — Materials Viewer (retires rclone)`
- `v1.0 — General Availability`
- `2026-Q2 — Generalization Foundations`

**Bad milestone names:**
- `Milestone 1`, `Milestone 2` (what ships?)
- `Cleanup` (what kind?)
- `TBD` (then file it when you know)

Human-first: a reader glancing at the Roadmap view should understand what each milestone delivers without clicking in.

## Target dates

Set a target date even if you're uncertain. A rough date ("end of May") is better than no date — the Roadmap view uses dates to lay things out, and items without dates get hidden or bunched.

Revise as you learn. Milestones are plans, not promises. Sliding a date is normal; leaving it blank or never-updated is the failure mode.

### Setting target dates

```bash
gh api --method PATCH repos/<owner>/<repo>/milestones/<number> \
  -f due_on="2026-05-15T00:00:00Z"
```

## Assigning issues to milestones

Every issue in a near-term milestone should know it. Every milestone issue should:
- Have a Priority (High for must-ship, Medium for should-ship, Low for stretch)
- Have a Work Stream
- Reference its milestone in the body's `## Milestone` section *or* just rely on the GitHub milestone field (both is redundant; just use the field)

```bash
gh issue edit <number> --repo <owner>/<repo> --milestone "v0.2 — Materials Viewer"
```

## The Roadmap view (how to set it up)

On the GitHub Project board:

1. Go to `github.com/users/<owner>/projects/<N>`
2. Click the `+` next to the existing views (Board, Table, etc.)
3. Pick **Roadmap**
4. Configure:
   - **Layout:** Horizontal (time axis)
   - **Field for dates:** use `Milestone due date` (requires issues to have milestones)
   - **Group by:** Work Stream (or Priority, depending on what you want to see)
   - **Color by:** Priority
5. Save the view

Once configured, every issue assigned to a milestone with a target date appears on the roadmap. Unassigned or un-dated issues don't appear — that's the nudge to set them up right.

## Milestone hygiene during a sweep

Checklist — run during `board-sweep.md`:

- [ ] Every near-term milestone (next 1–2) has a target date.
- [ ] Every open issue in a near-term milestone has Priority + Work Stream.
- [ ] The open/closed ratio inside the milestone is credible for the date.
- [ ] No issue in a milestone that shipped is still open (close or reassign).
- [ ] The Roadmap view renders without gaps — if it looks empty, issues aren't properly milestoned.

## Closing a milestone

When all issues in a milestone are closed and the release has shipped:

```bash
gh api --method PATCH repos/<owner>/<repo>/milestones/<number> -f state="closed"
```

Don't reopen closed milestones. If a bug shipped that you want to track, open a new issue in the next milestone.

## Cross-project milestones

When you have multiple projects (board A, board B) and a release cuts across both, create matching milestones in each project with identical names and target dates. The Roadmap view is per-project, so you'll see each project's slice — but the naming alignment lets the human holding both views mentally stitch them.

Multi-project *automated* roadmapping isn't something Projects v2 does natively; if you need it, export issue data and render yourself. Out of scope for this skill.

## When a milestone slips

Milestones slip. Handle it:

1. **Acknowledge the slip in a comment on the milestone's strategic issue** (e.g., the roadmap issue that tracks the milestone). Don't just slide the date silently.
2. **Update the target date** to a new realistic estimate.
3. **If the slip is large (>2 weeks or >50% of original duration)**, re-evaluate scope: can anything move to a later milestone to get this one shipped faster?
4. **If the slip is structural** (the milestone was always too ambitious), that's a signal to the user that planning granularity needs work — flag it.
