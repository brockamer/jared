# `/jared-start` — handoff-prompt pickup

**Date:** 2026-04-26
**Status:** Draft
**Scope:** Consumer-side change to `commands/jared-start.md`. Producer (`/jared-wrap`) is untouched.

## Problem

`/jared-wrap` produces a rich session-handoff prompt at `tmp/next-session-prompt-<YYYY-MM-DD-HHMM>.md` containing cross-issue synthesis (Frame, anti-targets, context pointers, recommended-issue `## To start`). The producer was designed so the next session ingests this prompt at start. Today the only mechanism to ingest it is for the user to manually pipe the prompt content into the next session's first turn — `/jared-start` itself does not look for it.

This means the synthesis that `/jared-wrap` carefully produces is routinely discarded. Sessions that begin with a bare `/jared-start <N>` lose the cross-issue posture (what's load-bearing, what NOT to do, what shipped) that the producer side spent compute to generate.

## Goal

`/jared-start` should look for the most recent handoff prompt and, if found, surface its synthesis as a "Handoff posture" block above the existing per-issue announcement, and (when no explicit issue argument is given) honor the prompt's `## To start` recommendation — with a drift check so a stale recommendation never silently routes the session to a closed/done issue.

## Non-goals

- **No producer-side changes.** `/jared-wrap` continues to write `tmp/next-session-prompt-*.md` exactly as today.
- **No CLI subcommand.** This is pure command-prompt template logic. The model executing `/jared-start` already has bash + glob + Read; no new `jared` subcommand is warranted.
- **No authoritative status promotion.** The prompt remains derived state. Session notes, issues, plans, and memory remain the durable record. The posture block is a synthesis surface, not a decision log.
- **No replacement of the existing per-issue context load.** Step 4 of the current flow (issue body, latest Session note, linked plan/spec, git state) runs unchanged.

## Behavior

At the top of `/jared-start`, before the existing WIP-cap check (current Step 1):

### Step 0 — look for the most recent handoff prompt

1. Glob `tmp/next-session-prompt-*.md`.
2. If `tmp/` doesn't exist or no matches: set `prompt = None`, proceed.
3. Otherwise lex-sort filenames descending, take the first. The filename's `YYYY-MM-DD-HHMM` is monotonic, so lex order matches chronological order. Set `prompt = <path>`.

### Branch table

| Prompt found? | `$ARGUMENTS` given? | Action |
|---|---|---|
| No | No | Existing behavior — ask which issue. |
| No | Yes | Existing flow on `$ARGUMENTS`. |
| Yes | No | Parse `## To start` for `/jared-start <N>`. **Drift-check** that issue. If pullable, run existing flow on it. If drifted (closed or Status=Done), surface posture + drift message and ask the user which issue to pull. |
| Yes | Yes | Run existing flow on `$ARGUMENTS`. Surface posture block above the per-issue announcement. No drift check (user picked their own issue). |

### Drift check

Only fires when the prompt's recommendation would be used (no `$ARGUMENTS`, prompt found). Run `${CLAUDE_PLUGIN_ROOT}/skills/jared/scripts/jared get-item <N>` on the prompt's recommended issue. Drift conditions:

- Issue is closed on GitHub.
- Issue Status is `Done`.

On drift: do **not** silently fall back. Print:

```
Handoff prompt recommends #<N>, but #<N> is now <closed|Done>.
The prompt's posture is still useful context for whatever you pull next:

<full posture block — Frame, anti-targets, context pointers>

Which issue would you like to pull?
```

Then wait for user input. The prompt's body is still rendered because its synthesis (anti-targets, context pointers) is cross-issue and remains relevant even when its `## To start` recommendation is stale.

### Posture-block layout

When prompt is found and being surfaced (any cell with "Yes" in the prompt-found column):

```
Handoff posture (tmp/next-session-prompt-<TIMESTAMP>.md, <relative-time>):
  Frame: <Frame paragraph, condensed to 2-3 sentences if needed>
  Anti-targets:
    - <bullet from "What NOT to do">
    - <...>
  Context pointers:
    - <bullet from "Context you'll need">
    - <...>

Starting #<N>: <title>
  [existing per-issue announcement, unchanged]
```

Two visually-separated blocks: cross-issue posture above, issue-specific below.

### Parsing rules

- **Most recent prompt:** `glob tmp/next-session-prompt-*.md`, lex-sort descending, take `[0]`. Empty match set → no prompt found.
- **Recommended issue:** in the prompt body, locate the section `## To start`. Within that section, find a fenced code block containing a line matching `/jared-start\s+(\d+)`. If no match: log "Handoff prompt has no `## To start` recommendation" and treat the prompt-found-no-args case as if no prompt were found (ask which issue), but still surface the posture block.
- **Frame:** read the section under `## Frame`. Condense to 2–3 sentences if longer; never fabricate.
- **Anti-targets:** read the section under `## What NOT to do`. Render as bullets. Empty if the section is empty.
- **Context pointers:** read the section under `## Context you'll need`. Render as bullets. Empty if the section is empty.
- **Missing sections:** omit the corresponding line from the posture block. Do not fabricate.
- **Relative time:** parse the filename's `YYYY-MM-DD-HHMM` and render relative to now ("6h ago", "yesterday", "3d ago"). On parse failure, fall back to the raw absolute timestamp.

## Files affected

- `commands/jared-start.md` — primary edit. Insert Step 0 (look for prompt) at the top of the flow. Thread the posture block into Step 5's announcement template. Document the drift-check branch.
- No CLI changes. The command file is the model's contract; the model executes the lookup with its existing bash + Read tools.
- No test changes. The command file is documentation for the model; nothing in the Python suite tests prompt content.

## Risks and mitigations

- **Prompt synthesis drift.** The prompt could go stale across multiple sessions if `/jared-wrap` isn't run. Mitigation: the relative-time display ("3d ago") makes staleness visible; the user/agent can decide whether to trust it.
- **Prompt's `## To start` recommends an issue that's been reshaped/abandoned but not closed.** The drift check only catches Closed/Done. A reshaped issue that's still Open + Up Next will pass the drift check; the existing pullable-check at Step 2 of the original flow will then catch any pullable-criteria failure (missing acceptance criteria, unmet `Depends on`). Mitigation: defer to Step 2's pullable-check; this is the correct layer for that concern.
- **Multiple prompts in `tmp/` from old sessions.** Lex-sort by filename timestamp picks the newest. Old prompts remain on disk (gitignored, ephemeral) and are harmless.
- **Parser fragility.** Section-header regex assumes the producer's template structure. Mitigation: when a section is missing, omit that line — never block or fabricate. The producer template is in `assets/next-session-prompt.md.template`; if it changes, the parser tolerates absence gracefully.

## Out of scope (explicitly)

- A `--no-handoff` flag to suppress the posture block. Not warranted yet; if the synthesis is irrelevant the user can ignore it.
- Cleaning up old prompts in `tmp/`. They're gitignored and ephemeral; no automatic cleanup is needed.
- Surfacing the posture block on `/jared` (status command). Different command, different surface; out of scope for this change.

## Acceptance criteria

- `/jared-start` with no args and a recent `tmp/next-session-prompt-*.md` containing a parseable `## To start` reads that file, drift-checks the recommended issue, and runs the existing flow on it (or asks on drift).
- `/jared-start` with no args and no prompt available falls back to the current "ask which issue" behavior.
- `/jared-start <N>` with a recent prompt available surfaces the posture block above the per-issue announcement, on the user-specified issue, with no drift check.
- `/jared-start <N>` with no prompt available behaves identically to today.
- Drift case (prompt recommends a Closed/Done issue) prints the posture block, the drift line, and asks the user which issue to pull. It does NOT silently fall through.
- Missing prompt sections (no `## Frame`, no anti-targets, no `## To start` line) are tolerated: corresponding lines are omitted, no fabrication, no error.
