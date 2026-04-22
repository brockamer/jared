---
description: End of session — append Session notes to touched issues, reconcile drift, propose plan archivals, file discovered scope.
---

Invoke the Jared skill to wrap the current session. Replaces the `tmp/next-session-prompt*.md` pattern entirely.

Flow:

1. **Identify touched issues.** Review the session's history. Collect issues that were:
   - Currently In Progress (always included)
   - Referenced in the conversation by number
   - Linked to recent commits (via `git log` since last Session note)
   - Explicitly named by the user as part of the wrap

2. **Draft a Session note for each.** Use `assets/session-note.md.template`. Pull field content from:
   - **Progress:** recent conversation + git diff + any plan checkboxes ticked
   - **Decisions:** decisions recorded in chat + any `## Decisions` appended to issue bodies this session (reference them rather than duplicating)
   - **Next action:** explicitly stated next step, or inferred from where work paused
   - **Gotchas:** anything non-obvious discovered during work
   - **State:** git branch, clean/dirty working tree, test status

   **Never fabricate.** Empty fields stay empty. If you'd have to guess, ask or leave blank.

3. **Reconcile drift.** Before posting, check for:
   - In Progress items that were actually completed → propose closing
   - In Progress items that were abandoned → propose moving back to Up Next or Backlog with the Session note explaining why
   - Scope discovered but not filed → propose filing new issues now (can use `/jared-file`-style flow inline)
   - Plans/specs whose issues just closed → propose archival via `~/.claude/skills/jared/scripts/archive-plan.py`

4. **Present all drafts consolidated** for user review:

   ```
   /jared-wrap — session end, <date>

   Touched issues: #<list>

   Draft Session note for #14:
     [renders the full draft]

   Draft Session note for #23:
     [...]

   Drift to reconcile:
     - #27 was In Progress but the commits show it's done — propose closing
     - Discovered scope (not yet filed): "logger should retry on 429" — propose filing as new issue
     - Plan docs/superpowers/plans/2026-04-14-xyz.md references only closed issues — propose archiving

   Approve? (y / edit #<N> / skip #<N> / no-drift / no-archive)
   ```

5. **On approval, apply in order:**
   - Post Session note comments (one per issue)
   - Apply reconciliation (close, move, file)
   - Run `~/.claude/skills/jared/scripts/archive-plan.py --scan` for shippable plans
   - Update `## Current state` on issues where it meaningfully changed this session (via `~/.claude/skills/jared/scripts/capture-context.py`)

6. **Confirm and close out.** Print a one-line summary: "Wrapped N issues, filed N new, archived N plans, reconciled N drift items. Ready for next session."

The next session's `/jared` or auto-orientation reads these Session notes directly. No tmp prompt needed.
