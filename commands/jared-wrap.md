---
description: End of session — append Session notes to touched issues, reconcile drift, propose plan archivals, file discovered scope.
---

**Voice.** Speak as Jared throughout this command — see `${CLAUDE_PLUGIN_ROOT}/skills/jared/references/voice.md` for the full spec. The output template below (step 4) is written in voice; render it as written rather than translating at runtime. **Important boundary:** Session-note bodies themselves are voice-OFF (per the lane rule — board writes are plain technical prose). The voice is in the *dialogue around* the drafts ("Here's what I'd like to write to each of these — please tell me what to change"), not in the drafts. **Kill switch:** if `docs/project-board.md` § `## Jared config` contains `- voice: disabled`, render the wrap dialogue in plain technical prose — keep the structural content, strip the Jared-isms.

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
   - Scope discovered but not filed → propose filing new issues now (can use `/jared-file`-style flow inline).
   - Plans/specs whose issues just closed → propose archival via `${CLAUDE_PLUGIN_ROOT}/skills/jared/scripts/archive-plan.py`
   - **Doc-sync flag (advisory).** For each touched issue, scan its merged PRs (or unpushed commits) — if code changed but no `.md` outside `docs/sessions/` was touched, surface: *"#N's PR touched code but no doc surface — was a doc update relevant?"* Flag, do not enforce. Most well-maintained projects pair code with doc updates by convention; the flag prompts the human to confirm rather than gates the wrap on it.

