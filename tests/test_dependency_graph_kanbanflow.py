"""dependency-graph.py on a KanbanFlow-backed board (#389).

Distinct from #386/#388: those fail because a github-only *method* is
reachable. This one fails because the script's *data source* is GitHub — it
requires --repo and then calls `gh issue list`. A KanbanFlow-backed project
need not have a GitHub repository at all, and the `Repo:` bullet is only
regex-validated, so the slug can legitimately name no real repo.

The graph data exists on this backend: the KanbanFlow provider parses its
emulated blocked-by labels into BoardItem.blocked_by. Only the reader pointed
at the wrong place.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.conftest import (
    KfTaskSpec,
    import_dep,
    patch_gh_by_arg,
    patch_kf_board_provider,
    run_script_main,
    write_minimal_kanbanflow_board,
)

KF_TASKS: list[KfTaskSpec] = [
    {"number": 1, "name": "alpha", "column": "Backlog", "priority": "High"},
    {
        "number": 2,
        "name": "beta",
        "column": "Up Next",
        "priority": "Medium",
        # The KanbanFlow provider emulates native edges with this label prefix.
        "labels": ["blocked-by:1"],
    },
]

_HEALTHY_BUDGET = {"resources": {"graphql": {"remaining": 4900, "limit": 5000, "reset": 0}}}


def _run_kf_depgraph(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    argv: list[str] | None = None,
) -> tuple[int, str, list[list[str]]]:
    write_minimal_kanbanflow_board(tmp_path)
    monkeypatch.setenv("JARED_NO_CACHE", "1")
    dep = import_dep()  # before patching; see conftest's dual-import docstring
    patch_kf_board_provider(monkeypatch, tmp_path, KF_TASKS)
    calls = patch_gh_by_arg(
        monkeypatch,
        {"api rate_limit": json.dumps(_HEALTHY_BUDGET)},
        default="{}",
    )
    rc, out = run_script_main(
        dep,
        argv or ["dependency-graph.py"],
        tmp_path,
        monkeypatch,
        capsys,
        include_stderr=True,
    )
    return rc, out, calls


def test_dependency_graph_runs_without_repo_on_kanbanflow(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """--repo was `required=True`; on this backend there may be no repo."""
    rc, out, _ = _run_kf_depgraph(tmp_path, capsys, monkeypatch)

    assert rc == 0
    assert "Could not resolve to a Repository" not in out


def test_dependency_graph_reads_edges_from_the_provider(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The emulated blocked-by label must become a real graph edge."""
    _, out, _ = _run_kf_depgraph(tmp_path, capsys, monkeypatch)

    assert "#2" in out
    assert "#1" in out


def test_dependency_graph_does_not_call_gh_issue_list_on_kanbanflow(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Pin the data source, not just the output.

    An empty graph would satisfy an output-only assertion for entirely the
    wrong reason, so assert the GitHub call is never made.
    """
    _, _, calls = _run_kf_depgraph(tmp_path, capsys, monkeypatch)

    joined = [" ".join(c) for c in calls]
    assert not any("issue list" in c for c in joined), joined


def test_dependency_graph_notes_that_edges_are_emulated(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """NATIVE_DEPENDENCIES is absent here, so the reader must be told the
    edges are label-emulated rather than native."""
    _, out, _ = _run_kf_depgraph(tmp_path, capsys, monkeypatch)

    assert "degraded:" in out


def test_priority_check_is_not_disabled_on_kanbanflow(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Priority is available on this backend, so the check must run.

    Two things broke it: the guard compared board.repo against `--repo`, which
    is now None here, and the fetch called Board.open_items(), a github-only
    method that raises BackendMismatch since Phase 2. Both are backend
    artefacts, not real absences — BoardItem carries priority on every backend.
    """
    _, out, _ = _run_kf_depgraph(tmp_path, capsys, monkeypatch)

    assert "priority check disabled" not in out
    assert "!= --repo None" not in out
