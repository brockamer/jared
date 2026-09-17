"""`BackendMismatch` — a guard that survives `python -O` (#388).

`Board.provider()`, `Board.board_items()` and `Board.open_items()` are
GitHub-only. They were guarded by `assert self.project_number is not None`,
which fails two ways:

1. A bare `AssertionError` with no message. `/jared-stage` on a KanbanFlow
   board gave the operator a traceback and no diagnosis.
2. `assert` is stripped under `python -O`. With optimisations on the guard
   vanishes, execution continues into the GitHub path, and the run ends in a
   `gh` error about a repository that does not exist — pointing the reader at
   their GitHub config rather than at a backend mismatch.

A typed exception fixes both.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from skills.jared.scripts.lib.board import BackendMismatch, Board
from tests.conftest import REPO_ROOT, write_minimal_kanbanflow_board


def test_board_items_raises_typed_error_on_kanbanflow(tmp_path: Path) -> None:
    board = Board.from_path(write_minimal_kanbanflow_board(tmp_path))

    with pytest.raises(BackendMismatch) as exc:
        board.board_items()

    msg = str(exc.value)
    assert "board_items" in msg  # names the method
    assert "kanbanflow" in msg  # names the configured backend
    assert "github" in msg  # names what it requires


def test_open_items_raises_typed_error_on_kanbanflow(tmp_path: Path) -> None:
    board = Board.from_path(write_minimal_kanbanflow_board(tmp_path))

    with pytest.raises(BackendMismatch, match="open_items"):
        board.open_items()


def test_backend_mismatch_carries_structured_fields(tmp_path: Path) -> None:
    """Callers should be able to branch without parsing the message."""
    board = Board.from_path(write_minimal_kanbanflow_board(tmp_path))

    with pytest.raises(BackendMismatch) as exc:
        board.board_items()

    assert exc.value.method == "board_items"
    assert exc.value.backend == "kanbanflow"


_O_PROBE = """
import sys
from pathlib import Path
sys.path.insert(0, {repo!r})
from skills.jared.scripts.lib.board import BackendMismatch, Board
board = Board.from_path(Path({doc!r}))
try:
    board.board_items()
except BackendMismatch:
    print("TYPED")
except Exception as e:
    print("WRONG:" + type(e).__name__)
else:
    print("NO_GUARD")
"""


def test_guard_survives_python_dash_O(tmp_path: Path) -> None:
    """The whole point of #388: `-O` must not change the failure mode.

    This has to be a real subprocess — `-O` is an interpreter flag set at
    startup, not something that can be toggled from inside a running test.
    """
    doc = write_minimal_kanbanflow_board(tmp_path)
    probe = _O_PROBE.format(repo=str(REPO_ROOT), doc=str(doc))

    result = subprocess.run(
        [sys.executable, "-O", "-c", probe],
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert result.stdout.strip() == "TYPED", f"stdout={result.stdout!r} stderr={result.stderr!r}"


def test_assert_based_guard_would_have_failed_this_probe(tmp_path: Path) -> None:
    """Validate the instrument: prove the -O probe can actually catch the bug.

    A probe that passes no matter what is worthless. This runs the *old*
    construct — a bare assert on the same condition — under `-O` and confirms
    it is stripped. If this ever stops printing NO_GUARD, the probe above is
    not testing what it claims to test.
    """
    probe = (
        "project_number = None\n"
        "try:\n"
        "    assert project_number is not None\n"
        "except AssertionError:\n"
        "    print('TYPED')\n"
        "else:\n"
        "    print('NO_GUARD')\n"
    )

    result = subprocess.run(
        [sys.executable, "-O", "-c", probe],
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert result.stdout.strip() == "NO_GUARD", (
        "the -O probe cannot distinguish a stripped assert from a live guard"
    )
