# Bootstrapping, Splitting, and Restructuring Boards

Two kinds of operations: starting fresh on a project that has no board yet (or no convention doc for an existing board), and splitting a board that's become two projects in disguise.

## Bootstrap — pairing Jared with a new project

When invoked against a repo with no `docs/project-board.md`:

### 1. Confirm the project

Ask the user:

- Does this repo already have a paired GitHub Project? If so, URL?
- If not, should Jared create one?

For solo-dev repos, the typical answer is "there's a project at `github.com/users/<me>/projects/<N>`, please use that." For a fresh initiative (software or otherwise), the answer might be "create one called X."

### 2. Run bootstrap-project.py

```bash
scripts/bootstrap-project.py \
  --url https://github.com/users/<owner>/projects/<N> \
  --repo <owner>/<repo>
```

The script:

1. Calls `gh project view` and `gh project field-list` to introspect the board.
2. Detects missing standard fields (Status, Priority). Offers to create them with Jared's default options if absent. Optionally offers a Work Stream field for projects with multiple distinct categories of work.
3. Writes `docs/project-board.md` with all IDs filled in, following the template at `assets/project-board.md.template`.
4. Prints a summary of what it found and what it created.

For a genuinely blank project (just created), the script proposes creating:

- **Status** field: Backlog / Up Next / In Progress / Done
- **Priority** field: High / Medium / Low
- **Work Stream** field (optional): asks if the project has distinct work categories worth bucketing; if yes, asks for the streams

For existing boards with custom fields, the script preserves them and records them in the convention doc; the user can tell Jared how to interpret any non-standard fields.

### Upgrading an older project-board.md

Projects that were paired with Jared before the machine-readable bullet block existed have a `docs/project-board.md` that carries the project URL only in a markdown link and the Project ID in a code fence, but no `- Project URL:` / `- Project number:` / `- Owner:` / `- Repo:` bullets. The jared CLI's parser tolerates that shape via fallbacks (URL regex, git-remote inference), but the convention doc itself is better off canonical.

Re-running `bootstrap-project.py` on a project whose `docs/project-board.md` is missing any of the five bullets triggers a **patch mode** instead of a full-template rewrite:

1. The script reads the existing doc, detects which bullets are absent, and renders only the five-line bullet block.
2. It writes a `<output>.new` file containing the existing doc with the bullet block inserted just after the H1 heading.
3. It shows a unified diff so you can verify nothing else changed.
4. You approve by `mv`-ing the `.new` over the original (or re-running with `--force`).

All prose, custom sections, code fences, and links are preserved verbatim; only the bullet block is added. After the patch, the doc parses via the canonical path (no fallback code needed), which the unit tests in `tests/test_bootstrap_project_patch.py` pin.

### Auto-move workflow dependency

GitHub Projects v2 has a built-in workflow called "Item closed" that moves items to the Done status whenever their underlying issue/PR closes. Jared's close discipline assumes it's enabled — and `bootstrap-project.py` now queries the project's workflows on init and emits a loud stderr warning when the workflow is off.

Three close paths, one of them safe either way:

| Path | Requires the workflow? |
|---|---|
| `jared close <N>` | No — polls for auto-move, falls back to explicit `Status=Done` |
| `gh issue close <N>` | **Yes** — no fallback |
| PR merge with `Closes #N` | **Yes** — no fallback |

If you run on a project with the workflow off, paths 2 and 3 silently leave items in their pre-close Status column (typically Backlog or In Progress) while GitHub reports them as closed. `sweep.py` / `/jared-groom` detect this (`check_closed_not_done`) and now propose `jared set <N> Status Done` per stuck item — the routine sweep drains the drift instead of just reporting it.

### 3. Optional: scaffold Superpowers-style planning

If the user wants plan/spec artifacts (many software projects do), offer to scaffold:

- `docs/plan-conventions.md` — copy of the version shipped by Jared (see `assets/plan-conventions.md.template`)
- `docs/superpowers/plans/` and `docs/superpowers/specs/` with READMEs
- `docs/superpowers/plans/archived/` directory for shipped plans

For non-software projects (renovation, event planning, etc.), skip this — plans/specs are software-ergonomic, not always worth the overhead.

