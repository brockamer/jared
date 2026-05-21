# Spec: `/jared-audit` — skeptical backlog audit

**Issue:** #169
**Date:** 2026-05-21

## Posture

`/jared-audit` is Jared acting as a skeptical expert kanban manager. It walks the backlog oldest-first, asks hard questions per item, and proposes operator-approved mutations. The outcome is a board you can pull from with confidence — no stale assumptions, no superseded work, no items whose framing will lead a session down a stray path.

Operator-triggered, never autonomous. Every mutation is approved before it lands.

## Scope (v1)

- **Issues** anywhere on the board (typically Backlog; Up Next and Blocked are in scope too).
- **Milestones** — independent pass over due dates, child alignment, dissolution.

Other entity types (labels, views, fields) are deferred.

## The skeptical checklist

For each item in the audit window, the conversation runs seven questions. The wording applies to both issues and milestones; type-specific examples in parentheses.

1. **Necessity** — is this still needed, or has the need evaporated?
2. **Scope realism** — has the scope grown into yak-shaving? *(Milestone: still a coherent ship?)*
3. **YAGNI** — speculative future-proofing dressed up as a ticket? *(Milestone: "Q4 2026 maybe" placeholder?)*
4. **Antipattern** — premature abstraction, work-avoidance, cargo-cult? *(Milestone: roadmap-theater?)*
5. **Framing accuracy** — do file paths / function names / numbers in the body still match the codebase today? *(Milestone: description still reflects intent?)*
6. **Dependency edges** — blockers actually still blocking? *(Milestone: child issues actually aligned with the ship?)*
7. **Calibration** — priority still right for today's shape? *(Milestone: due date still real, **and is it calibrated to the recent shipping trend** rather than parked 3–6 months out?)*

The questions are the action. Verdict buckets are the output.

## Verdict buckets

**Issues:** `close-as-completed` | `close-as-not-planned` | `reshape` | `leave-alone`

**Milestones:** `close` | `dissolve` | `reshape` | `leave-alone`

`leave-alone` should be the dominant verdict on a healthy backlog. Closing for its own sake is not a goal.

## Shape

- **`/jared-audit`** slash command — owns the seven-question doctrine, the calibration-first / batch-3-to-5 pacing, the verdict definitions, the close-reason rubric (`Completed` vs `Not planned`), and the close-comment requirements.
- **`jared audit fetch [--count N | --age-days N | --issues N,M,…] [--type issues|milestones|both]`** CLI subcommand — returns JSON working set (oldest-first; per issue: body, age, status, milestone, priority, open-dependents; per milestone: due date, child issues with status). The JSON also includes a top-level **`velocity`** block (recent closure rate + median age-at-close + median time-to-close) so the conversation can frame proposed dates against the recent trend rather than guessing thresholds.
- **Mutations** use existing `jared` atoms where they exist (`jared close`, `jared comment`, `jared set <field> <value>`). Body/title edits and all milestone mutations go through `gh api`. No new `jared apply-verdict` subcommand.

This mirrors the `jared ties` pattern: deterministic data-fetch in Python, semantic judgment in the live conversation.

## Pacing

One sentence in the slash-command prompt:

> *"Go deeper on the first item to calibrate depth; batch the rest in groups of 3–5."*

No state machine. Pacing is conversational discipline, not Python.

## Velocity-aware date heuristics

Static `--age-days` thresholds drift wrong on a project that ships fast. "90 days old" feels generous on a project closing 2 items a month, but is ancient on one closing 15 a week. The action calibrates to recent reality:

- **Default staleness threshold** (when `--age-days` is omitted): derived from `velocity.median_age_at_close` of items closed in the last 14 days, with a floor of 14 days and a ceiling of 60 days. Items older than `2 × median_age_at_close` are considered stale by default.
- **Velocity block in fetch output:** every `jared audit fetch` call returns:
  - `velocity.closures_last_14d` — count
  - `velocity.median_age_at_close` — days
  - `velocity.median_time_to_close` — days from `In Progress` → closed
