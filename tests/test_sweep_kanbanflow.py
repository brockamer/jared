"""sweep.py on a KanbanFlow-backed board (#386).

Before this work sweep exited 1 at its entry point: `parse_config` searched the
convention doc for a GitHub Projects URL, and a KanbanFlow doc has none by
construction. `/jared-init` step 6 ("run sweep to confirm the board is clean")
was therefore impossible on this backend, as was /jared-groom's sweep-backed
reporting.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.conftest import (
    KfTaskSpec,
    import_sweep,
    patch_gh_by_arg,
    patch_kf_board_provider,
    run_script_main,
    write_minimal_kanbanflow_board,
)

KF_TASKS: list[KfTaskSpec] = [
    {"number": 1, "name": "alpha", "column": "Backlog", "priority": "High"},
    {"number": 2, "name": "beta", "column": "In Progress", "priority": "Medium"},
    {"number": 3, "name": "gamma", "column": "Up Next", "priority": "Low"},
]


def _run_kf_sweep(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[int, str]:
    write_minimal_kanbanflow_board(tmp_path)
    monkeypatch.setenv("JARED_NO_CACHE", "1")
    # Import the script BEFORE patching. sweep.py puts scripts/ on sys.path and
    # imports `lib.board`, a different module object from the tests'
    # `skills.jared.scripts.lib.board`. Until that import happens the second
    # Board class does not exist in sys.modules and patching it silently no-ops
    # — the dual-import trap in conftest's module docstring.
    sweep = import_sweep()
    patch_kf_board_provider(monkeypatch, tmp_path, KF_TASKS)
    # A healthy GraphQL budget: the pre-flight gate runs before any backend
    # branching, and an unserved probe parses as remaining=0 -> early exit 0
    # with an empty stdout, which would make every assertion below vacuous.
    patch_gh_by_arg(
        monkeypatch,
        {
            "api rate_limit": json.dumps(
                {"resources": {"graphql": {"remaining": 4900, "limit": 5000, "reset": 0}}}
            )
        },
        default="{}",
    )
    return run_script_main(sweep, ["sweep.py"], tmp_path, monkeypatch, capsys)


def test_sweep_exits_zero_on_kanbanflow_board(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """#386's headline acceptance criterion."""
    rc, out = _run_kf_sweep(tmp_path, capsys, monkeypatch)

    assert rc == 0
    assert out.strip(), "sweep produced no output at all"


def test_sweep_banner_names_the_kanbanflow_board(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The banner must name the actual board, not a synthesised GitHub URL."""
    _, out = _run_kf_sweep(tmp_path, capsys, monkeypatch)

    assert "kanbanflow.com/board/B1" in out
    assert "github.com" not in out
    # The /orgs/ hint is meaningless off GitHub.
    assert "also tries /orgs/" not in out


def test_sweep_reads_items_from_the_provider_on_kanbanflow(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Pin the data source, not just the exit code.

    An empty item list would satisfy "exits 0" for entirely the wrong reason,
    so assert the provider's tasks actually reached the checks.
    """
    _, out = _run_kf_sweep(tmp_path, capsys, monkeypatch)

    assert "Open items on board: 3" in out


def test_sweep_degrades_issue_metadata_sections_on_kanbanflow(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Sections needing GitHub issue metadata skip rather than abort.

    These land in sweep's pre-existing `elif not issues_by_number` branches —
    the degrade posture is not invented here, it already existed for the
    no-repo case.
    """
    _, out = _run_kf_sweep(tmp_path, capsys, monkeypatch)

    assert "== Off-board issues (open in repo, missing from project) ==" in out
    assert "(skipped — no issue data)" in out
    # No invented capability tag for "has a GitHub repo issue list".
    assert "degraded: off-board" not in out


def test_sweep_does_not_call_gh_project_item_list_on_kanbanflow(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The whole point: no `gh project item-list` on a board that has no
    GitHub project."""
    write_minimal_kanbanflow_board(tmp_path)
    monkeypatch.setenv("JARED_NO_CACHE", "1")
    sweep = import_sweep()  # must precede the patch; see _run_kf_sweep
    patch_kf_board_provider(monkeypatch, tmp_path, KF_TASKS)
    calls = patch_gh_by_arg(
        monkeypatch,
        {
            "api rate_limit": json.dumps(
                {"resources": {"graphql": {"remaining": 4900, "limit": 5000, "reset": 0}}}
            )
        },
        default="{}",
    )

    run_script_main(sweep, ["sweep.py"], tmp_path, monkeypatch, capsys)

    joined = [" ".join(c) for c in calls]
    assert not any("project item-list" in c for c in joined), joined


def test_sweep_reports_a_kanbanflow_error_cleanly_instead_of_a_traceback(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Opening the door makes KanbanFlow's own failures reachable (#386).

    KanbanFlowError does not subclass RuntimeError, so without handling it an
    unset token, an auth failure or a rate limit would leak a raw traceback
    out of sweep instead of its one-line `sweep: <message>` convention — the
    #8 defect, newly reachable because this change removed the regex door.
    """
    write_minimal_kanbanflow_board(tmp_path)
    monkeypatch.setenv("JARED_NO_CACHE", "1")
    sweep = import_sweep()
    patch_gh_by_arg(
        monkeypatch,
        {
            "api rate_limit": json.dumps(
                {"resources": {"graphql": {"remaining": 4900, "limit": 5000, "reset": 0}}}
            )
        },
        default="{}",
    )

    # Make the provider raise the way a missing token does, on both Board
    # class objects (the dual-import trap).
    import importlib

    from skills.jared.scripts.lib.board import Board as SkillBoard

    # Raise the class sweep actually catches. sweep.py imports
    # `lib.kanbanflow_client`, a different module object from the tests'
    # `skills.jared.scripts.lib.kanbanflow_client`, so their KanbanFlowError
    # classes are distinct and `except` on one will NOT catch the other.
    # Raising the tests' copy here made this test fail against correct
    # production code — the dual-import trap in conftest's module docstring.
    kf_client = importlib.import_module("lib.kanbanflow_client")

    def _boom(self: object) -> object:
        raise kf_client.KanbanFlowError("KANBANFLOW_API_TOKEN is not set.")

    monkeypatch.setattr(SkillBoard, "provider", property(_boom))
    lib_board = importlib.import_module("lib.board")
    if lib_board.Board is not SkillBoard:
        monkeypatch.setattr(lib_board.Board, "provider", property(_boom))

    # include_stderr: run_script_main drains the capture buffer, so a second
    # capsys.readouterr() would come back empty.
    rc, out = run_script_main(
        sweep, ["sweep.py"], tmp_path, monkeypatch, capsys, include_stderr=True
    )

    assert rc == 1
    assert "Traceback" not in out
    assert "sweep: " in out
    assert "KANBANFLOW_API_TOKEN" in out