### 4. Run the first structural review

Once bootstrapped, run `/jared-reshape` (or `references/structural-review.md` manually) to catch any drift between the newly-documented conventions and the board's current state. For a genuinely fresh board, this is a quick no-op. For an existing board that just got its first convention doc, it can surface a lot.

## Non-software projects work identically

A kanban board for renovating a house works identically — the work streams are "Demo", "Rough-in", "Finish"; the issues are "Remove kitchen upper cabinets"; the milestones are "Phase 1 — Demo" with a deliverable "All walls and flooring removed, studs exposed, ready for rough-in."

The only thing Jared does specifically for software projects:

- Links issues to commits and PRs (if a code remote exists)
- Runs pre-PR checks (verifying test status, etc.) before proposing a close
- Suggests plan/spec artifacts

For a non-software project, these behaviors short-circuit. The rest of the discipline (WIP, pullable, aging, session continuity, context capture, structural review) is domain-agnostic.

## When to split a board

Creating a new project board is heavy — it fragments context, breaks existing workflows, forces a migration. Don't suggest lightly.

### Strong signals

1. **Two work streams with no cross-dependencies.** No issue in A depends on an issue in B (and vice versa). But check: cross-stream coordination still has value even without hard dependencies.
2. **Board > 100 open items and growing.** Filtering and visual triage get hard. Split by product line, team, or phase.
3. **Distinct stakeholders.** One stream is "engineering," another is "marketing" or "design," and they rarely review each other's items.
4. **Fundamentally different cadences.** A ships weekly, B ships quarterly — columns/priorities/milestones drift on different rhythms.
5. **External-project spinoff.** A cohesive set of work that could become its own repo eventually. Give it its own board early as a pre-spinoff signal.

### Weak signals (don't split on these alone)

- "The board is getting long" — groom first.
- "Some items aren't relevant to me" — use filtered views, not separate boards.
- "Priorities conflict" — priorities *should* conflict; that's why they're prioritized.

### Decision checklist

Before proposing a split:

- [ ] Clear boundary between what would move and what stays?
- [ ] Are the two populations stable (not temporary)?
- [ ] Do the two populations have different users or reviewers?
- [ ] Is the total cost (migration + two boards to maintain) less than the current friction?

Any No, propose grooming or filtered views instead.

## How to split

1. **Name the new board clearly.** `<Project> Pipeline` or `<Area> Roadmap` — scannable.
2. **Create:**
   ```bash
   gh project create --owner <owner> --title "<Name>"
   ```
3. **Set up fields** matching the source board: Status / Priority, plus any project-specific fields the source uses (e.g., Work Stream, if defined), adjusted for the new domain.
4. **Bootstrap conventions:**
   ```bash
   scripts/bootstrap-project.py --url <new-project-url> --repo <owner>/<repo>
   ```
   Write conventions to `docs/<n>-board.md` (not overwriting the source's).
5. **Migrate issues:** for each issue that belongs on the new board:
   - Capture current field values.
   - `gh project item-remove` from old.
   - `gh project item-add` to new.
   - Re-set field values.
   - **Do not copy issues** — move the canonical issue.
6. **Update cross-references** in remaining issue bodies.
7. **Test:** Roadmap view renders, Status transitions work.

## Coordinating multiple boards

- **Cross-board dependencies** via `<owner>/<repo>#N` references.
- **Meta-issue on the highest-level board** tracking active work across all boards (pointers, not duplicates).
- **Weekly rollup during sweeps** — brief summary of In Progress across boards, posted as a comment on the meta-issue.
- **Don't automate cross-board sync** until you've operated manually for at least a month.

## Red flags after a split

- **Items ping-ponging between boards.** Item belongs on one board — figure out which, move once.
- **Duplicate issues on both boards.** Close one, link to the other.
- **A board with no In Progress for >2 weeks.** Maybe that board is dead. Consolidate back or close it.

## Restructuring (not splitting)

Sometimes the answer is the same board with a different shape:

- Rename columns — rare, requires migration effort.
- Add / remove fields — e.g., adding a `Team` field when multi-team work emerges.
- Add / remove work streams — as the project grows.

Restructure with the same discipline as any schema change: announce, migrate data, update the convention doc in the same operation.
