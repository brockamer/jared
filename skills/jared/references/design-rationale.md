# Design Rationale

Why Jared exists, what decisions the skill embodies, and how to think about modifying it.

## Problem

Claude Code sessions and solo-dev projects tend to let their GitHub Project boards drift. Scope gets captured in comments, tmp files, or memory; priorities go stale; plans and specs stand alone without issues backing them; session handoffs happen via ad-hoc markdown drafts nobody reads again. By month two, the board is decorative — it exists but doesn't steer the work, and planning has effectively moved somewhere else.

Every session that ignores the board contributes to drift. Every new feature filed without metadata, every issue closed without verifying the board move, every technical-debt insight parked in "I'll file it later," every handoff that lives in `tmp/next-session-prompt.md` instead of on an issue — all of it compounds.

Jared's bet: if the board is the single source of truth *and* the system treats every small update as load-bearing, drift doesn't win. Done right, the board becomes the thing people actually use to plan, because it's the only thing that's current.

## Why a skill

Claude Code offers several primitives for changing behavior:

| Primitive | Strength | Weakness |
|---|---|---|
| CLAUDE.md | Always loaded, stable | Passive — depends on Claude remembering |
| Memory | Persists across sessions | Associative, not procedural |
| Hooks | Deterministic, harness-enforced | Blunt — no context awareness |
| Subagents | Powerful, isolated | Explicit invocation required |
| Slash commands | User-invoked, discoverable | Only fire when typed |
| **Skills** | **Auto-invoke on trigger, loaded on demand** | **Trigger quality is the variable** |

For board stewardship, we want behavior that:

1. Fires at specific conversational moments (session start, starting/completing work, scope discovery, mid-refactor triggers, "where are we").
2. Carries domain-specific procedures (two-step file, Priority is canonical, plan archival mechanics).
3. Is discoverable across projects without explicit invocation.
4. Can be versioned and iterated independently of any single project.

Skills fit all four. CLAUDE.md is passive; memory is associative; hooks are blunt; slash commands require explicit user action. Skills plus slash commands together cover both auto-trigger and explicit-invoke cases.

## Why user-level, not project-level

Jared lives at `~/.claude/skills/jared/`, not in any single project's repo.

- **Portability.** Applies to every project you touch, not just one.
- **Single source of truth for the discipline.** Procedure improvements benefit every project.
- **Project-specific config via local file.** The skill reads `docs/project-board.md` from the active project for field IDs, option IDs, conventions. Discipline is global; parameters are local.

Trade-off: the skill must treat all project-specific IDs as placeholders. Every hardcoded value is a portability bug. This was the main correctness issue in v1 — `operations.md` had findajob's IDs embedded — and a top fix in Jared.

## Key decisions

### 1. Pushy description for reliable triggering

Skills undertrigger by default. Claude tends to think "I can just do this." The description counters with explicit trigger contexts: session start, before substantive work, scope discovery, mid-refactor language, test-passing, PR-prep, "where are we." Passive descriptions fire 20% as often as they should.

### 2. Advisory, not executive, on grooming

Board sweeps identify drift. The skill *reports* drift with a proposal; it does *not* apply bulk changes unilaterally. Reasons:

- Grooming decisions (demote, archive, close as obsolete) are judgment calls.
- Silent grooming surprises the user.
- Propose-then-apply mirrors how a human PM works.

### 3. The invariant: board is a mirror, not a plan

Every ambiguity resolves by asking "which choice keeps the mirror honest?" Stated up front in SKILL.md as the invariant. This is a philosophical commitment that shapes everything downstream — it's why context capture matters, why Session notes replace tmp prompts, why plans archive on ship.

### 4. Delegate project-specific details to `docs/project-board.md`

Field IDs, option IDs, label schemas, WIP limits, work stream definitions — all in the project's local convention doc. The skill references that doc; it never duplicates it. Fixing v1's worst portability bug (hardcoded findajob IDs in `operations.md`) was non-negotiable.

### 5. MCP first, `gh` as fallback, scripts use `gh`

The skill's tool-discovery phase searches for GitHub MCP tools first — if loaded, they're preferred because they're schema-aware and agent-friendly. `gh` CLI is the fallback when MCP isn't present. The bundled scripts use `gh` because Python subprocesses can't call MCP tools.

Making this explicit in SKILL.md ("Tool selection" section) ensures a future session on a machine with different tooling doesn't stumble.

