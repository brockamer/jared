# Jared Level-Up — Design Spec

**Date:** 2026-04-22
**Author:** Daniel Brock (with Claude Opus 4.7)
**Status:** Approved for implementation planning

## Summary

Level up the `jared` skill from a functional-but-messy solo build into a premium-quality, properly-packaged Claude Code plugin. Rename the repo to match the plugin, move off hand-rolled symlinks to the supported marketplace install path, extract all clumsy multi-step GitHub operations into a unified `jared` CLI backed by a shared library module, rewrite `SKILL.md` around an MCP-first tool-selection discipline, add unit tests for pure logic plus opt-in integration tests against a real GitHub test board, and clean up naming / documentation / `.gitignore` debt.

Outcome: `/plugin install jared` works on any machine, conversational Jared stops running raw multi-step `gh` chains for common board operations, batch scripts share a consistent helper module, and regressions in risky areas (GitHub schema drift, MCP tool-name drift) are caught by an integration test suite.

## Context

### Current state

- **Repo**: `~/Code/claude-skills/` → `github.com/brockamer/claude-skills`. Contains exactly one plugin (`jared`); repo name is misaligned with contents.
- **Install**: hand-rolled symlinks (`~/.claude/skills/jared → ~/Code/claude-skills/skills/jared` and seven `~/.claude/commands/jared*.md` symlinks). Works only on the author's machine.
- **Structure** (good):
  - `.claude-plugin/plugin.json` — plugin metadata, `name: jared`.
  - `commands/` — seven slash-command stubs (`/jared`, `/jared-file`, `/jared-start`, `/jared-wrap`, `/jared-groom`, `/jared-reshape`, `/jared-init`).
  - `skills/jared/SKILL.md` — 18 KB main contract.
  - `skills/jared/references/` — 12 detail docs loaded on demand.
  - `skills/jared/scripts/` — five Python scripts (`sweep.py` 22 KB, `bootstrap-project.py` 16 KB, `dependency-graph.py` 12 KB, `capture-context.py` 8 KB, `archive-plan.py` 8 KB) plus `board-summary.sh`.
  - `skills/jared/assets/` — four templates.
- **Active consumer**: `~/Code/findajob` uses jared via its `docs/project-board.md` convention file. findajob does not contain the skill source; it is a pure consumer of the contract file format.

### Pain points motivating this work

1. **Conversational Jared runs multi-step `gh` chains inline** for routine operations (file issue = create + add-to-board + set priority + set status; move issue = lookup-item-id + set-status-field; close = close-issue + verify-auto-move). This is clumsy every single session and easy to get wrong.
2. **`references/operations.md` is thick with bash examples** that Jared has to expand from. The skill is working against itself by describing low-level operations instead of naming high-level verbs.
3. **Install path is a symlink hack** — not portable, not discoverable, not how Claude Code plugins are meant to be installed.
4. **Repo name (`claude-skills`) suggests a multi-skill container** but the `plugin.json` declares a single plugin named `jared`. Aspiration and reality disagree.
5. **Commit `30726d0`** hardcoded `~/.claude/skills/jared/scripts/...` paths in command stubs as a workaround for a working-directory resolution bug. This is a symptom of the install hack; proper plugins use `${CLAUDE_PLUGIN_ROOT}` instead.
6. **Batch scripts reimplement ID discovery, `gh` invocation, and field-option resolution** in slightly different ways each. No shared helper module.
7. **No tests.** Mutations to real GitHub state have no regression safety net.

## Goals

- Repo and plugin name aligned and canonical.
- `/plugin marketplace add brockamer/jared` → `/plugin install jared@jared` works on any machine.
- Conversational Jared runs **one** command per logical board operation; no more inline multi-step `gh` chains for routine work.
- Batch scripts share a helper library; duplication eliminated.
- MCP tools are preferred for single-call conversational ops when available; `jared` CLI handles orchestrations; raw `gh` is the escape hatch. This hierarchy is documented in `SKILL.md`.
- Pure-logic unit tests cover the helper library and CLI argument handling.
- Opt-in integration tests exercise the whole stack against a dedicated GitHub test board.
- Every path, every example, every reference uses `${CLAUDE_PLUGIN_ROOT}`-relative addressing (no hardcoded symlink paths).
- `docs/project-board.md` schema unchanged — findajob keeps working.

## Non-goals

