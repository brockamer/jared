---
**Shipped in #313, #319 on 2026-06-10. Final decisions captured in issue body.**
---

# Capability declaration + graceful degradation — Phase 6 (design)

**Issue:** #319 (Phase 6). Parent epic: #313.
**Date:** 2026-06-09
**Status:** Design — open questions **resolved 2026-06-09 with the operator** (see "Resolved design decisions" below). Ready for an implementation plan.
**Related references:** `skills/jared/scripts/lib/board_provider.py` (the `Capability` enum), `skills/jared/scripts/lib/github_provider.py`, `skills/jared/scripts/lib/kanbanflow_provider.py`, `docs/superpowers/specs/2026-06-02-board-provider-abstraction-design.md` (§ "`Capability` enum", § "Appendix A — Capabilities KanbanFlow will omit"), the slash-command stubs under `commands/`, `skills/jared/SKILL.md`, `skills/jared/references/operations.md`.

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
| ~~`SUB_ISSUES`~~ | ~~native sub-issue links~~ | **struck — phantom capability (see Resolved decision 4).** No surface consumes it on *either* backend; jared's epic model is the `epic` *label*, which is backend-neutral. |

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

## Resolved design decisions (settled 2026-06-09 with the operator)

The five open questions were pressure-tested against the codebase — an 84-surface capability inventory (four-region fan-out) plus five adversarial reviews — and settled with the operator before this plan was written. Three of the five reversed the initial tentative positions.

1. **Prose surfaces branch on the existing `- backend:` bullet — no subcommand, no generated block.** Slash-command stubs, `SKILL.md`, and references become capability-aware by reading the `- backend:` selector already present in `docs/project-board.md` § "Jared config" and branching ("if backend is `kanbanflow`, degrade `<surface>` with a note") — the *actual* voice-kill-switch pattern, which is a pure doc-read with no `jared voice-status` companion. Rejected: a `jared capabilities` subcommand (it surfaces a fact already one bullet away; the capability set is a compile-time constant `frozenset(Capability) − omitted`, not resolved live) and a generated capabilities block in the convention doc (derivable, so a snapshot only invites drift). The `Capability` enum stays a Python-layer concern: CLI subcommands and batch scripts read `board.provider.capabilities()` in-process and emit degradation through the single shared helper; stubs that invoke those scripts render the degraded output for free.

2. **Soft-skip-with-note is the default; whole-scope-absent invocations exit nonzero.** A missing capability degrades to a soft skip with a one-line note. Two refinements:
   - *Misleading-if-shown* surfaces (a velocity/aging value computed from absent timestamps reading "0 days" = falsely fresh) **omit** the value with a note rather than print a wrong number — they do not hard-error the command.
   - When the absent capability is the **entire explicitly-requested scope** of an invocation — canonically `jared audit fetch --type milestones` / `--type both` on a `MILESTONE_STATE`-absent backend, and the `jared file --milestone NAME` write path — the command **exits nonzero** with the degradation note rather than returning a hollow exit-0 success that feeds empty data downstream. This mirrors the existing `_cmd_file` refusal when `--milestone NAME` matches no open milestone.

3. **No standing degraded-features header.** The conditional "render only when degraded" header was rejected: it contradicts jared's consistent-shape doctrine (blank on GitHub, where an orientation line would reassure; all-seven-caps noise on KanbanFlow), and it conflated the prose `/jared` stub with the `jared summary` CLI (different mechanisms). Phase 6 relies on per-section notes only — no header on the CLI, no standing orientation line.

4. **`SUB_ISSUES` is a phantom capability — Phase 6 builds nothing for it.** No surface consumes `SUB_ISSUES` on *either* backend: the `BoardProvider` Protocol declares no sub-issue method, `GitHubProjectsProvider` advertises it via `frozenset(Capability)` yet implements nothing, and jared's real epic model is the `epic` *label* (`stage.py` `is_epic`), which is backend-neutral via `add_label`/`remove_label` and works identically on KanbanFlow. KanbanFlow keeps `SUB_ISSUES` marked absent (truthful), but Phase 6 adds **no note, no capability check, no test** for it — a guard on a path nothing reads is dead code (CLAUDE.md § dead-code doctrine; the #114 precedent). The inventory records `SUB_ISSUES` as "declared, no consumer — deliberate non-finding."

5. **Degradation-note granularity is per rendered section/surface, not per command × capability.** One note per distinct degraded behavior. A capability that gates four sweep sections (`VELOCITY_TIMESTAMPS` gates `check_stale_high_backlog`, `check_in_progress_staleness`, the `check_blocked_status_hygiene` aging sub-check, and `check_session_note_freshness`) emits four notes, matching sweep's existing five separate `(skipped — no issue data)` lines; a capability that removes one coherent region (the milestones block of `/jared-audit`) emits one. Where a section runs both a gated and an ungated sub-check, only the gated sub-check degrades. The single shared helper + single phrasing is preserved (the spec's real consistency anchor); only the keying is per-section.

### Two findings from the review (folded into this plan)

- **`/jared-wrap`'s back-end PR flow is scoped *out* of Phase 6.** The inventory tagged step 5b (commit → PR → merge) under `CLOSED_STATE`, but the spec's own Non-goals exclude the repo/git-axis from capability gating — PRs, worktrees, wrap-state are backend-independent. The plan does not gate that flow.
- **`GitHubProjectsProvider` advertises the full `frozenset(Capability)`**, including capabilities it does not implement (`SUB_ISSUES`). Harmless as a forward-declaration; this is noted so the declaration is not mistaken for a live gate.

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
