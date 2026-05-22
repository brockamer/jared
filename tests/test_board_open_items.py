"""Tests for Board.open_items() — open-only fetch path (#185).

Replaces the Done-inclusive `board_items()` call on hot-path consumers
(summary, next-session-prompt). The contract:

- Routes via `gh issue list --state open` + per-issue projectItems GraphQL,
  not `gh project item-list --limit N` whose cost scales with Done count.
- Returns dicts in the same shape `board_items()` returns for open items,
  so callers that filter by `status` keep working: each entry has
  `content.{number, title, state}`, plus top-level `status` and `priority`.
- Items not on the project board are excluded (issues that exist in the
  repo but were never added — distinct ghost-detection is sweep's job).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.conftest import patch_gh, patch_gh_by_arg, write_minimal_board


def test_open_items_returns_empty_list_when_no_open_issues(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Smallest happy path: no open issues → empty list, no extra GraphQL."""
    from skills.jared.scripts.lib.board import Board

    board_md = write_minimal_board(tmp_path)
    board = Board.from_path(board_md)

    patch_gh(monkeypatch, stdout="[]")

    assert board.open_items() == []


def test_open_items_calls_gh_issue_list_state_open_not_project_item_list(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The whole point of open_items() (#185): the hot path must not pay
    the cost of pulling Done items via `gh project item-list`.

    Pins the routing: at least one `gh issue list --state open` call;
    zero `gh project item-list` calls.
    """
    from skills.jared.scripts.lib.board import Board

    board_md = write_minimal_board(tmp_path)
    board = Board.from_path(board_md)

    calls = patch_gh_by_arg(monkeypatch, responses={"issue list": "[]"})

    board.open_items()

    joined_calls = [" ".join(argv) for argv in calls]
    assert any("issue list" in c and "--state open" in c for c in joined_calls), (
        f"open_items() must call `gh issue list --state open`; saw {joined_calls!r}"
    )
    assert not any("project item-list" in c for c in joined_calls), (
        f"open_items() must NOT call `gh project item-list`; saw {joined_calls!r}"
    )


def test_open_items_single_issue_shape_matches_board_items(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """For each open issue, fold its projectItems status/priority into the
    `board_items()`-shape dict callers already consume:
    `{"content": {"number", "title", "state"}, "status", "priority"}`.
    """
    from skills.jared.scripts.lib.board import Board
    from tests.conftest import graphql_item_response

    board_md = write_minimal_board(tmp_path)
    board = Board.from_path(board_md)

    patch_gh_by_arg(
        monkeypatch,
        responses={
            "issue list": json.dumps([{"number": 42, "title": "Thing to do", "state": "OPEN"}]),
            "api graphql": graphql_item_response(
                project_number=7, status="Up Next", priority="Medium"
            ),
        },
    )

    result = board.open_items()

    assert result == [
        {
            "content": {"number": 42, "title": "Thing to do", "state": "OPEN"},
            "status": "Up Next",
            "priority": "Medium",
        }
    ]


def test_open_items_excludes_issues_not_on_project_board(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """An open repo issue that was never added to the project (off-board
    ghost — distinct drift surfaced by sweep's check_off_board_issues)
    has no project item; it must not appear in open_items() output.
    """
    from skills.jared.scripts.lib.board import Board

    board_md = write_minimal_board(tmp_path)
    board = Board.from_path(board_md)

    # fetch_item_for_issue returns None when the issue has no projectItems
    # node matching this project (see graphql_item_response with no fields,
    # or an empty nodes list — emulate the empty-nodes case).
    empty_project_items = json.dumps(
        {
            "data": {
                "repository": {
                    "issue": {"projectItems": {"nodes": []}},
                }
            }
        }
    )
    patch_gh_by_arg(
        monkeypatch,
        responses={
            "issue list": json.dumps([{"number": 99, "title": "Ghost issue", "state": "OPEN"}]),
            "api graphql": empty_project_items,
        },
    )

    assert board.open_items() == []


def test_board_items_raises_when_limit_reached(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """`gh project item-list` silently truncates at --limit (#185 AC #2).
    When the result count equals the limit, we cannot distinguish "exactly
    that many items" from "more items exist but were dropped" — the safe
    move is to fail loudly so the caller knows to raise the cap (or
    paginate), rather than silently produce a wrong snapshot.
    """
    from skills.jared.scripts.lib.board import Board, GhInvocationError

    board_md = write_minimal_board(tmp_path)
    board = Board.from_path(board_md)
    monkeypatch.setenv("JARED_NO_CACHE", "1")

    items_payload = [
        {"id": f"item{i}", "content": {"number": i, "title": f"T{i}"}} for i in range(2000)
    ]
    patch_gh(monkeypatch, stdout=json.dumps({"items": items_payload}))

    with pytest.raises(GhInvocationError, match="truncat"):
        board.board_items()


def test_board_items_does_not_raise_when_below_limit(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Sanity: result count below the limit must not trip the guard.
    Common case (most boards have < 2000 items).
    """
    from skills.jared.scripts.lib.board import Board

    board_md = write_minimal_board(tmp_path)
    board = Board.from_path(board_md)
    monkeypatch.setenv("JARED_NO_CACHE", "1")

    items_payload = [
        {"id": f"item{i}", "content": {"number": i, "title": f"T{i}"}} for i in range(50)
    ]
    patch_gh(monkeypatch, stdout=json.dumps({"items": items_payload}))

    result = board.board_items()
    assert len(result) == 50