- Submitting jared to `claude-plugins-official` (out of scope; not what the user wants today).
- Setting up GitHub Actions CI (explicitly deferred; solo tool, tests run locally).
- Adding a second skill to this plugin (jared stays single-skill; if that changes, convert to a marketplace-style repo in a later project).
- Rewriting `SKILL.md`'s discipline-level content (the philosophy — board-as-mirror, WIP discipline, pullable, session continuity — is sound; only the **tool-selection** section changes).
- Changing `docs/project-board.md` schema (explicit frozen contract — see "Invariants").

## Decisions locked in

1. **Rename repo**: `brockamer/claude-skills` → `brockamer/jared`. Local dir `~/Code/claude-skills/` → `~/Code/jared/`.
2. **Install method**: proper plugin install via self-hosted marketplace. No symlinks. Dev loop documented based on verified `file://` marketplace behavior.
3. **Refactor scope**: aggressive (C). Unified `jared` CLI + shared helper module + SKILL.md rewrite around the new CLI + batch-script migration to the helper + unit tests + integration test track.
4. **Unit tests**: pure logic only (option B from the brainstorm). Pytest. No `gh` mocking for unit tests.
5. **Integration tests**: opt-in (`pytest -m integration`) against a dedicated `brockamer/jared-testbed` repo + project with fictional seed data. Ephemeral test issues cleaned up per test.
6. **TDD for Phase 2**: write failing test → implement → pass. Native to premium-quality bar.
7. **Versioning**: semver in `plugin.json`; git tag `v<version>` per release. This refactor ships as `0.2.0`.
8. **CI**: skipped. Can add later without affecting architecture.

## Invariants

- **`docs/project-board.md` format is frozen.** findajob actively depends on its schema. No breaking changes in this refactor. Any future evolution requires a migration script and a version field added to the convention doc — a separate project.
- **Every script-invocation path uses `${CLAUDE_PLUGIN_ROOT}/scripts/...`.** No hardcoded `~/.claude/skills/...` paths anywhere (the commit-30726d0 pattern gets reverted).
- **`plugin.json` `name` stays `jared`.** Only the repo and local directory rename.
- **Existing `scripts/*.py` CLI surfaces stay compatible** during the refactor (`sweep.py --help` still works; `bootstrap-project.py --url ... --repo ...` still works). Internal implementation migrates onto the shared helper; external interface unchanged.

## Architecture

### Three tiers of operation

**Tier 1 — single-call conversational ops.** Prefer the GitHub MCP plugin's typed tools (`create_issue`, `update_issue`, `add_issue_comment`, `get_file_contents`, etc.) when loaded. Fall back to `jared <cmd>` if MCP is absent. Fall back to raw `gh` as an escape hatch.

**Tier 2 — multi-step orchestrations.** Always invoke the `jared` CLI (`${CLAUDE_PLUGIN_ROOT}/scripts/jared <subcommand>`). These subcommands encapsulate multi-call flows: create-and-add-to-board, lookup-and-set-field, close-and-verify-auto-move, dependency-edge mutations.

**Tier 3 — batch / advisory / setup.** Named batch scripts (`sweep.py`, `bootstrap-project.py`, `dependency-graph.py`, `capture-context.py`, `archive-plan.py`). These run under `${CLAUDE_PLUGIN_ROOT}/scripts/`, use the shared helper, and are invoked only by their named slash commands.

### Why this split is correct

- Conversational Claude has access to MCP tools; Python subprocesses do not.
- Multi-call orchestrations are clumsy to string together in conversation; encapsulating them in a script makes each logical operation a single call.
- Batch scripts don't benefit from MCP (they're non-conversational) and their `gh`-only implementation is honest and portable.
- This resolves the MCP-vs-Python-subprocess tension without pretending Python can reach MCP.

### Module layout (post-refactor)

