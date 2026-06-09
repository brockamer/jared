---
**Shipped in #317 on 2026-06-05. Final decisions captured in issue body.**
---

# Phase 4 — Init-time Backend Selection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

## Issue

- #317

**Goal:** Make jared's board backend selectable at `jared init` and make a KanbanFlow-backed `docs/project-board.md` parse and run, adapting to a board's existing columns via a Status→column map rather than mutating board structure.

**Architecture:** Three pieces. (C-provider) `KanbanFlowProvider` gains a `status_column_map` applied at construction so all Status↔column translation is map-aware. (C-parse) `Board._parse` reads `backend` before validating required fields and validates per-backend. (A+B) `bootstrap-project.py` gains `--backend` and a read-only KanbanFlow bootstrap that maps columns (auto + interview), validates Priority, and writes a slim doc. Spec: `docs/superpowers/specs/2026-06-04-phase4-init-backend-selection-design.md`.

**Tech Stack:** Python 3, argparse, stdlib-only KanbanFlow client (Phase 2/3), pytest, ruff, mypy --strict. Tests use `tests/fake_kanbanflow.py::FakeKanbanFlowClient` (no network).

---

## File Structure

- `skills/jared/scripts/lib/kanbanflow_provider.py` — add `status_column_map` + `expected_board_id` to `KanbanFlowProvider.__init__`; build Status-keyed lookup dicts; route all translation sites through them. (Task 1)
- `skills/jared/scripts/lib/board.py` — make GitHub-only dataclass fields optional; add `status_column_map` + `board_id` fields; reorder `_parse` to read `backend` first; backend-aware required-field validation; add `_parse_status_column_map`; pass map + board id into the KanbanFlow provider. (Task 2)
- `skills/jared/scripts/bootstrap-project.py` — add `--backend`, make `--url` conditional, add the KanbanFlow bootstrap path (validate + interview + render). (Tasks 3, 4)
- `commands/jared-init.md` — ask the backend and dispatch. (Task 5)
- `CLAUDE.md` — note the KanbanFlow doc shape. (Task 5)
- Tests: `tests/test_kanbanflow_provider.py` (Task 1), `tests/test_board.py` (Task 2), `tests/test_bootstrap_noninteractive.py` + new `tests/test_bootstrap_kanbanflow.py` (Tasks 3, 4).

---

## Task 1: Provider — `status_column_map` + Status-keyed translation

**Files:**
- Modify: `skills/jared/scripts/lib/kanbanflow_provider.py` (`__init__` ~94–110; `_column_id` ~117–123; `_item_from_task` ~172; `list_open_items` ~224; `close` ~351)
- Test: `tests/test_kanbanflow_provider.py`

- [ ] **Step 1: Write the failing test (non-identity Done mapping is the regression guard)**

Add to `tests/test_kanbanflow_provider.py`:

```python
def _gtd_client() -> FakeKanbanFlowClient:
    """A board whose columns are NOT jared's canonical names."""
    from skills.jared.scripts.lib.kanbanflow_client import KfBoard, KfColumn, KfCustomFieldDef

    board = KfBoard(
        id="B1",
        name="GTD",
        columns=[
            KfColumn(unique_id="c-someday", name="Someday"),
            KfColumn(unique_id="c-soon", name="Planned Soon"),
            KfColumn(unique_id="c-now", name="Doing Now"),
            KfColumn(unique_id="c-blk", name="Blocked"),
            KfColumn(unique_id="c-complete", name="Complete"),  # Done renamed
        ],
    )
    fields = [
        KfCustomFieldDef(id="cf-priority", name="Priority", field_type="dropdown",
                         dropdown_options=["High", "Medium", "Low"]),
    ]
    return FakeKanbanFlowClient(board=board, field_defs=fields)


_GTD_MAP = {
    "Backlog": "Someday",
    "Up Next": "Planned Soon",
    "In Progress": "Doing Now",
    "Blocked": "Blocked",
    "Done": "Complete",
}


def test_status_map_move_writes_mapped_column(tmp_path: Path) -> None:
    client = _gtd_client()
    index = KfNumberIndex(tmp_path / "kf-index-B1.json")
    provider = KanbanFlowProvider(
        client=client, board=client.board, field_defs=client.field_defs,
        index=index, status_column_map=_GTD_MAP,
    )
    task = client.create_task(name="x", column_id="c-someday", number_value=5)
    provider._index.put(5, task.id)
    provider.move(5, "In Progress")
    assert client.get_task(task.id).column_id == "c-now"


def test_status_map_get_item_reports_canonical_status(tmp_path: Path) -> None:
    client = _gtd_client()
    index = KfNumberIndex(tmp_path / "kf-index-B1.json")
    provider = KanbanFlowProvider(
        client=client, board=client.board, field_defs=client.field_defs,
        index=index, status_column_map=_GTD_MAP,
    )
    task = client.create_task(name="x", column_id="c-now", number_value=6)
    provider._index.put(6, task.id)
    assert provider.get_item(6).status == "In Progress"


def test_status_map_list_open_excludes_mapped_done(tmp_path: Path) -> None:
    # The regression guard: Done is mapped from "Complete". A task there must
    # be excluded from open items. An identity Done->Done fake would pass even
    # with the map unwired — this renamed-Done case is what proves the wiring.
    client = _gtd_client()
    index = KfNumberIndex(tmp_path / "kf-index-B1.json")
    provider = KanbanFlowProvider(
        client=client, board=client.board, field_defs=client.field_defs,
        index=index, status_column_map=_GTD_MAP,
    )
    done_task = client.create_task(name="done", column_id="c-complete", number_value=7)
    open_task = client.create_task(name="open", column_id="c-now", number_value=8)
    nums = {it.number for it in provider.list_open_items()}
    assert 8 in nums
    assert 7 not in nums
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_kanbanflow_provider.py -k status_map -v`
Expected: FAIL — `TypeError: __init__() got an unexpected keyword argument 'status_column_map'`.

