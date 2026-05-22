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

## Flags

- `--report-only`: emit proposals only; skip the approval prompt. Intended for scheduled fires.
- `--up-next-cap <N>`: override the default Up Next cap of 3. Useful for projects with different WIP norms.

See `docs/superpowers/specs/2026-05-14-jared-stage-design.md` for the full design.
