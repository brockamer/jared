---
description: Bootstrap Jared on a project — introspect the board, write docs/project-board.md, run one-time migration of legacy patterns (tmp prompts, drifted plans, legacy labels).
---

Invoke the Jared skill to bootstrap against a project for the first time, or to refresh the setup on an existing project. One-time operation per project.

Flow:

1. **Confirm the project pairing.** Ask:
   - Does this repo already have a paired GitHub Project? If yes, URL?
   - If not, should Jared create one?

2. **Run `${CLAUDE_PLUGIN_ROOT}/skills/jared/scripts/bootstrap-project.py`.**
   ```bash
   ${CLAUDE_PLUGIN_ROOT}/skills/jared/scripts/bootstrap-project.py --url <project-url> --repo <owner>/<repo>
   ```
   This introspects the board's fields and emits `docs/project-board.md` with IDs filled in. For a fresh project, offers to create Status and Priority. Work Stream is optional — useful when the project has multiple distinct categories of work; skipped when it doesn't. For an existing convention doc, shows a diff.

   If the existing `docs/project-board.md` predates the machine-readable bullet block (URL only in a markdown link, Project ID in a code fence, no `- Project URL:` / `- Project number:` / `- Owner:` / `- Repo:` bullets), the script enters **patch mode**: it proposes inserting just the bullet block near the top of the file, preserving all prose and custom sections verbatim. See `references/new-board.md` → "Upgrading an older project-board.md".

3. **Run the migration pass** (see `references/migration.md`). Scan for and propose fixing:

   - **tmp handoff prompts** (`tmp/next-session-prompt-*.md`, `docs/session-prompts/*`, anything matching the pattern) — propose filing content as retro Session notes on referenced issues, or as new issues for unfiled scope, then delete the source files.

   - **Plan/spec drift** in `docs/superpowers/plans/` and `docs/superpowers/specs/`:
     - Plans without `## Issue` sections → propose filing issues or deleting
     - Plans whose issues are all closed → propose archiving via `${CLAUDE_PLUGIN_ROOT}/skills/jared/scripts/archive-plan.py`
     - Specs in the same state → same treatment

   - **Legacy priority labels** (`priority: high`, `priority: med`, `priority: low`) — propose stripping from open issues.

   - **Plan-conventions drift:** if `docs/plan-conventions.md` exists without the `## Issue` requirement or "After the plan ships" section, propose patching from `assets/plan-conventions.md.template`.

   - **Missing `archived/` directories** for plans and specs — propose creating with READMEs.

   - **Issue body reshaping** for In Progress and Up Next items missing `## Current state` or `## Decisions` sections — propose reshaping. Existing body content gets moved into a `## Legacy body` subsection or into `<details>`; nothing is destroyed.

   - **Retroactive Session notes** for In Progress issues with no recent Session note — propose drafting from recent commits and any handoff prompts being migrated. Mark as `## Session YYYY-MM-DD (reconstructed)`.

4. **Present the migration proposal in one consolidated bundle:**

   ```
   Migration proposal for <repo>:

   1. Bootstrap: <summary of changes to docs/project-board.md>
   2. tmp handoff prompts: <N found, proposed disposition>
   3. Drifted plans: <N found, proposed disposition>
   4. Legacy priority labels: <N issues affected>
   5. plan-conventions.md patch: <yes/no>
   6. Archived directories: <create/already exist>
   7. Issue body reshaping: <N issues>
   8. Reconstructed Session notes: <N issues>

   Plus specific items the user should manually review or delete:
     - <path>: <reason>
     - <path>: <reason>

   Approve bundles to execute, cherry-pick, or discuss?
   ```

5. **Execute approved bundles in order.** Commit the migration as a single commit with a detailed message so the diff is reviewable and reversible (see `references/migration.md` for rollback).

6. **Post-migration sweep.** Run `${CLAUDE_PLUGIN_ROOT}/skills/jared/scripts/sweep.py` to confirm the board is clean. Report residuals.

7. **Close with the standard session-start orientation** so the user sees the board in its new steady state.

This is a one-time event per project. From here on, routine discipline (`/jared-wrap`, `/jared-groom`, triggers) keeps the project in shape without another migration.

## Surfaces jared-init does NOT bootstrap

Jared bootstraps the **board convention doc** and migrates board-adjacent legacy patterns. It does not author other Claude Code surfaces — those belong to sibling skills. When `/jared-init` notices a missing surface outside its lane, defer to the appropriate skill rather than offer to write it:

| Missing surface | Defer to | Skill / command |
|---|---|---|
| `CLAUDE.md` not present | `/init` (the built-in command) | n/a (built-in) |
| `CLAUDE.md` audit / quality / improvements | `claude-md-improver` skill | `claude-md-management:claude-md-improver` |
| `~/.claude/settings.json`, hooks, env vars | `update-config` skill | `update-config` |
| Keybindings / chord shortcuts | `keybindings-help` skill | `keybindings-help` |
| Auto-memory entries | (system-managed; no skill writes here) | n/a |

The discipline is mutual: those skills don't write to the project board, and Jared doesn't write to the surfaces they own. Two writers diverge. See `SKILL.md` § "The lane" for the broader contract.

Install as a user-scope plugin (`/plugin install jared`) so `/jared-init` is available in any project you touch.
