# Context Capture — Keeping Issues Alive Mid-Work

Work reveals things. Design decisions get made while implementing. Gotchas get discovered. Assumptions turn out to be wrong. Sub-items get intentionally deferred. All of this is the content that disappears if it only lives in your head or in commit messages.

Jared's job is to capture this content on the active issue — not in a comment on another issue, not in a tmp file, not in a TODO. On the issue, in structured form, where future you (or future Claude) will actually find it.

## Two kinds of mid-work content

### Discovered scope

Actionable work that exceeds the current issue's boundary. Examples:

- "Oh — we should also refactor `cleaning.py`'s `normalize_whitespace` while we're here."
- "This exposes that our logging is inconsistent across the pipeline."
- "The config loader has a bug I just tripped on."

These are **new issues**. File them now. Do not park them as comments on the current issue. Do not inflate the current issue's scope.

See SKILL.md "While working — capture context as you go" for the filing routine. Fast path: `/jared-file` with the discovered scope.

### Evolving understanding

Content that refines the *current* issue, not a new one. Examples:

- "Decided to use `pathlib.Path` throughout for consistency."
- "Chose Redis over Memcached because we already run Redis for session state."
- "Turned out the existing `sync_sheet` already handles this — didn't need to write new code."
- "Deferred the caching layer until we have actual perf data — #<N> tracks it."

This goes on the *current* issue in one of two places:

- **`## Current state`** — updated as the implementation evolves. Overwrite. One paragraph answering "where is this right now?"
- **`## Decisions`** — appended. One entry per decision. Dated. Captures choices that aren't obvious from the diff.

## Trigger patterns

Jared pays attention to language and observable work signals. When any of these fire mid-session, consider capturing context:

**Linguistic triggers:**

- "I noticed..."
- "Turns out..."
- "Actually, let's..."
- "We should also..."
- "The tricky part is..."
- "I'm going to go with..."
- "This is getting complicated..."
- "Huh, that's weird..."
- "For now let's just..."
- "We'll come back to..."

**Observable triggers:**

- A test that was failing now passes.
- Claude is about to modify a third file in the same session without an issue covering the breadth.
- A significant design choice is being made in chat (e.g., "I'll use X instead of Y").
- The user says "actually, forget that" — something just got rolled back and the reason deserves capture.
- A PR description is being drafted.
- A block of `<details>` scope in the issue just got checked off.

When a trigger fires:

1. Decide: is this discovered scope (new issue) or evolving understanding (update current issue)?
2. If current issue: append to `## Decisions` for a choice-with-rationale, or update `## Current state` for a progress summary.
3. Use `scripts/capture-context.py` to do the body edit cleanly — it handles the `## Current state` overwrite vs `## Decisions` append logic.

## The capture script

```bash
# Update Current state (overwrites the section)
scripts/capture-context.py --issue <N> --repo <owner>/<repo> --current-state "Refactored the scorer to use the new prefilter module; tests pass except for test_tier_boost which needs fixture updates."

# Append a Decision
scripts/capture-context.py --issue <N> --repo <owner>/<repo> --decision "Chose to keep the legacy scorer path behind a feature flag for one release to give testers a fallback."

# Both in one call
scripts/capture-context.py --issue <N> --repo <owner>/<repo> \
  --current-state "..." \
  --decision "..."
```

The script preserves all other sections, including `## Acceptance criteria`, `## Depends on`, `## Planning`, and any `<details>` blocks. It's idempotent: calling it with the same `--current-state` twice doesn't duplicate content.

## When Jared captures automatically vs. asks

**Capture automatically** when the signal is unambiguous and the content is clear:

- A test passed — update `## Current state` to reflect that.
- A sub-item in acceptance criteria got checked off — reflect in `## Current state`.
- A branch got pushed — optional, noted in `## Current state`.

**Ask the user** when the decision has a rationale Jared would have to guess at:

- "We just decided to use Redis. Should I capture the rationale as a Decision on #N? If so, what's the one-sentence reason?"
- "You mentioned we should also refactor `cleaning.py`. File as a new issue now, or park the idea?"

Guessing rationales is worse than asking. A fabricated Decision entry is actively misleading — future you reads it and builds on a rationale that nobody actually held.

## What not to capture

- **Trivial progress** ("wrote one function"). `## Current state` is a paragraph, not a log.
- **Stream-of-consciousness.** If the content doesn't survive the question "would this help a future session?", don't capture it.
- **Content that belongs on a different issue.** If what you're capturing is really about issue #<M>, go capture it there.
- **Duplication with Session notes.** `## Current state` is the living summary; Session notes are the end-of-session snapshot. They overlap but aren't the same — Decisions never go in Session notes, progress belongs in both briefly.

## The goal

When a future session (yours or another Claude's) opens this issue, the first three sections (summary + Current state + Decisions) should be enough to resume work without reading the diff. That's the test. If you can't resume from the body, the body isn't doing its job.
