"""Tests for Board.fetch_open_issues_for_ties()."""

from pathlib import Path
from typing import Any
from unittest.mock import patch

from skills.jared.scripts.lib.board import Board
from skills.jared.scripts.lib.ties import OpenIssueForTies


def _board(tmp_path: Path) -> Board:
    doc = tmp_path / "project-board.md"
    doc.write_text(
        "# X\n\n"
        "- Project URL: https://github.com/users/x/projects/1\n"
        "- Project number: 1\n"
        "- Project ID: PVT_x\n"
        "- Owner: x\n"
        "- Repo: x/y\n\n"
        "### Status\n- Field ID: F1\n- Backlog: A\n- Up Next: B\n"
        "- In Progress: C\n- Blocked: D\n- Done: E\n\n"
        "### Priority\n- Field ID: F2\n- High: H\n- Medium: M\n- Low: L\n"
    )
    return Board.from_path(doc)


_GRAPHQL_RESPONSE_FULL: dict[str, Any] = {
    "data": {
        "repository": {
            "issues": {
                "nodes": [
                    {
                        "number": 10,
                        "title": "Issue 10",
                        "body": "Mentions #20",
                        "labels": {"nodes": [{"name": "perf"}, {"name": "enhancement"}]},
                        "milestone": {"title": "Phase 2 — perf settled"},
                        "projectItems": {
                            "nodes": [
                                {
                                    "fieldValueByName": {"name": "Backlog"},
                                    "priority": {"name": "Medium"},
                                }
                            ]
                        },
                        "trackedInIssues": {"nodes": []},
                    },
                    {
                        "number": 20,
                        "title": "Issue 20",
                        "body": "follow-up",
                        "labels": {"nodes": []},
                        "milestone": None,
                        "projectItems": {
                            "nodes": [
                                {
                                    "fieldValueByName": {"name": "Backlog"},
                                    "priority": {"name": "Low"},
                                }
                            ]
                        },
                        "trackedInIssues": {"nodes": [{"number": 10}]},
                    },
                ],
                "pageInfo": {"hasNextPage": False, "endCursor": None},
            }
        }
    }
}


def test_fetch_returns_typed_records(tmp_path: Path) -> None:
    board = _board(tmp_path)

    with patch.object(
        Board,
        "run_graphql",
        lambda self, query, **kw: _GRAPHQL_RESPONSE_FULL,
    ):
        results = board.fetch_open_issues_for_ties()

    assert len(results) == 2
    assert all(isinstance(r, OpenIssueForTies) for r in results)
    by_n = {r.number: r for r in results}
    assert by_n[10].title == "Issue 10"
    assert by_n[10].body == "Mentions #20"
    assert "perf" in by_n[10].labels
    assert by_n[10].milestone == "Phase 2 — perf settled"
    assert by_n[20].blocked_by == (10,)


def test_fetch_partial_mode_omits_body(tmp_path: Path) -> None:
    board = _board(tmp_path)
    response_no_body = {
        "data": {
            "repository": {
                "issues": {
                    "nodes": [
                        {
                            "number": 10,
                            "title": "Issue 10",
                            "labels": {"nodes": []},
                            "milestone": None,
                            "projectItems": {
                                "nodes": [
                                    {
                                        "fieldValueByName": {"name": "Backlog"},
                                        "priority": {"name": "Medium"},
                                    }
                                ]
                            },
                            "trackedInIssues": {"nodes": []},
                        }
                    ],
                    "pageInfo": {"hasNextPage": False, "endCursor": None},
                }
            }
        }
    }
    captured_queries: list[str] = []

    def fake_run_graphql(self: Board, query: str, **kw: Any) -> Any:
        captured_queries.append(query)
        return response_no_body

    with patch.object(Board, "run_graphql", fake_run_graphql):
        results = board.fetch_open_issues_for_ties(include_bodies=False)

    assert len(results) == 1
    assert results[0].body == ""
    # Verify the body field was NOT in the query.
    assert "body" not in captured_queries[0]


def test_fetch_uses_5m_cache(tmp_path: Path) -> None:
    board = _board(tmp_path)
    captured_cache: list[str | None] = []

    def fake_run_graphql(self: Board, query: str, *, cache: str | None = None, **kw: Any) -> Any:
        captured_cache.append(cache)
        return {
            "data": {
                "repository": {
                    "issues": {
                        "nodes": [],
                        "pageInfo": {"hasNextPage": False, "endCursor": None},
                    }
                }
            }
        }

    with patch.object(Board, "run_graphql", fake_run_graphql):
        board.fetch_open_issues_for_ties()

    assert captured_cache == ["5m"]
