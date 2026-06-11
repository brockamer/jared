# Marketplace-Readiness Review → Stranger-Ready Release

**Date:** 2026-06-10
**Status:** Design approved; pending implementation plan
**Scope:** A top-to-bottom review of the entire `jared` plugin — code, docs, and live
behavior on both backends — that drives the plugin to a tagged, stranger-installable,
marketplace-shippable release.

## Why

`jared` is mature (~12k LOC Python, ~21k LOC tests, ~20k words of runtime doctrine, two
backends, 19 CLI subcommands, 9 slash commands) but has only ever had **one user**. Shipping
to the Claude Code marketplace changes the audience: a stranger must be able to install it
cold and succeed using only public docs. This effort verifies that claim through actual
usage — not just code review — and fixes whatever blocks it, ending at a released version.

## Decisions (locked during brainstorm)

| Axis | Decision |
| --- | --- |
| **Deliverable** | Review → fix → tagged, marketplace-ready release. PRs land during the effort. |
| **Audience bar** | **Full stranger-ready.** Cold-install path and every operator-specific coupling are in scope as potential blockers. |
| **Backends** | **Both, live.** GitHub Projects v2 against `brockamer/jared-testbed`; KanbanFlow against the live "Jared Test" board (`p9vK6cR`). Includes the capability-degradation matrix. |
| **Live walkthrough** | **Main-session, serial.** The real Claude Code slash-command/Skill harness drives the UX layer end-to-end, in the operator's view. |
| **Read-only review** | **Parallel fan-out** via a workflow of subagents (operator-approved override of the serial default, scoped to static/read-only dimensions only). |
| **Clean room** | Prefer an ephemeral container on `docker.lan` (pinned fresh Python); fall back to a `proxmox.lan` LXC; env-scrubbed temp clone on this VM is the always-available backstop. |
| **Marketplace target** | **Both** — make the self-hosted `marketplace.json` path flawless now AND prep whatever a future curated/official submission requires. |

## Meta-approach

**Approach A — Review-complete-then-fix, with an inline-blocker exception.** Build the
*complete* findings ledger (static fan-out + full live walkthrough) before mutating anything,
so fix sequencing is informed by the whole picture. The one exception: a defect that **blocks
the walkthrough itself** (e.g., cold install fails, a command errors before it can be
exercised) is fixed inline — you cannot walk a surface that will not run. The discipline is to
separate *"blocks the audit"* from *"blocks the ship"*: only the former jumps the queue.

(Rejected: **B — Interleaved** review-fix-per-surface causes rework and muddies the ledger;
**C — Blocker-fast-path** converges with A in practice.)

## Critical distinction: install *mechanics* vs. slash-command *UX*

SSH-reachable ≠ harness-present. `/plugin marketplace add` and `/plugin install` are **Claude
Code harness operations**, not shell commands; an SSH shell on `docker.lan` is a bash prompt,
not an authenticated Claude Code session. The review therefore splits the "cold install" claim
into two layers tested in two places:

- **Install mechanics → clean room (shell, over SSH).** Fresh `git clone`; the `jared` CLI run
  cold under a pinned fresh Python with **no `GH_TOKEN`, no `~/.secrets`, clean PATH, no
  pre-existing `.venv`**; stdlib-only confirmation; hardcoded-path and `${CLAUDE_PLUGIN_ROOT}`
  assumptions; Python-version compatibility. All shell-level; runs fine remotely.
- **Marketplace + slash-command UX → main session (the "dirty" env, accepted for this layer).**
  `/plugin marketplace add brockamer/jared` → `/plugin install jared` → `/reload-plugins`, then
  the slash-command walkthrough. Only the real harness can exercise this; the main session is
  the only place it exists.

## Pre-confirmed findings (from brainstorm orientation)

These are settled before the formal review begins and feed straight into the ledger:

- **Cleanliness gate PASSES.** `.gitignore` is thorough; `tests/testbed.env` has **zero git
  history** (secret never committed); only `testbed.env.example` is tracked. A full-history
  secret scan still runs in Phase 1b, but the obvious paths are clean.
- **CLI is pure stdlib.** `pyyaml>=6.0` is declared a runtime dependency but is **never
  imported anywhere** (the lone `seed-issues.yaml` reference is a comment). → Cold install
  needs no `pip`. Fix is a one-line dep removal (**P2 cleanliness**, not a P0 blocker).
- **Version-compat is the residual install risk.** All scripts use `#!/usr/bin/env python3`
  (resolves to whatever is on PATH); code targets 3.11. 3.11+ syntax run on a stranger's
  3.9/3.10 interpreter is the real exposure — a Phase-1d check, not a missing dependency.

## Phases

### Phase 0 — Baseline & clean room
- Record green baseline: `pytest`, `pytest -m integration` (both backends), `ruff check`,
  `ruff format --check`, `mypy --strict`. Any pre-existing red is logged before we touch code.
- Stand up the clean room: confirm SSH auth to `docker.lan` (operator seeds `known_hosts`),
  spin an ephemeral container with a pinned Python; fall back to `proxmox.lan` LXC, then
  env-scrubbed temp clone.
- **Clean-room job #1:** confirm the `jared` CLI runs cold, stdlib-only, under fresh Python
  (the PyYAML / version-compat discriminator).