### 6. Native GitHub issue dependencies over body conventions

GitHub shipped issue dependencies to GA. The skill treats them as primary — they render natively and don't depend on prose parsing. Body conventions remain as fallback for cross-repo dependencies and for projects that don't have the feature enabled.

### 7. Lean VMS, not industrial

Solo-dev context doesn't need flow dashboards, classes of service, or formal retros. The skill keeps the lean core: WIP limits, pullable check, blocked-with-owner, aging, cycle time captured passively. Heavier VMS machinery is stubbed in design notes but not built — the discipline is the point, not the instrumentation.

### 8. Plans and specs are working artifacts; issues are permanent

The three rules (every plan/spec cites an issue; issues reverse-link; plans archive on ship) put the issue at the center. This is a directly-identified failure mode in findajob, where plans in `docs/superpowers/plans/` stood alone and drifted from reality. Jared enforces the link.

### 9. Session notes replace tmp handoff prompts

Manual session-handoff prompts (`tmp/next-session-prompt.md`) are a symptom of the board not being trustworthy. Jared's `/jared-wrap` appends structured Session notes on the issues themselves. Next session reads the board, not a tmp file. Pattern dies.

### 10. Issue body has living sections

`## Current state` (overwritten as work progresses) and `## Decisions` (append-only, dated) are the mid-work context capture vehicle. They're *visible* on the issue (not in `<details>`) because they're the primary content a future session wants to read. Acceptance criteria and deep scope go in `<details>` because they're reference, not surface.

### 11. Human-readable board surface enforced

A human glancing at the board must understand state. Titles ≤70 chars verb-first; one-sentence summary as first paragraph; living sections above reference material. This was sound in v1 and stays.

### 12. Named character, but not a roleplay

Jared is a character (from *Silicon Valley*) that helps the skill land as a distinct entity with a voice. One earnest aside per response is fine; schtick is not. The character is mnemonic, the discipline is the substance.

### 13. Portable to non-software projects

House renovation, event planning, a dissertation — the board discipline is the same. Jared's software-specific behaviors (commit/PR linking, plan/spec artifacts) short-circuit when the project doesn't have code. This is the forcing function that prevents software assumptions from leaking into core procedure.

## Not done, deliberately

- **Automated priority adjustment** ("High for 14d → auto-demote"). Priority is a human decision. Sweep flags; user decides.
- **Flow metric dashboards.** Cycle time is captured passively; if you want a chart, build one — not Jared's job.
- **Classes of service.** Solo dev doesn't need expedite/standard/fixed-date ceremony. Stubbed if the project grows into needing it.
- **Retros / kaizen loops.** Stubbed. If you add team members and want process improvement conversations, that's future work.
- **Cross-project roadmap aggregation.** V3. Projects v2 doesn't support it natively, and most users have one board.
- **Integration with non-GitHub PM tools.** Out of scope. Targets GitHub Projects v2 specifically.
- **Destructive operations without confirmation.** The skill files, moves, closes, comments, edits — all reversible. It does NOT delete issues, force-push, reset project state, or any destructive action without explicit user approval.

## How to modify

- **Adding to the discipline:** edit `SKILL.md` for when/why. Cross-reference to a `references/*.md` for how.
- **Changing project-specific values:** don't modify the skill — update `docs/project-board.md` in the affected project.
- **Adding a new `references/*.md`:** add to SKILL.md's reference list. Keep each under ~300 lines.
- **Tightening the trigger description:** run the skill-creator description optimizer against a trigger eval set.
- **Updating slash commands:** each is a `.md` file under `~/.claude/commands/`. They're thin wrappers that invoke the skill with a directive.

## Version history

- **v1.0 (2026-04-18)** — `manage-project-board`, initial release. Core discipline, operations reference, sweep script, milestone and dependency guidance, human-readable board conventions, design rationale.
- **v2.0 (2026-04-19)** — **Jared.** Rewrite addressing v1's portability bugs (hardcoded IDs, user/orgs URL parsing, dead code in bootstrap). Adds: explicit mirror-of-reality invariant; Tool selection (MCP-first); native issue dependencies as primary; lean VMS core (pullable check, blocked-as-state, aging); context capture routine (`## Current state`, `## Decisions`); session continuity (`/jared-wrap`, Session notes); plan-spec integration (issue-first, archive-on-ship); one-time migration pass; slash command set; portability to non-software projects; character/voice; updated issue body template.
