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

6. **Confirm and close out.** Print a one-line summary: "Wrapped N issues, filed N new, archived N plans, reconciled N drift items. Ready for next session."

7. **Offer the session handoff prompt.** Read the board's `session-handoff-prompt` config (parse `## Jared config` in `docs/project-board.md`):

   - `never` → skip this step entirely.
   - `always` → produce the prompt without asking.
   - `ask` (default, or absent) → ask: *"Draft a session-start prompt for the next session? (y/n)"* and only proceed on `y`.

   When producing the prompt:

   1. Generate the board-derived skeleton:

      ```bash
      ${CLAUDE_PLUGIN_ROOT}/skills/jared/scripts/jared next-session-prompt --include-session-checks
      ```

      Always pass `--include-session-checks`; the CLI no-ops the section when the board has no `## Session start checks` configured.

   2. Layer **synthesis** on top using this session's conversation context, the Session notes you just posted, and any saved memory entries that surfaced. Fill in the asset template at `${CLAUDE_PLUGIN_ROOT}/skills/jared/assets/next-session-prompt.md.template` (or use it as scaffolding):

      - **Frame** — 1–3 sentences on what shipped, what's load-bearing right now, the strategic posture for next session.
      - **What's likely to want attention this session** — ordered list with reasoning ("#N first because the binding constraint is X, not Y"). Pulls from Up Next + In Progress + your synthesis. If synthesis is thin (short session, few decisions), fall back to a plain priority-ordered bullet list.
      - **What NOT to do** — anti-targets with rationale. Sources: scheduled-agent reminders firing in the future, memory entries flagged as session-applicable, explicit user statements during the wrap (e.g. "don't pursue #X yet, we agreed to wait for the agent fire on Y"). Empty if no anti-targets surfaced.
      - **Context you'll need** — pointers to `CLAUDE.md` / `CLAUDE.local.md`, plan/spec files referenced in active issues' `## Planning` sections, relevant memory entry names.
      - **Quick health check on session start** — present iff the board has `## Session start checks` configured.
      - **To start** — call-to-action: *"`/jared-start <#N>` for the issue you decide to pull."*

   3. Write the result to `tmp/next-session-prompt-<YYYY-MM-DD-HHMM>.md` (timestamp = local time). Use `mkdir -p tmp` if `tmp/` doesn't exist. The file is `.gitignore`d (see `.gitignore`) — ephemeral, regenerated each wrap, never authoritative.

   4. **Archive older handoff prompts.** Only the most recent prompt is consulted by `/jared-start` (lex-sort descending, take first), so prior prompts otherwise pile up indefinitely. After the new file is durably written, move every other top-level `tmp/next-session-prompt-*.md` into `tmp/handoff-archive/`. Archive rather than delete — older prompts are a useful session log for tracing context drift, and disk cost is trivial. Run after the new write so a crash mid-archive can never leave the workspace with no prompt.

      ```bash
      NEW="tmp/next-session-prompt-<NEW-TIMESTAMP>.md"   # the file just written
      mkdir -p tmp/handoff-archive
      for f in tmp/next-session-prompt-*.md; do
        [ -e "$f" ] || continue          # nothing matched the glob
        [ "$f" = "$NEW" ] && continue    # leave the just-written file alone
        mv "$f" tmp/handoff-archive/
      done
      ```

      Idempotent: running `/jared-wrap` twice in a row leaves exactly one top-level prompt and the rest under `tmp/handoff-archive/`.

   5. End the wrap by telling the user: *"Handoff prompt at `tmp/next-session-prompt-<TIMESTAMP>.md`. Pipe it into your next session and clear when ready."*

   **Important contract.** The prompt is **derived**, not authoritative. Session notes on issues, plans, specs, and memory entries are the durable records. The prompt is a one-shot bridge between sessions and is regenerated next wrap. **Do not edit the prompt to record decisions** — capture them on issues, in plans, or as memory entries. The prompt's footer reminds the reader of this; honor it.

The next session's `/jared` or auto-orientation reads these Session notes directly; the handoff prompt is an optional convenience layered on top.