- Build the **coverage inventory**: every reviewable surface enumerated — 9 slash commands,
  19 CLI subcommands, ~18 reference docs, README / getting-started / CHANGELOG, batch scripts,
  assets/templates, plugin.json + marketplace.json. This is the anti-"silent skip" checklist
  that Phases 1–2 report coverage against.

### Phase 1 — Read-only review fan-out *(parallel workflow)*
Six dimensions, each adversarially verified before a finding lands in the ledger, classified
P0 / P1 / P2:
- **(a) Correctness** — logic/bugs across `lib/` + scripts + both providers
  (`github_provider`, `kanbanflow_provider`, the `BoardProvider` contract).
- **(b) Security** — subprocess / `gh` / GraphQL argument handling and injection surface; token
  handling; the `GH_TOKEN`/PAT path; **full git-history secret scan**.
- **(c) Doc↔code drift** — every backtick path exists; every slash-command stub matches the
  CLI's real args/behavior; SKILL.md and the capability/degradation prose match
  `capabilities.py`; reference docs match the code they describe.
- **(d) Packaging / install** — plugin.json + marketplace.json schema correctness and
  discoverability; the PyYAML dep removal; **Python-version floor** — determine the true
  minimum the code requires (3.11+ syntax audit) and ensure it is *declared* in shebang/docs/
  metadata rather than silently assumed; strict `${CLAUDE_PLUGIN_ROOT}` usage (no hardcoded
  `~/.claude`); macOS/Windows path assumptions.
- **(e) Test quality** — fakes masking live contracts (known failure mode); self-confirming
  classifier tests; subcommand coverage gaps; integration-vs-unit boundary.
- **(f) Stranger-onboarding** — do README → getting-started carry a newcomer from install →
  first filed issue with **zero** operator knowledge? Flag every operator coupling (Project #4,
  findajob / trailscribe, `bake-sites.md`, `~/.secrets`, the PAT quirk).

### Phase 2 — Live walkthrough *(main-session, serial — "be the stranger")*
Following **only public docs**, in dependency order:
- **Marketplace + install UX** (main session): `/plugin marketplace add` → `/plugin install` →
  `/reload-plugins`. Every reach for undocumented operator knowledge = a logged blocker.
- **Slash commands** end-to-end against the sandbox, both backends where applicable:
  `/jared-init → /jared-file → /jared (status) → /jared-start → /jared-stage → /jared-groom →
  /jared-audit → /jared-reshape → /jared-wrap`, plus the multi-session / worktree path.
- **CLI subcommands** — exercise all 19, verifying the invariant each owns (e.g., `file`'s
  atomic on-board-AND-status; `close`'s auto-move-to-Done with fallback).
- **KanbanFlow** — init a fresh board + core ops; confirm the **capability-degradation matrix**
  renders the correct soft-skip / omit / nonzero-exit behavior per `capabilities.py`.
- **migrate** — run the GitHub↔KanbanFlow write-path between sandbox boards (the riskiest path;
  the fake is known to mask the live contract).
Every defect lands in the same ledger.

### Phase 3 — Fix to release-ready
- Triage the ledger → sequence fixes. Per fix: branch (`fix/…`, `chore/…`) → TDD where code is
  involved → **verify inside the producing change** (no deferred smoke tests) → PR → `--merge`.
- Re-walk any fixed surface that was previously exercised in Phase 2.
- **Exit gate:** *release-ready = zero P0 + zero P1.* The P2 tail is optional; whatever is not
  fixed is recorded in the writeup as known/deferred. This bounds Phase 3.

### Phase 4 — Marketplace prep *(both targets)*
- **Self-hosted:** plugin.json / marketplace.json correct, discoverable, keywords/category/
  description sharp; cold-install re-verified post-fixes.
- **Curated submission:** research the official/curated marketplace requirements (naming,
  category, review guidelines, license, README screenshots — a social image already exists) and
  produce a submission-readiness checklist + any required artifacts, so submission is a decision
  not a project.

### Phase 5 — Release
- Semver bump with plugin.json ↔ pyproject parity; CHANGELOG entry (same PR as the tag);
  `git tag` + GitHub Release in the required format; `/plugin update jared` + `/reload-plugins`
  upgrade block.
- **Final gate:** clean-room cold-install of the *tagged* release.

## Deliverables

- **One durable review report / findings ledger** — the writeup is the artifact (per the
  anti-sprawl doctrine), classified P0/P1/P2 with disposition (fixed-in-PR-#N / deferred).
- The **merged PRs** that close P0+P1.
- The **tagged, released, cold-install-verified** version.
- A **curated-submission readiness checklist**.

Findings become fixes in this effort or writeup entries — **not** a pile of filed issues. The
effort as a whole should, per jared's own discipline, be tracked as a single epic on Project #4
so the work is visible (confirm at plan-transition).

## Risks & open items

- **Clean-room auth:** first SSH to `docker.lan`/`proxmox.lan` needs operator-seeded
  `known_hosts`/keys — a Phase-0 gate, not a blocker.
- **KanbanFlow live cost:** doubles the live surface and depends on the `~/.secrets` token + the
  intermittent `read:project` 401s noted in operator memory; budget retries.
- **Unbounded P2 tail:** mitigated by the Phase-3 exit gate (P0+P1 only).
- **Curated-submission process may not exist yet** as a formal program; if so, Phase 4's curated
  half degrades to "prep the artifacts a submission would plausibly need."
