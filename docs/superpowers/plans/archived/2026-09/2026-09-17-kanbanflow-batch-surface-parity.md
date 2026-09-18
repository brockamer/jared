---
**Shipped in #386, #388, #389, #402 on 2026-09-17. Final decisions captured in issue body.**
---

# KanbanFlow batch-surface parity — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every batch/analytic surface in jared — `sweep.py`, `stage.py`, `dependency-graph.py` and `jared audit fetch` — run correctly on a KanbanFlow-backed board, by routing each one's data source through `BoardProvider` instead of GitHub.

**Architecture:** Four issues (#386, #388, #389, #402) are one defect in two shapes. **Shape A:** a GitHub-only `Board` method is reachable on a non-GitHub backend, guarded by a bare `assert` that vanishes under `python -O`. **Shape B:** a script's *data source* is GitHub (`gh project item-list`, `gh issue list`) rather than `board.provider`. The fix is the completion of the #314 Phase-1 boundary that CLAUDE.md flags as outstanding. We add one typed exception, one neutral row adapter, and then migrate each surface onto it. The existing dict-shaped check functions are left untouched — only the *source* of their rows changes — which is what keeps GitHub output byte-identical.

**Tech Stack:** Python 3.11+, argparse, `pytest`, `ruff`, `mypy --strict`. No new dependencies.

**Spec:** The four issue bodies are the spec:
- #386 — `sweep.py` aborts at its entry point
- #388 — `stage.py` bare `AssertionError`, and the `-O` consequence
- #389 — `dependency-graph.py` reads `gh issue list`, not the board
- #402 — `jared audit fetch` reads `gh issue list`, not the board

Milestone context: `docs/superpowers/specs/2026-06-11-kanbanflow-parity-design.md` (KanbanFlow parity, milestone #10). That spec governs *capability* gates; it does not treat any of these four entry points.

## Issue(s)

- #386 — `sweep.py` aborts at its entry point on a KanbanFlow board
- #388 — `stage.py` raises a bare `AssertionError`, stripped under `python -O`
- #389 — `dependency-graph.py` reads `gh issue list`, not the board
- #402 — `jared audit fetch` reads `gh issue list`, not the board

All four merged in PR #419 and went out in v0.31.0.

## Global Constraints

- **GitHub behaviour must not change.** Every surface's stdout and exit code on a `github` board must be byte-identical to `main`. Task 1 pins this before any edit; every later task re-runs it.
- **`assert` is never a production guard.** Replace with a typed exception. `python -O` must not change any failure mode.
- **Degradation strings are machine-fixed.** Use `degraded_or_none(board, capability, feature, instead)` from `lib/capabilities.py`. Never hand-write a `degraded:` string.
- **Whole-scope-absent invocations exit nonzero; partial-scope-absent warns and downgrades with exit 0.** (Phase 6 posture, CLAUDE.md.)
- **Provider-internal ids never cross the boundary.** GitHub node-ids and KanbanFlow `_id`s stay inside the provider. Neutral code speaks the integer `IssueRef`.
- **Auto-close landmine.** Never pair a closing keyword with a literal issue number in a commit message, PR title, or PR body. Run the CLAUDE.md grep before **every** `git commit`:
  ```bash
  git log origin/main..HEAD --format='%B' | grep -nEi '(close[sd]?|fix(e[sd])?|resolve[sd]?)[^A-Za-z0-9]{0,4}#[0-9]'
  ```
  Four issue numbers in a PR about *fixing* and *closing* gaps makes this 4× the normal exposure. Refer to issues as `#N` only. Close them via `jared close` at wrap, never via a commit keyword.
- **Dual import path.** `lib.board` and `skills.jared.scripts.lib.board` are two module objects. A new exception class exists twice. Tests must import it by the same path the code under test raises it from — follow the existing `FieldNotFound` / `BoardConfigError` pattern in `tests/`.
- **Phase-numbered commits.** Prefix each commit `(Phase N)`. Merge strategy is `--merge`.
- **Branch:** `feature/386-kanbanflow-batch-surface-parity`.

## Established precedent to follow

`Board.fetch_open_issues_for_ties()` (`lib/board.py:687`) **already** does exactly what this plan generalises: when `NATIVE_DEPENDENCIES` is absent it skips the GitHub GraphQL path and routes through `board.provider.list_open_items()`. Read it before starting. It is the in-repo reference implementation for "capability gate → neutral provider source".

Note: CLAUDE.md currently lists `fetch_open_issues_for_ties` as an un-migrated Phase-1 holdout. That claim is stale — Phase 6 migrated it. Task 8 corrects the document.

## Verified findings that shape the design

These were confirmed by reading the code on `main` at `85e7ca8`. Do not re-derive them; do re-verify any line number before editing, because they have already moved once (see below).

1. **Line numbers in the issue bodies are stale.** PR #384 inserted a `require_python()` guard into every standalone script. `#386`'s cited `sweep.py:96` is now `105`, `:99` is `108`, `:792` is `801`. The three timestamp degradation notes cited as `858/879/1022` are at `863/884/1027`. The offset is **not uniform**. Resolve every citation by content, never by number.

2. **`sweep.py` has two GitHub data sources, not one.**
   - Source 1 — board items: `fetch_items(owner, project)` → `gh project item-list`. Carries `status`, `content`, custom fields. Includes `Done` items.
   - Source 2 — issue metadata: `fetch_open_issues_bulk(repo)` → `gh issue list`. Carries `createdAt`, `title`, `labels`, `body`.

   Only Source 2 carries `createdAt`. **This is why no `BoardItem.created_at` field is needed.** Source 2 is inherently GitHub-only (it needs a repo) and is already the thing `VELOCITY_TIMESTAMPS` gates.

3. **Sweep already has degrade branches for a missing Source 2.** `sweep.py:874` and `:895` read `elif not issues_by_number: print("  (skipped — no issue data)")`. The KanbanFlow path lands in these existing branches. We are not inventing a degrade posture; we are routing into one that exists.

4. **Sweep's warm path is already open-items-based.** `fetch_items_with_closed_cache` (`sweep.py:195`) pulls `board.open_items()` and merges it with a persistent closed-items cache. The full `gh project item-list` pull is only the **cold** path. So "open items + closed items" is already the architecture — only the *source* of each needs to become neutral.

5. **`list_open_items()` is not a drop-in for `fetch_items()`.** `fetch_items` returns **all** board items including `Done`; `list_open_items()` returns **open only**. They are used for different things. `fetch_items`'s Done subset exists only to warm the closed cache (`sweep.py:234`), and both providers implement `recently_closed()`, which is the neutral equivalent.

6. **`BoardItem` has no creation timestamp** — confirmed at `lib/board_provider.py:31`. Fields are `number, title, status, priority, body, labels, milestone, blocked_by, assignee, fields, provider_ref, url`. This is consistent with finding 2; do not add one.

7. **The three bare asserts** are at `lib/board.py:471` (`provider()`), `:538` (`board_items()`), `:647` (`open_items()`).

8. **`KanbanFlowProvider` declares zero capabilities.** `_OMITTED_CAPABILITIES` (`lib/kanbanflow_provider.py:44`) omits all seven, so `_CAPABILITIES == frozenset()`.

9. **Entry-point signatures differ, and none of the three takes a config path.**
   - `sweep.main()` — **no argv parameter**; reads `sys.argv`.
   - `dependency-graph.main()` — **no argv parameter**; reads `sys.argv`.
   - `stage.main(argv: list[str] | None = None)` — accepts argv.

   None has a `--config` flag. `sweep.find_config()` delegates to `Board.find_default_path()`, which autodiscovers relative to **cwd**. Every harness in this plan therefore uses `monkeypatch.chdir(tmp_path)` plus `monkeypatch.setattr(sys, "argv", [...])`. A `config=` keyword does not exist — do not write one.

10. **The test helpers already exist, under names this plan uses verbatim.** From `tests/conftest.py`:
    - `import_sweep()`, `import_stage()`, `import_dep()` — load each script as a module via `SourceFileLoader`.
    - `restrict_capabilities(monkeypatch, keep={...})` — forces `Board.capabilities()` to return only `keep`. **It already patches both module objects**, so it is the dual-import-safe way to exercise a degraded path *without a live KanbanFlow board*.
    - `patch_kf(monkeypatch, body=...)` — patches `kanbanflow_client._raw_http`, the transport seam, and no-ops sleep/now. This is how a real `KanbanFlowProvider` runs offline.
    - `write_minimal_board(tmp_path)` — writes a **GitHub**-shaped `docs/project-board.md`. There is **no KanbanFlow equivalent**; Task 1 adds one.

    Do not invent fixture names. `kanbanflow_board`, `github_board` and `repo_root` do not exist.

11. **The off-board-issues section already degrades.** `sweep.py:1018` reads `if not issues_by_number: print("  (skipped — no issue data)")`. On KanbanFlow `issues_by_number` is empty, so this section degrades today with no change. **Add no note here** — no listed capability describes "has a GitHub repo issue list", and mis-tagging one is exactly what ledger findings F11/F27/F53/F57 warn against.

12. **The neutral row shape is already safe for two helpers.** Verified:
    - `guess_repo_from_items` reads `content.get("repository")` off `i.get("content") or {}`. The neutral row omits `repository`, so it returns `None` → `repo` is `None` → `issues_by_number` stays empty → the existing degrade branches fire. That is the desired KanbanFlow behavior, reached with no extra code.
    - `field(item, *keys)` reads `item.get(k)` at top level and is called as `field(i, "priority")` — lowercase. `BoardItem.fields` is keyed lowercased. The two agree, so `row.setdefault(name, value)` puts custom fields exactly where `field()` looks.

## Design note — why these branches key on `backend`, not on a `Capability`

Phase 6 established that behavior differences key on `Capability`. This plan's data-source branches key on `board.backend != "github"` instead, deliberately.

A capability answers *"can this backend express this concept?"* — milestones, native edges, timestamps. "Which wire call fetches the rows" is not a concept the board model has; it is a provider implementation detail. There is no `Capability` that means "has a `gh project item-list`", and inventing one would put an implementation detail into a user-facing vocabulary that slash-command prose branches on.

So: **capability gates decide what to render; the backend selector decides where rows come from.** Both appear in this plan and they are not interchangeable. A reviewer seeing `board.backend != "github"` should read it as "pick the data source", never as a missed capability gate.

## Out of scope — discovered, deliberately not done here

**`VELOCITY_TIMESTAMPS` is declared absent but `recently_closed()` is implemented on KanbanFlow.** Verified: `KanbanFlowProvider.recently_closed()` (`lib/kanbanflow_provider.py`) reads real timestamps from `GET /board/events` and returns `ClosedItem`s with `closed_at`. Issue #402 calls this "the #390 pattern".

Do **not** flip the flag in this plan. The capability is compound — created / closed / transition times — and KanbanFlow has closed-at via the event log but no created-at on tasks. `docs/superpowers/specs/2026-06-11-kanbanflow-parity-design.md:93` already adjudicated this: *"feasible for `recently_closed`; **flag flip contingent**… None consume `recently_closed`."* Flipping it wholesale would wrongly enable five created-at-based gates.

**Proposed action:** comment the finding on #357 (the parity epic) at wrap, so the adjudication has the new evidence attached. No code change here.

## File Structure

| File | Responsibility | Change |
|---|---|---|
| `skills/jared/scripts/lib/board.py` | Config facade + `gh` seam. Gains `BackendMismatch`; loses three bare asserts. | Modify |
| `skills/jared/scripts/lib/neutral_items.py` | **New.** The one neutral row source every batch surface consumes. `BoardItem` → sweep-shaped dict. | Create |
| `skills/jared/scripts/sweep.py` | Board identity via provider; neutral row source; backend-neutral banner. | Modify |
| `skills/jared/scripts/stage.py` | Consume neutral row source; degrade rather than raise. | Modify |
| `skills/jared/scripts/dependency-graph.py` | Read edges via `provider.fetch_blocked_by_edges()`. | Modify |
| `skills/jared/scripts/lib/board.py` (`fetch_audit_window`) | Provider-sourced working set. | Modify |
| `tests/test_golden_github_surfaces.py` | **New.** Byte-identical GitHub regression pins. | Create |
| `tests/test_neutral_items.py` | **New.** Row-adapter unit tests. | Create |
| `tests/test_backend_mismatch.py` | **New.** Typed exception, incl. `-O` survival. | Create |
| `CLAUDE.md`, `CHANGELOG.md`, `docs/project-board.md` | Doctrine + boundary corrections. | Modify |

---

### Task 1: Golden GitHub regression pins

The single most important task. You cannot capture "today's behavior" after you have edited the file. Nothing else starts until this is green and committed.

**Files:**
- Test: `tests/test_golden_github_surfaces.py` (create)

**Interfaces:**
- Consumes: `tests/conftest.py` helpers `import_sweep`, `import_stage`, `import_dep`, `patch_gh_by_arg`, `write_minimal_board`.
- Produces, in `tests/conftest.py`:
  - `write_minimal_kanbanflow_board(tmp_path) -> Path`
  - `run_script_main(mod, argv, tmp_path, monkeypatch, capsys) -> tuple[int, str]`

  Tasks 2–7 consume both.

- [ ] **Step 1: Read the conftest helpers first**

Run: `sed -n '1,140p' tests/conftest.py && sed -n '440,500p' tests/conftest.py`

Understand the dual-import docstring, `restrict_capabilities`, and `patch_kf` before writing a line. Do not roll your own subprocess patch and do not invent fixture names.

- [ ] **Step 2: Add the two missing conftest helpers**

`main()` takes no argv on sweep and dependency-graph, and the convention doc is found by autodiscovery from **cwd** (finding 9). So the harness must chdir and set `sys.argv`:

```python
# tests/conftest.py

def run_script_main(
    mod: ModuleType,
    argv: list[str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> tuple[int, str]:
    """Drive a batch script's main() and return (exit_code, stdout).

    sweep.main() and dependency-graph.main() take no argv parameter — they
    read sys.argv — and locate docs/project-board.md by autodiscovery from
    cwd. So both must be staged, not passed.
    """
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", argv)
    rc = mod.main()
    return rc, capsys.readouterr().out


def write_minimal_kanbanflow_board(tmp_path: Path) -> Path:
    """Write a minimal valid KanbanFlow-backed docs/project-board.md.

    Mirrors write_minimal_board (which is GitHub-shaped). Per CLAUDE.md a
    KanbanFlow doc carries `- backend: kanbanflow`, a Repo: bullet, a Board
    ID / Board URL, and a `### Status column map`; it omits every GitHub
    Project identifier and all field/option-ID blocks.
    """
    board_md = tmp_path / "docs" / "project-board.md"
    board_md.parent.mkdir(parents=True, exist_ok=True)
    board_md.write_text(
        dedent("""\
        - Repo: brockamer/project-b
        - Board ID: BOARDID2
        - Board URL: https://kanbanflow.com/board/BOARDID2

        ## Jared config

        - backend: kanbanflow

        ### Status column map

        - Backlog: Backlog
        - Up Next: Up Next
        - In Progress: In Progress
        - Blocked: Blocked
        - Done: Done
        """)
    )
    return board_md
```

Verify the exact bullet spellings `Board.from_path` requires by reading `lib/board.py:195-225` — the kanbanflow branch names its required fields and raises `BoardConfigError` listing any that are missing. Run `Board.from_path(path)` on the fixture once and confirm it parses before moving on.

- [ ] **Step 3: Write the golden test for `sweep.py` on a GitHub board**

```python
# tests/test_golden_github_surfaces.py
"""Byte-identical GitHub-backend pins for the four batch surfaces.

These exist so the KanbanFlow provider migration (#386/#388/#389/#402) cannot
silently change GitHub output. If one of these fails, the migration regressed
GitHub — that is a defect, not a fixture to update. Update a golden only when
a GitHub-visible change is the deliberate, reviewed intent of the change.
"""

from __future__ import annotations

import pytest

from tests.conftest import patch_gh_by_arg  # noqa: F401  (fixture-style helper)

GOLDEN_GH_FIXTURE = {
    "items": [
        {"status": "Backlog", "priority": "High",
         "content": {"number": 1, "title": "alpha", "repository": "o/r"}},
        {"status": "In Progress", "priority": "Medium",
         "content": {"number": 2, "title": "beta", "repository": "o/r"}},
        {"status": "Done", "priority": "Low",
         "content": {"number": 3, "title": "gamma", "repository": "o/r"}},
    ],
    "issues": [
        {"number": 1, "title": "alpha", "createdAt": "2026-01-01T00:00:00Z",
         "labels": [], "body": ""},
        {"number": 2, "title": "beta", "createdAt": "2026-01-02T00:00:00Z",
         "labels": [], "body": ""},
    ],
}


def test_sweep_github_stdout_is_pinned(tmp_path, capsys, monkeypatch):
    """Full stdout of sweep.py on a github board, pinned byte-for-byte."""
    write_minimal_board(tmp_path)
    patch_gh_by_arg(monkeypatch, {
        ("project", "item-list"): {"items": GOLDEN_GH_FIXTURE["items"]},
        ("issue", "list"): GOLDEN_GH_FIXTURE["issues"],
    })
    rc, out = run_script_main(import_sweep(), ["sweep.py"], tmp_path, monkeypatch, capsys)

    assert rc == 0
    # Pin the banner and every section header. The banner is the line #386
    # changes; the headers prove no check was dropped.
    assert "Sweep for https://github.com/users/brockamer/projects/7" in out
    assert "== Metadata completeness ==" in out
    assert "== Stale High-priority Backlog" in out
    assert "== Off-board issues (open in repo, missing from project) ==" in out
    # Pin the whole thing so an accidental reordering or dropped line fails.
    assert out == _EXPECTED_SWEEP_GITHUB_STDOUT
```

Read `patch_gh_by_arg`'s signature at `tests/conftest.py:385` and match its actual key convention — the mapping shape above is illustrative, not copied from the source.

- [ ] **Step 4: Generate `_EXPECTED_SWEEP_GITHUB_STDOUT` from current `main`**

Do not hand-write the expected string. Write the test body first with a deliberately wrong constant, run it, and copy the real value out of the assertion diff:

```bash
cd /home/user/Code/jared && source .venv/bin/activate
pytest tests/test_golden_github_surfaces.py::test_sweep_github_stdout_is_pinned -v 2>&1 | head -60
```

The constant must be the *actual* current output on `main` at `85e7ca8`, not your reconstruction of it. A hand-written golden pins what you believe the code does, which is worth nothing as a regression guard.

- [ ] **Step 5: Repeat Steps 3–4 for the other three surfaces**

- `test_stage_github_stdout_is_pinned` — `stage.main()` **does** accept argv, so call `import_stage().main([])` directly; you still need `monkeypatch.chdir(tmp_path)` for doc autodiscovery.
- `test_dependency_graph_github_stdout_is_pinned` — no argv parameter; use `run_script_main(import_dep(), ["dependency-graph.py", "--repo", "brockamer/findajob"], ...)`.
- `test_audit_fetch_github_json_is_pinned` — call `fetch_audit_window` directly; pin the parsed JSON **structure** (keys present, item numbers, ordering), not the raw string. JSON key order is not a contract.

`tests/test_stage.py` and `tests/test_dependency_graph.py` already have working `capsys` harnesses — read them first and follow their shape rather than inventing one.

- [ ] **Step 6: Run the new tests and the whole suite**

Run: `pytest tests/test_golden_github_surfaces.py -v && pytest -q`
Expected: 4 new tests PASS. Full suite: **1003 passed, 1 skipped** (the baseline captured on `main` at `85e7ca8`). Any other number means you changed behavior in a task whose job was to change nothing.

- [ ] **Step 7: Commit**

```bash
git checkout -b feature/386-kanbanflow-batch-surface-parity
git add tests/test_golden_github_surfaces.py
git log origin/main..HEAD --format='%B' | grep -nEi '(close[sd]?|fix(e[sd])?|resolve[sd]?)[^A-Za-z0-9]{0,4}#[0-9]' || true
git commit -m "test(parity): pin GitHub stdout for the four batch surfaces (Phase 1)"
```

---

### Task 2: `BackendMismatch` — a guard that survives `python -O`

Addresses #388's core finding. Lands early so every later task's failure mode is already legible.

**Files:**
- Modify: `skills/jared/scripts/lib/board.py` (three `assert self.project_number is not None` at `:471`, `:538`, `:647` — re-verify by content)
- Test: `tests/test_backend_mismatch.py` (create)

**Interfaces:**
- Produces: `class BackendMismatch(Exception)` in `lib/board.py`, raised by `Board.provider()`, `Board.board_items()`, `Board.open_items()`. Later tasks catch it.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_backend_mismatch.py
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from skills.jared.scripts.lib.board import BackendMismatch, Board
from tests.conftest import write_minimal_kanbanflow_board


def test_board_items_raises_typed_error_on_kanbanflow(tmp_path: Path):
    board = Board.from_path(write_minimal_kanbanflow_board(tmp_path))
    with pytest.raises(BackendMismatch) as exc:
        board.board_items()
    msg = str(exc.value)
    assert "board_items" in msg          # names the method
    assert "kanbanflow" in msg           # names the configured backend
    assert "github" in msg               # names what it requires


def test_open_items_raises_typed_error_on_kanbanflow(tmp_path: Path):
    board = Board.from_path(write_minimal_kanbanflow_board(tmp_path))
    with pytest.raises(BackendMismatch, match="open_items"):
        board.open_items()
```

Note: these two need **no** `patch_kf`. The guard fires on `project_number is None`, which is decided by doc parsing alone — the provider is never constructed, so no network call happens.

- [ ] **Step 2: Write the `-O` survival test**

This is the finding that makes `assert` the wrong construct. It must be a real subprocess — `-O` is an interpreter flag, not a runtime setting.

```python
_O_PROBE = """
import sys
sys.path.insert(0, {repo!r})
from skills.jared.scripts.lib.board import BackendMismatch, Board
board = Board.from_path({doc!r})
try:
    board.board_items()
except BackendMismatch:
    print("TYPED")
except Exception as e:                      # noqa: BLE001 — probe
    print("WRONG:" + type(e).__name__)
else:
    print("NO_GUARD")
"""


def test_guard_survives_python_dash_O(tmp_path: Path):
    """Under -O an `assert` is stripped and execution falls into the GitHub
    path, producing a misleading gh error. A raise must not be strippable."""
    doc = write_minimal_kanbanflow_board(tmp_path)
    repo_root = Path(__file__).resolve().parents[1]   # the repo checkout
    probe = _O_PROBE.format(repo=str(repo_root), doc=str(doc))
    out = subprocess.run(
        [sys.executable, "-O", "-c", probe],
        capture_output=True, text=True, timeout=60,
    )
    assert out.stdout.strip() == "TYPED", out.stderr
```

- [ ] **Step 3: Run to verify both fail**

Run: `pytest tests/test_backend_mismatch.py -v`
Expected: FAIL — `ImportError: cannot import name 'BackendMismatch'`.

- [ ] **Step 4: Add the exception**

Put it beside the existing typed exceptions in `lib/board.py` (`BoardConfigError`, `FieldNotFound`, `OptionNotFound`, `ItemNotFound`, `GhInvocationError`) so the module's error vocabulary stays in one place.

```python
class BackendMismatch(Exception):
    """A GitHub-only Board method was called on a non-GitHub backend.

    Replaces three bare `assert self.project_number is not None` guards
    (#388). `assert` is stripped under `python -O`, which let execution fall
    through into the GitHub path and fail later with a `gh` error about a
    repository that does not exist — pointing the reader at their GitHub
    config rather than at the backend mismatch. A raise cannot be stripped.
    """

    def __init__(self, method: str, backend: str) -> None:
        super().__init__(
            f"{method}() is a github-only method; this board's backend is "
            f"'{backend}'. Route through board.provider instead — see "
            f"references/operations.md § 'Capabilities & degradation'."
        )
        self.method = method
        self.backend = backend
```

- [ ] **Step 5: Replace the three asserts**

Re-verify each line by content (`grep -n "assert self" skills/jared/scripts/lib/board.py`) before editing — they have moved once already.

```python
# was: assert self.project_number is not None  # github-only method
if self.project_number is None:
    raise BackendMismatch("board_items", self.backend)
```

Use the matching method name at each site: `provider`, `board_items`, `open_items`.

- [ ] **Step 6: Run the tests**

Run: `pytest tests/test_backend_mismatch.py -v && pytest -q`
Expected: new tests PASS; suite still **1003 passed, 1 skipped** plus the 4 golden + 3 new.

`mypy --strict` note: replacing `assert` with an `if ... raise` removes the narrowing `assert` gave the type checker. If mypy now complains that `self.project_number` is `int | None` further down the method, that is the guard doing its job — the `raise` in the `if` body narrows it identically. Run `mypy` and fix any genuine fallout in the same commit.

- [ ] **Step 7: Lint, type-check, commit**

```bash
ruff check . && ruff format --check . && mypy
git add skills/jared/scripts/lib/board.py tests/test_backend_mismatch.py
git log origin/main..HEAD --format='%B' | grep -nEi '(close[sd]?|fix(e[sd])?|resolve[sd]?)[^A-Za-z0-9]{0,4}#[0-9]' || true
git commit -m "fix(board): raise BackendMismatch instead of bare assert (#388) (Phase 2)"
```

---

### Task 3: The neutral row adapter — the shared code

This is the piece all four surfaces share, and the reason they are bundled.

**Files:**
- Create: `skills/jared/scripts/lib/neutral_items.py`
- Test: `tests/test_neutral_items.py` (create)

**Interfaces:**
- Consumes: `BoardItem` from `lib/board_provider.py`; `Board.provider` from `lib/board.py`.
- Produces:
  - `board_item_to_row(item: BoardItem) -> dict[str, Any]`
  - `neutral_open_rows(board: Board) -> list[dict[str, Any]]`

  Tasks 4–7 consume both.

**Why a dict and not the dataclass:** the existing check functions in `sweep.py` and `stage.py` read `i.get("status")`, `item.get("content")`, `content.get("number")`. Handing them the same dict shape from a neutral source is what keeps GitHub output byte-identical with a small diff. Converting every check to `BoardItem` would be a larger, riskier change with no user-visible benefit. YAGNI.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_neutral_items.py
from __future__ import annotations

from skills.jared.scripts.lib.board_provider import BoardItem
from skills.jared.scripts.lib.neutral_items import board_item_to_row


def test_row_shape_matches_what_sweep_checks_read():
    item = BoardItem(
        number=7, title="a title", status="Up Next", priority="High",
        labels=["bug"], milestone="M1", blocked_by=[3],
    )
    row = board_item_to_row(item)
    # Exactly the keys sweep.py / stage.py read off an item.
    assert row["status"] == "Up Next"
    assert row["priority"] == "High"
    assert row["content"]["number"] == 7
    assert row["content"]["title"] == "a title"
    assert row["labels"] == ["bug"]
    assert row["milestone"] == "M1"
    assert row["blocked_by"] == [3]


def test_none_status_and_priority_survive_as_none():
    """An item with no Status must not become the string 'None' — the
    metadata-completeness check tests for a missing value."""
    row = board_item_to_row(BoardItem(number=1, title="t", status=None, priority=None))
    assert row["status"] is None
    assert row["priority"] is None


def test_custom_fields_are_merged_at_top_level():
    """sweep's `field(i, "priority")` helper reads custom single-selects."""
    item = BoardItem(number=1, title="t", status="Backlog", priority="Low",
                     fields={"work stream": "infra"})
    row = board_item_to_row(item)
    assert row["work stream"] == "infra"
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/test_neutral_items.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named '...neutral_items'`.

- [ ] **Step 3: Write the module**

```python
"""The one backend-neutral row source every batch surface consumes.

`sweep.py`, `stage.py`, `dependency-graph.py` and `jared audit fetch` each
read board rows as dicts (`i.get("status")`, `item["content"]["number"]`).
Historically each built those dicts from a GitHub call — `gh project
item-list` or `gh issue list` — which is why all four broke on a KanbanFlow
board (#386, #388, #389, #402).

This module is the seam: the provider returns neutral `BoardItem`s on either
backend, and `board_item_to_row` maps one to the dict shape the existing
checks already read. The checks are untouched; only their source changes.

Precedent: `Board.fetch_open_issues_for_ties` already routes through
`provider.list_open_items()` under a capability gate (Phase 6). This
generalises that pattern.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .board_provider import BoardItem

if TYPE_CHECKING:
    from .board import Board


def board_item_to_row(item: BoardItem) -> dict[str, Any]:
    """Map a neutral BoardItem to the dict shape the batch checks read.

    `status` and `priority` stay `None` when absent — the
    metadata-completeness check distinguishes a missing value from a set one,
    so coercing to "" or "None" would silently pass a defective item.
    """
    row: dict[str, Any] = {
        "status": item.status,
        "priority": item.priority,
        "labels": list(item.labels),
        "milestone": item.milestone,
        "blocked_by": list(item.blocked_by),
        "content": {
            "number": item.number,
            "title": item.title,
            "body": item.body,
        },
    }
    # Custom single-selects sit at top level; sweep's `field()` helper reads
    # them there. Never let a custom field shadow a core key.
    for name, value in item.fields.items():
        row.setdefault(name, value)
    return row


def neutral_open_rows(board: Board) -> list[dict[str, Any]]:
    """Open board items as check-shaped rows, on any backend."""
    return [board_item_to_row(i) for i in board.provider.list_open_items()]
```

- [ ] **Step 4: Run the tests**

Run: `pytest tests/test_neutral_items.py -v`
Expected: PASS.

- [ ] **Step 5: Verify the row shape against the real GitHub provider**

A unit test on a hand-built `BoardItem` proves the mapper, not the pipeline. Add one test that drives `neutral_open_rows` through a patched `GitHubProjectsProvider` and asserts the rows satisfy the same assertions — otherwise you have validated the instrument only on the case you invented.

```python
def test_neutral_rows_from_github_provider_have_check_shape(tmp_path, monkeypatch):
    """Validate the instrument on the backend whose output is pinned.

    A mapper test on a hand-built BoardItem proves the mapper. This proves
    the pipeline: real GitHubProjectsProvider -> real list_open_items ->
    board_item_to_row -> the shape sweep's checks read.
    """
    board = Board.from_path(write_minimal_board(tmp_path))
    patch_gh(monkeypatch, graphql_item_response(project_number=7))
    rows = neutral_open_rows(board)
    assert rows, "fixture must yield at least one open item"
    for row in rows:
        assert "status" in row and "content" in row
        assert isinstance(row["content"]["number"], int)
```

Read `graphql_item_response`'s signature at `tests/conftest.py:197` and match its real parameters; the call above is illustrative.

- [ ] **Step 6: Lint, type-check, commit**

```bash
ruff check . && mypy
git add skills/jared/scripts/lib/neutral_items.py tests/test_neutral_items.py
git log origin/main..HEAD --format='%B' | grep -nEi '(close[sd]?|fix(e[sd])?|resolve[sd]?)[^A-Za-z0-9]{0,4}#[0-9]' || true
git commit -m "feat(lib): add backend-neutral row adapter for batch surfaces (Phase 3)"
```

---

### Task 4: `sweep.py` — the door, the banner, and the source (#386)

**Files:**
- Modify: `skills/jared/scripts/sweep.py` — `parse_config` (`:102`), the banner (`:801`), `fetch_items_with_closed_cache` (`:195`), `main`'s config block (`:769`)
- Test: `tests/test_sweep_checks.py` (extend), `tests/test_golden_github_surfaces.py` (must stay green)

**Interfaces:**
- Consumes: `neutral_open_rows`, `board_item_to_row` (Task 3); `BackendMismatch` (Task 2).
- Produces: `resolve_board_identity(board) -> tuple[str, str]` → `(banner_label, banner_url)`.

- [ ] **Step 1: Write the failing test — sweep exits 0 on a KanbanFlow board**

This is #386's headline acceptance criterion.

```python
def test_sweep_exits_zero_on_kanbanflow_board(tmp_path, capsys, monkeypatch):
    write_minimal_kanbanflow_board(tmp_path)
    patch_kf(monkeypatch, body=_KF_TASKS_JSON)   # canned board + tasks
    rc, out = run_script_main(import_sweep(), ["sweep.py"], tmp_path, monkeypatch, capsys)

    assert rc == 0
    # The banner names the actual board, not a synthesised GitHub URL.
    assert "https://github.com" not in out
    assert "kanbanflow.com/board/BOARDID2" in out
    # Sections needing GitHub issue metadata degrade rather than abort.
    assert "(skipped — no issue data)" in out
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/test_sweep_checks.py::test_sweep_exits_zero_on_kanbanflow_board -v`
Expected: FAIL with exit 1 and `no https://github.com/(users|orgs)/<name>/projects/<N> URL found`.

- [ ] **Step 3: Restructure `main()`'s config block — this is the real change**

The steps below replace `sweep.py:769-801` as one edit. Piecemeal edits do **not** compose: `owner`/`project` are bound at 774 and consumed at 816, and `explicit_args` at 812 assumes the GitHub flags exist. So the branch has to live in `main()`, and the `Board` has to be built *before* it.

Today the block reads, in order: `parse_config` → bind `owner, project` → build `capability_board` (786) → banner (801). Invert the first two so the board leads:

```python
    # --- Board identity (#386) -------------------------------------------
    # Build the Board first: it knows the backend, which decides whether a
    # GitHub owner/project pair is required at all. The old code called
    # parse_config() unconditionally and aborted on a doc with no GitHub
    # Projects URL, which is every KanbanFlow doc by construction.
    board: Board | None = None
    if cfg:
        try:
            board = Board.from_path(cfg)
        except Exception:  # noqa: BLE001 — offline doc parse; never fail the sweep
            board = None

    backend = board.backend if board else "github"

    owner: str | None = None
    project: str | None = None
    if backend == "github":
        if not args.owner or not args.project:
            if not cfg:
                print("sweep: no project-board.md found and no --owner/--project",
                      file=sys.stderr)
                return 1
            try:
                owner, project = parse_config(cfg)
            except RuntimeError as e:
                print(f"sweep: {e}", file=sys.stderr)
                return 1
        else:
            owner, project = args.owner, args.project
    elif args.owner or args.project:
        print(f"sweep: --owner/--project are github-only; this board's backend "
              f"is '{backend}'", file=sys.stderr)
        return 1
```

`capability_board` was a separate lazily-built `Board` at 786. It is now the same object — replace every later `capability_board` reference with `board`, and delete the duplicate `Board.from_path(cfg)` call. Keep the broad `except` and the `board = None` fallback: a doc that fails to parse must still not crash the sweep (today's behavior).

- [ ] **Step 4: Make the banner backend-neutral**

The GitHub branch must render the **exact** two lines it renders today, or Task 1's golden fails.

```python
def resolve_board_identity(board: Board | None, owner: str | None,
                           project: str | None) -> str:
    """The URL naming the actual board, on either backend (#386).

    The old banner synthesised `https://github.com/users/{owner}/projects/{n}`
    from the regex match, so a KanbanFlow board either aborted at the door or
    would have been mislabelled as a GitHub project.
    """
    if board is not None and board.backend == "kanbanflow":
        if board.board_id:
            return f"https://kanbanflow.com/board/{board.board_id}"
        return "KanbanFlow board (no Board ID in docs/project-board.md)"
    return f"https://github.com/users/{owner}/projects/{project}"
```

**`Board` has no `board_url` attribute** — verified against the dataclass (`lib/board.py:95-110`), whose KanbanFlow fields are `backend`, `status_column_map` and `board_id` only. The URL is synthesised from `board_id`, and `board_id` is parsed with `find_optional`, so it can legitimately be `None` — hence the fallback branch. Do not write `board.board_url`.

```python
    print(f"Sweep for {resolve_board_identity(board, owner, project)}")
    if backend == "github":
        print("  (also tries /orgs/ URL if that's the project's form)")
```

The second line stays GitHub-only — it is meaningless on KanbanFlow, and the golden pins its presence on GitHub.

- [ ] **Step 5: Route the item source through the provider**

At the `fetch_items_with_closed_cache` call site (`sweep.py:812-818`), select the source before the GitHub-only cache logic is reached:

```python
    try:
        if backend != "github":
            # No `gh project item-list` on this backend — the provider is the
            # source. The closed-items cache is a GitHub-only optimisation
            # keyed on project_number; the neutral path skips it. Done items
            # are not needed: every check filters them out, and the only Done
            # consumer is the cache warm-up itself (finding 5).
            items = neutral_open_rows(board)
        elif not explicit_args and cfg and board is not None:
            items = fetch_items_with_closed_cache(board, owner, project)
        else:
            items = fetch_items(owner, project)
    except (RuntimeError, GhInvocationError, BackendMismatch) as e:
        print(f"sweep: {e}", file=sys.stderr)
        return 1
```

Add `BackendMismatch` to the caught set — Task 2 made it reachable, and an uncaught one would give the operator a traceback instead of sweep's one-line message.

`board` is `Board | None`, so narrow it before `neutral_open_rows(board)`; if `board is None` on a non-GitHub backend the doc did not parse, which is already the `return 1` path above.

- [ ] **Step 6: Do NOT add a note to the off-board section**

`sweep.py:1018` already reads `if not issues_by_number: print("  (skipped — no issue data)")`. On KanbanFlow `guess_repo_from_items` returns `None` (finding 12), so `issues_by_number` is empty and this section degrades today with no change.

Add nothing here. No listed `Capability` describes "has a GitHub repo issue list", and mis-tagging one against `VELOCITY_TIMESTAMPS` is precisely the error ledger findings F11/F27/F53/F57 record. Verify by assertion instead:

```python
    assert "== Off-board issues (open in repo, missing from project) ==" in out
    assert "(skipped — no issue data)" in out
    assert "degraded: off-board" not in out   # no invented capability tag
```

- [ ] **Step 7: Run everything**

Run: `pytest tests/test_sweep_checks.py tests/test_golden_github_surfaces.py -v && pytest -q`
Expected: the new KanbanFlow test PASSES **and** the GitHub golden is unchanged. If the golden fails, you regressed GitHub — fix the code, do not update the golden.

- [ ] **Step 8: Verify the real acceptance criterion end-to-end**

Criterion 6 of #386 is "`/jared-init` step 6 completes on a KanbanFlow board." A unit test does not prove that. Run the script directly against a KanbanFlow convention doc:

```bash
cd /home/user/Code/jared && source .venv/bin/activate
./skills/jared/scripts/sweep.py --config <path-to-a-kanbanflow-project-board.md>; echo "exit: $?"
```

Expected: exit 0, a `kanbanflow.com` banner, degradation notes where capabilities are absent. Record the actual output in the commit body.

- [ ] **Step 9: Lint, type-check, commit**

```bash
ruff check . && mypy
git add skills/jared/scripts/sweep.py tests/
git log origin/main..HEAD --format='%B' | grep -nEi '(close[sd]?|fix(e[sd])?|resolve[sd]?)[^A-Za-z0-9]{0,4}#[0-9]' || true
git commit -m "feat(sweep): resolve board identity via provider, drop the github URL door (#386) (Phase 4)"
```

---

### Task 5: `stage.py` — consume the neutral source (#388)

Task 2 already replaced `stage.py`'s bare `AssertionError` with `BackendMismatch`. This task decides whether stage *degrades* or *refuses*, and wires the neutral source.

**Files:**
- Modify: `skills/jared/scripts/stage.py` — `fetch_items_for_stage` (`:484`)
- Test: `tests/test_stage.py` (extend)

**Interfaces:**
- Consumes: `neutral_open_rows` (Task 3), `BackendMismatch` (Task 2).

**Posture decision:** `/jared-stage` proposes Backlog → Up Next promotions. Its core ranking needs Status and Priority, which the provider supplies on both backends. Only its **Backlog-age tiebreaker** needs `createdAt`, which KanbanFlow lacks. So the posture is **soft-skip-with-note**: stage runs, ranks without the age tiebreaker, and emits one note. It does not refuse — the scope is present, only one input is absent.

- [ ] **Step 1: Write the failing test**

```python
def test_stage_runs_on_kanbanflow_without_age_tiebreaker(tmp_path, capsys, monkeypatch):
    write_minimal_kanbanflow_board(tmp_path)
    patch_kf(monkeypatch, body=_KF_TASKS_JSON)
    monkeypatch.chdir(tmp_path)
    rc = import_stage().main([])          # stage.main DOES take argv
    out = capsys.readouterr().out

    assert rc == 0
    assert "degraded:" in out
    assert "AssertionError" not in out
    assert "Traceback" not in out
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/test_stage.py::test_stage_runs_on_kanbanflow_without_age_tiebreaker -v`
Expected: FAIL — `BackendMismatch` propagates out of `board.board_items()` (Task 2 made it typed, but stage still does not handle it).

- [ ] **Step 3: Route the source and gate the tiebreaker**

```python
def fetch_items_for_stage(board: Board, *, skip_native_edges: bool) -> list[dict[str, Any]]:
    if board.backend != "github":
        return neutral_open_rows(board)
    raw_items: list[dict[str, Any]] = board.board_items()
    ...
```

Gate the age tiebreaker through `degraded_or_none(board, Capability.VELOCITY_TIMESTAMPS, "Backlog age tiebreaker", "no creation timestamps on this backend")` and emit the note once, in the section that renders the ranking.

- [ ] **Step 4: Run the tests**

Run: `pytest tests/test_stage.py tests/test_golden_github_surfaces.py -v && pytest -q`
Expected: PASS, GitHub golden unchanged.

- [ ] **Step 5: Lint, type-check, commit**

```bash
ruff check . && mypy
git add skills/jared/scripts/stage.py tests/test_stage.py
git log origin/main..HEAD --format='%B' | grep -nEi '(close[sd]?|fix(e[sd])?|resolve[sd]?)[^A-Za-z0-9]{0,4}#[0-9]' || true
git commit -m "feat(stage): source items from the provider, degrade the age tiebreaker (#388) (Phase 5)"
```

---

### Task 6: `dependency-graph.py` — read edges from the board (#389)

**Files:**
- Modify: `skills/jared/scripts/dependency-graph.py` — the `--repo` requirement and the `gh issue list` call
- Test: `tests/test_dependency_graph.py` (extend)

**Interfaces:**
- Consumes: `neutral_open_rows` (Task 3); `board.provider.fetch_blocked_by_edges()`.

**Why this one is genuinely different:** #386 and #388 fail because a GitHub-only *method* is reachable. This one fails because the script's *data source* is GitHub. `--repo` is a required argument and the script never reads the board at all. The KanbanFlow provider already models dependencies — `_parse_blocked_by()` reads a `_BLOCKED_BY_PREFIX` label and populates `BoardItem.blocked_by` — so the graph data exists; only the reader points at the wrong place.

- [ ] **Step 1: Write the failing test**

```python
def test_dependency_graph_reads_edges_from_provider_on_kanbanflow(
    tmp_path, capsys, monkeypatch
):
    write_minimal_kanbanflow_board(tmp_path)
    patch_kf(monkeypatch, body=_KF_TASKS_WITH_BLOCKED_BY_JSON)
    rc, out = run_script_main(
        import_dep(), ["dependency-graph.py"], tmp_path, monkeypatch, capsys
    )                                     # note: no --repo
    assert rc == 0
    assert "Could not resolve to a Repository" not in out
    assert "#3 blocked by #1" in out      # from the fixture's blocked_by


def test_dependency_graph_does_not_call_gh_issue_list_on_kanbanflow(
    tmp_path, capsys, monkeypatch
):
    """Pin the data source, not just the output — an empty graph would pass
    an output-only assertion for entirely the wrong reason."""
    import skills.jared.scripts.lib.board as skill_board

    calls: list[list[str]] = []
    monkeypatch.setattr(
        skill_board, "run_gh", lambda args, **kw: (calls.append(args), [])[1]
    )
    write_minimal_kanbanflow_board(tmp_path)
    patch_kf(monkeypatch, body=_KF_TASKS_WITH_BLOCKED_BY_JSON)
    run_script_main(import_dep(), ["dependency-graph.py"], tmp_path, monkeypatch, capsys)

    assert not any(c[:2] == ["issue", "list"] for c in calls)
```

**Dual-import warning for the second test.** `dependency-graph.py` inserts `scripts/` on `sys.path` and imports `lib.board` — a *different* module object from `skills.jared.scripts.lib.board`. Patching `run_gh` on only one leaves the other live. Follow `restrict_capabilities` (`tests/conftest.py:130`), which patches both and documents exactly this trap; if the single patch above does not record the calls, that is why.

- [ ] **Step 2: Run to verify both fail**

Run: `pytest tests/test_dependency_graph.py -k kanbanflow -v`
Expected: FAIL — `--repo` is required, then a `gh` GraphQL "Could not resolve to a Repository" error.

- [ ] **Step 3: Make `--repo` optional and add the provider path**

```python
parser.add_argument("--repo", help="owner/repo (github backend only; "
                                   "inferred from the board doc when omitted)")
```

```python
if board.backend != "github":
    rows = neutral_open_rows(board)
    edges = board.provider.fetch_blocked_by_edges()
else:
    ...existing gh path, unchanged...
```

Emit `degraded_or_none(board, Capability.NATIVE_DEPENDENCIES, "dependency edges", "edges emulated via blocked-by labels")` so the reader knows the edges are label-emulated rather than native.

- [ ] **Step 4: Run the tests**

Run: `pytest tests/test_dependency_graph.py tests/test_golden_github_surfaces.py -v && pytest -q`
Expected: PASS, GitHub golden unchanged.

- [ ] **Step 5: Lint, type-check, commit**

```bash
ruff check . && mypy
git add skills/jared/scripts/dependency-graph.py tests/test_dependency_graph.py
git log origin/main..HEAD --format='%B' | grep -nEi '(close[sd]?|fix(e[sd])?|resolve[sd]?)[^A-Za-z0-9]{0,4}#[0-9]' || true
git commit -m "feat(depgraph): read edges from board.provider, make --repo optional (#389) (Phase 6)"
```

---

### Task 7: `jared audit fetch` — provider-sourced working set (#402)

**Files:**
- Modify: `skills/jared/scripts/lib/board.py` — `fetch_audit_window` (`:1967`)
- Test: `tests/test_cmd_audit.py` (extend)

**Interfaces:**
- Consumes: `board.provider.list_open_items()`, `board.provider.fetch_blocked_by_edges()`.

- [ ] **Step 1: Write the failing tests — straight from #402's acceptance criteria**

```python
def _kf_board(tmp_path, monkeypatch) -> Board:
    """A KanbanFlow-backed Board whose provider runs offline via patch_kf."""
    patch_kf(monkeypatch, body=_KF_TASKS_JSON)
    return Board.from_path(write_minimal_kanbanflow_board(tmp_path))


def test_audit_fetch_returns_items_on_kanbanflow(tmp_path, monkeypatch):
    board = _kf_board(tmp_path, monkeypatch)
    result = fetch_audit_window(board, count=5, entity_type="issues")
    assert result["items"], "#402: KanbanFlow returned an empty working set"
    assert len(result["items"]) <= 5
    first = result["items"][0]
    assert {"number", "body", "labels", "milestone", "open_dependents"} <= set(first)


def test_audit_fetch_does_not_call_gh_for_issues_on_kanbanflow(tmp_path, monkeypatch):
    """#402's own acceptance criterion: pin the data source, not the output."""
    import skills.jared.scripts.lib.board as skill_board

    calls: list[list[str]] = []
    board = _kf_board(tmp_path, monkeypatch)
    monkeypatch.setattr(
        skill_board, "run_gh", lambda args, **kw: (calls.append(args), [])[1]
    )
    fetch_audit_window(board, count=5, entity_type="issues")

    assert not any(c[:2] == ["issue", "list"] for c in calls)


def test_audit_fetch_degrades_unsorted_without_velocity_timestamps(
    tmp_path, capsys, monkeypatch
):
    """Falls back to all open items (ordered by number), not to an empty list."""
    board = _kf_board(tmp_path, monkeypatch)
    result = fetch_audit_window(board, count=None, entity_type="issues")
    assert result["items"]
    numbers = [i["number"] for i in result["items"]]
    assert numbers == sorted(numbers), "fallback ordering must be deterministic"
    assert "degraded:" in capsys.readouterr().err
```

`fetch_audit_window` lives in `lib/board.py`, so these tests reach it through the `skills.jared.scripts.lib.board` import path and the dual-import trap does not bite — but the `run_gh` patch in the second test must target that same module object, which is why it is patched by reference rather than by dotted string.

- [ ] **Step 2: Run to verify they fail**

Run: `pytest tests/test_cmd_audit.py -k kanbanflow -v`
Expected: FAIL — `items` is `[]` (the `gh issue list` against a repo with no issues).

- [ ] **Step 3: Branch the data source inside `fetch_audit_window`**

The existing `VELOCITY_TIMESTAMPS` gate in this function only decides the *sort*; it does not change the *source*. Add the source branch:

```python
if board.backend != "github":
    items = [board_item_to_row(i) for i in board.provider.list_open_items()]
    edges = board.provider.fetch_blocked_by_edges()
    dependents: dict[int, list[int]] = {}
    for e in edges:
        dependents.setdefault(e.blocker, []).append(e.dependent)
    for row in items:
        row["open_dependents"] = dependents.get(row["content"]["number"], [])
else:
    ...existing run_gh(["issue", "list", ...]) path, unchanged...
```

Sort by `number` ascending when `VELOCITY_TIMESTAMPS` is absent (the documented fallback: "all open items, unsorted" → deterministic by number, so `--count N` is reproducible).

- [ ] **Step 4: Run the tests**

Run: `pytest tests/test_cmd_audit.py tests/test_golden_github_surfaces.py -v && pytest -q`
Expected: PASS, GitHub golden unchanged.

- [ ] **Step 5: Lint, type-check, commit**

```bash
ruff check . && mypy
git add skills/jared/scripts/lib/board.py tests/test_cmd_audit.py
git log origin/main..HEAD --format='%B' | grep -nEi '(close[sd]?|fix(e[sd])?|resolve[sd]?)[^A-Za-z0-9]{0,4}#[0-9]' || true
git commit -m "feat(audit): source the audit window from board.provider (#402) (Phase 7)"
```

---

### Task 8: Doctrine, boundary correction, and the changelog

**Files:**
- Modify: `CLAUDE.md` (the Phase-1 boundary paragraph), `CHANGELOG.md`, `skills/jared/references/operations.md`

- [ ] **Step 1: Correct the stale Phase-1 boundary claim in CLAUDE.md**

The current text reads:

> Phase-1 boundary: a few batch/analytic surfaces still use `Board` methods directly — `sweep.py`/`stage.py` (`open_items`/`board_items`), `_cmd_ties`/`_cmd_propose_partition` (`fetch_open_issues_for_ties`). Those migrate when the KanbanFlow provider lands (epic #313, Phases 2–6).

Two corrections: `fetch_open_issues_for_ties` was already migrated in Phase 6 (verified — it routes through `provider.list_open_items()` under a `NATIVE_DEPENDENCIES` gate), and `sweep.py`/`stage.py` migrate in *this* work. Replace with a statement of what is now true, naming `lib/neutral_items.py` as the seam.

- [ ] **Step 2: Correct the stale module comment in `sweep.py`**

The comment block above `fetch_items` (`sweep.py:120-127`) reads:

> sweep.py doesn't need a full Board instance — it only extracts owner + project-number from the convention doc (see parse_config) and reads field values from gh JSON, not field IDs from the convention doc.

Task 4 makes that false: `main()` now builds a `Board` first and uses it for backend selection, identity and capabilities. Rewrite the comment to say what is now true. A comment that contradicts the code beneath it is worse than no comment.

- [ ] **Step 3: Document the neutral row seam in `references/operations.md`**

One short subsection under the capability model: what `neutral_items` is for, and the rule — **a new batch surface reads rows from `neutral_open_rows(board)`, never from `gh` directly.** This is the doctrine that stops a fifth sibling from being written.

- [ ] **Step 4: Add the CHANGELOG entry**

Per CLAUDE.md the entry lands in the same PR, not a later sweep.

```markdown
**Bug fixes**
- `sweep.py` no longer aborts at its entry point on a KanbanFlow board; board identity resolves through the provider and the banner names the actual board (#386)
- `Board.provider()`/`board_items()`/`open_items()` raise a typed `BackendMismatch` instead of a bare `assert`, which `python -O` stripped (#388)
- `dependency-graph.py` reads edges from `board.provider`; `--repo` is now optional (#389)
- `jared audit fetch` sources its working set from `board.provider`, so `/jared-audit` is no longer empty on KanbanFlow (#402)

**Refactor**
- New `lib/neutral_items.py` — the single backend-neutral row source for all batch surfaces, completing the #314 Phase-1 boundary
```

- [ ] **Step 5: Full verification**

```bash
pytest -q && ruff check . && ruff format --check . && mypy
```
Expected: all green; test count = 1003 baseline + every test added in Tasks 1–7.

- [ ] **Step 6: Commit and open the PR**

```bash
git add CLAUDE.md CHANGELOG.md skills/jared/references/operations.md
git log origin/main..HEAD --format='%B' | grep -nEi '(close[sd]?|fix(e[sd])?|resolve[sd]?)[^A-Za-z0-9]{0,4}#[0-9]' || true
git commit -m "docs(parity): correct the Phase-1 boundary, document the neutral row seam (Phase 8)"
git push -u origin feature/386-kanbanflow-batch-surface-parity
```

**PR body must not pair a closing keyword with any of #386, #388, #389, #402.** Reference them as "Addresses #386, #388, #389, #402." Close them via `jared close` at wrap.

---

## Self-review

**Spec coverage.** #386: Tasks 4 (door, banner, source, `/jared-init` step 6) + 1 (github regression) + 6 of its acceptance criteria mapped. #388: Tasks 2 (typed exception, `-O`) + 5 (degrade posture). #389: Task 6. #402: Task 7 — all five of its acceptance criteria have a named test. Shared code: Task 3. Doctrine: Task 8.

**Known gap, deliberate.** #388's blast-radius table lists three asserts; Task 2 replaces all three, but only `board_items` and `open_items` have a behavioral test. `provider()`'s assert at `:471` is guarded by the same change and covered by the `-O` probe indirectly. If Task 2's implementer finds a reachable path through `provider()` on a non-GitHub backend, add a third test rather than assuming symmetry.

**Type consistency.** `board_item_to_row` / `neutral_open_rows` are used with those exact names in Tasks 4, 5, 6 and 7. `BackendMismatch(method, backend)` is constructed with two positional args at all three sites. `resolve_board_identity(board) -> tuple[str, str]` is used only in Task 4.

**Instrument validation.** Task 3 Step 5 exists because a mapper test on a hand-built `BoardItem` validates the mapper, not the pipeline. Task 6 and Task 7 each pin the *data source* (no `gh issue list` call) rather than only the output, because an empty graph or an empty window would pass an output-only assertion for entirely the wrong reason.
