# Capability declaration + graceful degradation — Phase 6 (design)

**Issue:** #319 (Phase 6). Parent epic: #313.
**Date:** 2026-06-09
**Status:** Design — not yet started. Drafted during the 2026-06-09 structural review; **open design questions below are unresolved and must be settled (with the operator) before a plan is written.**
**Related references:** `skills/jared/scripts/lib/board_provider.py` (the `Capability` enum), `lib/github_provider.py`, `lib/kanbanflow_provider.py`, `docs/superpowers/specs/archived/2026-06/2026-06-02-board-provider-abstraction-design.md` (§ "`Capability` enum", § "Appendix A — Capabilities KanbanFlow will omit"), the slash-command stubs under `commands/`, `skills/jared/SKILL.md`, `skills/jared/references/operations.md`.

## Context — the larger feature

Epic #313 makes jared's board backend pluggable. Phase 1 (#314) defined a `Capability` enum and had `GitHubProjectsProvider` advertise the **full** set; Phase 3 (#316) built `KanbanFlowProvider`, which by design omits several capabilities (Appendix A). But nothing yet *acts* on the enum — every command still assumes GitHub's full feature set. On a KanbanFlow board, a command that reaches for a milestone's due date or an issue's closed-at timestamp gets nothing, or worse, wrong output.

Phase 6 closes that gap: each capability-dependent surface checks the active provider's capabilities and **degrades with a documented note** instead of failing or lying. This is where "capability-based parity" — core board loop works on both backends, GitHub-only richness degrades gracefully — becomes user-visible. Phase 6 is independent of Phase 5 and runs in parallel after Phase 4.

## Problem

The capabilities KanbanFlow omits, and the surfaces that depend on them (from Appendix A):

| Capability | What it gates | Surfaces that assume it |
|---|---|---|
| `MILESTONE_STATE` | milestone open/close + due dates | `/jared-reshape` (Roadmap, milestone dates), `/jared-audit` (date-gate heuristics), `milestones-and-roadmap` reference |
| `VELOCITY_TIMESTAMPS` | created / closed / transition times | `sweep.py` (aging, stale-In-Progress, stale-High), velocity-calibrated audit window, `/jared-groom` aging checks |
| `NATIVE_DEPENDENCIES` | a real relation edge vs. a `blocked-by:<N>` label-marker | `dependency-graph.py`, `jared blocked-by`, sweep's native-dependency hygiene |
| `MARKDOWN_BODY` | rendered markdown vs. plain text | issue-body templates, `human-readable-board` reference |
| `CLOSED_STATE` | a real closed state vs. "in the Done column" | `jared close`, sweep's "stuck closed item" check, Done semantics |
| `MCP_TIER` | the MCP-first operations tier | `references/operations.md` three-tier model |
| `SUB_ISSUES` | native sub-issue links | epic/sub-issue surfaces |

