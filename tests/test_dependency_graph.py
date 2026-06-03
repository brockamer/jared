"""Tests for dependency-graph.py — #299 field-sourced Priority.

`dependency-graph.py` used to read priority from `priority:` labels, which
jared doctrine strips, so `find_priority_inversions` could never fire on a
doctrine-following board. #299 re-sources Priority from the project field
(via `Board.open_items()`). These tests pin that behavior and its
graceful-degradation paths.

Board is injected into `fetch_field_priorities` so the test passes its own
`Board` instance — sidestepping the dual-import-path gotcha (see the docstring
atop conftest.py) entirely via duck typing.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from skills.jared.scripts.lib.board import Board
from tests.conftest import import_dep, patch_gh_multi, write_minimal_board


def _board_with_open_items(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    statuses: dict[int, tuple[str, str]],
    labels_by_number: dict[int, list[str]] | None = None,
) -> Board:
    """Build a Board from a minimal tmp doc (project 7) with open_items() faked.

    `statuses` maps issue number -> (Status, Priority); patch_gh_multi feeds
    those through the real `Board.open_items()` GraphQL parse.
    """
    write_minimal_board(tmp_path)
    open_issues = [{"number": n, "title": f"issue {n}"} for n in statuses]
    patch_gh_multi(
        monkeypatch,
        open_issues=open_issues,
        statuses=statuses,
        labels_by_number=labels_by_number or {},
    )
    return Board.from_path(tmp_path / "docs" / "project-board.md")


def test_fetch_field_priorities_reads_project_field_not_labels(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # #1 carries a *misleading* priority:low label but a High Priority field;
    # the field must win and the label must be ignored.
    board = _board_with_open_items(
        monkeypatch,
        tmp_path,
        statuses={1: ("Up Next", "High"), 2: ("Backlog", "Low")},
        labels_by_number={1: ["priority:low"]},
    )
    dep = import_dep()

    priorities = dep.fetch_field_priorities("brockamer/findajob", board=board)

    assert priorities == {1: "High", 2: "Low"}


def test_priority_inversion_fires_on_doctrine_board(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # AC#1: with field-sourced Priority, a High issue depending on a Low one
    # is a real inversion the check can finally flag.
    board = _board_with_open_items(
        monkeypatch,
        tmp_path,
        statuses={1: ("Up Next", "High"), 2: ("Backlog", "Low")},
    )
    dep = import_dep()

    priorities = dep.fetch_field_priorities("brockamer/findajob", board=board)
    inversions = dep.find_priority_inversions({1: {2}}, priorities)

    assert inversions == [(1, 2)]


def test_fetch_field_priorities_degrades_on_repo_mismatch(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Board doc repo (brockamer/findajob) != --repo: a silent join on
    # mismatched numbers would manufacture phantom inversions, so degrade to {}.
    board = _board_with_open_items(monkeypatch, tmp_path, statuses={1: ("Up Next", "High")})
    dep = import_dep()

    priorities = dep.fetch_field_priorities("brockamer/other-repo", board=board)

    assert priorities == {}
    assert capsys.readouterr().err  # warned, didn't silently no-op


def test_fetch_field_priorities_degrades_on_missing_board_config(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # No board doc (board=None path): Board.from_default() raises
    # BoardConfigError; the priority check disables rather than crashing the
    # whole graph analysis.
    dep = import_dep()

    class _NoBoard:
        @classmethod
        def from_default(cls, project_root: object = None) -> object:
            raise dep.BoardConfigError("no board doc")

    monkeypatch.setattr(dep, "Board", _NoBoard)

    priorities = dep.fetch_field_priorities("brockamer/jared")

    assert priorities == {}
    assert capsys.readouterr().err
