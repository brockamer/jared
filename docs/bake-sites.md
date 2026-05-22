# Bake sites — projects where jared runs in real sessions

Beyond `jared` itself (`brockamer/jared`) and the integration-test fixture (`brockamer/jared-testbed`), jared is in active steward-mode use against the projects below. Each entry confirms jared operates against the project in real sessions and notes any project-specific quirks future sessions should be aware of.

This file is the formal claim for #167 (v1.0 readiness — verify jared works against ≥1 board besides jared/jared-testbed).

## findajob — `brockamer/findajob`

- **Board:** <https://github.com/users/brockamer/projects/1>
- **Kind of work:** Self-hosted job-search pipeline (LinkedIn / Indeed / ATS ingestion, LLM scoring, web UI). Mixed feature / fix / docs / tracking issues; high-velocity board with multiple Claude sessions concurrently driving issues to PR.
- **Project doc location:** `docs/maintainers/project-board.md` — *not* the default `docs/project-board.md`. The jared CLI discovers it via fallback path search; new projects should prefer the default location.
- **Quirks:**
  - **High concurrency.** When multiple sessions are active, use `git worktree add` for branching so each session has an isolated working tree. The shared `~/Code/findajob` checkout will routinely be on a feature branch with untracked files from another in-flight session.
  - **`migration-required` callout.** Issue bodies regularly carry a `migration-required` callout for operator action on deploy. Respect it when filing.
- **Evidence:** #60 (this repo) measured a complete `/jared`-driven session at 4.40% GraphQL + 0.76% REST `core` saturation on 2026-05-22.

## trailscribe — `brockamer/trailscribe`

- **Board:** <https://github.com/users/brockamer/projects/3>
- **Kind of work:** Cloudflare Workers project — Garmin inReach SMS-driven assistant. Lower-velocity than findajob; smaller backlog focused on feature work and KV → Durable Object migration.
- **Project doc location:** `docs/project-board.md` (default).
- **Quirks:** None observed.

## Adding a bake site

A project qualifies when:

1. It has `docs/project-board.md` (or a documented fallback path under `docs/`) populated per `skills/jared/assets/project-board.md`.
2. jared CLI subcommands (`summary`, `move`, `comment`, `close`) succeed against it in real sessions.
3. At least one PR has been driven through the full `/jared` → `/jared-start` → work → wrap cycle against its board.

List newly-qualified projects above with the same fields. Surface any new project-specific quirks so future sessions don't hit them blind.
