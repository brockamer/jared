# Session Continuity — The End of tmp/next-session-prompt.md

Manual session-handoff prompts are a symptom of the board not being trustworthy. Jared makes them unnecessary.

## The model

**End of session:** Jared appends a standardized Session note to every In Progress issue, plus any other issue meaningfully touched this session.

**Start of next session:** Jared reads the In Progress issues and their most recent Session notes. That *is* the handoff. No tmp file, no pasted prompt.

## Session note format

One comment per session per touched issue. Template at `assets/session-note.md.template`.

```markdown
## Session YYYY-MM-DD

**Progress:** What got done this session, in one to three sentences.

**Decisions:** Material choices made and why, each dated. Empty if none.

**Next action:** The specific concrete next step. Not "continue work" — something like "wire `scorer.py::apply_tier_boost` into the main scoring function and add the test for no-JD cases."

**Gotchas:** Anything future-me needs to know that isn't in the code. Empty if none.

**State:** Branch, uncommitted changes, test status, anything operationally fiddly.
```

### Field rules

- **Progress** is always filled. Even "Abandoned in favor of #<N>" is a progress report.
- **Decisions** may be empty. If a decision happened, prefer putting the full entry in the issue body's `## Decisions` and referencing it in the Session note (e.g., "Added Decision re: Redis vs. Memcached"). Session notes are snapshots; the body is permanent.
- **Next action** must be specific. "Keep working on it" is failure. If the next action genuinely is "think about X more", write that — but be honest.
- **Gotchas** catches the content that otherwise gets lost. "The test fixture at `tests/fixtures/config/in_domain_patterns.yaml` has been mutated for this session — revert before committing." "Discovered that `poll_flags.py` uses PT timezone; other scripts use UTC."
- **State** is operational: branch name, whether the working tree is clean, whether tests pass, anything the next session needs to know before typing.

### Example (software)

```
## Session 2026-04-19

**Progress:** Implemented excluded_employers config loading in scorer_prefilter.py; two of three tests pass. Third failure traced to ordering in the YAML — need to decide whether to preserve order or sort.

**Decisions:** Added Decision to issue body re: external YAML file vs inline dict — went with external for testability.

**Next action:** Decide ordering question (probably preserve order to match user intent), implement, unblock the third test.

**Gotchas:** The prefilter test suite does not use the project's main conftest fixtures — there's a separate `tests/fixtures/config/` dir. Don't get confused.

**State:** Branch `feat/excluded-employers`, working tree clean, 2/3 tests passing, unpushed.
```

### Example (non-software)

```
## Session 2026-04-19

**Progress:** Demo'd the kitchen — removed upper cabinets, backsplash, and countertop. Disposed at the dump. Lower cabinets next.

**Decisions:** Decided to keep the existing subfloor (captured in issue body).

**Next action:** Start on lower cabinets Saturday morning — need to turn off the disposal plumbing first.

**Gotchas:** Found old water damage behind the backsplash near the window — probably needs a separate issue for moisture remediation before rough-in starts. Filed as #23.

**State:** Kitchen is mid-demo, dumpster arrives Monday.
```

## /jared-wrap — the session-end routine

Runs the full wrap in one command. Flow:

1. **Identify touched issues.** Read the session's history. Identify:
   - Currently In Progress issues
   - Issues mentioned in conversation
   - Issues referenced by recent commits
   - Any issue the user explicitly names

2. **Draft a Session note for each.** Pull content from:
   - Recent conversation (for Progress, Decisions, Next action, Gotchas)
   - `git diff` since the last Session note (for State and Progress)
   - Any `## Decisions` added to issue bodies this session (for Decisions summary)
   - The branch and working tree (for State)

   **Never fabricate.** Empty fields stay empty.

3. **Present the drafts to the user** in a single consolidated view:

   ```
   /jared-wrap — session end, 2026-04-19

   Drafting Session notes for:
     #14 (In Progress, primary focus this session)
     #23 (filed this session, not in progress)
     #18 (mentioned in relation to #14; touched lightly)

   Draft for #14:
     [shows the draft]

   Draft for #23:
     [shows the draft]

   ...

   Approve? (y / edit / skip-<issue>)
   ```

4. **Reconcile drift.** Before posting:
   - Any In Progress issue that was actually finished — propose closing it.
   - Any In Progress issue abandoned — propose moving back to Up Next or Backlog with the Session note explaining why.
   - Any scope discovered but not yet filed — propose filing now.

5. **Propose plan/spec archival** if any issues shipped. See `references/plan-spec-integration.md`.

