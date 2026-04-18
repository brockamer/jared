# Design Rationale

Why this skill exists, what decisions it embodies, and how to think about modifying it.

## Problem

Claude Code sessions work on GitHub repositories. Most of those repositories have a GitHub Project board. In practice, the board drifts — work gets done without the board being updated, new scope gets captured in ad-hoc places (Slack, comments, memory), priorities go stale, dependencies are invisible. The board stops being the single source of truth and becomes decorative.

Every session that ignores the board contributes to drift. Every new feature filed without a Priority, every issue closed without a Status move, every technical-debt insight parked in "I'll file it later" — all of it compounds.

The result: by month 2 of a project, the board is unreliable, the user has lost confidence in it, and planning happens outside the system. The board exists but doesn't steer the work.

## Why a skill

Claude Code offers several primitives for changing behavior:

| Primitive | Strength | Weakness |
|---|---|---|
| CLAUDE.md instructions | Always loaded, stable | Passive — depends on Claude remembering to follow |
| Memory system | Persists across sessions | Associative, not procedural; easy to miss |
| Hooks | Deterministic, harness-enforced | Blunt — no context awareness, intrusive |
| Subagents | Powerful, isolated | Explicit invocation required |
| Slash commands | User-invoked, discoverable | Only fire when user types the command |
| **Skills** | **Auto-invoke on trigger description, loaded on demand** | **Depend on trigger match quality** |

For board stewardship, we want behavior that:
1. Fires at specific conversational moments (starting/completing work, session start, scope discovery, user asks "where are we")
2. Carries domain-specific procedures (filing is 2-step, priority field is canonical, etc.)
3. Is discoverable across projects without explicit invocation
4. Can be versioned and iterated independently of any single project

Skills are the only primitive that fits all four. CLAUDE.md is passive, memory is associative, hooks are blunt, slash commands require explicit user action.

## Why user-level, not project-level

The skill lives at `~/.claude/skills/manage-project-board/`, not at `<project>/.claude/skills/`. Reasons:

1. **Portability.** Applies to every project Claude Code touches, not just one.
2. **Single source of truth for the discipline.** If procedures improve, every project benefits.
3. **Project-specific config via local config file.** The skill reads `docs/project-board.md` (or equivalent) from the active project for field IDs, option IDs, board conventions. Discipline is global; parameters are local.

The trade-off: the skill can't assume project-specific details in-body. All references to "Priority field ID" must be parameterized. That's more work to author but makes the skill meaningful across projects.

## Key design decisions

### 1. "Pushy" description for reliable triggering

Skills undertrigger by default — Claude tends to think "I can just do this without consulting the skill." The description counters that with explicit trigger contexts: session start, starting work, completing work, scope discovery, user phrases like "where are we / what's next." If the description were passive ("Use when managing a board"), the skill would fire on 20% of the moments it should.

### 2. Advisory, not executive, on grooming

Board sweeps identify drift. The skill *reports* drift to the user with a proposal; it does *not* apply bulk changes unilaterally. The user approves before mass edits. Reasons:
- Grooming decisions (demote High to Medium, close as obsolete) are judgment calls.
- Silent grooming would surprise the user.
- Propose-then-apply mirrors how a human PM works.

### 3. Delegate project-specific details to `docs/project-board.md`

Field IDs, option IDs, label schemas — all in the project's local convention doc. The skill references that doc; it doesn't duplicate it. Reasons:
- Single source of truth.
- Project-specific details are expected to evolve (new options, renamed fields) independently of the skill.
- Keeping the skill generic makes it portable to other projects.

### 4. Phased rollout (v1 MVP → v2 milestones+deps → v3 multi-board)

Building all features at once is premature. V1 delivers the core discipline and is usable immediately. V2 and V3 are marked as future extensions in the SKILL.md body; we add them when (a) V1 is stable and (b) there's a concrete project need.

### 5. No auto-invocation of `gh` destructive commands without confirmation

The skill can file issues, move items, close issues, comment, edit — all reversible. It does NOT delete issues, force-push, reset project state, or any destructive action without explicit user approval in context. Reversibility is a feature.

### 6. Human-readable board surface enforced, machine-readable detail allowed

The board's value is that a human glances and understands. Titles ≤70 chars, one-sentence body summaries, detail in `<details>` blocks. The issue body can hold JSON, SQL, long implementation notes — but not at the top, and not as the first thing a reader sees. See `references/human-readable-board.md`.

## Not done, deliberately

- **Automated dependency graph rendering.** V2.
- **Cross-project roadmap aggregation.** V3. Projects v2 doesn't do this natively, and the user's second project doesn't exist yet.
- **Integration with external PM tools (Linear, Jira, etc.).** Out of scope. Skill targets GitHub Projects v2 specifically.
- **Automated priority adjustment (e.g., "High for 14d → auto-demote"). ** Explicitly rejected — priority is a human decision, not an algorithmic one. The sweep flags stale items; the user decides.

## How to modify this skill

- **Adding to the discipline:** edit `SKILL.md` to describe when + why. Cross-reference to a `references/*.md` file for how.
- **Changing project-specific values:** don't. Those live in `docs/project-board.md` in each project. If the schema of that file changes across projects, update the skill's parser/reader logic.
- **Adding a new `references/*.md`:** add to SKILL.md's reference list. Keep each reference focused (≤300 lines).
- **Tightening the trigger description:** run the skill-creator description optimizer (`scripts/run_loop.py` in skill-creator) with an eval set of should-trigger / should-not-trigger queries.

## Version history

- **v1.0 (2026-04-18)** — Initial release. Core discipline + operations + sweep + milestones/roadmap + dependencies + new-board guidance + human-readable board + design rationale. Authored via skill-creator.
