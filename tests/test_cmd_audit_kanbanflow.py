"""`jared audit fetch` on a KanbanFlow-backed board (#402).

fetch_audit_window sourced its working set from `gh issue list --repo <Repo:>`
and never consulted board.provider, so on a KanbanFlow-backed project every
window flag returned `"items": []` and /jared-audit had nothing to audit. The
VELOCITY_TIMESTAMPS gate in the same function only chose the sort order; it
never changed the data source.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from skills.jared.scripts.lib.board import Board, fetch_audit_window
from tests.conftest import (
    KfTaskSpec,
    patch_kf_board_provider,
    write_minimal_kanbanflow_board,
)

KF_TASKS: list[KfTaskSpec] = [
    {"number": 3, "name": "gamma", "column": "Backlog", "priority": "Low"},
    {"number": 1, "name": "alpha", "column": "Backlog", "priority": "High"},
    {
        "number": 2,
        "name": "beta",
        "column": "Up Next",
        "priority": "Medium",
        "labels": ["blocked-by:1"],
        "description": "a body",
    },
]


def _kf_board(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Board:
    board = Board.from_path(write_minimal_kanbanflow_board(tmp_path))
    patch_kf_board_provider(monkeypatch, tmp_path, KF_TASKS)
    return board


def test_audit_fetch_returns_items_on_kanbanflow(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """#402's headline symptom: every window flag returned an empty list."""
    board = _kf_board(tmp_path, monkeypatch)

    result = fetch_audit_window(board, count=5, entity_type="issues")

    assert result["items"], "KanbanFlow returned an empty working set"
    assert len(result["items"]) <= 5
    first = result["items"][0]
    assert {"number", "title", "body", "labels", "open_dependents"} <= set(first)


def test_audit_fetch_does_not_call_gh_for_issues_on_kanbanflow(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """#402's own stated acceptance criterion: pin the data source."""
    import skills.jared.scripts.lib.board as skill_board

    board = _kf_board(tmp_path, monkeypatch)
    calls: list[list[str]] = []

    def _record(args: list[str], **kw: object) -> list[object]:
        calls.append(args)
        return []

    monkeypatch.setattr(skill_board, "run_gh", _record)

    fetch_audit_window(board, count=5, entity_type="issues")

    assert not any(c[:2] == ["issue", "list"] for c in calls), calls


def test_audit_fetch_orders_deterministically_without_timestamps(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The documented fallback is all open items in a stable order.

    Without creation timestamps there is nothing to sort by, so `--count N`
    would otherwise return a different N on every call.
    """
    board = _kf_board(tmp_path, monkeypatch)

    result = fetch_audit_window(board, count=10, entity_type="issues")

    numbers = [i["number"] for i in result["items"]]
    assert numbers == sorted(numbers)


def test_audit_fetch_honours_explicit_issue_numbers_on_kanbanflow(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """--issues N,M must work on this backend."""
    board = _kf_board(tmp_path, monkeypatch)

    result = fetch_audit_window(board, issues=[1, 3], entity_type="issues")

    assert sorted(i["number"] for i in result["items"]) == [1, 3]


def test_audit_fetch_age_mode_falls_back_to_all_items_on_kanbanflow(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With no window flag, age filtering is impossible without createdAt.

    The documented fallback is all open items — not an empty list, and not a
    KeyError from indexing a createdAt that does not exist.
    """
    board = _kf_board(tmp_path, monkeypatch)

    result = fetch_audit_window(board, entity_type="issues")

    assert len(result["items"]) == len(KF_TASKS)


def test_audit_fetch_surfaces_open_dependents_on_kanbanflow(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """open_dependents is the inverted blocked-by edge. #2 is blocked by #1,
    so #1 has #2 as a dependent."""
    board = _kf_board(tmp_path, monkeypatch)

    result = fetch_audit_window(board, count=10, entity_type="issues")
    by_number = {i["number"]: i for i in result["items"]}

    assert by_number[1]["open_dependents"] == [2]
    assert by_number[2]["open_dependents"] == []
