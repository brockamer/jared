"""The backend-neutral row adapter (#386/#388/#389/#402).

`sweep.py`, `stage.py`, `dependency-graph.py` and `jared audit fetch` all read
board rows as dicts. Historically each built those dicts from a GitHub call,
which is why all four broke on a KanbanFlow board. `neutral_items` maps the
provider's neutral `BoardItem` to the dict shape those checks already read, so
the checks stay untouched and only their source changes.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from skills.jared.scripts.lib.board import Board
from skills.jared.scripts.lib.board_provider import BoardItem
from skills.jared.scripts.lib.neutral_items import (
    board_item_to_issue,
    board_item_to_row,
    neutral_issue_rows,
    neutral_open_rows,
)
from tests.conftest import patch_gh, write_minimal_board


def test_row_shape_matches_what_the_checks_read() -> None:
    item = BoardItem(
        number=7,
        title="a title",
        status="Up Next",
        priority="High",
        labels=["bug"],
        milestone="M1",
        blocked_by=[3],
    )

    row = board_item_to_row(item)

    assert row["status"] == "Up Next"
    assert row["priority"] == "High"
    assert row["content"]["number"] == 7
    assert row["content"]["title"] == "a title"
    assert row["labels"] == ["bug"]
    assert row["milestone"] == "M1"
    assert row["blocked_by"] == [3]


def test_none_status_and_priority_survive_as_none() -> None:
    """The metadata-completeness check distinguishes a missing value from a
    set one, so coercing to "" or the string "None" would silently pass a
    defective item."""
    row = board_item_to_row(BoardItem(number=1, title="t", status=None, priority=None))

    assert row["status"] is None
    assert row["priority"] is None


def test_custom_fields_are_merged_at_top_level() -> None:
    """sweep's `field(item, *keys)` helper reads custom single-selects off the
    top level of the row, lowercased — the same casing BoardItem.fields uses."""
    item = BoardItem(
        number=1,
        title="t",
        status="Backlog",
        priority="Low",
        fields={"work stream": "infra"},
    )

    row = board_item_to_row(item)

    assert row["work stream"] == "infra"


def test_a_custom_field_cannot_shadow_a_core_key() -> None:
    """A board with a custom field literally named "status" must not be able
    to overwrite the real Status column in the row."""
    item = BoardItem(
        number=1,
        title="t",
        status="Backlog",
        priority="Low",
        fields={"status": "BOGUS"},
    )

    row = board_item_to_row(item)

    assert row["status"] == "Backlog"


def test_rows_are_independent_of_the_source_item() -> None:
    """Mutating a row's list must not reach back into the BoardItem — the
    checks sort and filter these in place."""
    item = BoardItem(number=1, title="t", status="Backlog", priority="Low", labels=["a"])

    row = board_item_to_row(item)
    row["labels"].append("b")

    assert item.labels == ["a"]


# --- instrument validation: the mapper vs the real pipeline ----------------

_OPEN_ITEMS_RESPONSE = {
    "data": {
        "repository": {
            "issues": {
                "pageInfo": {"hasNextPage": False},
                "nodes": [
                    {
                        "number": 11,
                        "title": "real issue",
                        "state": "OPEN",
                        "labels": {"nodes": [{"name": "bug"}]},
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
                                                "name": "High",
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


def test_neutral_rows_from_the_real_github_provider_have_check_shape(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Validate the instrument on the backend whose output is pinned.

    The tests above prove the mapper against a hand-built BoardItem. This
    proves the pipeline: real GitHubProjectsProvider -> real list_open_items
    -> board_item_to_row -> the shape the checks read. A mapper that is
    correct in isolation and wrong end-to-end would pass every test above.
    """
    board = Board.from_path(write_minimal_board(tmp_path))
    patch_gh(monkeypatch, json.dumps(_OPEN_ITEMS_RESPONSE))

    rows = neutral_open_rows(board)

    assert len(rows) == 1
    row = rows[0]
    assert row["content"]["number"] == 11
    assert row["content"]["title"] == "real issue"
    assert row["status"] == "Up Next"
    assert row["priority"] == "High"
    assert row["labels"] == ["bug"]


# --- the flat issue-row projection (dependency-graph, audit fetch) ---------


def test_issue_row_shape_matches_gh_issue_list() -> None:
    """`gh issue list --json number,title,body,labels,state` is the shape
    dependency-graph and `jared audit fetch` read. Labels arrive as dicts with
    a `name` key, not bare strings — code downstream indexes ["name"]."""
    item = BoardItem(
        number=5,
        title="t",
        status="Backlog",
        priority="High",
        body="a body",
        labels=["bug", "epic"],
    )

    row = board_item_to_issue(item)

    assert row["number"] == 5
    assert row["title"] == "t"
    assert row["body"] == "a body"
    assert row["labels"] == [{"name": "bug"}, {"name": "epic"}]
    assert row["state"] == "OPEN"


def test_neutral_issue_rows_come_from_the_provider(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    board = Board.from_path(write_minimal_board(tmp_path))
    patch_gh(monkeypatch, json.dumps(_OPEN_ITEMS_RESPONSE))

    rows = neutral_issue_rows(board)

    assert [r["number"] for r in rows] == [11]
    assert rows[0]["labels"] == [{"name": "bug"}]
