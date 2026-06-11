# Marketplace-Readiness Review — Coverage Inventory & Findings Ledger

**Epic:** #348 · **Spec:** `docs/superpowers/specs/2026-06-10-marketplace-readiness-review-design.md`
**Status:** living document — updated each phase.
**Severity:** **P0** = ship-blocker · **P1** = must-fix before release · **P2** = polish (optional, else deferred to this writeup).

This is the durable artifact the spec promises. The **coverage inventory** is the anti-silent-skip
checklist: every surface Phases 1–2 must touch, with a `covered` marker set when it is reviewed/walked.
The **findings ledger** accumulates every defect with evidence and disposition.

---

## Coverage inventory

### Slash commands (9) — *Phase 2 walkthrough (main session)*
| # | command | covered |
|---|---|---|
| 1 | `/jared` (status) | ☐ |
| 2 | `/jared-init` | ☐ |
| 3 | `/jared-file` | ☐ |
| 4 | `/jared-start` | ◑ (used live to start #349 — see F2) |
| 5 | `/jared-stage` | ☐ |
| 6 | `/jared-groom` | ☐ |
| 7 | `/jared-audit` | ☐ |
| 8 | `/jared-reshape` | ☐ |
| 9 | `/jared-wrap` | ☐ |

### CLI subcommands (19) — *Phase 2, each verifies the invariant it owns*
| # | subcommand | invariant to verify | covered |
|---|---|---|---|
| 1 | `file` | atomic: issue created **and** on board **and** Status+Priority set | ◑ (filed #348–#354) |
| 2 | `move` | Status transition to a valid column | ◑ (moved #349) |
| 3 | `set` | single-select field set by name | ☐ |
| 4 | `close` | close + verify/force auto-move to Done | ☐ |
| 5 | `comment` | comment posted to issue | ☐ |
| 6 | `blocked-by` | native GitHub dependency edge add/`--remove` | ◑ (wired 6 edges) |
| 7 | `get-item` | JSON: number + item-id + field values | ◑ |
| 8 | `summary` | one-screen board status | ◑ |
| 9 | `add-to-board` | idempotent recovery path | ☐ |
| 10 | `next-session-prompt` | board-derived handoff skeleton | ◑ |
| 11 | `ties` | board-level ties for target issue | ◑ |
| 12 | `audit` | audit working-set fetch | ☐ |
| 13 | `session-resolve` | resolve action; nonzero on REFUSE_* | ◑ (PROCEED_SOLO) |
| 14 | `session-lock-write` | write presence lock | ◑ |
| 15 | `session-lock-clear` | remove presence lock | ☐ |
| 16 | `worktree-add` | worktree + fresh branch from origin/main | ☐ |
| 17 | `wrap-state` | wrap-time state computation | ☐ |
| 18 | `propose-partition` | partition proposal across issues | ☐ |
| 19 | `migrate` | cross-backend copy; surface losses; on-success doc flip | ☐ (riskiest — both directions) |

### Library modules (15) — *Phase 1a correctness / 1b security*
`board.py` · `board_provider.py` · `github_provider.py` · `kanbanflow_provider.py` · `kanbanflow_client.py` · `kf_number_index.py` · `cache.py` · `capabilities.py` · `migrate.py` · `partition.py` · `session_lock.py` · `ties.py` · `worktree.py` · `wrap_state.py` · `__init__.py`

### Batch scripts (6) — *Phase 1a*
`sweep.py` · `bootstrap-project.py` · `dependency-graph.py` · `capture-context.py` · `archive-plan.py` · `stage.py`

### Reference docs (16) — *Phase 1c doc↔code drift*
`operations.md` · `board-sweep.md` · `structural-review.md` · `session-continuity.md` · `plan-spec-integration.md` · `parallel-sessions.md` · `dependencies.md` · `milestones-and-roadmap.md` · `migration.md` · `new-board.md` · `human-readable-board.md` · `jared-cli.md` · `context-capture.md` · `design-rationale.md` · `pii-pre-flight.md` · `voice.md`

### Assets / templates (4) — *Phase 1c*
`issue-body.md.template` · `session-note.md.template` · `project-board.md.template` · `plan-conventions.md.template`

### Top-level docs (7) — *Phase 1c / 1f onboarding*
`README.md` · `getting-started.md` · `CHANGELOG.md` · `CLAUDE.md` · `docs/bake-sites.md` · `docs/github-api-tool-selection.md` · `docs/project-board.md`

### Plugin metadata (2) — *Phase 1d packaging*
`.claude-plugin/plugin.json` · `.claude-plugin/marketplace.json`

### Tests (59 files / 21,047 LOC) — *Phase 1e quality audit*
SKILL.md (`skills/jared/SKILL.md`, 5.4k words) is reviewed under Phase 1c.

---

## Phase 0 — baseline & clean room  *(recorded 2026-06-11)*

### Offline baseline — dev venv (system Python 3.14)
| check | result |
|---|---|
| `ruff check .` | **PASS** — all checks passed |
| `ruff format --check .` | **PASS** — 82 files already formatted |
| `mypy` (`--strict` per pyproject) | **PASS** — no issues in 82 source files |
| `pytest` (unit) | **PASS** — 890 passed, 3 deselected, 17.9s |

This is the **regression floor**: any red introduced in Phase 3 is ours.

### Live integration baseline — both backends
| backend | test | result |
|---|---|---|
| GitHub Projects v2 (`jared-testbed`) | `test_integration_item_add_idempotency` | **PASS** |
| KanbanFlow (live board `p9vK6cR`) | `test_kanbanflow_live.py` (2 tests) | **PASS** (run with `KANBANFLOW_API_TOKEN`, `GH_TOKEN` unset) |

### Clean room
- **Host:** `docker.lan` — SSH key-auth OK, Docker 29.5.2. (`proxmox.lan` LXC fallback unavailable: key not authorized — **not needed**, docker.lan is sufficient.)
- **Clean-room job #1 — stdlib-only cold run** (fresh `python:<v>-slim`, **no `pip install`**, repo mounted read-only, `py_compile` + `compileall` + `jared --help`):

| 3.9 | 3.10 | 3.11 | 3.12 | 3.13 | 3.14 |
|---|---|---|---|---|---|
| COLD-OK | COLD-OK | COLD-OK | COLD-OK | COLD-OK | COLD-OK |

→ **Version floor ≤ 3.9** (no 3.10+ syntax; `match` would fail `py_compile` on 3.9). **PyYAML provably unnecessary** — the CLI imports and builds its parser with zero third-party packages. The cold-install story is structurally sound.

---

## Findings ledger

| id | sev | dim | finding | evidence | status |
|---|---|---|---|---|---|
| **F1** | P2 | 1d | `pyyaml>=6.0` is declared a runtime dependency in `pyproject.toml`/`requires.txt` but is **never imported** anywhere in shipped code or tests (only a comment references `seed-issues.yaml`). Dead metadata; remove from `[project] dependencies`. | repo-wide `import yaml` grep empty; cold-run COLD-OK with no pip install | **confirmed** → fix in Phase 3 |
| **F2** | P2 | 1c | The phase issues filed on the board use a bold **Deliverables** block, not the `## Acceptance criteria` / `## Depends on` headers that `/jared-start`'s pullable check keys on. Likely a convention-doc clarification (epic-child phase issues vs. leaf work items) rather than a code defect — but worth a deliberate ruling. | observed starting #349; body has no `## Acceptance criteria` header | **observed** → adjudicate in Phase 1c |

### Positive confirmations (closed, non-issues)
- **Cleanliness gate passes** — `.gitignore` thorough; `tests/testbed.env` has zero git history (secret never committed); only `testbed.env.example` tracked. (Full-history secret scan still owed in Phase 1b.)
- **CLI is pure stdlib** — cold-runs on Python 3.9–3.14 with no dependencies.
- **No orphan session lock** — the `.jared/session-346.lock` seen earlier was already cleared by its wrap; `session-resolve` returned `PROCEED_SOLO`.
