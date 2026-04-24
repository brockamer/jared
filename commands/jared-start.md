---
description: Begin work on an issue — move to In Progress, load full context (body, latest Session note, linked plan/spec), announce the session plan.
---

Invoke the Jared skill to start work on an issue. Takes an argument: the issue reference (number or URL).

Argument parsing: `$ARGUMENTS` may contain `#14`, `14`, a URL, or a short string like "the excluded employers issue". Resolve to a specific issue number, asking to clarify if ambiguous.

Flow:

1. **Check WIP.** Run `${CLAUDE_PLUGIN_ROOT}/skills/jared/scripts/jared summary` and read the `In Progress (N)` header — that `N` is the current count. If it's already at the project's configured cap (default 3), STOP and ask what moves out or pauses. Do NOT silently exceed WIP.

2. **Check pullable state.** Read the target issue's body and verify:
   - First paragraph is a clear summary
   - `## Acceptance criteria` is populated (not empty or placeholder)
   - `## Depends on` — all referenced issues are closed or already done
   If any is missing, pause and propose reshaping the issue first. Pullable is a discipline, not a formality.

3. **Move to In Progress.** One call:

   ```bash
   ${CLAUDE_PLUGIN_ROOT}/skills/jared/scripts/jared move <N> "In Progress"
   ```

4. **Load context.** Fetch:
   - Full issue body (including `## Current state`, `## Decisions`, acceptance criteria in `<details>`)
   - Most recent Session note comment (matches `## Session YYYY-MM-DD` header)
   - Any plan or spec linked from `## Planning` — read and summarize
   - Git state: current branch, uncommitted changes, last 5 commits touching related files

5. **Announce the session plan.** Output something like:

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

6. **Wait for confirmation** before starting work. User may amend the plan, ask questions, or say "go."

This replaces the pattern of manually reading the issue, the plan, and a handoff prompt before starting. The board + latest Session note is the handoff.
