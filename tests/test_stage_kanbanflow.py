"""stage.py on a KanbanFlow-backed board (#388).

`stage.py` reached `Board.board_items()`, a github-only method, and died with
a bare `AssertionError` and no message — worse than sweep, which at least
printed a sentence. Phase 2 made that a typed `BackendMismatch`; this routes
the data source through the provider so stage actually runs.

Posture is soft-skip-with-note, not refusal: stage's ranking needs Status and
Priority, which the provider supplies on both backends. Only the Backlog-age
tiebreaker needs creation timestamps, and that gate already existed.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.conftest import (
    KfTaskSpec,
    import_stage,
    patch_kf_board_provider,
    write_minimal_kanbanflow_board,
)

KF_TASKS: list[KfTaskSpec] = [
    {
        "number": 1,
        "name": "alpha",
        "column": "Backlog",
        "priority": "High",
        "description": "A summary.\n\n## Acceptance criteria\n\n- it works\n",
    },
    {"number": 2, "name": "beta", "column": "In Progress", "priority": "Medium"},
    {"number": 3, "name": "gamma", "column": "Up Next", "priority": "Low"},
]


def _run_kf_stage(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[int, str]:
    write_minimal_kanbanflow_board(tmp_path)
    monkeypatch.setenv("JARED_NO_CACHE", "1")
    # Import before patching: stage.py puts scripts/ on sys.path and imports
    # `lib.board`, a second Board class object. See conftest's docstring.
    stage = import_stage()
    patch_kf_board_provider(monkeypatch, tmp_path, KF_TASKS)
    monkeypatch.chdir(tmp_path)

    rc = stage.main([])  # stage.main DOES take argv, unlike sweep
    return rc, capsys.readouterr().out


def test_stage_runs_to_completion_on_kanbanflow(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    rc, out = _run_kf_stage(tmp_path, capsys, monkeypatch)

    assert rc == 0
    assert out.strip(), "stage produced no output at all"


def test_stage_emits_no_traceback_or_bare_assertion_on_kanbanflow(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """#388's reported symptom: a bare AssertionError and a traceback."""
    _, out = _run_kf_stage(tmp_path, capsys, monkeypatch)

    assert "AssertionError" not in out
    assert "Traceback" not in out


def test_stage_degrades_the_backlog_age_tiebreaker_on_kanbanflow(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Soft-skip-with-note: stage still ranks, minus the age tiebreaker."""
    _, out = _run_kf_stage(tmp_path, capsys, monkeypatch)

    assert "degraded:" in out


def test_stage_sees_the_providers_items_on_kanbanflow(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Pin the data source. An empty item list would satisfy "exits 0" for
    entirely the wrong reason, so assert a seeded task reached the output."""
    _, out = _run_kf_stage(tmp_path, capsys, monkeypatch)

    assert "#1" in out


def test_stage_uses_the_providers_emulated_edges_on_kanbanflow(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Blocker detection must use the edges the provider actually has.

    NATIVE_DEPENDENCIES is absent, but the DATA is not: the KanbanFlow
    provider parses `blocked-by:` labels into BoardItem.blocked_by. Treating
    "no native capability" as "no edges" would hide real blockers and let
    stage promote a blocked item. dependency-graph (#389) and audit (#402)
    both consume these edges; stage must agree.

    #4 is blocked by #2, which is In Progress and therefore still open, so #4
    must not be proposed for promotion.
    """
    write_minimal_kanbanflow_board(tmp_path)
    monkeypatch.setenv("JARED_NO_CACHE", "1")
    stage = import_stage()
    patch_kf_board_provider(
        monkeypatch,
        tmp_path,
        [
            *KF_TASKS,
            {
                "number": 4,
                "name": "delta",
                "column": "Backlog",
                "priority": "High",
                "labels": ["blocked-by:2"],
                "description": "A summary.\n\n## Acceptance criteria\n\n- it works\n",
            },
        ],
    )
    monkeypatch.chdir(tmp_path)

    stage.main([])
    out = capsys.readouterr().out

    promote_block = out.split("== Blocked revisit ==")[0]
    assert "#4" not in promote_block, (
        "#4 is blocked by open #2 via an emulated edge and must not be promoted"
    )
