# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

This repo **is** a Claude Code plugin called `jared`. Jared is a skill + slash commands + Python CLI that stewards a GitHub Projects v2 board as the single source of truth. The plugin is installed via Claude Code's marketplace system (`.claude-plugin/marketplace.json`), not as a Python wheel — `pyproject.toml` exists only to configure dev tooling and pin deps for the venv (`[tool.setuptools] packages = []`).

When editing, remember the consumer is Claude Code itself (reading `SKILL.md` and slash-command markdown) plus human/agent users on the CLI side — not a Python application.

## Developer setup

```bash
uv venv .venv
source .venv/bin/activate
uv pip install -e ".[dev]"    # installs pytest, ruff, mypy
```

To test plugin changes interactively in Claude Code, install from a local `file://` URL (the plugin cache at `~/.claude/plugins/cache/` is copied at install time, so edits require `/plugin update jared` + `/reload-plugins` to pick up):

```
/plugin marketplace remove jared-marketplace
/plugin marketplace add file:///home/brockamer/Code/jared
/plugin install jared
```

## Common commands

```bash
pytest                          # full unit-test suite (fast, offline, default)
pytest -m integration           # opt-in integration tests — require tests/testbed.env
pytest tests/test_cmd_file.py   # single file
pytest tests/test_cmd_file.py::test_file_sets_status_and_priority  # single test
ruff check .                    # lint
ruff format .                   # format
mypy                            # strict type-check (config in pyproject.toml)
```

`pyproject.toml` sets `addopts = "-m 'not integration'"` — integration tests are opt-in only; they hit a real `brockamer/jared-testbed` GitHub project and need `tests/testbed.env` (see `tests/testbed-setup.md`).

The batch scripts (`sweep.py`, `bootstrap-project.py`, `archive-plan.py`, `capture-context.py`, `dependency-graph.py`) all route their `gh` calls through `lib/board.py`'s `run_gh` / `run_gh_raw` / `run_graphql` (imported as `board_run_gh*`). They pass `ruff` and `mypy --strict` cleanly alongside the rest of the tree — no lint or type-check excludes.

## Architecture — the three-tier operations model

Any board operation picks the highest-precision tool available at runtime:

1. **MCP first.** If the GitHub MCP server is loaded, prefer its typed tools for issues/projects. Conversational code should check `tool_search` before shelling out.
2. **`jared` CLI second.** `skills/jared/scripts/jared` is a Python entry point (argparse) that orchestrates the multi-step GitHub operations that are error-prone to stitch together by hand — `file`, `move`, `set`, `close`, `comment`, `blocked-by`, `get-item`, `summary`. Each subcommand owns an invariant (e.g., `file` guarantees "issue on board AND Status set" atomically; `close` verifies auto-move to Done and falls back to explicit Status=Done).
3. **Raw `gh` CLI fallback.** Documented in `skills/jared/references/operations.md` for cases the CLI doesn't cover.

Python subprocesses can't call MCP tools, so batch scripts (`sweep.py` et al.) use `gh` directly. That's deliberate — interactive conversations choose MCP; batch jobs use `gh`.

## The `Board` helper — shared core

`skills/jared/scripts/lib/board.py` is the one module every `jared`-CLI subcommand leans on. It:

- Parses `docs/project-board.md` (in whatever project Jared is invoked against) to extract project number / ID / owner / repo, plus field IDs and single-select option IDs. The convention doc uses `### <field-name>` headers with `- Field ID: …` and `- <option>: OPTION_…` bullets.
- Wraps `gh` via `run_gh` (parses JSON stdout) / `run_gh_raw` (text) / `run_graphql` (named variables via `-F`/`-f` based on type).
- Exposes typed exceptions — `BoardConfigError`, `FieldNotFound`, `OptionNotFound`, `ItemNotFound`, `GhInvocationError` — which CLI subcommands catch and convert to non-zero exits with a human-readable stderr line.

**When adding a new subcommand, extend `Board` with the shared piece and keep the command file thin.** Don't `subprocess.run(["gh", ...])` directly from the entry point — go through `run_gh*` so tests can monkeypatch one place.