- [ ] **Step 3: Add the constant and rewrite the constructor's column plumbing**

In `kanbanflow_provider.py`, add a module-level constant near the top (after imports):

```python
_CANONICAL_STATUSES = ("Backlog", "Up Next", "In Progress", "Blocked", "Done")
```

Change `__init__` to accept the new params and build Status-keyed dicts. Replace the four `self._column_*` / `self._swimlane_*` assignment lines' column portion:

```python
    def __init__(
        self,
        *,
        client: KanbanFlowClientLike,
        board: KfBoard,
        field_defs: list[KfCustomFieldDef],
        index: KfNumberIndex,
        status_column_map: dict[str, str] | None = None,
        expected_board_id: str | None = None,
    ) -> None:
        self._client = client
        self._board = board
        self._index = index
        self._status_column_map = status_column_map or {}
        # Raw board column maps — kept only for the "available columns" error message.
        self._column_id_by_name = {c.name: c.unique_id for c in board.columns}
        self._column_name_by_id = {c.unique_id: c.name for c in board.columns}
        # Status-keyed maps — every Status<->column translation goes through these,
        # so a renamed column (e.g. Done<-"Complete") stays correct on read AND write.
        self._column_id_by_status: dict[str, str] = {}
        self._status_by_column_id: dict[str, str] = {}
        for status in _CANONICAL_STATUSES:
            col_name = self._status_column_map.get(status, status)  # identity fallback
            col_id = self._column_id_by_name.get(col_name)
            if col_id is not None:
                self._column_id_by_status[status] = col_id
                self._status_by_column_id[col_id] = status
        self._swimlane_id_by_name = {s.name: s.unique_id for s in board.swimlanes}
        self._swimlane_name_by_id = {s.unique_id: s.name for s in board.swimlanes}
        self._field_def_by_name = {d.name: d for d in field_defs}
        self._field_name_by_id = {d.id: d.name for d in field_defs}
        if expected_board_id is not None and board.id != expected_board_id:
            print(
                f"WARNING: KanbanFlow token points at board '{board.id}' but the doc "
                f"records '{expected_board_id}'. Operating on '{board.id}'.",
                file=sys.stderr,
            )
```

Add `import sys` at the top of the file if not already present.

- [ ] **Step 4: Route the three resolution sites through the Status-keyed dicts**

`_column_id` (resolve a canonical Status to a column id):

```python
    def _column_id(self, status: str) -> str:
        if status not in self._column_id_by_status:
            available = ", ".join(sorted(self._column_id_by_name)) or "(none)"
            raise FieldNotFound(
                f"Status column for '{status}' not on the board. Available columns: {available}"
            )
        return self._column_id_by_status[status]
```

`_item_from_task` — change the `status=` line (~172) from `self._column_name_by_id.get(...)` to:

```python
            status=self._status_by_column_id.get(task.column_id) if task.column_id else None,
```

`list_open_items` — change the Done lookup (~224) from `self._column_id_by_name.get("Done")` to:

```python
        done_id = self._column_id_by_status.get("Done")
```

(`close()` at ~351 already calls `self._column_id("Done")`, so it is now map-aware with no further change.)

- [ ] **Step 5: Run the new tests + the full provider suite**

Run: `pytest tests/test_kanbanflow_provider.py -v`
Expected: PASS — new `status_map` tests pass AND all pre-existing tests still pass (they use a canonically-named fake board, so identity mapping reproduces prior behavior).

- [ ] **Step 6: Type-check and commit**

Run: `mypy && ruff check skills/jared/scripts/lib/kanbanflow_provider.py`
Expected: clean.

```bash
git add skills/jared/scripts/lib/kanbanflow_provider.py tests/test_kanbanflow_provider.py
git commit -m "feat(316): KanbanFlowProvider status_column_map + board-id verify (Phase 4.1)"
```

---

## Task 2: Board — backend-aware parse + status map + provider wiring

**Files:**
- Modify: `skills/jared/scripts/lib/board.py` (dataclass fields ~62–86; `_parse` ~129–213; add `_parse_status_column_map`; `provider` property ~394–425)
- Test: `tests/test_board.py`

- [ ] **Step 1: Write the failing tests (a KanbanFlow doc parses; a broken one fails; GitHub still works)**

Add to `tests/test_board.py`:

```python
_KF_DOC = """# Project Board

- Backend: kanbanflow
- Board URL: https://kanbanflow.com/board/p9vK6cR
- Board ID: p9vK6cR
- Board name: Jared Test
- Repo: brockamer/jared

### Status column map
- Backlog: Planned One Day
- Up Next: Planned This Week
- In Progress: Doing Now
- Blocked: Blocked
- Done: Done

## Jared config
- backend: kanbanflow
"""


def test_parse_kanbanflow_doc(tmp_path: Path) -> None:
    p = tmp_path / "project-board.md"
    p.write_text(_KF_DOC)
    board = Board.from_path(p)
    assert board.backend == "kanbanflow"
    assert board.repo == "brockamer/jared"
    assert board.owner == "brockamer"  # derived from repo
    assert board.board_id == "p9vK6cR"
    assert board.status_column_map["In Progress"] == "Doing Now"


def test_kanbanflow_doc_missing_repo_fails(tmp_path: Path) -> None:
    p = tmp_path / "project-board.md"
    p.write_text(_KF_DOC.replace("- Repo: brockamer/jared\n", ""))
    with pytest.raises(BoardConfigError, match="Repo"):
        Board.from_path(p)


def test_kanbanflow_doc_missing_status_map_fails(tmp_path: Path) -> None:
    p = tmp_path / "project-board.md"
    body = _KF_DOC.split("### Status column map")[0] + "## Jared config\n- backend: kanbanflow\n"
    p.write_text(body)
    with pytest.raises(BoardConfigError, match="Status column map"):
        Board.from_path(p)
```

`BoardConfigError` is already imported in `test_board.py` (it is used by `test_missing_file_raises_board_config_error`); if not, add it to the existing `from skills.jared.scripts.lib.board import ...` line.

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_board.py -k kanbanflow -v`
Expected: FAIL — the GitHub-required-field gate rejects the doc (`missing required field(s): Project URL, Project ID, Project number`) before `backend` is read.

- [ ] **Step 3: Make GitHub-only dataclass fields optional + add new fields**

In the `Board` dataclass, change the five leading required fields to carry defaults and add two fields (place `status_column_map` and `board_id` alongside `backend`):

```python
    project_number: int | None = None
    project_id: str = ""
    owner: str = ""
    repo: str = ""
    project_url: str = ""
```

And near the `backend` field:

```python
    # KanbanFlow Status->column map (canonical Status -> board column name).
    # Empty for GitHub boards. Parsed from the `### Status column map` block.
    status_column_map: dict[str, str] = field(default_factory=dict)
    # KanbanFlow board id (from `- Board ID:`); None for GitHub. Used for the
    # provider's board-identity soft-verify.
    board_id: str | None = None
```

(All fields after `project_number` already have defaults, so dataclass ordering stays valid.)

- [ ] **Step 4: Add the status-map parser**

Add as a `@staticmethod` on `Board` (near `_parse_jared_config`):

```python
    @staticmethod
    def _parse_status_column_map(text: str) -> dict[str, str]:
        """Parse the optional `### Status column map` block into {Status: column}."""
        m = re.search(
            r"^### Status column map\s*\n(.*?)(?=^#{2,3}\s|\Z)",
            text,
            re.MULTILINE | re.DOTALL,
        )
        if not m:
            return {}
        result: dict[str, str] = {}
        for line in m.group(1).splitlines():
            bm = re.match(r"\s*-\s*([^:]+):\s*(.+?)\s*$", line)
            if bm:
                result[bm.group(1).strip()] = bm.group(2).strip()
        return result
