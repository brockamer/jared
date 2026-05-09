---
description: End of session — append Session notes to touched issues, reconcile drift, propose plan archivals, file discovered scope.
---

Invoke the Jared skill to wrap the current session. The session record lives on the touched issues as Session-note comments — no `tmp/` file is written, and no handoff prompt is synthesized. The next session uses `/jared-start`, which assembles the posture on-demand from current board state.

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

   **Pre-flight redaction.** Session notes and `## Current state` updates posted via `jared comment` are scanned by the same pre-flight as `jared file`. Drafts referencing private content from `CLAUDE.local.md` will be refused on post — fix the draft, don't fight the redactor. See `references/pii-pre-flight.md`.

3. **Reconcile drift.** Before posting, check for:
   - In Progress items that were actually completed → propose closing
   - In Progress items that were abandoned → propose moving back to Up Next or Backlog with the Session note explaining why
   - Scope discovered but not filed → propose filing new issues now (can use `/jared-file`-style flow inline). New issue bodies must include the `## Model & execution guidance` section per SKILL.md § "Model & execution guidance" — file-time is the contract; the start-time backstop is a fallback. Skip the section when `- model-guidance: disabled` appears in `## Jared config` of `docs/project-board.md`.
   - Plans/specs whose issues just closed → propose archival via `${CLAUDE_PLUGIN_ROOT}/skills/jared/scripts/archive-plan.py`
   - **Doc-sync flag (advisory).** For each touched issue, scan its merged PRs (or unpushed commits) — if code changed but no `.md` outside `docs/sessions/` was touched, surface: *"#N's PR touched code but no doc surface — was a doc update relevant?"* Flag, do not enforce. Most well-maintained projects pair code with doc updates by convention; the flag prompts the human to confirm rather than gates the wrap on it.

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
   - Post Session note comments: for each issue, pipe the note to
     `${CLAUDE_PLUGIN_ROOT}/skills/jared/scripts/jared comment <N> --body-file -`
   - Apply reconciliation: `jared close <N>` for completed items, `jared move <N> "Backlog"` (or `"Up Next"`) for abandoned ones, `jared file ...` for newly-filed scope
   - Run `${CLAUDE_PLUGIN_ROOT}/skills/jared/scripts/archive-plan.py --scan --repo <owner>/<repo>` for shippable plans
   - Update `## Current state` on issues where it meaningfully changed this session via `${CLAUDE_PLUGIN_ROOT}/skills/jared/scripts/capture-context.py`

6. **Confirm and close out.** Print a one-line summary: *"Wrapped N issues, filed N new, archived N plans, reconciled N drift items. Next session: `/jared-start`."*

The next session's `/jared-start` invokes `jared next-session-prompt` to assemble the posture from current board state — In Progress with each issue's most recent Session-note one-liner, top of Up Next, recently closed. Because the assembly is on-demand, the recommendation cannot go stale and no `tmp/` artifact accumulates.
