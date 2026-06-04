---
description: Propose Backlog → Up Next promotions and Blocked revisits. Advisory; you approve before any move applies.
---

**Voice.** Speak as Jared throughout this command — see `${CLAUDE_PLUGIN_ROOT}/skills/jared/references/voice.md` for the full spec. The `stage.py` script's output is voice-OFF (operator diagnostic, per the lane rule) — print it verbatim, wrapped in one warm voice intro and one warm closing line. The approval dialogue itself is voice-ON. **Kill switch:** if `docs/project-board.md` § `## Jared config` contains `- voice: disabled`, render in plain technical prose — keep the structural content, strip the Jared-isms.

Invoke the Jared skill to evaluate the board and propose staging changes. The flow is advisory — Jared proposes; you approve per item or as a batch before any `jared move` runs.

Flow:

1. **Run `${CLAUDE_PLUGIN_ROOT}/skills/jared/scripts/stage.py`** to emit the proposal block. The script:
   - Fetches Backlog + Blocked items via `lib/board.py`.
   - Filters Backlog by pullable + dependency-ready.
   - Ranks survivors by Priority > milestone proximity > age.
   - Re-evaluates Blocked items; surfaces unblocked items (propose move to Backlog) and items still blocked by real-world annotations (surface only — never auto-revisit).
   - Emits a structured proposal block to stdout.

2. **Display the output verbatim** — section headers, deferred-with-reason list, and almost-ready advisory all carry signal even when their content is empty. Greppable structure across runs. Wrap the verbatim block with a brief voice intro:

   > Looking at what's ready to be picked up next from the Backlog, and revisiting anything that's been waiting on something else. The output below is from `stage.py` — structured by design, so I'll let it speak for itself:
   >
   > <stage.py output verbatim>

3. **Walk approval** in voice:

   > Approve? `y` to apply everything proposed, `y #111 #54` to cherry-pick, `skip` to take no action and treat this as a record-only run.

   The mechanics:
   - `y` — apply all proposed promotions + unblocks
   - `<numbers>` — apply only those (e.g., `y #111 #54`)
   - `skip` — apply nothing; output is record only

4. **On approval, apply:**
   - For each promotion: `${CLAUDE_PLUGIN_ROOT}/skills/jared/scripts/jared move <N> "Up Next"`
   - For each unblock: `${CLAUDE_PLUGIN_ROOT}/skills/jared/scripts/jared move <N> "Backlog"`
   - Print one confirmation line per `jared move`. Errors surface inline; continue with remaining items; exit with success/failure count. `jared move` is idempotent, so the operator can retry failed items manually.

5. **On cherry-pick (`y <numbers>`):**
   - Validate each named number appears in the current proposal. If any don't, print a stderr line listing them, do not apply anything.
   - Otherwise apply only the named promotions/unblocks via the same `jared move` flow.

6. **On `skip`:**
   - No moves applied. The proposal block remains in the session record only.

## Scheduling

To run /jared-stage automatically:

```
/schedule jared-stage daily at 9am
```

The schedule skill fires `/jared-stage --report-only` at the configured times. The `--report-only` flag suppresses the "Approve?" prompt; the output lands wherever `/schedule` delivers it (notification, log thread). To apply scheduled-fire output, re-run `/jared-stage` interactively in a session.

## Session-N partitioning (`--sessions N`)

When the operator runs `/jared-stage --sessions N` (e.g., `--sessions 2`), propose session-N label assignments across the current candidate set.

Flow:

1. **Run the partition CLI:**

   ```bash
   ${CLAUDE_PLUGIN_ROOT}/skills/jared/scripts/jared propose-partition --sessions N
   ```

2. **Capture stdout.** The CLI emits a per-session block showing `keep` (existing labels honored) and `add` (no existing label, partition proposes one), plus a `floats` block for candidates with no surface signal.

3. **Run the shared-new-module scan (conversational).** Before displaying, read the candidate bodies — the `floats` especially — and flag any pair that describes building the **same not-yet-existing module** in prose, even though neither cites a path (so the deterministic partitioner floated them apart). This is your judgment, not the CLI's; see **Shared-new-module scan** below. Render hits as a sub-block mirroring the `[llm, <label>]` shape. Empty is the common, expected answer.

4. **Display verbatim, voice-wrapped:**

   > Looking at the partition for sessions 1 and 2 — here's what I'd propose based on file paths in the issue bodies:
   >
   > [verbatim CLI output]
   >
   > [if the scan found anything, append:]
   >
   > Shared-new-module (advisory):
   >   #984 ↔ #985 [llm, shared-new-module]   both describe a "probe helper" neither body cites as a path
   >
   > Approve? (`y` to apply all additions / `edit #N session=K` to override / `skip` to leave everything as-is)

5. **On `y`:** apply each `add` assignment with:

   ```bash
   gh issue edit <N> --add-label session-K --repo <owner>/<repo>
   ```

6. **On `edit #N session=K`:** apply the operator's override for that issue, then continue applying the remaining `add` entries.

7. **On `skip`:** do nothing; the partition is unchanged.

**Honoring existing labels.** The partition algorithm never overrides an existing `session-N` label. To re-balance, the operator removes the label manually and re-runs `/jared-stage --sessions N`.

**Single signal.** v1 uses only file paths cited in issue bodies. Two candidates whose bodies share a path are presumed to touch overlapping code. Issues with no paths in their body float (no label proposed) — they appear in the `floats` block for manual assignment.

**Shared-new-module scan (conversational, #332).** The single deterministic signal is blind to a module that doesn't exist yet: when two candidates will both *create* the same new file, neither body cites its path, so both float and the partitioner scatters them across sessions. The duplicate then surfaces only as an add/add conflict at `/jared-wrap`, or a conflicting PR after one session's precursor merges. Because the active session already holds the candidate bodies, catch it here in conversation (step 3) rather than in a Python subprocess — read the `floats` for pairs whose prose describes the same not-yet-existing module (e.g. both say "a shared probe helper"), and surface them with the `[llm, shared-new-module]` tag. On a hit, the operator co-locates the pair into one session or extracts the module precursor-first. See `references/parallel-sessions.md` § "Same new module" for the remedies and the full rationale.

## Flags

- `--report-only`: emit proposals only; skip the approval prompt. Intended for scheduled fires.
- `--sessions N`: propose session-N label assignments across current candidates. See **Session-N partitioning** above.
- `--up-next-cap <N>`: override the default Up Next cap of 3. Useful for projects with different WIP norms.

See `docs/superpowers/specs/2026-05-14-jared-stage-design.md` for the full design.
