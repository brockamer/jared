# CLAUDE.md

This file provides guidance to AI coding agents (Claude Code, Codex, and others) when working with code in this repository.

## What this repo is

This repo **is** a Claude Code plugin called `jared`. Jared is a skill + slash commands + Python CLI that stewards a GitHub Projects v2 board as the single source of truth. The plugin is installed via Claude Code's marketplace system (`.claude-plugin/marketplace.json`), not as a Python wheel — `pyproject.toml` exists only to configure dev tooling and pin deps for the venv (`[tool.setuptools] packages = []`).

When editing, remember the consumer is Claude Code itself (reading `SKILL.md` and slash-command markdown) plus human/agent users on the CLI side — not a Python application.

## Developer setup

```bash
uv venv .venv
source .venv/bin/activate
uv pip install -e ".[dev]"    # installs pytest, ruff, mypy
```

To test plugin changes interactively in Claude Code, install from the local clone — run from the repo root (the plugin cache at `~/.claude/plugins/cache/` is copied at install time, so edits require `/plugin update jared` + `/reload-plugins` to pick up):

```
/plugin marketplace remove jared-marketplace
/plugin marketplace add ./
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
2. **`jared` CLI second.** `skills/jared/scripts/jared` is a Python entry point (argparse) that orchestrates the multi-step GitHub operations that are error-prone to stitch together by hand. The core surface is `file`, `move`, `set`, `set-milestone`, `close`, `comment`, `blocked-by`, `get-item`, `summary`, plus internal/automation helpers (`add-to-board`, `ties`, `next-session-prompt`, `wrap-state`, `session-resolve`, `session-lock-write`, `session-lock-clear`, `worktree-add`, `propose-partition`, `audit`, `migrate`) — ~20 subcommands in all. Each subcommand owns an invariant (e.g., `file` guarantees "issue on board AND Status set" atomically; `close` verifies auto-move to Done and falls back to explicit Status=Done; `migrate` surfaces every named loss before the first write and flips the convention doc on full success).
3. **Raw `gh` CLI fallback.** Documented in `skills/jared/references/operations.md` for cases the CLI doesn't cover.

Python subprocesses can't call MCP tools, so batch scripts (`sweep.py` et al.) use `gh` directly. That's deliberate — interactive conversations choose MCP; batch jobs use `gh`.

## The `Board` helper — shared core

`skills/jared/scripts/lib/board.py` is the one module every `jared`-CLI subcommand leans on. It:

- Parses `docs/project-board.md` (in whatever project Jared is invoked against) to extract project number / ID / owner / repo, plus field IDs and single-select option IDs. The convention doc uses `### <field-name>` headers with `- Field ID: …` and `- <option>: OPTION_…` bullets.
- Wraps `gh` via `run_gh` (parses JSON stdout) / `run_gh_raw` (text) / `run_graphql` (named variables via `-F`/`-f` based on type).
- Exposes typed exceptions — `BoardConfigError`, `FieldNotFound`, `OptionNotFound`, `ItemNotFound`, `GhInvocationError` — which CLI subcommands catch and convert to non-zero exits with a human-readable stderr line.

**When adding a new subcommand, extend `Board` with the shared piece and keep the command file thin.** Don't `subprocess.run(["gh", ...])` directly from the entry point — go through `run_gh*` so tests can monkeypatch one place.

