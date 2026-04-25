# Design: `/jared-wrap` produces an optional session handoff prompt

**Issue:** brockamer/jared#35
**Status:** Spec — awaiting plan
**Date:** 2026-04-25

## Problem

On queue-heavy projects (findajob, trailscribe), the user repeatedly asks Claude at the end of a session to "do a wrap and give me a session handoff prompt so I can clear this session." Claude obliges, synthesizing a multi-section prompt from session context, board state, memory, and just-written Session notes. The user clears the conversation and pastes the prompt into the next session.

This pattern is happening *despite* `session-continuity.md`'s explicit doctrine that Session notes + auto-orientation make handoff prompts unnecessary, and *despite* SKILL.md line 218 listing "writing a next-session prompt" as an anti-pattern.

The doctrine isn't wrong — it's incomplete. Session notes capture per-issue state. Auto-orientation surfaces the queue. Neither captures *session-shaped* content: cross-issue narrative, strategic framing, conditional decision trees, anti-targets with rationale, session-start operational commands. That content lives in the wrap session's conversation — the only place that has the synthesis to produce it.

The fix is to fold this into `/jared-wrap` as a derived, ephemeral output. The prompt is no longer a hand-rolled parallel source of truth; it's a generated artifact bridging two sessions, sourced from durable records (Session notes, board, memory) and discarded after use.

## Concept

At the end of `/jared-wrap`, after Session notes are drafted/posted and drift is reconciled, the slash command asks: *"Draft a session-start prompt for the next session?"* On `y`, Claude (still in the wrap session, with full conversation context) writes a structured prompt and saves it to `tmp/next-session-prompt-<YYYY-MM-DD-HHMM>.md`. The user clears their session and pipes the file in next time.

The prompt is **ephemeral** — `.gitignored`, regenerated each wrap, never committed. Session notes and memory remain the durable records. The prompt is just the bridge.

## Two layers of generation

**Slash-command layer (rich, contextual).** `/jared-wrap` synthesizes the full prompt using everything in scope: posted Session notes, the conversation that just happened (decisions, anti-targets, strategic framing the user said out loud), memory entries, board state. This is where prompt quality comes from — Claude has context to write the "binding constraint is upstream-starvation" framing because that thought *happened* in the prior session.

**CLI layer (skeletal, board-derived).** New subcommand `jared next-session-prompt` emits only what's mechanically derivable from the board — In Progress + Up Next + recent closes + per-issue last Session note one-liner. No synthesis. Useful for cron, ad-hoc inspection, or retroactive handoff after a wrap-less session.

The slash command can call the CLI subcommand to get the skeleton, then layer synthesis on top.

## Prompt structure

Section ordering and presence are configurable per-project via `docs/project-board.md`. Default scaffold:

1. **Frame** — release context, what shipped, what's load-bearing right now (1–3 sentences). Synthesized from conversation + recent closes.
2. **What's likely to want attention this session** — ordered queue with reasoning ("#273 first because the binding constraint is upstream pipeline starvation, not apply-laziness"). Pulls Up Next, layers in synthesis. Empty if no synthesis happened → falls back to plain board-derived bullets.
3. **What NOT to do** — anti-targets with rationale. Sources: scheduled-agent reminders firing in the future, memory entries flagged as session-applicable, things the user explicitly said out loud during wrap.
4. **Context you'll need** — pointers to CLAUDE.md, plan/spec docs, relevant memory entries.
5. **Quick health check on session start** — operational commands. Only emitted if `docs/project-board.md` defines a `session-start-checks` block. Pure config; jared doesn't infer these.

If wrap doesn't have rich synthesis content (short session, no decisions made), sections 1/2's prose collapses to bullet form derived from the board. The prompt degrades gracefully — board state alone is still better than nothing.

## Opt-in mechanism

Three layers, in priority order:

1. **Per-wrap question.** Slash command always asks at the end. Default behavior unchanged from today otherwise.
2. **Project default.** `docs/project-board.md` can specify `session-handoff-prompt: always | ask | never`. `always` skips the question and produces it; `never` skips both. Default is `ask`.
3. **No global default toward "always".** Stays opt-in across the board. Projects that prefer pure session-notes-only workflow don't get nagged.

## Relationship to `/jared-start`

Different layers, both fire next session in sequence:

- **Handoff prompt** — read first; sets *session-level* framing, decides which issue to pull
- **`/jared-start <#N>`** — invoked second, after picking; drills *issue-level* context

The handoff prompt explicitly ends with: *"To start: `/jared-start <#>`."* The two are complementary — the prompt picks the issue, `/jared-start` drills into it.

## Anti-pattern reconciliation

SKILL.md line 218 needs a one-line tweak. From:

> **Writing a next-session prompt.** Use `/jared-wrap` instead.

To:

> **Hand-rolling a next-session prompt outside `/jared-wrap`.** If you want one, ask `/jared-wrap` for it — the wrap-time prompt is derived from durable records and stays ephemeral; a hand-rolled tmp file becomes a parallel source of truth and rots.

`session-continuity.md` gets a new section ("Optional session handoff prompt") explaining the contract: **derived, ephemeral, never authoritative**.

## Files touched

- `skills/jared/scripts/jared` — new `next-session-prompt` subcommand (skeleton only, board-derived)
- `commands/jared-wrap.md` — extends Step 6 with the optional draft-prompt step
- `skills/jared/SKILL.md` — line 218 reframe + cross-reference
- `skills/jared/references/session-continuity.md` — new "Optional handoff prompt" section
- `skills/jared/assets/next-session-prompt.md.template` — new template file
- `skills/jared/assets/project-board.md.template` — add `session-handoff-prompt` and optional `session-start-checks` config keys
- `tests/test_cmd_next_session_prompt.py` — unit tests for the CLI subcommand
- `.gitignore` — ensure `tmp/next-session-prompt-*.md` is ignored (it likely already is via `tmp/`, but verify)

## Out of scope

- Auto-firing on every wrap without opt-in
- Storing the prompt in git or as an issue comment (would re-create the parallel-record problem)
- Generating prompts from board state alone, mid-conversation, on demand (use `jared next-session-prompt` for the skeleton; rich synthesis requires wrap-session context)
- Cross-project prompts (one prompt per project per wrap)
- Self-clearing the conversation (the prompt is what the user pastes into a fresh session; the clearing remains the user's action)

## Risks and mitigations

1. **Prompt quality regresses to mush on a low-context wrap.** Mitigation: graceful degradation — sections 1/2 collapse to board-derived bullets when synthesis is empty. Documented as expected behavior; the user's signal that the wrap session was thin.
2. **Users start treating the prompt as authoritative.** ("I'll just edit the prompt instead of updating the issue.") Mitigation: ephemeral storage + `.gitignore` + a footer line in the prompt itself: *"Regenerated each wrap; do not edit. Source of truth is the issues, plans, and memory."*
3. **`session-start-checks` config rots.** The operational commands drift from reality. Mitigation: those checks are user-authored and user-maintained. Any rot is the user's signal that they're stale.
4. **Two versions of jared treat handoff prompts differently.** Mitigation: bump plugin minor version (0.3.x → 0.4.0) since this changes `/jared-wrap` semantics; update `references/session-continuity.md` so the contract is documented in one place.

## Acceptance

A successful implementation:

- Adds the CLI subcommand and tests for it (board-derived skeleton, no GitHub side effects, deterministic output)
- Updates `/jared-wrap` to ask the optional question and produce the rich prompt when the user accepts
- Reframes SKILL.md line 218 and adds the new section to `session-continuity.md`
- Adds the two new config keys to the project-board template (`session-handoff-prompt`, `session-start-checks`)
- Verifies on the jared project itself by running `/jared-wrap` end-to-end and producing a usable prompt
- Verifies on at least one queue-heavy project (findajob recommended) that a wrap-generated prompt matches the quality of the hand-asked prompts the user has been getting