- **Date proposals are aggressive.** When the conversation proposes a new milestone due date (during reshape), the default anchor is `velocity.median_time_to_close × remaining_open_children` days from today, biased toward the near term. A proposal that pushes past this anchor MUST surface a one-line written rationale (e.g., "external dependency lands week of X") that gets included in the operator's approval prompt. Default cadence: weeks, not quarters.
- The slash-command markdown documents the velocity block, the anchor formula, and the rationale-required rule.

## Atomicity

Per-issue mutations are all-or-nothing via the existing `jared` atoms (each atom owns its own invariant). Batch-level atomicity is not provided; if item 4 of a batch fails after items 1–3 succeeded, the operator sees the failure and re-runs just item 4. This is the right trade for the failure mode (rare race conditions on body edits), and it avoids inventing rollback semantics for a low-risk concern.

## Close-comment requirements

Close comments are non-empty by default. The conversation prompts the operator for:

- **Trigger condition** — what would cause re-filing? (esp. for `Not planned`)
- **Supersede reference** — which open issue (if any) absorbs this work?
- **Rationale** — why now, why this verdict?

Then the conversation drafts free-form prose incorporating those elements. Free-form because the right shape varies by verdict reason; the required elements exist because non-empty close comments are the issue's specific concern.

PII pre-flight runs on every proposed body edit and close comment, the same way it does in `jared file`.

## Files touched

- **New:** `commands/jared-audit.md` (the seven-question doctrine + pacing + close-reason rubric live here)
- **Modify:** `skills/jared/scripts/lib/board.py` — add `fetch_audit_window(...)` and `compute_velocity(...)` (closures + median age-at-close + median time-to-close over the last 14 days)
- **Modify:** `skills/jared/scripts/jared` — wire `audit fetch` subcommand
- **Modify:** `skills/jared/SKILL.md` — inventory entry for `/jared-audit` + add staleness triggers
- **Modify:** `skills/jared/references/operations.md` — one paragraph describing the action
- **New:** `tests/test_cmd_audit.py` — oldest-first ordering, open-dependents enrichment, milestone fetch shape, velocity computation (closure count + median age-at-close)

No new `lib/stale_audit.py` module. No new `references/stale-audit.md` reference file. The slash-command markdown is where the doctrine lives.

## Deferred (post-v1)

- Coupling with `jared-groom` aging output as input (worth exploring once both behaviors exist)
- Scheduled / recurring mode (operator-triggered first; automation later)
- "Flag-during-normal-work" queue ("I noticed #194 is stale while doing X" → queued for next audit)
- First-class `jared milestone-*` mutation atoms (deferred until milestone-audit reveals which mutations are actually load-bearing; `gh api` is fine for v1)

## Acceptance criteria

Per #169, with these clarifications:

- Window selection accepts `--count`, `--age-days`, or `--issues`; `--type` (default `issues`) extends to `milestones` or `both`. Omitting `--age-days` selects items older than `2 × velocity.median_age_at_close` (floor 14d, ceiling 60d), not a static default.
- Fetch output includes the velocity block; reshape proposals that set or move due dates MUST anchor to that block and document the reasoning if they push more than a few weeks out.
- Each item produces one of the four verdicts (typed by entity), justified with citations to current code where applicable.
- Open-dependent check runs before any `close-as-*` verdict (for issues: native blocked-by dependents that are still open). For a milestone `close` verdict, the equivalent check surfaces any open child issues belonging to the milestone.
- Reshape verdicts produce preview-then-apply mutations the operator can edit or reject.
- Calibration depth on item 1; batches of 3–5 thereafter.
- Per-issue atomicity via existing atoms (batch-level atomicity explicitly out of scope).
- Close comments non-empty by default; PII pre-flight on all drafts.
- Post-run, the operator can point to a concrete delta (closed / reshaped / untouched).