```

- [ ] **Step 5: Reorder `_parse` to be backend-aware**

In `_parse`, move the backend read above the missing-fields gate and branch validation. Replace the block from the `missing: list[str] = []` gate through the `return cls(...)` with:

```python
        jared_config = cls._parse_jared_config(text)
        backend = jared_config.get("backend", "github")
        session_handoff_prompt = jared_config.get("session-handoff-prompt", "ask")
        session_start_checks = cls._parse_session_start_checks(text)
        operator_docs, code_surface = cls._parse_operator_docs(text)

        if backend == "kanbanflow":
            status_column_map = cls._parse_status_column_map(text)
            board_id = find_optional(r"Board ID:\s*(\S+)")
            missing = []
            if repo is None:
                missing.append("Repo")
            if not status_column_map:
                missing.append("Status column map")
            if missing:
                raise BoardConfigError(
                    f"{source} (backend=kanbanflow) missing: {', '.join(missing)}. "
                    "Run /jared-init to bootstrap or patch the file."
                )
            assert repo is not None
            return cls(
                owner=repo.split("/")[0],
                repo=repo,
                backend="kanbanflow",
                status_column_map=status_column_map,
                board_id=board_id,
                session_handoff_prompt=session_handoff_prompt,
                session_start_checks=session_start_checks,
                operator_docs=operator_docs,
                code_surface=code_surface,
                _raw_doc=text,
            )

        # backend == "github" (default): GitHub Project identifiers required.
        missing = []
        if project_url is None:
            missing.append("Project URL")
        if project_id is None:
            missing.append("Project ID")
        if project_number_val is None:
            missing.append("Project number")
        if owner is None:
            missing.append("Owner")
        if repo is None:
            missing.append("Repo")
        if missing:
            raise BoardConfigError(
                f"{source} missing required field(s): {', '.join(missing)}. "
                "Run /jared-init to bootstrap or patch the file."
            )
        assert project_url is not None
        assert project_id is not None
        assert project_number_val is not None
        assert owner is not None
        assert repo is not None

        field_ids, field_options = cls._parse_field_blocks(text)
        return cls(
            project_number=project_number_val,
            project_id=project_id,
            owner=owner,
            repo=repo,
            project_url=project_url,
            _field_ids=field_ids,
            _field_options=field_options,
            session_handoff_prompt=session_handoff_prompt,
            session_start_checks=session_start_checks,
            operator_docs=operator_docs,
            code_surface=code_surface,
            _raw_doc=text,
            backend=backend,
        )
```

(Delete the now-superseded original `missing`-gate block and the single `return cls(...)` that followed it, so the GitHub path is the branch above.)

- [ ] **Step 6: Wire the map + board id into the provider**

In the `provider` property, the `kanbanflow` branch — pass the new args:

```python
                self._provider = KanbanFlowProvider(
                    client=client,
                    board=kf_board,
                    field_defs=field_defs,
                    index=index,
                    status_column_map=self.status_column_map,
                    expected_board_id=self.board_id,
                )
```

In the `github` branch, narrow the now-optional `project_number` for mypy — add before constructing `GitHubProjectsProvider`:

```python
                assert self.project_number is not None  # github docs always carry it
```

- [ ] **Step 7: Run the KanbanFlow tests + the FULL board suite (GitHub must stay green)**

Run: `pytest tests/test_board.py -v`
Expected: PASS — new `kanbanflow` tests pass AND every pre-existing GitHub-doc test passes unchanged. **If any existing test needs editing, STOP** — per the Phase-1 gate that is a behavior regression to surface, not absorb.

- [ ] **Step 8: Full suite + type-check + commit**

Run: `pytest -m 'not integration' -q && mypy && ruff check .`
Expected: all clean, no conftest signature change.

```bash
git add skills/jared/scripts/lib/board.py tests/test_board.py
git commit -m "feat(316): backend-aware Board._parse + KanbanFlow status map (Phase 4.2)"
```

---

## Task 3: Bootstrap — `--backend` flag + conditional `--url`

**Files:**
- Modify: `skills/jared/scripts/bootstrap-project.py` (`build_parser` ~707–746; top of `main` ~747–760)
- Test: `tests/test_bootstrap_noninteractive.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_bootstrap_noninteractive.py`:

```python
import importlib.util
from pathlib import Path


