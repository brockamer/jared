---
description: End of session — append Session notes to touched issues, reconcile drift, propose plan archivals, file discovered scope.
---

**Voice.** Speak as Jared throughout this command — see `${CLAUDE_PLUGIN_ROOT}/skills/jared/references/voice.md` for the full spec. The output template below (step 4) is written in voice; render it as written rather than translating at runtime. **Important boundary:** Session-note bodies themselves are voice-OFF (per the lane rule — board writes are plain technical prose). The voice is in the *dialogue around* the drafts ("Here's what I'd like to write to each of these — please tell me what to change"), not in the drafts. **Kill switch:** if `docs/project-board.md` § `## Jared config` contains `- voice: disabled`, render the wrap dialogue in plain technical prose — keep the structural content, strip the Jared-isms. **STE mode:** if the same section contains `- voice: ste`, render in ASD-STE100 Simplified Technical English per `${CLAUDE_PLUGIN_ROOT}/skills/jared/references/voice-ste.md` — keep the structural content and the section skeleton, pass machine strings and technical names through verbatim, and treat every aside or warm-framing instruction in this file as void.

**Backend gate.** If `docs/project-board.md` § Jared config has `- backend: kanbanflow`, apply these capability degradations:
- Step 2 (Session note): Use a plain-text Session note format (section names as plain-text labels rather than markdown headers): `degraded: markdown body rendering unavailable on kanbanflow — session notes use plain-text format` (MARKDOWN_BODY absent).