**Board-provider abstraction (Phase 1, #314).** Board operations now go through a backend-neutral `BoardProvider` contract (`lib/board_provider.py`): semantic methods (`get_item`, `list_open_items`, `file`, `set_field`, `move`, `close`, `comment`, `add_blocked_by`, `set_milestone`, …) that speak the stable integer `IssueRef` and neutral dataclasses (`BoardItem`, `Edge`, `Milestone`, `ClosedItem`) — provider-internal IDs (GitHub node-ids, KanbanFlow `_id`) never cross the boundary. `GitHubProjectsProvider` (`lib/github_provider.py`) is the sole implementation; all `gh`/GraphQL/`field_id`/`option_id` live private inside it. `Board` is now the **config-parsing facade**: it parses `docs/project-board.md`, reads the `- backend:` selector (default `github`), and exposes `board.provider`. New CLI subcommands should call `board.provider.<method>` — the CLI file is free of raw `run_gh`/`field_id`/`option_id`. (The module-level `run_gh`/`run_gh_raw`/`run_graphql` in `board.py` remain the subprocess seam the provider and batch scripts route through.) Phase-1 boundary: a few batch/analytic surfaces still use `Board` methods directly — `sweep.py`/`stage.py` (`open_items`/`board_items`), `_cmd_ties`/`_cmd_propose_partition` (`fetch_open_issues_for_ties`). Those migrate when the KanbanFlow provider lands (epic #313, Phases 2–6).

## Dual import path — important gotcha

The `Board` module is imported via two different paths in the same process tree:

- `from skills.jared.scripts.lib.board import Board` — used by unit tests (pytest's `pythonpath = ["."]`).
- `from lib.board import Board` — used by the `jared` CLI itself, which does `sys.path.insert(0, <scripts/>)` at startup.

These produce **two different module objects** in `sys.modules`, each with its own `Board` class. For `subprocess.run` monkeypatching this is fine (both modules share the one global `subprocess`), but patching anything defined *on* `Board` (e.g., a classmethod) requires patching both — or refactoring so the two sides converge. See the docstring atop `tests/conftest.py` and use the helpers there (`patch_gh`, `patch_gh_by_arg`, `import_cli`) rather than rolling your own.

The CLI entry point is an extension-less script (`skills/jared/scripts/jared`), so tests load it via `SourceFileLoader` (`conftest.import_cli`) to call `main(argv)` in-process.

## The board model Jared enforces

These aren't just docs — the CLI validates them:

- **Status columns:** `Backlog / Up Next / In Progress / Blocked / Done`. **Blocked is a Status column, never a label.** Do not introduce a "blocked" label anywhere.
- **Required fields:** every issue must have Status + Priority set the moment it lands on the board. `jared file` enforces this atomically (create issue → `item-add` → set Priority → set Status → verify; any step failing halts the workflow).
- **Blocked-by is a native GitHub issue dependency**, modeled via the `addBlockedBy` / `removeBlockedBy` GraphQL mutations (see `_cmd_blocked_by` in the CLI).
- Issues not added to a project auto-sort to the bottom with null Status and effectively disappear — the whole point of the `jared file` atomicity is to make this impossible.

## Layout

```
.claude-plugin/           plugin.json + marketplace.json (self-hosted single-plugin marketplace)
commands/                 Slash-command stubs (/jared, /jared-file, /jared-groom, /jared-init,
                          /jared-reshape, /jared-stage, /jared-start, /jared-wrap)
skills/jared/
  SKILL.md                The skill contract — what Jared is, when to trigger, the discipline
  references/             Loaded on demand: operations.md, structural-review.md, board-sweep.md,
                          session-continuity.md, plan-spec-integration.md, etc.
  scripts/
    jared                 Unified CLI (argparse entry point)
    lib/board.py          Shared Board helper — parse + gh wrapper + lookups
    sweep.py, bootstrap-project.py, dependency-graph.py, capture-context.py, archive-plan.py
                          Batch scripts — go through lib/board.py wrappers; pytest + ruff + mypy clean
  assets/                 Templates: issue-body, session-note, project-board.md, plan-conventions
tests/                    pytest unit + integration suite; conftest has import helpers
docs/superpowers/         Specs and plans governing this plugin's own work (2026-04-22-jared-levelup)
docs/bake-sites.md        Projects (beyond jared/jared-testbed) where jared runs in real sessions
```

## Scripts invoked from skill/command context

Use `${CLAUDE_PLUGIN_ROOT}/skills/jared/scripts/jared <subcommand>`. **Never hardcode `~/.claude/skills/...` paths** — the plugin cache location is an implementation detail of Claude Code's install system.

## Evolving Jared's discipline

When adding a new Jared rule (kill switch, project-level toggle, body-shape convention, naming rule), default to **doctrine** — SKILL.md, slash-command stubs, or a `references/` doc. Claude reads the doc when composing or evaluating and follows the rule.

Reach for Python parsing in `lib/board.py` **only when a CLI surface gates on the value programmatically.** If no subcommand refuses, accepts, or branches based on the field, parsing it creates dead code: the field exists, the test passes, and nothing reads it. The #114 model-guidance feature shipped a parsed field with a four-case unit test in Phase 4 that Phase 6 reverted — the consumers were slash-command surfaces that read the doc directly.

Corollary: when investigation (audit, bake test, code review, sweep, reshape) produces findings, default to NOT filing follow-up issues. See `skills/jared/SKILL.md` § "Discovered scope" for the discipline.

## Branch + PR workflow

Main is protected — every substantive change lands via a PR (`gh pr create` → `gh pr merge --merge --delete-branch`). Direct `git push origin main` is reserved for post-merge hotfixes or release-tag pushes the operator explicitly requested.

- **Feature branches** are disposable and pre-authorized. Pattern: `feature/<issue>-<slug>` (or `chore/...`, `fix/...`). WIP-style commits are fine — the PR is the review surface.
- **Phase-numbered commits.** When implementing from a plan with explicit phases, prefix commits with `(Phase N.M)`: e.g., `feat(jared): wire next-session-prompt CLI (Phase 3.2)`. Preserves the phase trail when squashing isn't used.
- **Merge strategy is `--merge`, not squash or rebase.** Preserves the phase-by-phase commit trail on main — git archaeology depends on it (e.g., v0.2.0's merge commit walks back through 33 phase commits).
- **Parallel sessions must use git worktrees**, not `git checkout -b` in the shared repo — the shared `.git/HEAD` is the trap. See `skills/jared/references/parallel-sessions.md`.

## Multi-session work — `--session N` opt-in

When running two or more Claude sessions against this repo simultaneously, pass
`--session N` to `/jared-start` to opt into worktree isolation:

- `/jared-start <issue>` (solo, default) — no worktree. CWD unchanged. Writes
  a session-presence lock at `<repo>/.jared/session-<pid>.lock` so a later
  session can detect this one.
- `/jared-start <issue> --session 1` — creates `~/Code/<repo>-<issue>/`, checks
  out a fresh `feature/<issue>-<slug>` branch from `origin/main`, shifts CWD
  into the worktree. The `session=1` claim is the durable per-session identity
  (operator applies the `session-1` GitHub label separately, per the labeling
  discipline).
- `/jared-start <issue> --no-worktree` — explicit acknowledgment of the
  shared-`.git/HEAD` risk when starting alongside another active session.
  Use sparingly.

If `/jared-start` detects an active sibling session and neither flag is passed,
it refuses with guidance. Solo work is the common case; the lock + refusal layer
exists so the moment a second session enters the picture, the discipline kicks
in automatically.

`/jared-wrap` clears the lock at session end. Stale locks (from crashed sessions)
are **not** auto-swept: the recorded PID is the lock-writing CLI subprocess, which
exits immediately, so PID-liveness can't tell a crashed session from a live one
(see `lib/session_lock.py` `list_active_locks`). Instead, the next `/jared-start`
surfaces the orphan in its refusal, and the operator clears it explicitly with
`jared session-lock-clear --issue N` after confirming the session is actually dead.

For background and the recovery-sequence incident that motivated this mechanism,
see issue #231 and `docs/superpowers/specs/2026-05-23-multi-session-impl-design.md`.

## Versioning

Semantic versioning in `.claude-plugin/plugin.json` and mirrored in `pyproject.toml`. Git tag `v<x.y.z>` per release. `pyproject.toml` configures dev tooling and pins venv deps but isn't published as a package — the version field exists for parity, not distribution. Check `.claude-plugin/plugin.json` for the current version rather than relying on this paragraph (which used to hardcode it).

**Every tag push must be accompanied by a GitHub Release.** Use `gh release create v<x.y.z> --title "v<x.y.z> — <short description>" --notes "<body>"` immediately after `git push origin v<x.y.z>`. The release notes follow the v0.13.0+ format: `## What's changed` with `**Features** / **Bug fixes** / **Refactor** / **Doctrine**` sub-headings, each item ending with `(#<PR>)`; followed by `## Backward compatibility` (if relevant), `## Validation` (if relevant), and `## Upgrading` with the `/plugin update jared` + `/reload-plugins` block. A git tag alone is not enough — the GitHub Release is the public-facing artifact.

**Every release also gets a CHANGELOG entry.** `CHANGELOG.md` at the repo root is the scannable cross-tag surface — one or a few one-liners per shipped tag, newest at top, items tagged with the PR or issue number that landed them (GitHub auto-links both). The per-release GitHub Release stays the deep-dive artifact; the CHANGELOG is the at-a-glance view someone scanning history wants. Format mirrors the release-notes sub-heading convention (**Features** / **Bug fixes** / **Refactor** / **Doctrine** / **Performance** / **Patch**); see existing entries for the shape. The discipline is to land the CHANGELOG entry in the same release PR that ships the tag — not in a separate sweep — so the artifact and the summary travel together. `jared groom` surfaces a soft advisory line (`release PR #N shipped v<x.y.z> without a CHANGELOG.md entry`) when a recently-merged `release/v*` PR didn't touch `CHANGELOG.md`, so the discipline is backstopped — see `sweep.check_release_changelog_gate` (#220).
