"""Tests for dependency-graph.py.

Two concerns:

  #299 — field-sourced Priority. `dependency-graph.py` used to read priority
  from `priority:` labels, which jared doctrine strips, so
  `find_priority_inversions` could never fire on a doctrine-following board.
  #299 re-sources Priority from the project field (via `Board.open_items()`).
  Those tests pin that behavior and its graceful-degradation paths. Board is
  injected into `fetch_field_priorities` so the test passes its own `Board`
  instance — sidestepping the dual-import-path gotcha (see the docstring atop
  conftest.py) entirely via duck typing.

  #300 — graph-algorithm coverage. The 416-line script's topo-sort, critical
  path, orphan detection, and section-ref parsing had zero tests despite
  backing `/jared-groom` and `/jared-reshape`. The algorithm tests below
  characterize current correct behavior on small hand-built graphs; they run
  offline (orphan detection monkeypatches the one network call,
  `fetch_issue_state`).
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


# ---------------------------------------------------------------------------
# #300 — graph-algorithm coverage (topo-sort, critical path, orphan, refs)
# ---------------------------------------------------------------------------


def test_topological_sort_orders_dependencies_before_dependents() -> None:
    dep = import_dep()
    # 1 depends on 2, 2 depends on 3 → dependencies must emit first: [3, 2, 1].
    order, cycles = dep.topological_sort({1: {2}, 2: {3}})

    assert cycles == []
    assert order == [3, 2, 1]


def test_topological_sort_detects_cycle() -> None:
    dep = import_dep()
    # 1 ↔ 2: no zero-in-degree node, so nothing emits and the stuck nodes
    # surface as a cycle group.
    order, cycles = dep.topological_sort({1: {2}, 2: {1}})

    assert order == []
    assert cycles == [[1, 2]]


def test_critical_path_returns_longest_dependency_chain() -> None:
    dep = import_dep()
    # 1 → {2, 3}, 2 → 4: the longest chain is 1 → 2 → 4 (length 3), not 1 → 3.
    chain = dep.critical_path({1: {2, 3}, 2: {4}, 3: set(), 4: set()})

    assert chain == [1, 2, 4]


def test_find_orphaned_flags_dependency_on_closed_issue(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dep = import_dep()
    # #1 depends on #2; #2 is outside the open set and CLOSED → orphaned edge.
    monkeypatch.setattr(dep, "fetch_issue_state", lambda repo, n: "CLOSED")

    orphaned = dep.find_orphaned({1: {2}}, "owner/repo", {1})

    assert orphaned == [(1, 2)]


def test_find_orphaned_ignores_open_dependency(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dep = import_dep()
    # #2 is still OPEN → not an orphan.
    monkeypatch.setattr(dep, "fetch_issue_state", lambda repo, n: "OPEN")

    orphaned = dep.find_orphaned({1: {2}}, "owner/repo", {1})

    assert orphaned == []


def test_parse_section_refs_extracts_refs_under_heading() -> None:
    dep = import_dep()
    body = (
        "Summary line.\n\n"
        "## Depends on\n"
        "- #12 — the client\n"
        "- #34\n\n"
        "## Other\n"
        "- #99 should be ignored\n"
    )
    # Refs are scoped to the section: #99 under a later heading is excluded.
    assert dep.parse_section_refs(body, "Depends on") == [12, 34]


def test_parse_section_refs_returns_empty_when_section_absent() -> None:
    dep = import_dep()
    assert dep.parse_section_refs("no relevant section here, has #5", "Depends on") == []