```
jared/                                  (repo root, formerly claude-skills/)
├── .claude-plugin/
│   ├── plugin.json                     (unchanged; homepage/repo URLs updated)
│   └── marketplace.json                (NEW — self-hosted marketplace manifest)
├── commands/                           (7 stubs, all rewritten to use ${CLAUDE_PLUGIN_ROOT})
│   ├── jared.md                        (fast status)
│   ├── jared-file.md
│   ├── jared-start.md
│   ├── jared-wrap.md
│   ├── jared-groom.md
│   ├── jared-reshape.md
│   └── jared-init.md
├── skills/jared/
│   ├── SKILL.md                        (tool-selection section rewritten)
│   ├── references/
│   │   ├── operations.md               (drastically trimmed — raw-gh fallback only)
│   │   ├── jared-cli.md                (NEW — subcommand reference)
│   │   └── (other references unchanged)
│   ├── scripts/
│   │   ├── jared                       (NEW — unified Python CLI with subcommands)
│   │   ├── lib/
│   │   │   ├── __init__.py
│   │   │   └── board.py                (NEW — shared helper module)
│   │   ├── sweep.py                    (migrated onto lib/board.py)
│   │   ├── bootstrap-project.py        (migrated)
│   │   ├── dependency-graph.py         (migrated)
│   │   ├── capture-context.py          (migrated)
│   │   └── archive-plan.py             (migrated)
│   └── assets/                         (unchanged)
├── tests/
│   ├── conftest.py
│   ├── test_board.py                   (unit — shared helper)
│   ├── test_cli.py                     (unit — argparse dispatch)
│   ├── test_sweep.py                   (unit — sweep's pure logic)
│   ├── test_capture_context.py         (unit — body parse/modify)
│   ├── test_integration.py             (opt-in — exercises real GitHub)
│   └── testbed-setup.md                (reproducible testbed setup doc)
├── docs/superpowers/specs/
│   └── 2026-04-22-jared-levelup-design.md  (this document)
├── pyproject.toml                      (dev deps: pytest, ruff, mypy)
├── README.md                           (rewritten install + dev sections)
└── .gitignore                          (audited: __pycache__, .pytest_cache, .mypy_cache, testbed.env)
```

### `scripts/jared` subcommands

Each subcommand: `--help` with one runnable example, clear error on missing args, exit code 0 on success, 1 on user error, 2 on infra error (gh / network / auth failure).

| Subcommand | Signature | Purpose |
|---|---|---|
| `file` | `jared file --title "..." --body-file PATH --priority {High,Medium,Low} [--status STATUS] [--label L ...]` | Create issue + add to project + set fields, all atomically. Kills the "mandatory two-step footgun." |
| `move` | `jared move <issue-number> <status-name>` | Look up item-id, set Status field. |
| `set` | `jared set <issue-number> <field-name> <option-name>` | Generic single-select field setter. |
| `close` | `jared close <issue-number>` | Close issue + verify auto-move to Done (retry once if needed). |
| `comment` | `jared comment <issue-number> [--body-file -]` | Add comment from stdin or file. |
| `blocked-by` | `jared blocked-by <dependent> <blocker> [--remove]` | Native GitHub issue-dependency mutation. Handles schema-name variants (`addBlockedBy` vs `addIssueDependency`). |
| `get-item` | `jared get-item <issue-number>` | JSON dump: issue#, item-id, status, priority, all fields. |
| `summary` | `jared summary` | Read-only one-screen board summary. Replaces `board-summary.sh`. |

### `scripts/lib/board.py`

Single class `Board` that lazily parses `docs/project-board.md` and caches:

- `project_id`, `project_number`, `owner`
- Field ID and option ID maps, keyed by human name
- Repo owner/slug

Methods:

- `find_item_id(issue_number: int) -> str` — lookup via `gh project item-list`, raises `ItemNotFound` on miss.
- `run_gh(args: list[str]) -> dict` — wrapper with JSON decode, stderr capture, exit-code handling.
- `run_graphql(query: str, **vars) -> dict` — graphql wrapper used by `blocked-by` and introspection.
- `field_id(name: str) -> str`, `option_id(field: str, option: str) -> str` — raise on missing with actionable message.

Typed exceptions: `BoardConfigError`, `ItemNotFound`, `FieldNotFound`, `OptionNotFound`, `GhInvocationError`. Each message names the exact remediation.

## Phase plan

### Phase 0 — Housekeeping

1. Push the unpushed commit to `origin/main`.
2. `gh repo rename jared --repo brockamer/claude-skills`.
3. `git remote set-url origin git@github.com:brockamer/jared.git`.
4. `mv ~/Code/claude-skills ~/Code/jared`.
5. Grep all project files for `claude-skills` and `~/Code/claude-skills`; update hits.
6. Update `plugin.json` — `homepage` and `repository` fields.
7. Audit `.gitignore`: add `__pycache__/`, `*.pyc`, `.pytest_cache/`, `.mypy_cache/`, `tests/testbed.env`. Untrack any tracked `__pycache__`.
8. Initial README rewrite — placeholder, filled in Phase 1 with verified install steps.

**Risk**: low. GitHub redirects old URLs for renamed repos.

### Phase 0.5 — Test-board setup

