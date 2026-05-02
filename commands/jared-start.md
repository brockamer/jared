---
description: Begin work on an issue — move to In Progress, load full context (body, latest Session note, linked plan/spec), announce the session plan.
---

Invoke the Jared skill to start work on an issue. Takes an optional argument: the issue reference (number or URL).

Argument parsing: `$ARGUMENTS` may contain `#14`, `14`, a URL, a short string like "the excluded employers issue", or be empty. Resolve to a specific issue number, asking to clarify if ambiguous.

Flow:

1. **Look for the most recent handoff prompt.** Glob `tmp/next-session-prompt-*.md`. The filename's `YYYY-MM-DD-HHMM` is monotonic, so lex-sort descending and take the first match. If no match, set `prompt = None` and skip to step 2.

   When a prompt is found, parse the following sections by `##` headers (omit any missing section — never fabricate):
   - **Frame** — content under `## Frame`. Condense to 2–3 sentences if longer.
   - **Anti-targets** — bullets under `## What NOT to do`.
   - **Context pointers** — bullets under `## Context you'll need`.
   - **Recommended issue** — within the section under `## To start`, find a fenced code block containing a line matching `/jared-start\s+(\d+)` and capture the number.
   - **Relative time** — parse the filename's `YYYY-MM-DD-HHMM` and render relative to now ("6h ago", "yesterday", "3d ago"). Fall back to the absolute timestamp on parse failure.

   Resolve the target issue:
   - If `$ARGUMENTS` is non-empty: use it. No drift check on the prompt's recommendation.
   - If `$ARGUMENTS` is empty AND a recommended issue was parsed: drift-check by running `${CLAUDE_PLUGIN_ROOT}/skills/jared/scripts/jared get-item <N>`. If the issue is closed on GitHub or its Status is `Done`, the recommendation is stale — output the **posture block** (see step 6) followed by:

     ```
     Handoff prompt recommends #<N>, but #<N> is now <closed|Done>.
     The prompt's posture is still useful context for whatever you pull next.

     Which issue would you like to pull?
     ```

     Wait for user input, then resume the flow at step 2 with the user-supplied issue. If the recommended issue is pullable, set it as the target and continue.

   - If `$ARGUMENTS` is empty AND no recommended issue was parseable (or no prompt found): ask which issue. When a prompt was found but had no parseable `## To start`, the posture block is still surfaced in step 6.

2. **Check WIP.** Run `${CLAUDE_PLUGIN_ROOT}/skills/jared/scripts/jared summary` and read the `In Progress (N)` header — that `N` is the current count. If it's already at the project's configured cap (default 3), STOP and ask what moves out or pauses. Do NOT silently exceed WIP.

3. **Check pullable state.** Read the target issue's body and verify:
   - First paragraph is a clear summary
   - `## Acceptance criteria` is populated (not empty or placeholder)
   - `## Depends on` — all referenced issues are closed or already done
   If any is missing, pause and propose reshaping the issue first. Pullable is a discipline, not a formality.

4. **Move to In Progress.** One call:

   ```bash
   ${CLAUDE_PLUGIN_ROOT}/skills/jared/scripts/jared move <N> "In Progress"
   ```

5. **Load context.** Fetch:
   - Full issue body (including `## Current state`, `## Decisions`, acceptance criteria in `<details>`)
   - Most recent Session note comment (matches `## Session YYYY-MM-DD` header)
   - Any plan or spec linked from `## Planning` — read and summarize
   - Git state: current branch, uncommitted changes, last 5 commits touching related files

6. **Run tied-issues pre-pull analysis.** Run:

   ```bash
   ${CLAUDE_PLUGIN_ROOT}/skills/jared/scripts/jared ties <N>
   ```

   Capture stdout. If non-empty, prepend it as a "Ties to consider" block at the top of the announce, before the per-issue summary. If exit code is non-zero or stdout is empty, suppress the block and proceed.

   The block is **advisory** — never gate the start on tie resolution. Operators may close superseded predecessors, sequence feeders first, fold same-file issues into the target's PR, or ignore the block entirely. Each tie carries a confidence tag (`strong` / `medium` / `weak`) and a heuristic suggested action.

7. **Announce the session plan.** When a prompt was found in step 1, prepend a **posture block**:

   ```
   Handoff posture (tmp/next-session-prompt-<TIMESTAMP>.md, <relative-time>):
     Frame: <Frame, condensed to 2-3 sentences>
     Anti-targets:
       - <bullet from "What NOT to do">
       - ...
     Context pointers:
       - <bullet from "Context you'll need">
       - ...
   ```

   Then the per-issue announcement:

   ```
   Starting #<N>: <title>

   Summary: <first paragraph>

   Last Session note (YYYY-MM-DD):
     Next action: "<from note>"
     Gotchas: <if any>
     State: <if any>

   Plan/spec: <path if any, one-line summary>

   Acceptance criteria:
     - <criterion 1>
     - ...

   Proposed plan for this session:
     1. <first concrete step, based on Next action and context>
     2. <second>
     3. <commit / PR boundary>

   Git: branch <name>, <clean | N modified>, last relevant commit <hash> <msg>
   ```

   The posture block is omitted when no prompt was found in step 1. Up to three visually-separated blocks when all are present: cross-issue posture above, ties block (from step 6) next, issue-specific below.

8. **Wait for confirmation** before starting work. User may amend the plan, ask questions, or say "go."

This replaces the pattern of manually reading the issue, the plan, and a handoff prompt before starting. The board + latest Session note + (when present) the most recent handoff prompt is the handoff.