Today each of these would, on KanbanFlow, either error (calling a method the provider can't fulfil) or silently produce misleading output (an aging report computed from absent timestamps). Neither is acceptable. The discipline the operator already holds elsewhere — **no silent caps; log what was dropped** — is exactly the bar here: a degraded surface must *say so*, in one clear line, not quietly omit.

## Goals

- Every capability-dependent surface (the table above, enumerated exhaustively during planning) checks `provider.capabilities()` and, when the required capability is absent, **degrades with a consistent, documented note** rather than failing or emitting wrong output.
- A **single degradation helper** produces that note in one format, so the behavior is uniform across surfaces instead of re-invented per command. Shape: `degraded: <feature> unavailable on <backend> — <what happens instead>`.
- **GitHub backend behavior is unchanged** — it advertises the full set, so no surface degrades; this is the regression bar.
- The capability set is **resolved once** per invocation (it is static per backend), not re-queried per call.
- Degradation is **tested** per capability using a capability-restricted fake provider, **and** the user-visible path is confirmed live against a real KanbanFlow board (see Acceptance).

## Non-goals (Phase 6)

- **No new capabilities and no provider changes** beyond what Phase 1/3 defined — Phase 6 *consumes* the enum, it doesn't extend the contract. (If planning reveals a missing capability, that is a finding to surface, not silently add.)
- **No migration logic** — that is Phase 5 (#318).
- **No repo/git-axis changes** — PRs, worktrees, session locks, wrap-state, plan archival are backend-independent and never gated by board capabilities.
- **No attempt to *emulate* a missing capability beyond what already shipped.** blocked-by's label-marker emulation landed with `KanbanFlowProvider`; Phase 6 makes the dependency surfaces *aware* that they are reading emulated edges, it does not build new emulations.

## Architecture

### Two layers gate differently

1. **Python surfaces (CLI subcommands + batch scripts).** Straightforward: read `board.provider.capabilities()`, branch, and route the note through the degradation helper. `sweep.py`'s velocity section, `dependency-graph.py`'s edge source, `jared close`'s Done semantics — each guards its capability-dependent block.

2. **Markdown surfaces (slash-command stubs + SKILL.md + references).** These can't "check" at runtime — they are prose Claude reads. The mechanism must therefore *surface* the capability set to Claude so the rendered behavior adapts. The leading candidate (open question) is a small **`jared capabilities`** subcommand that prints the active backend and its capability set, which the relevant slash-command stubs instruct Claude to consult and degrade against (e.g., `/jared-reshape` skips the Roadmap-date section with a note when `MILESTONE_STATE` is absent). This parallels how the voice kill-switch is surfaced today: doctrine instructs the reader to check a value and branch.

### The degradation helper is the consistency anchor

A single function (Python) + a single documented note phrasing (doctrine) so that "this feature degraded because the backend lacks X" reads identically whether it surfaces from `sweep.py`, `jared close`, or a slash command. Without this anchor, each surface invents its own wording and the degradation becomes noise.

### Default posture: skip-with-note, not error

A missing capability degrades to a soft skip with a one-line note by default. Whether *any* surface is meaningless enough without its capability to warrant a hard error (rather than a skip) is an open question — but the default is soft.

## Open design questions — settle before writing the plan

1. **How do markdown surfaces become capability-aware?** A `jared capabilities` subcommand + per-stub doctrine instructing Claude to consult it and branch? Or bake conditional capability notes directly into each stub's prose? The former centralizes; the latter avoids a runtime call but scatters the logic.
2. **Soft-skip vs hard-error per surface.** Is there any surface where degrading silently-ish is worse than refusing outright (e.g., a velocity report that would be actively misleading)? Default soft; enumerate exceptions.
3. **Should `jared` / `jared summary` print a standing backend + degraded-features header**, so the operator always knows which surface they're on and what's unavailable — rather than discovering it per command?
4. **`SUB_ISSUES`** — Phase 1 anticipated it but Appendix A's omission list doesn't name it for KanbanFlow. Confirm whether KanbanFlow's subtasks satisfy it (KF tasks embed `subTasks`) or whether epic/sub-issue surfaces degrade too.
5. **Granularity of the note.** One note per degraded *command*, or one per degraded *check within* a command (e.g., sweep has several timestamp-dependent sections)? Per-check is more honest but noisier.

## Acceptance criteria

- Each capability-dependent surface from the table checks the provider's capability set and degrades with a documented note instead of failing or emitting wrong output; the enumeration is complete (a grep/inventory in the plan proves no capability-assuming surface was missed).
- A single degradation-note format is used across all surfaces (one helper, one phrasing).
- **GitHub backend: zero behavior change** — full capability set means no surface degrades. The existing unit suite passes untouched on the GitHub path.
- New unit tests assert the degraded path for each capability using a capability-restricted fake provider (advertise a subset, assert the note + the skipped behavior).
- **Live verification (required, not fake-only):** capability resolution **and at least one degraded surface** are exercised against a **real KanbanFlow board**, not just `FakeKanbanFlowClient`. The fake can mask the live capability-response shape the same way it masked write-path returns in #317 / PR #334 — so the user-visible degradation must be confirmed live.
- `ruff check .`, `ruff format .`, `mypy` clean.

## Documentation Impact

- Each slash-command stub that degrades (`/jared-reshape`, `/jared-audit`, `/jared-groom`, others found during planning) — document the KanbanFlow-degraded behavior inline.
- `skills/jared/references/operations.md` — a capability/degradation section; scope the MCP-first three-tier guidance to `MCP_TIER` (GitHub-only).
- `skills/jared/SKILL.md` — note the capability model and where degradation is doctrine vs. code.
- `docs/project-board.md` — a "capabilities on this backend" note so a KanbanFlow-stewarded project documents what degrades.
- `CLAUDE.md` — capability-consumption note alongside the existing board-provider abstraction paragraph.
- `CHANGELOG.md` + GitHub Release — at ship, under **Features**.
- A new implementation plan in `docs/superpowers/plans/` at activation, citing `## Issue: #319`.