**Board-provider abstraction (Phase 1, #314).** Board operations now go through a backend-neutral `BoardProvider` contract (`lib/board_provider.py`): semantic methods (`get_item`, `list_open_items`, `file`, `set_field`, `move`, `close`, `comment`, `add_blocked_by`, `set_milestone`, …) that speak the stable integer `IssueRef` and neutral dataclasses (`BoardItem`, `Edge`, `Milestone`, `ClosedItem`) — provider-internal IDs (GitHub node-ids, KanbanFlow `_id`) never cross the boundary. `GitHubProjectsProvider` (`lib/github_provider.py`) is the sole implementation; all `gh`/GraphQL/`field_id`/`option_id` live private inside it. `Board` is now the **config-parsing facade**: it parses `docs/project-board.md`, reads the `- backend:` selector (default `github`), and exposes `board.provider`. New CLI subcommands should call `board.provider.<method>` — the CLI file is free of raw `run_gh`/`field_id`/`option_id`. (The module-level `run_gh`/`run_gh_raw`/`run_graphql` in `board.py` remain the subprocess seam the provider and batch scripts route through.) **The Phase-1 boundary is closed.** Every batch/analytic surface now reads through the provider: `sweep.py`, `stage.py`, `dependency-graph.py` and `fetch_audit_window` go via `lib/neutral_items.py`, and `fetch_open_issues_for_ties` was migrated in Phase 6. **A new batch surface reads rows from `neutral_open_rows(board)` or `neutral_issue_rows(board)` — never from `gh` directly.** `neutral_items` offers two projections because the surfaces historically consumed two shapes: `board_item_to_row` yields the board-row shape (`status`/`priority` at top level, `number`/`title`/`body` under `content`) that sweep and stage read, and `board_item_to_issue` yields the flat `gh issue list --json` shape that dependency-graph and audit read. The checks themselves were deliberately left untouched — only their source changed — which is what kept GitHub output byte-identical through the migration (pinned by `tests/golden/*.txt`).

A KanbanFlow-backed `docs/project-board.md` carries `- backend: kanbanflow`, a `Repo:`
bullet, a `Board ID:` / `Board URL:`, and a `### Status column map` block (canonical
Status → the board's actual column name); it omits the GitHub Project identifiers and
field/option-ID blocks (the provider resolves columns/options live from the API, with the
board-scoped `KANBANFLOW_API_TOKEN` selecting the board). Init-time selection landed in #317
(Phase 4 of epic #313). The token itself resolves from `KANBANFLOW_API_TOKEN` first and then
from that board's own file at `$XDG_CONFIG_HOME/jared/kanbanflow/boards/<Board ID>.env`, so one
machine can drive several boards without a wrapper; `bootstrap-project.py` stays env-only
because `/jared-init` learns the Board ID from the connection itself (see #409).


**Backend selector vs capability gate — they are not interchangeable.** A `Capability` answers *"can this backend express this concept?"* (milestones, native edges, timestamps). "Which wire call fetches the rows" is not a concept the board model has, so the data-source branches key on `board.backend != "github"` instead. **Capability gates decide what to render; the backend selector decides where rows come from.** Reviewers should read `board.backend != "github"` as "pick the data source", never as a missed capability gate. Never invent a capability to describe an implementation detail, and never tag a section with a capability that does not govern it — ledger findings F11/F27/F53/F57 record what a mis-tagged `degraded:` string costs.

**An absent capability does not mean absent data.** `NATIVE_DEPENDENCIES` is absent on KanbanFlow, but the provider emulates edges with `blocked-by:` labels and exposes them through `fetch_blocked_by_edges()`. The canonical note says *"emulated labels only"*, not *"no edges"* — so consuming them agrees with what the operator is told. `sweep`, `stage`, `dependency-graph` and `audit` all consume these edges and must stay consistent; treating the absent capability as absent data hid real blockers and let `/jared-stage` propose a blocked item for promotion (#402).
**Capability-aware degradation (Phase 6, #319).** Phase 6 *consumes* the `Capability` enum
the provider seam declares — it adds no capabilities and changes no provider. `Board.capabilities()`
is the **static, network-free** resolver: it reads the provider class's `default_capabilities()`
classmethod by backend name *without constructing the provider* (constructing the KanbanFlow
provider makes live API calls). GitHub advertises `frozenset(Capability)` (the full set); KanbanFlow
advertises `{Capability.MILESTONE_ASSIGNMENT}` — the one capability KanbanFlow supports beyond the
core board loop (swimlanes; #390) — and omits the rest. `lib/capabilities.py` is the single
consistency anchor — one note phrasing (`degraded: <feature> unavailable on <backend> — <instead>`)
and one per-surface gate (`degraded_or_none(board, capability, feature, instead) -> str | None`).
Two layers gate differently: **Python surfaces** (CLI subcommands + `sweep.py`/`dependency-graph.py`/
`stage.py`) call the gate in-process, keyed **per rendered section** (a capability gating four sweep
sections emits four notes); **prose surfaces** (slash-command stubs, `SKILL.md`, references) do *not*
call the helper — they branch on the `- backend:` bullet directly (the voice-kill-switch pattern, no
subcommand). Default posture is soft-skip-with-note; misleading-if-shown values are omitted;
**whole-scope-absent invocations exit nonzero** (`jared audit fetch --type milestones` on a
`MILESTONE_STATE`-absent backend; `--type both` is only *partial*-scope-absent, so it warns and
downgrades to issues-only with exit 0). GitHub degrades nothing — the full set means zero behavior change,
which is the regression bar. `SUB_ISSUES` is a deliberate non-finding: no consumer on either backend
(jared's epic model is the `epic` *label*), so Phase 6 builds no note, check, or test for it — a guard
on a path nothing reads would be dead code.

**A coarse capability flag can gate two unrelated questions (#390).** `MILESTONE_STATE` meant "open/close
+ due dates," but `_cmd_file`'s and `_cmd_set_milestone`'s `--milestone` gates only needed "can an item be
grouped under a milestone name" — a different, orthogonal question that KanbanFlow answers yes to via
swimlanes. Splitting off `Capability.MILESTONE_ASSIGNMENT` let those two gates flip independently of the
three genuinely date/state-based consumers (`stage.py` milestone-proximity ranking, the audit-window
milestones fetch, `migrate`'s loss description), which stay correctly gated on `MILESTONE_STATE`. The
tell: check what each consumer actually *reads* off the capability before assuming a `degraded:` refusal
and a working implementation disagree because of a bad gate rather than a bad split.

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
commands/                 Slash-command stubs (/jared, /jared-audit, /jared-file, /jared-groom,
                          /jared-init, /jared-reshape, /jared-stage, /jared-start, /jared-wrap)
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
- **Never pair a closing keyword with a literal issue number in a commit message, PR title, or PR
  body.** GitHub's parser reads those surfaces on merge to `main`, and it honours neither negation, nor
  quotation, nor backticks, nor markdown. This has now fired **three** times, every time from text that
  was *explaining or negating* the danger: a PR body reading "Does not clo&#115;e" plus the number
  (2026-06-11, #350); commit `60ccc9e` (2026-09-12, #350) whose message *quoted the keyword while
  explaining the first incident*; and a commit during #369 (2026-09-16) that described this very rule's
  suffix format and put markdown emphasis between the keyword and the number. Refer to issues as `#N`
  only; to describe a keyword, name it ("a closing keyword paired with the issue number") rather than
  writing it beside digits. Check **before `git commit`**, not before `gh pr create` — by PR time the
  payload is already in history:

  ```bash
  grep -nEi '(close[sd]?|fix(e[sd])?|resolve[sd]?)[^A-Za-z0-9]{0,4}#[0-9]'
  ```

  **Do not narrow this pattern.** An earlier version allowed only `[[:space:]]*:?[[:space:]]*` between
  the keyword and the number, so *any* intervening punctuation walked through it — `**bold**`,
  `*italic*`, `_underscore_`, a stray paren. That hole is what let the third firing reach a pushed
  commit, and a clean result from the narrow form is not evidence. The form above deliberately
  over-matches: a flagged line is a prompt to rephrase or confirm, not proof of a defect. The asymmetry
  justifies it — a false negative silently closes an issue, a false positive costs one rephrase.
  `tests/test_autoclose_guard.py` reads this exact pattern out of this file and asserts it against the
  known-armed fixtures, so narrowing it fails the suite rather than failing silently.

  Run it on all three surfaces — the commit message, and the PR title and body:

  ```bash
  git log origin/main..HEAD --format='%B' | grep -nEi '(close[sd]?|fix(e[sd])?|resolve[sd]?)[^A-Za-z0-9]{0,4}#[0-9]'
  ```

  `docs/project-board.md` § "Project workflows — recommended settings" has carried the narrative form of
  this rule since #156; it is repeated here because that file is not loaded into a session by default and
  CLAUDE.md is. The risk is structural in this repo, not incidental — an epic about *closing* issues and
  *fixing* findings uses those words as ordinary prose on every line, and writing *about* the landmine is
  itself the highest-risk activity.

## Multi-session work — `--session N` opt-in

When running two or more Claude sessions against this repo simultaneously, pass
`--session N` to `/jared-start` to opt into worktree isolation:

- `/jared-start <issue>` (solo, default) — no worktree. CWD unchanged. Writes
  a session-presence lock at `<repo>/.git/jared/session-<issue>.lock` so a later
  session can detect this one. The lock lives under the **git common dir**, not
  in the working tree: `list_active_locks` does no liveness sweep, so a lock that
  got committed would make `/jared-start` refuse in every clone forever (#376).
  Keyed by issue, not PID — the writing subprocess exits immediately (#259).
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
see issue #231 and
`docs/superpowers/specs/archived/2026-05/2026-05-23-multi-session-impl-design.md`.

## Versioning

Semantic versioning in `.claude-plugin/plugin.json` and mirrored in `pyproject.toml`. Git tag `v<x.y.z>` per release. `pyproject.toml` configures dev tooling and pins venv deps but isn't published as a package — the version field exists for parity, not distribution. Check `.claude-plugin/plugin.json` for the current version rather than relying on this paragraph (which used to hardcode it).

**Every tag push must be accompanied by a GitHub Release.** Use `gh release create v<x.y.z> --title "v<x.y.z> — <short description>" --notes "<body>"` immediately after `git push origin v<x.y.z>`. The release notes follow the v0.13.0+ format: `## What's changed` with `**Features** / **Bug fixes** / **Refactor** / **Doctrine**` sub-headings, each item ending with `(#<PR>)`; followed by `## Backward compatibility` (if relevant), `## Validation` (if relevant), and `## Upgrading` with the `/plugin update jared` + `/reload-plugins` block. A git tag alone is not enough — the GitHub Release is the public-facing artifact.

**Every release also gets a CHANGELOG entry.** `CHANGELOG.md` at the repo root is the scannable cross-tag surface — one or a few one-liners per shipped tag, newest at top, items tagged with the PR or issue number that landed them (GitHub auto-links both). The per-release GitHub Release stays the deep-dive artifact; the CHANGELOG is the at-a-glance view someone scanning history wants. Format mirrors the release-notes sub-heading convention (**Features** / **Bug fixes** / **Refactor** / **Doctrine** / **Performance** / **Patch**); see existing entries for the shape. The discipline is to land the CHANGELOG entry in the same release PR that ships the tag — not in a separate sweep — so the artifact and the summary travel together. `jared groom` surfaces a soft advisory line (`release PR #N shipped v<x.y.z> without a CHANGELOG.md entry`) when a recently-merged `release/v*` PR didn't touch `CHANGELOG.md`, so the discipline is backstopped — see `sweep.check_release_changelog_gate` (#220).
