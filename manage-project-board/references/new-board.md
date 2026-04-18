# When and How to Create a New Board

Creating a new project board is a heavy action — it fragments context, breaks existing workflows, and forces a migration. Don't suggest it lightly. But when it's the right call, making it cleanly matters.

## When to suggest a new board

Strong signals:

1. **Two work streams with no cross-dependencies.** If no issue in Stream A depends on an issue in Stream B (and vice versa), they could be two boards. But check: cross-stream coordination still has value even without hard dependencies.

2. **Board > 100 open items and growing.** At that scale, filtering and visual triage get hard. Split by product line, team, or phase.

3. **Distinct stakeholders.** If one stream is "engineering" and another is "marketing" or "design", and they rarely review each other's items, separate boards let each audience see its relevant surface without noise.

4. **Fundamentally different cadences.** If Stream A ships weekly and Stream B ships quarterly, their columns/priorities/milestones drift on different rhythms. Separate boards let each use its own conventions.

5. **External-project spinoff.** A cohesive set of work that could become its own repo eventually. Give it its own board early as a pre-spinoff signal.

Weak signals (don't split on these alone):

- "The board is getting long" — try grooming before splitting
- "Some items aren't relevant to me" — use filtered views, not separate boards
- "The priorities conflict" — priorities *should* conflict; that's why they're prioritized

## Decision checklist

Before proposing a split:

- [ ] Is there a clear boundary between what would move and what stays?
- [ ] Are the two populations stable (not temporary)?
- [ ] Do the two populations have different users or reviewers?
- [ ] Is the total cost (migration + two boards to maintain) less than the cost of the current friction?

If any is No, propose grooming or filtered views instead.

## How to create a new board

1. **Name it clearly.** `<Project> Pipeline` or `<Area> Roadmap` — scannable.

2. **Create the board:**
   ```bash
   gh project create --owner <owner> --title "<Name>"
   ```
   Capture the returned project number.

3. **Set up the same field structure as the source board.** Minimum:
   - Status field: Backlog / Up Next / In Progress / Done
   - Priority field: High / Medium / Low
   - Work Stream field: (fields specific to the new board's domain)

4. **Document conventions** in a new `docs/<name>-board.md` or at the repo root. Copy the structure from `docs/project-board.md` in the source, adjust field IDs and option IDs for the new board.

5. **Migrate issues:**
   - For each issue that belongs on the new board: `gh project item-remove <old-project> --id <item-id>` then `gh project item-add <new-project> ...`
   - Preserve field values by capturing them before removal and setting them after add.
   - **Do not copy issues** — that duplicates content and fragments history. Move the single canonical issue.

6. **Update cross-references** in remaining issue bodies that link to moved items. `gh issue` URLs stay valid after a project move, but any `Project: <N>` references in issue bodies need updating.

7. **Test:** verify the Roadmap view renders, the Status transitions work, item-add/remove sequences complete without loss.

## Coordinating multiple boards

If you have 2+ boards for the same org / repo:

- **Cross-board dependency references** via body conventions: `Depends on: <owner>/<repo>#N` (cross-project).
- **Keep a meta-issue** on the highest-level board that tracks active work across all boards (pointers, not duplicates).
- **Weekly rollup** during sweeps: a brief summary of In Progress across all boards, posted as a comment on the meta-issue.
- **Don't automate cross-board sync** until you've operated this way for at least a month. Premature automation hides problems.

## Red flags after a split

- Items ping-ponging between boards (wrong home). Accept — item belongs on one board, figure out which, move once.
- Duplicate issues on both boards (usually because someone didn't know the split happened). Close one, link to the other.
- A board with no In Progress item for >2 weeks. Maybe that board is dead. Consolidate back or close it.

## Restructuring (not just splitting)

Sometimes the answer isn't more boards, it's the same board with a different shape:

- Rename columns (Status options) — rare, requires migration effort but sometimes right.
- Add / remove fields — e.g., adding a `Team` field if multi-team work emerges.
- Add / remove work streams — e.g., introducing a new stream as the project grows.

Restructure with the same discipline as any schema change: announce, migrate data, update the convention doc in the same operation.