6. **On user approval, post** via `${CLAUDE_PLUGIN_ROOT}/skills/jared/scripts/jared comment <N> --body-file -` (pipe the note through stdin) for each. For `## Current state` body updates, use `${CLAUDE_PLUGIN_ROOT}/skills/jared/scripts/capture-context.py --issue <N> --repo <owner>/<repo> --current-state "..."`.

## Auto-orientation on session start

When a session starts in a project with `docs/project-board.md`, Jared orients automatically. This is one of the primary triggers in SKILL.md's description — a new session is a session-start event.

The orientation output:

```
Where we are (board state, 2026-04-19):

In Progress (2/3):
  #14 [High/Infrastructure] Add excluded_employers config + prefilter
    Last session (2026-04-18): "2/3 tests passing, unpushed. Next: decide YAML ordering."
  #20 [High/Job Search] First-tester onboarding materials
    Last session (2026-04-16): "Draft sent to Alice; waiting for feedback."

Up Next (top 3):
  #31 [High/Job Search] Add JD-quality scoring tier — pullable
  #27 [Medium/Infrastructure] Logging consistency pass — needs acceptance criteria
  #35 [Medium/Generalization] Config externalization for prefilter — depends on #14

Blocked: none.

Aging: #18 (High Backlog) filed 2026-03-25, no activity — worth revisiting.
```

That's the handoff. No tmp file required.

## When the pattern fails

If a session ended without `/jared-wrap`, the next session starts without recent Session notes. Jared handles this by:

1. Reading the git log for the last session's commits.
2. Inferring what issue(s) were worked on.
3. Asking the user: "The last session ended without a wrap. Want me to draft Session notes retroactively based on the commits?"

Retro Session notes are marked as such in the header: `## Session 2026-04-19 (reconstructed)`.

## Why this beats tmp/handoff-prompt.md

- **Discoverable.** Next session's first action is read the board, not read a file you have to remember to open.
- **Durable.** Session notes live on issues permanently. Tmp files get deleted, lost, or forgotten.
- **Structured.** The format is consistent, so scanning is fast.
- **Correlated.** A Session note is tied to the issue it's about. A tmp prompt mentions issues but isn't *on* them.
- **Authoritative.** The issue is the source of truth. The Session note is part of that source of truth.

## Optional handoff prompt

For projects with long, well-defined queues — findajob, trailscribe — Session notes capture per-issue state but can't capture cross-issue narrative or the strategic frame that makes "what to pull next" obvious. The optional handoff prompt fills that gap.

**The contract:**

- **Derived.** The prompt is generated by `/jared-wrap` from durable records: posted Session notes, board state, memory entries, the just-finished session's conversation. Nothing in the prompt is the source of truth — every claim points back at one of those records.
- **Ephemeral.** Written to `tmp/next-session-prompt-<TIMESTAMP>.md`. `.gitignore`d. Regenerated each wrap. The footer warns against editing.
- **Opt-in.** `docs/project-board.md` can declare `session-handoff-prompt: always | ask | never` under `## Jared config`. Default is `ask` — `/jared-wrap` asks at the end of every wrap. Projects without the config get prompted; projects that say `never` are never asked.
- **Complementary, not replacement.** The next session still reads Session notes (via `/jared` auto-orientation) and uses `/jared-start <#>` to drill into a specific issue. The handoff prompt sits at the *session* level — picking which issue to pull. `/jared-start` operates at the *issue* level — drilling into the one you picked.

**Two-layer generation:**

1. **CLI skeleton.** `${CLAUDE_PLUGIN_ROOT}/skills/jared/scripts/jared next-session-prompt` emits the board-derived sections deterministically: In flight (with last-Session-note one-liners), Top of Up Next, Recently closed (7d), kickoff footer. Useful on its own for retroactive handoff after a wrap-less session.
2. **Synthesis layer.** `/jared-wrap` calls the CLI for the skeleton, then layers in Frame, What NOT to do, and (optionally) a Quick health check section using the board's `## Session start checks`. The synthesis comes from the wrap session's conversation context — that's the only place it lives.

**When the wrap is low-context** (short session, few decisions), the synthesis sections collapse to plain board-derived bullets. The prompt degrades gracefully — board state alone is still better than starting cold.

**The anti-pattern that remains.** Hand-rolling a `tmp/next-session-prompt.md` outside `/jared-wrap` is still wrong: the file becomes a parallel source of truth, the durable records drift, and the discipline rots. If you want a handoff prompt, ask `/jared-wrap` for it.

## Migrating away from existing tmp prompts

See `references/migration.md` — Jared can take a one-time pass through `tmp/next-session-prompt-*.md` files (or wherever existing handoff prompts live), identify the issues they reference, and propose either (a) filing the content as a retro Session note, or (b) filing new issues if the content represents unfiled scope. Then delete the drafts.
