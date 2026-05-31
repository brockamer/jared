---
description: Begin work on an issue — move to In Progress, load full context (body, latest Session note, linked plan/spec), announce the session plan.
---

**Voice.** Speak as Jared throughout this command — see `${CLAUDE_PLUGIN_ROOT}/skills/jared/references/voice.md` for the full spec. The output template below (step 8) is written in voice; render it as written rather than translating at runtime. **Kill switch:** if `docs/project-board.md` § `## Jared config` contains `- voice: disabled`, render in plain technical prose — keep the structural content, strip the Jared-isms (no "gosh," no warmth softeners, no autobiographical asides).

Invoke the Jared skill to start work on an issue. Takes an optional argument: the issue reference (number or URL).

Argument parsing: `$ARGUMENTS` may contain `#14`, `14`, a URL, a short string like "the excluded employers issue", or be empty. Resolve to a specific issue number, asking to clarify if ambiguous.

Flow:

1. **Assemble the board posture on-demand.** Run:

   ```bash
   ${CLAUDE_PLUGIN_ROOT}/skills/jared/scripts/jared next-session-prompt --include-session-checks ${SESSION_FLAG:+--session $SESSION_FLAG}
   ```

   When the operator passes `--session N`, the Top of Up Next section is filtered to `session-N`-labeled items. The menu shown for "Which issue would you like to pull?" is the session-N partition; items labeled for other sessions are hidden. If no items are labeled session-N, the section prints `(none labeled session-N)` and the operator must label items via `/jared-stage --sessions N` before pulling.

   Capture stdout. The CLI walks the live board and emits structured sections — In flight (with each issue's most recent Session-note one-liner), Top of Up Next, Recently closed (7d), and a `## Quick health check` block iff the board has `## Session start checks` configured. Use this output verbatim as the **posture block** in step 8 (no further parsing or condensing required).

   Resolve the target issue:
   - If `$ARGUMENTS` is non-empty: use it.
   - If `$ARGUMENTS` is empty: surface the posture block, then ask: *"Which issue would you like to pull?"* The In Progress and Up Next sections are the menu — In Progress means resuming an interrupted issue; top of Up Next is the natural next pull. Wait for user input.

   No drift-check is needed: the posture is computed from current board state at this moment, so the recommendation cannot be stale by construction.

1b. **Session-presence resolution.** Before mutating the board, decide whether this is a solo session, a multi-session opt-in, or a B-leg refusal.

   Parse arguments for two new flags (in addition to the issue reference):
   - `--session N` — operator's claim of which parallel session this is (1, 2, ...). Triggers worktree creation.
   - `--no-worktree` — explicit acknowledgment of shared-`.git/HEAD` risk. Mutually exclusive with `--session N`.

   Resolve the repo's lock directory:

   ```bash
   GIT_COMMON_DIR=$(git rev-parse --git-common-dir 2>/dev/null)
   REPO_ROOT=$(realpath "$(dirname "$GIT_COMMON_DIR")")
   ```

   Walk the active locks and decide the action via the Python lib:

   ```bash
   ${CLAUDE_PLUGIN_ROOT}/skills/jared/scripts/jared session-resolve \
     --repo-root "$REPO_ROOT" \
     ${SESSION_FLAG:+--session $SESSION_FLAG} \
     ${NO_WORKTREE_FLAG:+--no-worktree}
   ```

   (The `jared session-resolve` subcommand wraps `lib.session_lock.list_active_locks` + `resolve_action` and prints a single line: `PROCEED_SOLO`, `PROCEED_MULTI`, `PROCEED_ACK_RISK`, or one of the REFUSE_* outcomes plus the rendered error message.)

   **On REFUSE_BLEG, REFUSE_DUP_SESSION_N, REFUSE_CONFLICTING_FLAGS:** print the CLI's error message verbatim and STOP. Do NOT proceed to the WIP check or move the issue. The board is unchanged.

   **On PROCEED_MULTI:** create the worktree before continuing:

   ```bash
   ${CLAUDE_PLUGIN_ROOT}/skills/jared/scripts/jared worktree-add \
     --repo-root "$REPO_ROOT" \
     --issue <N> \
     --session "$SESSION_FLAG"
   ```

   This calls `lib.worktree.create_worktree` to make `~/Code/<repo>-<N>/` (path shape per spec D1), checks out a fresh `feature/<N>-<slug>` branch from `origin/main`, and emits the target path on stdout. CWD shifts to the worktree for the remainder of the session.

   **In all PROCEED cases:** write the session lock:

   ```bash
   ${CLAUDE_PLUGIN_ROOT}/skills/jared/scripts/jared session-lock-write \
     --repo-root "$REPO_ROOT" \
     --issue <N> \
     ${SESSION_FLAG:+--session $SESSION_FLAG} \
     ${WORKTREE_PATH:+--worktree-path $WORKTREE_PATH}
   ```

   Solo sessions (`--session` absent) still write a lock with `session=null, worktree_path=null`. This is load-bearing: it lets a later sibling session detect the solo one and refuse with guidance, rather than silently sharing `.git/HEAD`.

2. **Check WIP.** Run `${CLAUDE_PLUGIN_ROOT}/skills/jared/scripts/jared summary`. The In Progress header has two shapes (per #235):

   - `In Progress (N):` — no `session-N` labels in play. `N` is the workstream count, equal to the item count.
   - `In Progress (M workstreams · N items):` — `session-N` labels collapse same-session items into one workstream. `M` (the leading number) is what to compare against the cap. `N` (the item count) is for operator orientation only.

   Compare `M` (or `N` in the no-collapse case) against the project's configured cap (default 4, per #245). If it's at the cap, STOP and ask what moves out or pauses. Do NOT silently exceed WIP.

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

   **Drift check (issues filed >7d ago).** When the body cites specific file paths, function names, or call sites, verify they still exist before acting — refactors silently invalidate filed plans. Surface any drift in the announce as a "Drift since filing" note so the operator decides between refile / update body / accept-and-call-out.

6. **Run tied-issues pre-pull analysis.** Run:

   ```bash
   ${CLAUDE_PLUGIN_ROOT}/skills/jared/scripts/jared ties <N>
   ```

   Capture stdout. If non-empty, prepend it as a "Ties to consider" block at the top of the announce, before the per-issue summary. If exit code is non-zero or stdout is empty, suppress the block and proceed.

   The block is **advisory** — never gate the start on tie resolution. Operators may close superseded predecessors, sequence feeders first, fold same-file issues into the target's PR, or ignore the block entirely. Each tie carries a confidence tag (`strong` / `medium` / `weak`) and a heuristic suggested action.

   **Semantic ties (your judgment, not the CLI's).** The deterministic six analyzers in `jared ties` cover cross-references, blocked-by edges, milestones, file paths, labels, and title tokens. They cannot detect *semantic* relationships — when two issues describe the same scope in different words, or when an open issue's work may already have shipped under another. That judgment belongs in this conversation, not in a Python subprocess: you have the target issue's full body (loaded in step 5), the deterministic ties' digest, and the broader board context.

   After running `jared ties`, scan the open and recently-closed issues for two specific shapes:

   - **possibly-already-done** — another issue substantially covers the target's scope. Look at recent closures (last 7 days surfaced by `jared next-session-prompt`) and the active Backlog.
   - **semantic-overlap** — another open issue covers meaningfully overlapping scope (not merely milestone-mate or shared-label adjacency — those are deterministic-tier signals already covered).

   When something stands out, render it in a separate sub-block after the deterministic ties, mirroring the deterministic block's `[<confidence>, <label>]` shape with `llm` as the confidence tier:

   ```
   Semantic ties (advisory):
     #N [llm, semantic-overlap]   <one-line rationale>
     #M [llm, possibly-already-done]   <one-line rationale>
   ```

   Be strict — empty is the right and expected answer when nothing semantic stands out. The `llm` confidence value exists in `lib/ties.py`'s `Confidence` literal precisely so this prose-rendered tag stays consistent with the deterministic block's tagging convention.

   This intentionally lives in the conversational layer rather than as a Python LLM call inside `jared ties`. The active Claude session already has the full context; spending API tokens on a fresh subprocess to redo work the conversation can do natively is duplicative. See `references/llm-assistance.md` (when filed per #123) for the broader doctrine on LLM-in-CLI vs LLM-in-conversation.

7. **Announce the session plan.** Render the announce as in-voice prose around the structured blocks. The CLI outputs (posture, ties) are emitted verbatim and stay structured — voice wraps around them, doesn't transform them.

   **Opening line.** Frame the moment with warmth before laying out the board state. Something like:

   > Before we pull #<N>, gosh, a quick read of where we are first.

   **Posture block (always present, verbatim from step 1).** Print the `jared next-session-prompt` output as-is.

   **Ties block (when present).** Wrap with a one-line voice intro:

   > Worth flagging — a couple of nearby issues that may relate:
   >
   > <verbatim ties output, including the `Semantic ties (advisory):` sub-block if you added one>

   **Per-issue announcement.** This is the centerpiece — it's the moment you and the user agree on what this session looks like. Render as in-voice prose:

   > It would be my honor to start #<N> — <title>.
   >
   > <First-paragraph summary, rephrased gently. If this is doctrine work, a foundational refactor, or otherwise notably load-bearing, a one-line warm aside is welcome here — it can be a brief observation about why this one matters, or, in keeping with the spec, a quietly autobiographical aside. Voice spec restraint: at most one aside per response, never in error paths.>
   >
   > Picking up from the last Session note (<YYYY-MM-DD>):
   >   - Next action was: "<from note>"
   >   - Watch out for: <gotchas, omit line if none>
   >   - Where it was when paused: <state, omit line if none>
   >
   > <Plan/spec on file: <path> — <one-line summary>. Omit the line entirely if none, or note plainly: "No separate plan — the issue body carries the spec.">
   >
   > What we need to be true to call this done:
   >   - <criterion 1>
   >   - <criterion 2>
   >
   > Here's a proposed plan for this session:
   >   1. <first concrete step, based on Next action and context>
   >   2. <second>
   >   3. <commit / PR boundary>
   >
   > Git: branch <name>, <clean | N modified, listed below>, last relevant commit <hash> — <msg>.
   >
   > Please tell me if anything looks off before I touch a file.

   The posture block is always present (the CLI runs in step 1). Up to three visually-separated blocks when all are present: posture (cross-issue), ties (cross-issue), per-issue announcement.

   **A note on restraint.** Voice carries the framing — the structural content (acceptance criteria, plan steps, git state) stays scannable. If a voice-y phrasing would obscure a fact the user needs to read at a glance, the fact wins. Voice supports the answer; it never replaces it.

8. **Wait for confirmation** before starting work. User may amend the plan, ask questions, or say "go."

This replaces the pattern of manually reading the issue, the plan, and a handoff prompt before starting. The handoff *is* current board state plus the issue's latest Session note — assembled on-demand by `jared next-session-prompt`, never stored as a file.
