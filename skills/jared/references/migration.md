# Migration — One-Time Adoption Pass

When Jared is first invoked on an existing project, the project likely has patterns that predate the discipline. This reference documents what Jared proposes fixing during the first-adoption pass.

Run via `/jared-init` followed by `/jared-reshape`, or directly by asking Jared to "migrate this project."

## The pass, in order

### 1. Bootstrap the convention doc

If `docs/project-board.md` (or PROJECT_BOARD.md, .github/project-board.md) doesn't exist, run `scripts/bootstrap-project.py` to generate it. If it exists but is stale, run with `--diff` to surface drift and propose updates.

### 2. Strip hardcoded values from older convention docs

Older convention docs (like v1 of the manage-project-board skill) sometimes had project-specific IDs embedded. If detected, propose replacing with placeholders.

### 3. Migrate tmp handoff prompts

Scan `tmp/`, `scratch/`, `working/`, and similar directories for files matching patterns like:

- `next-session-prompt*.md`
- `handoff*.md`
- `session-kickoff*.md`
- Anything in `docs/session-prompts/` (the findajob pattern)

For each one:

1. Parse to identify referenced issues.
2. Classify the content:
   - **Recap of work done** → propose filing as a retro Session note on the issue.
   - **Plan for upcoming work** → propose: is there an issue for this? If yes, Session note. If no, file a new issue with the content in the body.
   - **Unfiled scope** → propose filing as new issues.
   - **Stale / superseded** → propose deletion.
3. After processing, delete the source file.

Retro Session notes use the header `## Session YYYY-MM-DD (reconstructed from prompt draft)` so they're not mistaken for real-time notes.

### 4. Migrate plan/spec drift

Scan the plan/spec directories (wherever they live for the project — commonly `docs/superpowers/plans/` and `specs/`).

For each plan:

- **No `## Issue` section** → propose filing an issue that describes the plan's scope. After filing, add the `## Issue` section to the plan and `## Planning` section to the issue.
- **References issues that are all closed** → propose archiving to `archived/YYYY-MM/` with the archival header.
- **References issues that are all closed but plan has never been archived** → same archival proposal.
- **References no longer-existing issues** → investigate: was the issue renumbered? Deleted? Propose a fix.

Same scan for specs.

### 5. Strip legacy priority labels

If the project uses the Priority field but also has legacy `priority: high` / `priority: med` / `priority: low` labels, propose stripping the labels from all open issues. The field is canonical.

`scripts/sweep.py` detects these; follow up with:

```bash
# Remove in bulk (after user approval)
for label in "priority: high" "priority: med" "priority: low"; do
  gh issue list --repo <owner>/<repo> --label "$label" --state open --limit 200 --json number --jq '.[].number' \
    | xargs -I {} gh issue edit {} --repo <owner>/<repo> --remove-label "$label"
done
```

### 6. Update plan-conventions if it exists

If `docs/plan-conventions.md` exists without the `## Issue` requirement or the "After the plan ships" archival section, propose patching it with the Jared-shipped template additions. See `assets/plan-conventions.md.template` for the target state.

The patch is *additive* — preserving existing requirements like Documentation Impact, Verification gate, etc.

### 7. Establish the `archived/` directory

Create `docs/superpowers/plans/archived/` and `docs/superpowers/specs/archived/` (or equivalent) with READMEs explaining the archival convention. This is where the script-based archival routine deposits files.

### 8. Issue body template adoption

For In Progress and Up Next issues, offer to reshape their bodies to include `## Current state`, `## Decisions`, and `## Planning` sections if missing. Existing body content goes into a `## Legacy body` subsection or into the `<details>` block — nothing is destroyed, just reorganized.

Don't do this for Backlog en masse — too noisy. Reshape on-demand when an issue gets promoted to Up Next.

### 9. Session-note kickstart

For every currently-In-Progress issue without a recent Session note:

- Propose drafting a reconstructed Session note based on recent commits, the issue body, and any existing handoff prompts being migrated.
- User reviews each, approves, and Jared posts.

From here on, `/jared-wrap` maintains the discipline.

### 10. Final sweep

After the migration pass, run a full `scripts/sweep.py` to confirm the board is clean. Report any residual issues (items that need human judgment — "this plan references #5 and #6, but #5 is closed and #6 is open; should the plan stay or archive?").

## The migration proposal

Rather than applying these changes serially, Jared bundles them into a single proposal:

```
Migration proposal for findajob (2026-04-19):

1. Bootstrap/reconcile docs/project-board.md: no changes needed (fresh convention doc).

2. tmp/ handoff prompts (7 files found):
     tmp/next-session-prompt-deployment-drift-fix.md
       → references #82 (open). Propose: file as retro Session note.
     tmp/next-session-prompt-migration.md
       → references #44 (closed). Propose: delete.
     tmp/next-session-prompt-phase-b.md, -phase-c.md
       → references #58 Phase 2/3. Propose: Session notes on #58.
     ... etc

3. docs/session-prompts/board-stewardship-kickoff.md:
     → Superseded by /jared-reshape command. Propose: delete.

4. docs/superpowers/plans/ scan (8 active plans):
     2026-04-14-lxc-migration.md → references #78 (closed). Archive.
     2026-04-15-gdrive-sync-audit.md → no ## Issue section. File issue or delete.
     ... etc

5. Legacy priority labels: 3 open issues have them. Strip.

6. docs/plan-conventions.md: missing ## Issue section requirement. Patch.

7. Issue body reshaping: 2 In Progress issues lack ## Current state / ## Decisions. Reshape.

8. Reconstructed Session notes for In Progress: #14, #20. Draft from recent commits.

Approve bundles (1–8) to execute, cherry-pick, or discuss?
```

User approves. Jared executes in order, reporting per-bundle success.

## After migration

The project is in steady state. From here:

- `/jared-wrap` at end of each session.
- `/jared-groom` weekly (or when drift is spotted).
- `/jared-reshape` quarterly (or after major releases / pivots).
- Triggers fire automatically during normal work.

Migration is a one-time event. If the discipline is maintained, the project never needs migrating again — small corrections from sweeps keep it honest.

## Rollback

If anything in the migration goes wrong, the changes are all recoverable:

- Plans moved to `archived/` → `git mv` back.
- Issue bodies reshaped → `git log` finds the pre-change body via `gh issue` API history.
- Labels stripped → re-apply via `gh issue edit --add-label`.
- Files deleted → `git show HEAD^:path/to/file` recovers from the migration commit.

Jared commits the migration as a single commit with a detailed message so the diff is reviewable and reversible.
