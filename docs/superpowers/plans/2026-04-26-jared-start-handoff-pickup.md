# /jared-start handoff-prompt pickup — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Alter `/jared-start` so it looks for the most recent `tmp/next-session-prompt-*.md` and surfaces its synthesis (Frame, anti-targets, context pointers) as a Handoff posture block above the per-issue announcement, honoring the prompt's `## To start` recommendation when no `$ARGUMENTS` is given (with a drift check for stale recommendations).

**Architecture:** This is a **doc-as-code** edit. The "code" is markdown documentation in `commands/jared-start.md` that the model invoking the slash command reads and executes step-by-step. There is no Python implementation, no CLI subcommand, and no automated test layer. The verification surface is (a) reading the modified file end-to-end for coherence, (b) the existing `ruff` + `mypy` invariants (untouched by this change), and (c) live invocation of `/jared-start` in a fresh Claude Code session post-merge.

**Tech Stack:** Markdown command-prompt template only. No Python, no shell, no test framework.

**Spec:** `docs/superpowers/specs/2026-04-26-jared-start-handoff-pickup-design.md` (commit 880e945)
**Issue:** [#44](https://github.com/brockamer/jared/issues/44)

---

## File Structure

This change touches one file. No new files, no deletions.

| Path | Action | Responsibility |
|---|---|---|
| `commands/jared-start.md` | Modify | Add Step 1 (look for handoff prompt + drift check + parse posture sections), modify Step 6 (announcement) to prepend the posture block when a prompt was found, renumber existing Steps 1–6 to 2–7. |

The existing 6-step flow becomes a 7-step flow. Steps shift down by 1; only the new Step 1 is logically inserted, and the prior Step 5 (now Step 6, "Announce the session plan") is the only existing step whose body changes.

---

## Branch + Commit Strategy

Per memory `feedback_jared_git_workflow`: feature branch off `main`, PR to `main` via `--merge`, phase-numbered commits if multiple phases.

This is a single-phase change (one atomic edit), so one commit on `feature/44-jared-start-handoff-pickup`, then PR. No phase prefix needed since there is only one phase; conventional commit prefix `feat(commands)` is sufficient.

---

## Tasks

### Task 1: Create feature branch

**Files:**
- (none yet — git operation)

- [ ] **Step 1: Verify clean working tree on `main`**

Run:
```bash
git status
```

Expected: branch `main`, working tree clean (the spec commit `880e945` is the most recent commit; no untracked or modified files except permitted scratch like `CLAUDE.local.md` if present).

- [ ] **Step 2: Create the feature branch**

Run:
```bash
git checkout -b feature/44-jared-start-handoff-pickup
```

Expected: `Switched to a new branch 'feature/44-jared-start-handoff-pickup'`.

---

### Task 2: Edit `commands/jared-start.md`

**Files:**
- Modify: `commands/jared-start.md` (full rewrite of the body — the front matter `description:` line stays as-is)

The front-matter `description:` line is preserved unchanged. The flow body is rewritten end-to-end (a single Edit operation against the existing body is cleaner than four surgical edits, since renumbering and the inserted step interleave).

- [ ] **Step 1: Confirm current file state**

Run:
```bash
wc -l commands/jared-start.md
```

Expected: 60 lines (the spec was written against this baseline; if line count differs, re-read the file before editing).

- [ ] **Step 2: Replace the body of `commands/jared-start.md`**

Use the Edit tool to replace the entire body of `commands/jared-start.md` (everything from line 5 onward — `Invoke the Jared skill...` through end of file) with the following exact text:

````markdown
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

6. **Announce the session plan.** When a prompt was found in step 1, prepend a **posture block**:

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

   The posture block is omitted when no prompt was found in step 1. Two visually-separated blocks when both are present: cross-issue posture above, issue-specific below.

7. **Wait for confirmation** before starting work. User may amend the plan, ask questions, or say "go."

This replaces the pattern of manually reading the issue, the plan, and a handoff prompt before starting. The board + latest Session note + (when present) the most recent handoff prompt is the handoff.
````

Match `old_string` against the existing body starting from `Invoke the Jared skill to start work...` through the end of the file. Use the Edit tool with the unique anchor `Invoke the Jared skill to start work on an issue. Takes an argument:` to disambiguate (the existing first line says `Takes an argument`; the new text says `Takes an optional argument`).

If the Edit tool reports the `old_string` is not unique or is not found, Read the current file and adjust the anchor — do NOT proceed with a partial edit.

---

### Task 3: Verify the edit

**Files:** none modified — verification only.

- [ ] **Step 1: Read the edited file end-to-end with fresh eyes**

Use Read on `commands/jared-start.md`. Check:
- Front matter (`description:` line) is unchanged.
- The flow has 7 numbered steps (1 through 7).
- Step 1 is the new "Look for the most recent handoff prompt" step.
- Steps 2–5 are the prior Steps 1–4, unchanged in body.
- Step 6 is the prior Step 5 ("Announce the session plan"), modified to prepend the posture block.
- Step 7 is the prior Step 6 ("Wait for confirmation"), unchanged.
- The closing paragraph mentions "the most recent handoff prompt" alongside board + Session note.
- No broken references to step numbers (search the body for `step <digit>` mentions and confirm they all point to the new numbering).

- [ ] **Step 2: Run lint and type-check (invariant — should still pass)**

Run:
```bash
ruff check . && mypy
```

Expected: both succeed with zero errors. (Neither tool reads `commands/*.md`, so this is a guard against accidentally modifying Python files alongside the markdown change.)

- [ ] **Step 3: Confirm no Python files were touched**

Run:
```bash
git diff --stat main
```

Expected: a single file (`commands/jared-start.md`) appears in the diffstat. If anything else is listed, investigate before continuing.

- [ ] **Step 4: Confirm the new step references resolve internally**

Run:
```bash
grep -nE 'step [0-9]' commands/jared-start.md
```

Expected output (line numbers approximate):
- `... output the **posture block** (see step 6) followed by:` (Step 1's drift-case branch references step 6).
- `Wait for user input, then resume the flow at step 2 with the user-supplied issue.` (Step 1's drift-case branch references step 2).
- `When a prompt was found in step 1, prepend a **posture block**:` (Step 6 references step 1).
- `The posture block is omitted when no prompt was found in step 1.` (Step 6 references step 1).

If the references in the rendered file mismatch (e.g., `step 5` instead of `step 6`), fix before committing.

---

### Task 4: Commit and open PR

**Files:**
- (commit + push + PR — git operations against the modified file)

- [ ] **Step 1: Stage and commit**

Run:
```bash
git add commands/jared-start.md
git commit -m "$(cat <<'EOF'
feat(commands): /jared-start picks up most recent handoff prompt

Closes #44.

`/jared-start` now globs `tmp/next-session-prompt-*.md`, lex-sorts by
filename timestamp, and surfaces the most recent prompt's synthesis
(Frame, anti-targets, context pointers) as a posture block above the
existing per-issue announcement.

When `$ARGUMENTS` is empty and the prompt has a parseable `## To start`,
that issue is used as the target — drift-checked first via
`jared get-item`. Closed/Done recommendations surface the posture block
plus a drift line and ask which issue to pull, never silently routing
to a stale recommendation. When `$ARGUMENTS` is non-empty, the user's
choice wins; the posture block is still surfaced because the synthesis
is cross-issue.

Spec: docs/superpowers/specs/2026-04-26-jared-start-handoff-pickup-design.md
Plan: docs/superpowers/plans/2026-04-26-jared-start-handoff-pickup.md

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

Expected: commit succeeds; one file changed.

- [ ] **Step 2: Push the branch**

Run:
```bash
git push -u origin feature/44-jared-start-handoff-pickup
```

Expected: branch published, upstream tracking set.

- [ ] **Step 3: Open the PR**

Run:
```bash
gh pr create --base main --title "feat(commands): /jared-start picks up most recent handoff prompt (#44)" --body "$(cat <<'EOF'
## Summary
- `/jared-start` now picks up the most recent `tmp/next-session-prompt-*.md` and surfaces its synthesis (Frame, anti-targets, context pointers) as a Handoff posture block above the existing per-issue announcement.
- When no `$ARGUMENTS` is given and the prompt has a parseable `## To start`, that issue is used — drift-checked via `jared get-item`. Closed/Done recommendations surface the posture and ask which issue to pull instead of silently routing.
- When `$ARGUMENTS` is given, the user's choice wins; the posture block is still surfaced.
- No Python changes, no test changes — this is a doc-as-code edit to the slash-command template.

Closes #44.

Spec: `docs/superpowers/specs/2026-04-26-jared-start-handoff-pickup-design.md`
Plan: `docs/superpowers/plans/2026-04-26-jared-start-handoff-pickup.md`

## Test plan
- [ ] Read `commands/jared-start.md` end-to-end; confirm 7 numbered steps, internal step references resolve, no broken anchors.
- [ ] `ruff check . && mypy` — invariant, should pass.
- [ ] Live (post-merge): in a fresh Claude Code session with `tmp/next-session-prompt-2026-04-26-XXXX.md` present, run `/jared-start` (no args). Confirm the posture block renders, the recommended issue is drift-checked, and either the existing flow continues or the drift fallback fires.
- [ ] Live (post-merge): `/jared-start <N>` with a prompt present. Confirm posture block renders; drift check is skipped; flow runs on `<N>`.
- [ ] Live (post-merge): `/jared-start` with no prompt in `tmp/`. Confirm fallback "ask which issue" behavior is unchanged from prior.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

Expected: PR created, URL printed. Capture the URL for the user.

- [ ] **Step 4: Surface the PR URL**

Print the PR URL to the user as the final action of this plan. The user will run live verification scenarios in a fresh Claude Code session before merging.

---

## Self-review notes (already applied)

- **Spec coverage:** All 7 acceptance criteria from the spec map to behavior in the new Step 1 and the modified Step 6. The `## To start`-missing edge case is handled in Step 1's last bullet ("When a prompt was found but had no parseable `## To start`, the posture block is still surfaced in step 6").
- **Placeholder scan:** Every code block contains the actual target text. No `TBD` / `TODO` / "implement later" markers. The "Live (post-merge)" Test plan items are deliberately deferred to the user, not the implementing agent — the live scenario requires a fresh Claude Code session, which the plan-executing agent cannot manufacture.
- **Step references:** All `step N` mentions in the target text use the new numbering (1–7). Verified in Task 3 Step 4 with a grep.
- **Type / signature consistency:** No types or function signatures involved (markdown only). The `${CLAUDE_PLUGIN_ROOT}/skills/jared/scripts/jared` invocations match the pattern used elsewhere in the file.