The back-end PR flow (step 5b: commit → push → PR → merge), worktree removal, and lock-clear are **backend-independent** — they operate on git/GitHub repo state, not the board, and run unchanged on every backend (Phase-6 Non-goal: no repo/git-axis gating).

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
   > *(Under `- voice: ste` this line is void: render one statement of fact instead.)* STE opening line: `Session end, <date>. <One sentence: what merged, what is In Progress.>`
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

   **Precondition — repo and branch guard.** The back-end flow assumes two facts, and neither is safe to assume. First, that `origin` is the repo this board tracks: jared is often paired with a clone of a project the operator cannot push to, and the loop would push and open a PR against that upstream. Second, that the session worked on a feature branch rather than the repo's default branch: a repo whose default branch is `master` fell straight through the old `main`-only check and ran the PR loop on its default branch. Both are F72 (#393). Establish the facts before any network write. Anything the guard cannot establish is a skip — the flow errs toward doing nothing rather than toward writing somewhere:

   ```bash
   BOARD_REPO=$(sed -n 's/^- Repo: *//p' docs/project-board.md 2>/dev/null | head -1)
   ORIGIN_SLUG=$(git remote get-url origin 2>/dev/null \
     | sed -E 's#^(git@[^:]+:|ssh://[^/]+/|https?://[^/]+/)##; s#/+$##; s#\.git$##')
   DEFAULT_BRANCH=$(git symbolic-ref --short refs/remotes/origin/HEAD 2>/dev/null | sed 's#^origin/##')
   BRANCH=$(git rev-parse --abbrev-ref HEAD)

   if [ -z "$BOARD_REPO" ] || [ -z "$ORIGIN_SLUG" ]; then
     echo "SKIP: cannot confirm origin is ours (board doc Repo: '${BOARD_REPO:-unset}', origin: '${ORIGIN_SLUG:-unset}') — skipping back-end PR flow."
   elif [ "$ORIGIN_SLUG" != "$BOARD_REPO" ]; then
     echo "SKIP: origin is $ORIGIN_SLUG, but docs/project-board.md records $BOARD_REPO — skipping back-end PR flow."
   elif [ -z "$DEFAULT_BRANCH" ]; then
     echo "SKIP: cannot resolve this repo's default branch — skipping back-end PR flow. Set it once with: git remote set-head origin -a"
   elif [ "$BRANCH" = "$DEFAULT_BRANCH" ]; then
     echo "SKIP: on $BRANCH, this repo's default branch — skipping back-end PR flow."
   else
     echo "PROCEED: feature branch $BRANCH on $ORIGIN_SLUG (default branch $DEFAULT_BRANCH)."
   fi
   ```

   On any `SKIP:` line, skip the loop entirely and jump directly to the lock-clear + worktree-removal bullets below; print the line so the operator knows which fact was missing. The lock-clear still runs (the session may have written one), and the worktree-removal bullet is a no-op after the default-branch skip (worktrees are never created against the default branch). On `PROCEED:`, enter the loop.

   Three notes on the mechanism. The ownership check compares `origin` against the `- Repo:` bullet `docs/project-board.md` already carries, so it needs no new configuration and makes no network call; the `sed -E` normalises the four remote-URL shapes (`git@host:o/r.git`, `ssh://git@host/o/r.git`, `https://host/o/r.git`, and either with a trailing slash) to a bare `owner/repo`. The default branch is read from `refs/remotes/origin/HEAD`, which `git clone` writes and `git remote add` does not — when it is absent the guard refuses to guess rather than falling back to the literal `main`, because that fallback is the defect. And a `- Repo:` bullet that is missing, or escaped by a Markdown formatter (#381), produces the first skip rather than a silent pass.

   `tests/test_wrap_stub_guards.py` extracts this block and runs it against synthetic repositories — a `master` default branch, a foreign `origin`, all four URL shapes, and a repo with no `origin/HEAD`. Edit the block and the tests exercise the edit; rephrase a `SKIP:` or `PROCEED:` line and they fail first.

   **Integrate `main` before the PR.** Parallel sessions diverge from `main` while they work. Before pushing or opening the PR, fold the current `main` into the branch and resolve *here* — in the session that has full context — rather than discovering it at merge time:

   ```bash
   git fetch origin && git merge --no-edit origin/main
   ```

   - **Clean merge:** re-run the formatter and tests (`ruff format . && ruff check . && pytest`), then enter the loop. Formatting *on top of* `main` is the point — it collapses spurious whitespace/format conflicts (a line you never logically touched, reformatted differently on each branch) before they can reach the PR.
   - **Conflict:** resolve in place, re-run format + tests, and `git commit` the merge. Genuine logic collisions (two sessions editing the same function) surface here, in-session, instead of as a terse "unmergeable" after the PR already exists.

   Merge, not rebase — the branch may already be pushed, and a merge avoids the force-push a rebase would require. See `references/parallel-sessions.md` § "Integrate `main` before the PR" for the rationale and the two conflict classes this addresses.

   Loop:

   ```bash
   STEP=$(${CLAUDE_PLUGIN_ROOT}/skills/jared/scripts/jared wrap-state)
   ```

   **Check the exit code before dispatching on `$STEP`.** `wrap-state` exits non-zero
   with an empty stdout when it cannot determine PR state — `gh pr view` failed for a
   reason other than "no PR exists" (auth, network, rate limit), so reporting
   `create_pr` would tell you to open a PR that may already exist (F7, #371). On a
   non-zero exit: print the CLI's stderr verbatim, do **not** dispatch a step, and exit
   the loop. The lock-clear block below still runs. Re-run `/jared-wrap` once the `gh`
   failure is addressed. A detached HEAD reaches this path too, since the branch name
   `wrap-state` resolves is empty there.

   Each iteration of the loop runs the CLI to determine the next step, then executes that step. Loop exits on `cleanup` (which runs the lock-clear + worktree-remove block below), or when the operator declines a confirm prompt, or when a non-actionable step (`wait_checks`, `surface_failure`, `surface_conflict`, `update_branch`, `blocked_on_review`) is returned. `update_branch` exits-then-re-run (like `surface_conflict` — you act, push, and re-run `/jared-wrap`); `blocked_on_review` is terminal for the loop (it either ends in an operator-confirmed `--admin` merge or a "get a review" exit).

   **Step actions:**

   - **`commit`** (working tree dirty): Stage in two parts, then ask for the message. Scope first, wording second — the operator has to know *what* is going in before they name it. F71 (#392) was the opposite order: one prompt about wording, which read as consent to every untracked path in the tree.

     ```bash
     git add -u                                 # tracked modifications and deletions
     git ls-files --others --exclude-standard   # untracked — nothing above stages these
     ```

     Show `git status` as before. If that second command lists anything, show the list and ask: *"Also stage these N untracked path(s)? (y/N)"* — default **No**. On `y`, stage them by explicit path (`git add -- <path> ...`); a blanket form cannot tell a file nobody added yet from one that must never enter git history, and this loop pushes and opens a PR a step later. A deliberately-untracked file has to be able to survive a wrap.

     Then ask: *"Commit message? (or 'skip' to leave uncommitted and exit)"*. On a message: run `git commit -m "$msg"`. On `skip`: exit wrap (the lock is still cleared at the end). Loop continues after a successful commit. When only tracked files changed — the common case — the untracked question does not appear and this is still one prompt.

   - **`push`** (local commits ahead of remote): Run `git push -u origin $(git rev-parse --abbrev-ref HEAD)`. On failure, surface the git error and exit. Loop continues on success.

   - **`create_pr`** (no PR for the branch): Auto-generate title from the issue title (the issue moved to In Progress at start). Auto-generate body from the issue's first paragraph + the commit subjects on the branch. Run:

     ```bash
     gh pr create --title "$TITLE" --body "$BODY"
     ```

     On failure, surface the gh error and exit. Loop continues on success.

   - **`wait_checks`** (PR exists, checks pending): Print *"PR #N: checks pending. Re-run `/jared-wrap` when they're green and I'll handle the merge."* Exit the loop (do not poll). The remaining wrap steps (lock-clear) still run.

   - **`surface_failure`** (PR exists, checks failed): Print the failed check names from `gh pr checks $PR --json`. Exit the loop. Lock-clear runs.

   - **`update_branch`** (`mergeStateStatus=BEHIND` — branch trails base): The branch is cleanly behind `main` (no conflict, just out of date — `main` advanced after the last push). Integrate and re-push: `git fetch origin && git merge --no-edit origin/main`, re-run format + tests, `git push`, then re-run `/jared-wrap`. Same merge-not-rebase rule as the integrate-before-PR step. Exit the loop. Lock-clear runs.

   - **`surface_conflict`** (checks green but not mergeable): Print *"PR #N: conflict with main. Integrate in this worktree (`git fetch && git merge origin/main`), resolve, push, and re-run `/jared-wrap`."* Exit the loop. Lock-clear runs. (This is the fallback when the integrate-before-PR step above was skipped or `main` advanced after it ran — merge, not rebase, since the branch is already pushed.)

   - **`blocked_on_review`** (`reviewDecision=REVIEW_REQUIRED`, or `mergeStateStatus=BLOCKED`): The PR is reported `mergeable` but branch protection won't let it merge — typically a solo-author PR needing a review that will never arrive, or a protected-branch block. GitHub reports this as `MERGEABLE`, which is why the loop used to mis-route it to `confirm_merge`. Print *"PR #N: blocked by required review / branch protection."* Then check `docs/project-board.md` § `## Jared config` for an `admin-merge` sanction:
     - **If `- admin-merge: <strategy>` is present** (e.g. `--merge`): offer the operator-confirmed escape — render a confirm block, and on `y` run `gh pr merge <N> --admin <strategy>`. `--admin` bypasses branch protection; it is offered *only* because the board doc explicitly sanctions it, and run *only* on an explicit operator `y`. The strategy comes from the board doc (not hardcoded), so the sanction also pins `--merge` vs `--squash`.
     - **If absent:** print *"No admin-merge sanction in the board doc — get a review, or add `- admin-merge: --merge` to `## Jared config` to sanction the escape."* Do not offer `--admin`.

     Exit the loop. Lock-clear runs.

   - **`confirm_merge`** (checks green, mergeable): Render the confirm-merge block:

     ```
     PR #<N>: <title>
       branch:     <branch>
       mergeable:  yes
       checks:     <count> passed | none (no CI checks ran)
       sibling:    <enumerate other session locks if present, with their branches>

     Merge? (y / edit / no)
     ```

     Render the `checks:` line honestly from `checks_status`: `<count> passed` when checks ran and passed, or `none (no CI checks ran)` when the status-check rollup was empty — never label an empty rollup as "passed" (#285).

     On `y`: run `gh pr merge <N> --merge --delete-branch`. On success, loop continues (next state will be `cleanup`). On failure (e.g., GitHub rejected as not-mergeable since the last check), surface the gh error and exit the loop.

     On `edit`: prompt for new title/body inline; run `gh pr edit <N> --title "$NEW_TITLE" --body "$NEW_BODY"`; re-render the confirm block.

     On `no`: exit the loop. Lock-clear runs.

   - **`cleanup`** (PR merged, branch still local): Run the lock-clear + worktree-remove block below.

   **Concurrent-merge safety.** Two sessions reaching `confirm_merge` at nearly the same time both run the same `wrap-state` query just before the merge. GitHub's PR-merge API is atomic — the first call serializes ahead of the second. If the first's merge invalidates the second's mergeable state, the second's `gh pr merge` call returns an error from GitHub, which surfaces to the operator. No Jared-side lock is used.

   - Clear this session's presence lock. The lock is keyed by the issue this session was started against (`<N>` = the `/jared-start` argument), not by PID — PID-keyed locks were stale-on-arrival because the writing CLI subprocess exits immediately (#259):
     ```bash
     GIT_COMMON_DIR=$(git rev-parse --git-common-dir 2>/dev/null)
     REPO_ROOT=$(realpath "$(dirname "$GIT_COMMON_DIR")")
     ${CLAUDE_PLUGIN_ROOT}/skills/jared/scripts/jared session-lock-clear --repo-root "$REPO_ROOT" --issue <N>
     ```
     Removes `<repo>/.jared/session-<N>.lock` so the next `/jared-start` doesn't see this session as a live sibling. Sibling sessions' locks (other issues) are left untouched.
   - **Worktree removal (multi-session only).** When this session worked from a worktree (created by `/jared-start <N> --session N` — non-null `worktree_path` on the lock) AND the session's `feature/<N>-<slug>` branch has merged into main, remove the worktree and delete the branch from the main checkout. Read the branch name from the worktree first — it's slugified from the issue title (#278), not a fixed string, so don't reconstruct it by hand:
     ```bash
     BRANCH=$(git -C "<worktree-path>" rev-parse --abbrev-ref HEAD)
     git -C "$REPO_ROOT" worktree remove "<worktree-path>"
     git -C "$REPO_ROOT" branch -d "$BRANCH"
     ```
     The cleanup is **scoped to this session's issue**, not lockdir-wide — sibling worktrees from other parallel sessions are not touched. Skip the bullet entirely for solo sessions (worktree_path is null) and for sessions whose branch hasn't merged yet (the operator decides whether to keep the unmerged worktree around). The rule comes from operator feedback after the 2026-05-24 wrap of #227's session-1 left an orphan `~/Code/jared-227/` on disk — see the `the wrap-cleanup rule` user-memory note for the original framing.

6. **Confirm and close out.** Render the closing line in voice:

   > Wrapped <N> issues, filed <N> new, archived <N> plans, reconciled <N> drift items. Lovely work today — I'd be delighted to pick this back up whenever you are. Next session: `/jared-start` to pull, or `/jared-stage` to see staging proposals.
   > *(Under `- voice: ste` this line is void: render one statement of fact instead.)* STE closing line: `Wrapped <N> issues, filed <N> new, archived <N> plans, reconciled <N> items. Next session: /jared-start to start an issue, or /jared-stage for promotions.`

   If the numbers are all zero (a no-op wrap — nothing touched, nothing reconciled), say so plainly: *"Quiet wrap — nothing to write, no drift to reconcile. Until next time."* Under `- voice: ste`: `No changes in this session. Nothing to write.`

The next session's `/jared-start` invokes `jared next-session-prompt` to assemble the posture from current board state — In Progress with each issue's most recent Session-note one-liner, top of Up Next, recently closed. Because the assembly is on-demand, the recommendation cannot go stale and no `tmp/` artifact accumulates.