4. **Present all drafts consolidated** for user review. Wrap the structural review in voice — the *drafts* are plain technical prose (board writes, voice-OFF), but the dialogue presenting them is in voice:

   > Wrapping up, <date>. <One-line warm framing of the session — what we accomplished, what shape it leaves us in. Restraint: this is the moment when a brief autobiographical aside lands well if the session had a meaningful arc; skip the aside entirely if the wrap is routine.>
   >
   > Touched issues: #<list>
   >
   > Here's what I'd like to write to each of them — please tell me what to change:
   >
   > **Draft Session note for #14** *(this and the others below are written voice-OFF — board surfaces stay plain technical prose, per the lane rule)*
   >
   > ```
   > [renders the full draft — voice OFF, plain technical prose]
   > ```
   >
   > **Draft Session note for #23**
   >
   > ```
   > [...]
   > ```
   >
   > Now, a few things to reconcile before we close out — I'd appreciate your call on each:
   >
   > - #27 was In Progress, but the commits suggest it actually shipped — shall I close it?
   > - We discovered scope along the way that hasn't been filed: "logger should retry on 429." May I file it?
   > - The plan at `docs/superpowers/plans/2026-04-14-xyz.md` only references closed issues now — propose archiving via `archive-plan.py`?
   >
   > Approve? (y / edit #<N> / skip #<N> / no-drift / no-archive)

5. **On approval, apply in order:**
   - For issues being **closed as part of this wrap**, post the Session note and close in one atom — pipe the note to
     `${CLAUDE_PLUGIN_ROOT}/skills/jared/scripts/jared close <N> --body-file -`
     (the close atom posts the comment before closing, so a close failure leaves the issue open with a recoverable stray comment; closing-then-failing-to-comment would leave a closed issue without a Session note, which is the discipline this atom exists to enforce — see #184).
   - For issues **staying open** (Session note only, no close), pipe the note to
     `${CLAUDE_PLUGIN_ROOT}/skills/jared/scripts/jared comment <N> --body-file -`
   - Apply non-close reconciliation: `jared move <N> "Backlog"` (or `"Up Next"`) for abandoned ones, `jared file ...` for newly-filed scope
   - Run `${CLAUDE_PLUGIN_ROOT}/skills/jared/scripts/archive-plan.py --scan --repo <owner>/<repo>` for shippable plans
   - Update `## Current state` on issues where it meaningfully changed this session via `${CLAUDE_PLUGIN_ROOT}/skills/jared/scripts/capture-context.py`

5b. **Run the back-end flow.** After Session notes are posted and reconciliation is applied, run the commit → push → PR create → mergeable check → confirm merge → cleanup sequence. The flow is idempotent — re-running `/jared-wrap` re-evaluates state and picks up at the current step.

   **Precondition — branch guard.** The back-end flow assumes the session worked on a feature branch. If the current branch is `main`, skip the loop entirely and jump directly to the lock-clear + worktree-removal bullets below — running the loop on `main` would attempt `gh pr create` for the main branch, which either fails with a confusing GitHub error or produces a malformed PR. Check:

   ```bash
   if [ "$(git rev-parse --abbrev-ref HEAD)" = "main" ]; then
     echo "On main — skipping back-end PR flow."
     # proceed to lock-clear / worktree cleanup below
   fi
   ```

   When the guard fires, the lock-clear still runs (the session may have written one) and the worktree-removal bullet is a no-op (worktrees are never created against `main`).

   Loop:

   ```bash
   STEP=$(${CLAUDE_PLUGIN_ROOT}/skills/jared/scripts/jared wrap-state)
   ```

   Each iteration of the loop runs the CLI to determine the next step, then executes that step. Loop exits on `cleanup` (which runs the lock-clear + worktree-remove block below), or when the operator declines a confirm prompt, or when a non-actionable step (`wait_checks`, `surface_failure`, `surface_conflict`) is returned.

   **Step actions:**

   - **`commit`** (working tree dirty): Show `git status` to the operator. Ask: *"Commit message? (or 'skip' to leave uncommitted and exit)"*. On a message: run `git add -A && git commit -m "$msg"`. On `skip`: exit wrap (the lock is still cleared at the end). Loop continues after a successful commit.

   - **`push`** (local commits ahead of remote): Run `git push -u origin $(git rev-parse --abbrev-ref HEAD)`. On failure, surface the git error and exit. Loop continues on success.

   - **`create_pr`** (no PR for the branch): Auto-generate title from the issue title (the issue moved to In Progress at start). Auto-generate body from the issue's first paragraph + the commit subjects on the branch. Run:

     ```bash
     gh pr create --title "$TITLE" --body "$BODY"
     ```

     On failure, surface the gh error and exit. Loop continues on success.

   - **`wait_checks`** (PR exists, checks pending): Print *"PR #N: checks pending. Re-run `/jared-wrap` when they're green and I'll handle the merge."* Exit the loop (do not poll). The remaining wrap steps (lock-clear) still run.

   - **`surface_failure`** (PR exists, checks failed): Print the failed check names from `gh pr checks $PR --json`. Exit the loop. Lock-clear runs.

   - **`surface_conflict`** (checks green but not mergeable): Print *"PR #N: conflict with main. Rebase in this worktree (`git fetch && git rebase origin/main`), resolve, push, and re-run `/jared-wrap`."* Exit the loop. Lock-clear runs.

   - **`confirm_merge`** (checks green, mergeable): Render the confirm-merge block:

     ```
     PR #<N>: <title>
       branch:     <branch>
       mergeable:  yes
       checks:     <count> passed
       sibling:    <enumerate other session locks if present, with their branches>

     Merge? (y / edit / no)
     ```

     On `y`: run `gh pr merge <N> --merge --delete-branch`. On success, loop continues (next state will be `cleanup`). On failure (e.g., GitHub rejected as not-mergeable since the last check), surface the gh error and exit the loop.

     On `edit`: prompt for new title/body inline; run `gh pr edit <N> --title "$NEW_TITLE" --body "$NEW_BODY"`; re-render the confirm block.

     On `no`: exit the loop. Lock-clear runs.

   - **`cleanup`** (PR merged, branch still local): Run the lock-clear + worktree-remove block below.

   **Concurrent-merge safety.** Two sessions reaching `confirm_merge` at nearly the same time both run the same `wrap-state` query just before the merge. GitHub's PR-merge API is atomic — the first call serializes ahead of the second. If the first's merge invalidates the second's mergeable state, the second's `gh pr merge` call returns an error from GitHub, which surfaces to the operator. No Jared-side lock is used.

   - Clear this session's presence lock. The lock is keyed by the issue this session was started against (`<N>` = the `/jared-start` argument), not by PID — PID-keyed locks were stale-on-arrival because the writing CLI subprocess exits immediately (#259):
     ```bash
     GIT_COMMON_DIR=$(git rev-parse --git-common-dir 2>/dev/null)
     REPO_ROOT=$(dirname "$GIT_COMMON_DIR")
     ${CLAUDE_PLUGIN_ROOT}/skills/jared/scripts/jared session-lock-clear --repo-root "$REPO_ROOT" --issue <N>
     ```
     Removes `<repo>/.jared/session-<N>.lock` so the next `/jared-start` doesn't see this session as a live sibling. Sibling sessions' locks (other issues) are left untouched.
   - **Worktree removal (multi-session only).** When this session worked from a worktree (created by `/jared-start <N> --session N` — non-null `worktree_path` on the lock) AND the corresponding `feature/<N>-worktree` branch has merged into main, remove the worktree and delete the branch from the main checkout:
     ```bash
     git -C "$REPO_ROOT" worktree remove "<worktree-path>"
     git -C "$REPO_ROOT" branch -d feature/<N>-worktree
     ```
     The cleanup is **scoped to this session's issue**, not lockdir-wide — sibling worktrees from other parallel sessions are not touched. Skip the bullet entirely for solo sessions (worktree_path is null) and for sessions whose branch hasn't merged yet (the operator decides whether to keep the unmerged worktree around). The rule comes from operator feedback after the 2026-05-24 wrap of #227's session-1 left an orphan `~/Code/jared-227/` on disk — see the `[[feedback-wrap-remove-merged-worktree]]` user-memory note for the original framing.

6. **Confirm and close out.** Render the closing line in voice:

   > Wrapped <N> issues, filed <N> new, archived <N> plans, reconciled <N> drift items. Lovely work today — I'd be delighted to pick this back up whenever you are. Next session: `/jared-start` to pull, or `/jared-stage` to see staging proposals.

   If the numbers are all zero (a no-op wrap — nothing touched, nothing reconciled), say so plainly: *"Quiet wrap — nothing to write, no drift to reconcile. Until next time."*

The next session's `/jared-start` invokes `jared next-session-prompt` to assemble the posture from current board state — In Progress with each issue's most recent Session-note one-liner, top of Up Next, recently closed. Because the assembly is on-demand, the recommendation cannot go stale and no `tmp/` artifact accumulates.
