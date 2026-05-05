---
description: File a new issue with full metadata — create + add to board + Priority + Status + any other required project fields, all atomically via `jared file`.
---

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
   - `## Model & execution guidance` — classify the work into Cheap (Haiku-class) / Standard (Sonnet-class) / Smart (Opus / `advisor()`) tiers, name subagent dispatch hints (`Explore`, `general-purpose`, `claude-code-guide`, `advisor()`), and outline a short Execution sketch. See SKILL.md § "Model & execution guidance" for the rendered example. Skip this section if the project's `docs/project-board.md` has `- model-guidance: disabled` in `## Jared config`.
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

7. **Report.** Show the issue URL and the CLI's confirmation line. Note
   whether `## Planning` references exist.

Defaults when the user doesn't specify:

- Status: Backlog (always set — never leave as None)
- Priority: Medium (if the user doesn't name one)
- Other required fields (e.g., Work Stream): ask — never guess
- Labels: infer from content (e.g., "fix" → `bug`, "add" → `enhancement`,
  "refactor X" → `refactor`)

Do not file without Status, Priority, and all required project fields set.
An issue without required field values sorts to the bottom and disappears.
