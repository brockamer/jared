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
    """Smallest happy path: no open issues → empty list."""
    from skills.jared.scripts.lib.board import Board

    board_md = write_minimal_board(tmp_path)
    board = Board.from_path(board_md)

    patch_gh(
        monkeypatch,
        stdout=json.dumps(
            {"data": {"repository": {"issues": {"pageInfo": {"hasNextPage": False}, "nodes": []}}}}
        ),
    )

    assert board.open_items() == []


def test_open_items_does_not_call_project_item_list(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The whole point of open_items() (#185): never route through
    `gh project item-list`, whose cost scales with total board size on
    mature boards. Implementation detail (one batched GraphQL query)
    can change; the regression target is "no item-list."
    """
    from skills.jared.scripts.lib.board import Board

    board_md = write_minimal_board(tmp_path)
    board = Board.from_path(board_md)

    calls = patch_gh_by_arg(
        monkeypatch,
        responses={
            "api graphql": json.dumps(
                {
                    "data": {
                        "repository": {
                            "issues": {
                                "pageInfo": {"hasNextPage": False},
                                "nodes": [],
                            }
                        }
                    }
                }
            ),
        },
    )

    board.open_items()

    joined_calls = [" ".join(argv) for argv in calls]
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

    board_md = write_minimal_board(tmp_path)
    board = Board.from_path(board_md)

    # The batched `repository.issues(states: OPEN)` query — one open issue
    # with one project item attached.
    batched_response = json.dumps(
        {
            "data": {
                "repository": {
                    "issues": {
                        "pageInfo": {"hasNextPage": False},
                        "nodes": [
                            {
                                "number": 42,
                                "title": "Thing to do",
                                "state": "OPEN",
                                "projectItems": {
                                    "nodes": [
                                        {
                                            "id": "PVTI_aaa",
                                            "project": {"number": 7},
                                            "fieldValues": {
                                                "nodes": [
                                                    {
                                                        "name": "Up Next",
                                                        "field": {"name": "Status"},
                                                    },
                                                    {
                                                        "name": "Medium",
                                                        "field": {"name": "Priority"},
                                                    },
                                                ]
                                            },
                                        }
                                    ]
                                },
                            }
                        ],
                    }
                }
            }
        }
    )
    patch_gh(monkeypatch, stdout=batched_response)

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
    has no projectItems node for this project; it must not appear in
    open_items() output.
    """
    from skills.jared.scripts.lib.board import Board

    board_md = write_minimal_board(tmp_path)
    board = Board.from_path(board_md)

    batched_response = json.dumps(
        {
            "data": {
                "repository": {
                    "issues": {
                        "pageInfo": {"hasNextPage": False},
                        "nodes": [
                            {
                                "number": 99,
                                "title": "Ghost issue",
                                "state": "OPEN",
                                "projectItems": {"nodes": []},
                            }
                        ],
                    }
                }
            }
        }
    )
    patch_gh(monkeypatch, stdout=batched_response)

    assert board.open_items() == []


def test_open_items_raises_when_pagination_required(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Silent-pagination guard mirrors the truncation discipline on
    `board_items()`: hasNextPage=true means >100 open issues, and
    pagination isn't implemented. Raise loudly so the caller knows the
    snapshot is incomplete.
    """
    from skills.jared.scripts.lib.board import Board, GhInvocationError

    board_md = write_minimal_board(tmp_path)
    board = Board.from_path(board_md)

    batched_response = json.dumps(
        {
            "data": {
                "repository": {
                    "issues": {
                        "pageInfo": {"hasNextPage": True},
                        "nodes": [],
                    }
                }
            }
        }
    )
    patch_gh(monkeypatch, stdout=batched_response)

    with pytest.raises(GhInvocationError, match="hasNextPage"):
        board.open_items()


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


def test_fetch_recently_closed_raises_when_limit_reached(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """CLI's _fetch_recently_closed hits `gh issue list --state closed --limit 200`.
    Same silent-truncation hazard as `board_items()`: hitting the cap
    means "more items might have been dropped" — and summary's
    stuck-closed detector silently degrades if items past the cap exist.
    """
    from tests.conftest import import_cli

    cli = import_cli()
    # The dual-import-path gotcha (CLAUDE.md): the CLI raises lib.board's
    # GhInvocationError, not skills.jared.scripts.lib.board's. Grab the
    # right class off the loaded CLI module via the Board import.
    cli_gh_invocation_error = cli.GhInvocationError

    board_md = write_minimal_board(tmp_path)
    board = cli.Board.from_path(board_md)
    payload = [
        {"number": i, "title": f"closed-{i}", "closedAt": f"2026-05-{(i % 28) + 1:02d}T10:00:00Z"}
        for i in range(200)
    ]
    patch_gh(monkeypatch, stdout=json.dumps(payload))

    with pytest.raises(cli_gh_invocation_error, match="truncat"):
        cli._fetch_recently_closed(board, days=14)


def test_summary_degrades_gracefully_on_recently_closed_truncation(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """If `_fetch_recently_closed` truncates on an exceptionally busy board
    (>200 closures in 14d), `_detect_stuck_closed_recent` must swallow
    the error and let summary render the rest. The operator sees a
    stderr notice, not a stack trace.
    """
    from tests.conftest import import_cli

    cli = import_cli()
    cli_gh_invocation_error = cli.GhInvocationError

    board_md = write_minimal_board(tmp_path)
    board = cli.Board.from_path(board_md)

    def explode(*_args: object, **_kw: object) -> object:
        raise cli_gh_invocation_error("simulated truncation at limit=200")

    monkeypatch.setattr(cli, "_fetch_recently_closed", explode)

    result = cli._detect_stuck_closed_recent(board, days=14)
    captured = capsys.readouterr()

    assert result == []
    assert "stuck-closed detection skipped" in captured.err
    assert "jared sweep" in captured.err