1. Create `brockamer/jared-testbed` repo (private).
2. Create paired Project v2 with Status (Backlog/Up Next/In Progress/Done) + Priority (High/Medium/Low) + Work Stream (three fictional options).
3. Seed with 15 issues describing a fictional software project ("Sparrow Robotics — internal tooling roadmap" or equivalent). Spread across all statuses/priorities/streams. Include one blocked item and one closed item.
4. Write `tests/testbed-setup.md` — reproducible creation instructions (including the `gh` commands to recreate from scratch if needed).
5. Write `tests/testbed.env.example` with the owner + project number + repo slug. Real `testbed.env` is gitignored.

**Risk**: low. Isolated from production boards; seeds are fictional.

### Phase 1 — Marketplace packaging

1. Write `.claude-plugin/marketplace.json` per the confirmed schema: top-level `name`, `description`, `owner`, `plugins: [{ name: "jared", description, source: ".", homepage }]`.
2. `/plugin marketplace add file:///home/brockamer/Code/jared`.
3. `/plugin install jared` (or `jared@jared` depending on installed name). `/reload-plugins`.
4. Run `/jared` — confirm it loads from `~/.claude/plugins/cache/...`, not the symlink path.
5. **Verify `file://` behavior** with a 2-minute test: edit a file in `~/Code/jared/skills/jared/SKILL.md`; check whether the cache reflects the edit without action (→ symlinked source, edits are live) or needs `/plugin update jared` (→ copied source). Record result in README.
6. Only after verified working: `rm ~/.claude/skills/jared` and `rm ~/.claude/commands/jared*.md`. `/reload-plugins`. Confirm still functional.
7. Push to GitHub; test `/plugin marketplace add brockamer/jared` (or the https-URL form) from a scratch directory. Confirm install works over the network.
8. Rewrite README: install instructions (one path), dev-loop (based on verified behavior), structure overview, versioning note.

**Risk**: medium. Marketplace schema shifts between Claude Code versions are possible. Mitigation: use `$schema` field for validation; read docs before committing schema.

### Phase 2 — `scripts/jared` CLI + shared library

TDD-style. For each subcommand:

1. Write failing unit test covering the pure-logic portion (arg parsing, option lookup, error formatting).
2. Implement the subcommand, minimally.
3. Tests pass. Commit.
4. Integration test added (opt-in) that exercises the subcommand against the testbed, asserts post-state via `gh` query, cleans up.

Implementation order:

1. `scripts/lib/board.py` — foundational. Tests for `Board` construction, field/option lookup, `find_item_id` (mocked via golden-file `gh` response).
2. `scripts/jared` entry point + argparse skeleton. Tests for dispatch, `--help`, unknown-subcommand error.
3. `jared get-item` — simplest, read-only.
4. `jared summary` — also read-only; replaces `board-summary.sh`.
5. `jared set`, `jared move` — single-field mutations.
6. `jared close` — close + verify.
7. `jared comment` — comment add.
8. `jared file` — the full atomic-create flow. Most complex.
9. `jared blocked-by` — graphql mutation with schema-name fallback.

Quality bar for every file:

- Type hints; `mypy --strict` passes.
- Ruff formatted + linted (config in `pyproject.toml`).
- Every public function has a one-line docstring.
- Every error path prints an actionable message to stderr and returns exit 1 (user error) or 2 (infra error).
- No hardcoded board/repo/field IDs anywhere — everything via `Board`.

### Phase 3 — Batch-script migration

Each of `sweep.py`, `bootstrap-project.py`, `dependency-graph.py`, `capture-context.py`, `archive-plan.py`:

1. Read current file.
2. Replace inline `gh`-call patterns + ID-lookup logic with `Board` helper calls.
3. CLI surface unchanged (external compatibility invariant).
4. Run each with its documented example against the testbed; confirm output matches pre-refactor behavior.
5. Commit per script (five commits, one per migration).

Expect significant code deletion. sweep.py in particular likely drops by a third.

### Phase 4 — `SKILL.md` + references rewrite

1. **`SKILL.md` tool-selection section**: replace current text with the three-tier decision tree (MCP → `jared <cmd>` → raw gh, with criteria for each). Link to `references/jared-cli.md`.
2. **Operations discipline**: every example in `SKILL.md` that currently says "run `gh project item-edit ...`" becomes "run `jared set ...`". The conversational instructions get crisper.
3. **`references/operations.md`**: trim to a short raw-gh fallback card. Delete the long bash blocks — they live in `jared`'s `--help` output and in `references/jared-cli.md` now.
4. **`references/jared-cli.md`**: NEW. Canonical subcommand reference. Generated from `--help` + editorial cleanup.
5. **Other references**: light touch-ups where they reference operation flows. Most content unchanged.

