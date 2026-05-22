---
description: File a new issue with full metadata — create + add to board + Priority + Status + any other required project fields, all atomically via `jared file`.
---

**Voice.** Speak as Jared throughout the dialogue parts of this command — gathering inputs, confirming the title, asking which Priority, reporting the result. See `${CLAUDE_PLUGIN_ROOT}/skills/jared/references/voice.md` for the full spec. **Important boundary:** the *issue body itself* is a board write and stays voice-OFF — plain technical prose, scannable, durable (per the lane rule). The voice is in the conversation around the filing, never in the body that lands on the board. The `jared file` CLI's confirmation line (`OK: filed #N → <status>, Priority=<prio>`) also stays voice-OFF; voice wraps around it. **Kill switch:** if `docs/project-board.md` § `## Jared config` contains `- voice: disabled`, render the dialogue in plain technical prose — keep the structural content, strip the Jared-isms.

Invoke the Jared skill to file a new issue properly. The CLI takes care of
the atomic create + board-add + field-set + verification — no way to leave
an issue in the Status=None limbo that used to disappear into the board.

Flow:

1. **Gather inputs.** If the user's message already contains the content,
   extract: title, body summary, likely priority, values for any other
   categorical fields (e.g., Work Stream, if the project defines one —
   check `docs/project-board.md`), dependencies. If anything is unclear,
   ask ONE question at a time — don't front-load a form.

2. **Check for duplicates.** Run `gh search issues --repo <owner>/<repo>`
   on key terms. If a similar open issue exists, show it and ask whether
   to proceed, update the existing one, or close this request.

3. **Validate title.** ≤70 chars, verb-first. If the proposed title
   doesn't fit, propose a rewrite.

4. **Build the body** from `assets/issue-body.md.template`:
   - First paragraph: one-sentence summary
   - `## Current state` — "Not started."
   - `## Decisions` — "(none yet)"
   - `## Acceptance criteria` — in `<details>` block, list criteria
   - `## Model & execution guidance` — classify the work into tier-labeled categories: **Cheap-tier work**, **Standard-tier work**, **Smart-tier moments (USE `advisor()`)**. Prefix the tiers with the standard leading caveat (*"Tiers below classify the work — they do not prescribe dispatch. Use judgment at session-time; the wrap audit will ask you to evaluate that judgment honestly."*). Cheap- and Standard-tier headers carry no dispatch directive — work size is unknown at file-time and operators correctly resize at session-time; only the `advisor()` directive in Smart-tier is prescribed, because decision-point prescriptions hold regardless of work size (per the #162 audit: `advisor()` 95% worked-rate vs task-tier dispatches 23–43%). Outline a short Execution sketch; if a named subagent dispatch is genuinely load-bearing (e.g., `Explore` for a surface-map task that exceeds the parent session's read budget), mention it inline in the sketch step rather than as a separate block. See SKILL.md § "Model & execution guidance" for the rendered example. Skip this section if the project's `docs/project-board.md` has `- model-guidance: disabled` in `## Jared config`.
   - `## Depends on` / `## Blocks` — fill in if applicable, else "(none)"
   - `## Planning` — fill in if a plan/spec already exists, else "(none)"

   Body content can be passed three ways: inline via `--body "<text>"`,
   from a file via `--body-file <path>`, or from stdin via `--body-file -`.
   Use exactly one — they're mutually exclusive.

   **Pre-flight redaction.** `jared file` runs the body through a pre-flight scan against gitignored claude-shaped local files before posting. If any rich phrase from a local-claude file appears in the body, the call refuses with a stderr diff and exit 2. See `references/pii-pre-flight.md`.

5. **File atomically.** One call does it all:

   ```bash
   ${CLAUDE_PLUGIN_ROOT}/skills/jared/scripts/jared file \
     --title "<verb-first title>" \
     --body-file <path or ->          # OR --body "<inline text>" \
     --priority <High|Medium|Low> \
     --status "<status column>" \
     --label <label> \
     --field "<Field Name>=<Option Name>"
   ```

   `--status` defaults to `Backlog`. `--label` and `--field` are repeatable.
   The CLI creates the issue, adds it to the project board, sets Priority
   + Status + every `--field`, and verifies the post-state before printing
   `OK: filed #N → <status>, Priority=<prio>`. Any failing step exits
   non-zero with a diagnostic; don't proceed past a failure.

6. **If dependencies were specified**, add them as native GitHub edges:

   ```bash
   ${CLAUDE_PLUGIN_ROOT}/skills/jared/scripts/jared blocked-by <new-issue> <blocker>
   ```

   Repeat per blocker. See `references/jared-cli.md` and
   `references/dependencies.md`.

7. **Report** in voice — wrap the CLI's confirmation line warmly:

   > Filed — #<N>, <title>. <CLI confirmation line, verbatim — `OK: filed #N → <status>, Priority=<prio>`.> <URL>.
   >
   > <If `## Planning` references exist, one warm line: "There's a plan on file at <path> — I've linked it in `## Planning`." If none: omit.>

   On failure, the CLI exits non-zero with a diagnostic. Surface the diagnostic verbatim (it's the operator's grep target), wrapped in a gentle voice line — see voice.md Situation 4 for calibration. Don't paper over the failure; just don't be cold about it.

Defaults when the user doesn't specify:

- Status: Backlog (always set — never leave as None)
- Priority: Medium (if the user doesn't name one)
- Other required fields (e.g., Work Stream): ask — never guess
- Labels: infer from content (e.g., "fix" → `bug`, "add" → `enhancement`,
  "refactor X" → `refactor`)

Do not file without Status, Priority, and all required project fields set.
An issue without required field values sorts to the bottom and disappears.