def _load_bootstrap():
    spec = importlib.util.spec_from_file_location(
        "bootstrap_project", Path("skills/jared/scripts/bootstrap-project.py")
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def test_url_with_kanbanflow_is_rejected() -> None:
    # --url + kanbanflow is enforced in main() via parser.error (SystemExit),
    # not at parse time; parse the args then assert the cross-field guard fires.
    b = _load_bootstrap()
    parser = b.build_parser()
    args = parser.parse_args(["--backend", "kanbanflow", "--repo", "o/r", "--url", "https://x"])
    assert args.backend == "kanbanflow" and args.url == "https://x"
    # The guard lives at the top of main(); confirm it raises SystemExit.
    with pytest.raises(SystemExit):
        b.main_guard(args, parser)  # see Step 3 — extract the cross-field check


def test_backend_defaults_to_github() -> None:
    b = _load_bootstrap()
    args = b.build_parser().parse_args(
        ["--url", "https://github.com/users/o/projects/4", "--repo", "o/r"]
    )
    assert args.backend == "github"
```

Reuse this `_load_bootstrap()` helper (importlib, since `bootstrap-project.py` carries a `.py` extension) in any later bootstrap test that needs the module. Note: to make the cross-field rule unit-testable without running the full `main()`, Step 3 extracts it into a small `main_guard(args, parser)` helper that `main()` calls.

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_bootstrap_noninteractive.py -k "backend or kanbanflow" -v`
Expected: FAIL — `--backend` is not a known argument.

- [ ] **Step 3: Add the flag and make `--url` conditional**

In `build_parser`, change `--url` to not be unconditionally required and add `--backend`:

```python
    parser.add_argument("--url", required=False, help="GitHub Project v2 URL (required for --backend github)")
    parser.add_argument(
        "--backend",
        choices=["github", "kanbanflow"],
        default="github",
        help="Board backend. 'kanbanflow' uses KANBANFLOW_API_TOKEN; 'github' needs --url.",
    )
```

Extract the cross-field rule into a testable helper above `main`, and call it at the top of `main()`:

```python
def main_guard(args, parser) -> None:
    """Enforce backend/url cross-field rules. Raises SystemExit via parser.error."""
    if args.backend == "kanbanflow" and args.url:
        parser.error("--url is not valid with --backend kanbanflow (the board-scoped token selects the board)")
    if args.backend == "github" and not args.url:
        parser.error("--url is required for --backend github")
```

At the very top of `main()`, after `args = parser.parse_args()`:

```python
    main_guard(args, parser)
    if args.backend == "kanbanflow":
        return bootstrap_kanbanflow(args)  # added in Task 4
```

(`bootstrap_kanbanflow` is stubbed to `raise NotImplementedError` for now so Task 3 compiles; Task 4 implements it. Add `def bootstrap_kanbanflow(args): raise NotImplementedError` temporarily above `main`.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_bootstrap_noninteractive.py -k "backend or kanbanflow" -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add skills/jared/scripts/bootstrap-project.py tests/test_bootstrap_noninteractive.py
git commit -m "feat(317): bootstrap --backend flag + conditional --url (Phase 4.3)"
```

---

## Task 4: Bootstrap — KanbanFlow validate + interview + render

**Files:**
- Modify: `skills/jared/scripts/bootstrap-project.py` (implement `bootstrap_kanbanflow`; add `map_status_columns`, `validate_priority_field`, `render_kanbanflow_doc`)
- Test: Create `tests/test_bootstrap_kanbanflow.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_bootstrap_kanbanflow.py`:

```python
"""Unit tests for the KanbanFlow bootstrap path (Phase 4, #317)."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from skills.jared.scripts.lib.kanbanflow_client import KfBoard, KfColumn, KfCustomFieldDef
from tests.fake_kanbanflow import FakeKanbanFlowClient


def _load_bootstrap():
    spec = importlib.util.spec_from_file_location(
        "bootstrap_project", Path("skills/jared/scripts/bootstrap-project.py")
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def _gtd_board() -> KfBoard:
    return KfBoard(
        id="p9vK6cR", name="Jared Test",
        columns=[
            KfColumn(unique_id="c1", name="Maybe Never?"),
            KfColumn(unique_id="c2", name="Planned One Day"),
            KfColumn(unique_id="c3", name="Planned This Week"),
            KfColumn(unique_id="c4", name="Will Do Today"),
            KfColumn(unique_id="c5", name="Doing Now"),
            KfColumn(unique_id="c6", name="Blocked"),
            KfColumn(unique_id="c7", name="Done"),
        ],
    )


def test_map_status_columns_auto_and_interview(monkeypatch) -> None:
    b = _load_bootstrap()
    # Auto: Blocked, Done. Interview answers for Backlog/Up Next/In Progress:
    answers = iter(["Planned One Day", "Planned This Week", "Doing Now"])
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(answers))
    mapping, unmapped = b.map_status_columns(_gtd_board())
    assert mapping == {
        "Backlog": "Planned One Day", "Up Next": "Planned This Week",
        "In Progress": "Doing Now", "Blocked": "Blocked", "Done": "Done",
    }
    assert set(unmapped) == {"Maybe Never?", "Will Do Today"}


def test_validate_priority_field_missing_hard_stops() -> None:
    b = _load_bootstrap()
    with pytest.raises(SystemExit):
        b.validate_priority_field([])  # no custom fields => hard stop


def test_validate_priority_field_present_ok() -> None:
    b = _load_bootstrap()
    defs = [KfCustomFieldDef(id="x", name="Priority", field_type="dropdown",
                             dropdown_options=["High", "Medium", "Low"])]
    b.validate_priority_field(defs)  # no raise


def test_render_kanbanflow_doc_shape() -> None:
    b = _load_bootstrap()
    doc = b.render_kanbanflow_doc(
        board=_gtd_board(),
        repo="brockamer/jared",
        status_map={"Backlog": "Planned One Day", "Up Next": "Planned This Week",
                    "In Progress": "Doing Now", "Blocked": "Blocked", "Done": "Done"},
    )
    assert "- backend: kanbanflow" in doc
    assert "### Status column map" in doc
    assert "- In Progress: Doing Now" in doc
    assert "- Board ID: p9vK6cR" in doc
    # Secrets stay in env: the doc documents the env-var NAME as guidance, and
    # render_kanbanflow_doc never receives the token value, so it cannot leak it.
    assert "KANBANFLOW_API_TOKEN" in doc
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_bootstrap_kanbanflow.py -v`
Expected: FAIL — `map_status_columns` / `validate_priority_field` / `render_kanbanflow_doc` not defined.

- [ ] **Step 3: Implement the three helpers + `bootstrap_kanbanflow`**

In `bootstrap-project.py`, add (replacing the temporary `bootstrap_kanbanflow` stub):

```python
import sys

_CANONICAL_STATUSES = ("Backlog", "Up Next", "In Progress", "Blocked", "Done")


def map_status_columns(board) -> tuple[dict[str, str], list[str]]:
    """Auto-map exact column-name matches; interview for the rest. 1:1.

    Returns (status->column map, leftover-unmapped-column-names).
    """
    col_names = [c.name for c in board.columns]
    mapping: dict[str, str] = {}
    used: set[str] = set()
    for status in _CANONICAL_STATUSES:
        if status in col_names:
            mapping[status] = status
            used.add(status)
    for status in _CANONICAL_STATUSES:
        if status in mapping:
            continue
        choices = [n for n in col_names if n not in used]
        print(f'\nWhich column is "{status}"?')
        for i, n in enumerate(choices, 1):
            print(f"  [{i}] {n}")
        raw = input(f'Column for "{status}" (name or number): ').strip()
        chosen = choices[int(raw) - 1] if raw.isdigit() else raw
        if chosen not in col_names:
            print(f"bootstrap: '{chosen}' is not a column on this board", file=sys.stderr)
            raise SystemExit(1)
        mapping[status] = chosen
        used.add(chosen)
    unmapped = [n for n in col_names if n not in used]
    return mapping, unmapped


def validate_priority_field(field_defs) -> None:
    """Hard-stop unless a 'Priority' dropdown with High/Medium/Low exists."""
    pri = next((d for d in field_defs if d.name == "Priority"), None)
    needed = {"High", "Medium", "Low"}
    if pri is None or not needed.issubset(set(pri.dropdown_options)):
        print(
            "bootstrap: no 'Priority' custom field with options High, Medium, Low. "
            "jared requires it. Create a dropdown custom field named 'Priority' "
            "(options: High, Medium, Low) in the KanbanFlow board's "
            "Settings -> Custom fields, then re-run.",
            file=sys.stderr,
        )
        raise SystemExit(1)


def render_kanbanflow_doc(*, board, repo: str, status_map: dict[str, str]) -> str:
    rows = "\n".join(f"- {s}: {status_map[s]}" for s in _CANONICAL_STATUSES)
    return f"""# Project Board — How It Works

- Backend: kanbanflow
- Board URL: https://kanbanflow.com/board/{board.id}
- Board ID: {board.id}
- Board name: {board.name}
- Repo: {repo}

Auth: set `KANBANFLOW_API_TOKEN` in your environment (board-scoped token from
KanbanFlow Settings -> API). The token is never stored in this file.

### Status column map
{rows}

### Priority
- Field name: Priority
- Options: High, Medium, Low

## Jared config
- backend: kanbanflow
- voice: enabled
"""


def bootstrap_kanbanflow(args) -> int:
    from lib.kanbanflow_client import KanbanFlowClient

    try:
        client = KanbanFlowClient.from_env()
        board = client.get_board()
        field_defs = client.list_custom_field_defs()
    except Exception as e:  # noqa: BLE001 - surface any connect/auth failure
        print(f"bootstrap: KanbanFlow connect failed: {e}", file=sys.stderr)
        return 1

    print(f"Connected to KanbanFlow board: {board.name} ({board.id})")
    status_map, unmapped = map_status_columns(board)
    validate_priority_field(field_defs)  # hard-stop if missing

    if unmapped:
        print(
            f"NOTE: columns not mapped to a jared Status — items there are invisible "
            f"to jared: {', '.join(unmapped)}",
            file=sys.stderr,
        )
    if not board.swimlanes:
        print(
            "NOTE: no swimlanes on this board — milestones map to swimlanes and are "
            "unavailable; jared's dateless milestone convention degrades gracefully.",
            file=sys.stderr,
        )

    doc = render_kanbanflow_doc(board=board, repo=args.repo, status_map=status_map)
    out = Path(args.output)
    if out.exists() and not args.force:
        print(f"bootstrap: {out} exists; pass --force to overwrite", file=sys.stderr)
        return 1
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(doc)
    print(f"Wrote {out}")
    return 0
```

(`args.output` and `args.force` already exist in `build_parser`. The `from lib.kanbanflow_client import ...` import matches how the CLI imports lib modules — bootstrap runs with `scripts/` on `sys.path`.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_bootstrap_kanbanflow.py -v`
Expected: PASS.

- [ ] **Step 5: Full suite + lint + type-check**

Run: `pytest -m 'not integration' -q && ruff check . && ruff format --check . && mypy`
Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add skills/jared/scripts/bootstrap-project.py tests/test_bootstrap_kanbanflow.py
git commit -m "feat(317): KanbanFlow bootstrap — map/validate/render (Phase 4.4)"
```

---

## Task 5: `/jared-init` dispatch + CLAUDE.md note

**Files:**
- Modify: `commands/jared-init.md` (the bootstrap-invocation step)
- Modify: `CLAUDE.md` (Board helper / Architecture section)

- [ ] **Step 1: Update the `/jared-init` stub**

In `commands/jared-init.md`, at the bootstrap-invocation step (~step 2), add a backend-selection instruction before the command, and document both invocations:

```markdown
2. **Choose the backend, then run `bootstrap-project.py`.** Ask the operator
   (voice ON — first impression): *GitHub Projects or KanbanFlow?*

   - GitHub (default):
     ```
     ${CLAUDE_PLUGIN_ROOT}/skills/jared/scripts/bootstrap-project.py --backend github --url <project-url> --repo <owner>/<repo>
     ```
   - KanbanFlow (requires `KANBANFLOW_API_TOKEN` in env; the token selects the
     board, so no `--url`). The script interviews the operator to map jared's
     Status columns onto the board's existing columns:
     ```
     ${CLAUDE_PLUGIN_ROOT}/skills/jared/scripts/bootstrap-project.py --backend kanbanflow --repo <owner>/<repo>
     ```
   Script output (including the column interview) stays voice-OFF / verbatim.
```

- [ ] **Step 2: Add a CLAUDE.md note on the KanbanFlow doc shape**

In `CLAUDE.md`, under "The `Board` helper" / "Board-provider abstraction", append a sentence noting the KanbanFlow doc shape:

```markdown
A KanbanFlow-backed `docs/project-board.md` carries `- backend: kanbanflow`, a `Repo:`
bullet, a `Board ID:` / `Board URL:`, and a `### Status column map` block (canonical
Status → the board's actual column name); it omits the GitHub Project identifiers and
field/option-ID blocks (the provider resolves columns/options live from the API, with the
board-scoped `KANBANFLOW_API_TOKEN` selecting the board). Init-time selection lands in #317
(Phase 4 of epic #313).
```

- [ ] **Step 3: Commit (docs only, no test)**

```bash
git add commands/jared-init.md CLAUDE.md
git commit -m "docs(317): /jared-init backend dispatch + KanbanFlow doc shape (Phase 4.5)"
```

---

## Task 6: Live end-to-end verification + backfill #317 acceptance criteria

**Files:** none (verification + board op). Uses the live board `p9vK6cR` and `KANBANFLOW_API_TOKEN`.

- [ ] **Step 1: Bootstrap the live board into a throwaway doc**

Run (worktree-resident script; token in env — never echoed into a tracked file):

```bash
KANBANFLOW_API_TOKEN=<token> /home/brockamer/Code/jared-317/skills/jared/scripts/bootstrap-project.py \
  --backend kanbanflow --repo brockamer/jared --output /tmp/kf-board.md --force
```

Complete the column interview (`Planned One Day`→Backlog, `Planned This Week`→Up Next, `Doing Now`→In Progress). Expect a NOTE about the unmapped `Maybe Never?` / `Will Do Today` columns and — if Priority isn't set up yet — a hard stop telling you to create the `Priority` field. If it hard-stops, create the field in the KanbanFlow UI and re-run.
Expected: `/tmp/kf-board.md` written with the slim KanbanFlow shape.

- [ ] **Step 2: Exercise a real board cycle against the live board**

Point a jared command at the throwaway doc and run a `file → summary → move → close` cycle (worktree-resident script). Use `--board /tmp/kf-board.md` if supported, else copy it to the worktree's `docs/project-board.md` temporarily (do NOT commit it):

```bash
KANBANFLOW_API_TOKEN=<token> /home/brockamer/Code/jared-317/skills/jared/scripts/jared \
  --board /tmp/kf-board.md summary
```

Expected: connects, lists items by their mapped Status. Then `file` a throwaway task, `move` it through columns, `summary` to confirm placement, `close` it.

- [ ] **Step 3: Clean up**

Delete the throwaway task from the live board (KanbanFlow UI or `jared close` then UI-delete). Confirm no `/tmp/kf-board.md` or `cache_dir/kf-index-p9vK6cR.json` got committed (the index lives outside the repo by design).

- [ ] **Step 4: Backfill #317 acceptance criteria from this plan**

The issue was filed as a stub ("spec + plan when activated"). Now that both exist, write real acceptance criteria onto #317 (matching this plan's Task-level outcomes), so the board reflects a pullable, well-specified issue:

```bash
/home/brockamer/Code/jared-317/skills/jared/scripts/jared set 317 ... # or jared comment / gh issue edit to add ## Acceptance criteria
```

Acceptance criteria to record: bootstrap `--backend kanbanflow` maps columns (auto+interview), validates Priority (hard-stop), warns on unmapped/swimlanes, writes a slim doc; `Board._parse` parses a KanbanFlow doc (backend-first, repo+map required); `KanbanFlowProvider` honors the map on read+write; live `file→move→summary→close` succeeds; full suite green with no GitHub-test/conftest changes.

- [ ] **Step 5: Open the PR**

```bash
git -C /home/brockamer/Code/jared-317 push -u origin feature/317-add-init-time-backend-selection-phase-4
gh pr create --title "feat(317): init-time backend selection (Phase 4)" --body "<summary + Refs #317, epic #313>"
```

---

## Self-Review notes

- **Spec coverage:** Piece A → Tasks 3, 5. Piece B → Task 4. Piece C-provider → Task 1. Piece C-parse → Task 2. Board-id verify → Task 1 (`expected_board_id`) + Task 2 (parse + wire). Live e2e → Task 6. Non-goals (no structure creation, no swimlane/Priority mapping, no migration/capability-enforcement) are respected — no task implements them.
- **Regression guard:** Task 1 Step 1's renamed-Done test is the guard the advisor flagged; Task 2 Step 7 enforces "no GitHub-test changes."
- **Type consistency:** `status_column_map` (Status→column name) and `expected_board_id` are used identically across Tasks 1–2; `_CANONICAL_STATUSES` is defined in both the provider (Task 1) and bootstrap (Task 4) — intentional (separate modules), same tuple value.