### Phase 5 — Command stubs + cleanup

1. Rewrite all 7 `commands/jared*.md` stubs to use `${CLAUDE_PLUGIN_ROOT}/scripts/jared <subcommand>` invocations. Reverts the commit-30726d0 hardcoded paths.
2. Delete `scripts/board-summary.sh` (superseded by `jared summary`).
3. Remove any tracked `__pycache__` content; confirm `.gitignore` catches it going forward.
4. Final grep sweep for `claude-skills`, `~/.claude/skills/`, stale references.
5. Bump `plugin.json` version to `0.2.0`. Tag `v0.2.0`. Push.

## Integration test track

Integration tests are written in Phase 2 alongside the unit tests (TDD discipline covers both), but they run under a separate pytest marker so day-to-day `pytest` stays fast and offline.

- **Fixture discipline**: every test that mutates state creates issues prefixed `[TEST-{timestamp}-{suffix}]` so they're visibly disposable and cannot be confused with the fictional seed data. Cleanup (close + delete) runs in pytest `teardown` regardless of test outcome.
- **Coverage target**: one integration test per `jared` subcommand; one roundtrip test (`file → move → set → close`); one dependency-graph mutation test.
- **Auth**: uses the active `gh` session (user's PAT). No secrets in the repo.
- **Runs locally only**: `pytest -m integration`. Default `pytest` excludes these via `pytest.ini` marker config.
- **Test data reset**: `tests/testbed-reset.py` script (additive, not a regular test) that re-seeds the testbed from scratch if it gets polluted. Run manually when needed.

## Dev loop (post-refactor)

Documented in README based on verified Phase 1.5 result. Expected shape (pending verification):

- **If `file://` marketplace symlinks the source**: edits in `~/Code/jared/` are live. Run `/reload-plugins` to pick up new commands or SKILL.md changes.
- **If `file://` marketplace copies**: edits require `/plugin update jared` to re-sync. `/reload-plugins` picks up new state.

Either workflow is acceptable; both documented.

## Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Marketplace schema drift across Claude Code versions | Low-Med | Install breaks | Use `$schema` validation; re-test after Claude Code updates |
| Phase 1 install failure before symlink removal | Low | Temporary broken install | Fixed step order: verify install before `rm` symlinks |
| findajob breaks due to `docs/project-board.md` change | Low | Blocked user workflow | Hard invariant; format frozen; integration test against real findajob file (read-only) in one test case |
| GitHub dependency-mutation schema changes (`addBlockedBy` vs `addIssueDependency`) | Med | `jared blocked-by` fails | Schema introspection fallback already implemented in current dependency-graph.py; port pattern to `jared blocked-by` |
| Test board pollution over time | Med | Integration tests flaky | Ephemeral-prefix + teardown discipline; `tests/testbed-reset.py` escape hatch |
| sweep.py migration introduces subtle behavior change | Med | False positives/negatives in grooming | Pre/post comparison: run old sweep.py + new sweep.py against testbed, diff outputs |
| `${CLAUDE_PLUGIN_ROOT}` unavailable in some context | Low | Commands fail | Verified by reading ralph-loop + superpowers usage — Claude Code sets it reliably in plugin command/skill context |

## Open items / post-execution responsibilities

For the user:

- Run `/plugin update jared` after commits you want to pick up (if `file://` copies).
- Don't re-create symlinks under `~/.claude/skills/` or `~/.claude/commands/` — the plugin install is authoritative.
- Tag a new `v<x.y.z>` in this repo before publishing any new version.
- Integration tests run locally when you care; not required before every commit.

For future Jared sessions:

- Any new common board operation becomes a new `jared` subcommand, not a raw-`gh` recipe in a reference doc.
- `docs/project-board.md` schema changes require a separate migration project; this spec's frozen-contract invariant stands.

## Success criteria

- `/plugin install jared@jared` from a fresh machine succeeds and `/jared` produces a status summary.
- Conversational Jared filing an issue invokes `${CLAUDE_PLUGIN_ROOT}/scripts/jared file ...` (one command) instead of the four-step `gh` dance.
- `pytest` passes (unit tests) with mypy-strict + ruff clean.
- `pytest -m integration` passes against the seeded testbed.
- `sweep.py` against findajob produces output identical to pre-refactor run (regression safety).
- No remaining references to `~/.claude/skills/jared/` in any file.
- `plugin.json` version `0.2.0`; `v0.2.0` tag pushed.
