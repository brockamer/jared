# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

This repo **is** a Claude Code plugin called `jared`. Jared is a skill + slash commands + Python CLI that stewards a GitHub Projects v2 board as the single source of truth. The plugin is installed via Claude Code's marketplace system (`.claude-plugin/marketplace.json`), not as a Python wheel — `pyproject.toml` exists only to configure dev tooling and pin deps for the venv (`[tool.setuptools] packages = []`).

When editing, remember the consumer is Claude Code itself (reading `SKILL.md` and slash-command markdown) plus human/agent users on the CLI side — not a Python application.

## Developer setup

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"       # installs pytest, ruff, mypy
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

Several legacy batch scripts (`sweep.py`, `bootstrap-project.py`, `archive-plan.py`, `capture-context.py`, `dependency-graph.py`) are excluded from ruff via `extend-exclude` — Phase 3 will migrate them onto the new `Board` helper. Don't reintroduce lint coverage over them piecemeal without doing the migration.

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
commands/                 Slash-command stubs (/jared, /jared-file, /jared-start, /jared-groom,
                          /jared-wrap, /jared-reshape, /jared-init)
skills/jared/
  SKILL.md                The skill contract — what Jared is, when to trigger, the discipline
  references/             Loaded on demand: operations.md, structural-review.md, board-sweep.md,
                          session-continuity.md, plan-spec-integration.md, etc.
  scripts/
    jared                 Unified CLI (argparse entry point)
    lib/board.py          Shared Board helper — parse + gh wrapper + lookups
    sweep.py, bootstrap-project.py, dependency-graph.py, capture-context.py, archive-plan.py
                          Batch scripts — legacy, pre-Board, ruff-excluded
  assets/                 Templates: issue-body, session-note, project-board.md, plan-conventions
tests/                    pytest unit + integration suite; conftest has import helpers
docs/superpowers/         Specs and plans governing this plugin's own work (2026-04-22-jared-levelup)
```

## Scripts invoked from skill/command context

Use `${CLAUDE_PLUGIN_ROOT}/skills/jared/scripts/jared <subcommand>`. **Never hardcode `~/.claude/skills/...` paths** — the plugin cache location is an implementation detail of Claude Code's install system.

## Versioning

Semantic versioning in `.claude-plugin/plugin.json` (currently `0.2.0-dev`). Git tag `v<x.y.z>` per release. `pyproject.toml` version tracks the plugin version but isn't published as a package.
