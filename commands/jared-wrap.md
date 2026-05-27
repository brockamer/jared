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

   **Guidance audit append.** Append a `## Guidance audit (#N)` H2 to the Session-note draft as a sibling section to `## Session YYYY-MM-DD` — not a bold-labeled field inside it. One comment per wrap, two H2s inside. Three judgment-evaluation questions, honest self-report:

   ```
   ## Guidance audit (#N)

   - Smart-tier decisions: routed through `advisor()`?                                                  [yes / no / N/A]
   - Were your session's model and dispatch choices well-matched to the work size?                       [yes / no / N/A]
   - Looking back, did any cheap-tier or surface-mapping work run inline that would have been better dispatched? [yes / no / N/A — if no, name the closest call you considered]
   ```

   **A `no` or surfaced regret on any line REQUIRES a one-line "why" appended beneath that bullet.** Not optional. Examples:
   - *"no — over-dispatched a Haiku for what turned out to be a 1-line python pipe; should have stayed inline"*
   - *"no — should have called `advisor()` before committing to the API shape; caught it late in review"*
   - *"yes — Explore for the surface map was load-bearing; advisor() before commit caught two issues"*

   `N/A` is appropriate when no work of the relevant type happened in this session (e.g., no decision points to route through `advisor()`); `N/A` does not require a why.

   **Skip the audit append when** `docs/project-board.md`'s `## Jared config` contains `- model-guidance: disabled`. (The config key name is historical — it now disables the audit rail.) For closures that don't warrant an audit (epic rollups, scope-question issues, no-work sessions, doc trivia), use `jared close --no-audit <reason>` instead — that posts a small exempt-marker comment so the closure is countable as exempt.

   **Audit-emission rail (#227, decoupled in #228).** `jared close <N>` enforces this contract at the CLI: unless the kill switch is on, the close refuses unless either the close body (`--body` / `--body-file`) contains `## Guidance audit (#N)`, OR `--no-audit <reason>` is passed. The escape posts a `_Audit-exempt close: <reason>_` marker comment so the closure is countable as exempt. Acceptable reasons name the shape of the legitimate skip — `epic-rollup`, `scope-question`, `no-work-session`, `docs-trivia`. The rail closes the silent-skip path that left ~37% of post-v0.19.0 closures audit-less, and forces every close into one of three buckets: audit-emitted, `--no-audit`-exempt, or refused. Decoupled from `## Model & execution guidance` section presence in #228 (which cut the section); the rail now fires on every close.

   **The audit evaluates judgment, not compliance.** The original 2026-05-13 findajob#150 surfacing concern (Claude proceeded at parent-session model without dispatching for cheap-tier work) is preserved by question 3, which names the failure-mode work types explicitly to force forensic examination rather than relying on the operator to surface a feeling. The over-prescription pattern from the 2026-05-20 #162 audit is surfaced by question 2 ("well-matched to the work size"). The decision-point discipline that works at 95% (`advisor()`) is preserved by question 1. The audit's value is the trigger — asking the question at wrap-time removes the dependency on the operator noticing the gap.

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
