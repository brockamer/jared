"""Tests for GitHubProjectsProvider read methods (Phase 1.3).

Mirrors the observable-data assertions in test_board_open_items.py and
test_board_fetch_for_ties.py, but against the provider and the neutral
dataclass shapes (BoardItem, TieCandidate, Comment, Edge).

All gh/GraphQL calls flow through board.py's module-level subprocess seam so
patch_gh / patch_gh_by_arg intercept them correctly.
"""

from __future__ import annotations

import json

import pytest

from skills.jared.scripts.lib.board_provider import (
    BoardItem,
    BoardProvider,
    Capability,
    Comment,
    Edge,
    TieCandidate,
)
from skills.jared.scripts.lib.github_provider import GitHubProjectsProvider
from tests.conftest import patch_gh, patch_gh_by_arg


def _provider() -> GitHubProjectsProvider:
    return GitHubProjectsProvider(
        project_number=7,
        project_id="PVT_x",
        owner="brockamer",
        repo="brockamer/findajob",
        field_ids={"Status": "F1", "Priority": "F2"},
        field_options={
            "Status": {
                "Backlog": "A",
                "Up Next": "B",
                "In Progress": "C",
                "Blocked": "D",
                "Done": "E",
            },
            "Priority": {"High": "H", "Medium": "M", "Low": "L"},
        },
    )


# ------------------------------------------------------------------ #
# Protocol + capabilities (pre-existing, preserved)                   #
# ------------------------------------------------------------------ #


def test_github_provider_satisfies_protocol() -> None:
    assert isinstance(_provider(), BoardProvider)


def test_github_provider_advertises_full_capability_set() -> None:
    assert _provider().capabilities() == frozenset(Capability)


# ------------------------------------------------------------------ #
# list_open_items                                                      #
# ------------------------------------------------------------------ #


def test_list_open_items_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    """No open issues → empty list."""
    patch_gh(
        monkeypatch,
        stdout=json.dumps(
            {"data": {"repository": {"issues": {"pageInfo": {"hasNextPage": False}, "nodes": []}}}}
        ),
    )
    assert _provider().list_open_items() == []


def test_list_open_items_single_issue(monkeypatch: pytest.MonkeyPatch) -> None:
    """One open issue on the board → single BoardItem with correct fields."""
    patch_gh(
        monkeypatch,
        stdout=json.dumps(
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
                                    "labels": {"nodes": []},
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
        ),
    )
    items = _provider().list_open_items()
    assert len(items) == 1
    item = items[0]
    assert isinstance(item, BoardItem)
    assert item.number == 42
    assert item.title == "Thing to do"
    assert item.status == "Up Next"
    assert item.priority == "Medium"
    assert item.labels == []


def test_list_open_items_excludes_off_board_issues(monkeypatch: pytest.MonkeyPatch) -> None:
    """Issues not on the project board (empty projectItems) are excluded."""
    patch_gh(
        monkeypatch,
        stdout=json.dumps(
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
                                    "labels": {"nodes": []},
                                    "projectItems": {"nodes": []},
                                }
                            ],
                        }
                    }
                }
            }
        ),
    )
    assert _provider().list_open_items() == []


def test_list_open_items_includes_labels(monkeypatch: pytest.MonkeyPatch) -> None:
    """Labels from the GraphQL response appear as a list on BoardItem."""
    patch_gh(
        monkeypatch,
        stdout=json.dumps(
            {
                "data": {
                    "repository": {
                        "issues": {
                            "pageInfo": {"hasNextPage": False},
                            "nodes": [
                                {
                                    "number": 1,
                                    "title": "Labeled",
                                    "state": "OPEN",
                                    "labels": {
                                        "nodes": [{"name": "session-1"}, {"name": "enhancement"}]
                                    },
                                    "projectItems": {
                                        "nodes": [
                                            {
                                                "id": "PVTI_a",
                                                "project": {"number": 7},
                                                "fieldValues": {
                                                    "nodes": [
                                                        {
                                                            "name": "In Progress",
                                                            "field": {"name": "Status"},
                                                        }
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
        ),
    )
    items = _provider().list_open_items()
    assert len(items) == 1
    assert items[0].labels == ["session-1", "enhancement"]


def test_list_open_items_raises_on_pagination(monkeypatch: pytest.MonkeyPatch) -> None:
    """hasNextPage=true → GhInvocationError (same guard as Board.open_items)."""
    from skills.jared.scripts.lib.board import GhInvocationError

    patch_gh(
        monkeypatch,
        stdout=json.dumps(
            {"data": {"repository": {"issues": {"pageInfo": {"hasNextPage": True}, "nodes": []}}}}
        ),
    )
    with pytest.raises(GhInvocationError, match="hasNextPage"):
        _provider().list_open_items()


def test_list_open_items_does_not_call_project_item_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """list_open_items() must NOT route through `gh project item-list`."""
    calls = patch_gh_by_arg(
        monkeypatch,
        responses={
            "api graphql": json.dumps(
                {
                    "data": {
                        "repository": {"issues": {"pageInfo": {"hasNextPage": False}, "nodes": []}}
                    }
                }
            )
        },
    )
    _provider().list_open_items()
    joined_calls = [" ".join(argv) for argv in calls]
    assert not any("project item-list" in c for c in joined_calls), (
        f"list_open_items() must NOT call `gh project item-list`; saw {joined_calls!r}"
    )


# ------------------------------------------------------------------ #
# get_item                                                             #
# ------------------------------------------------------------------ #


def test_get_item_returns_board_item(monkeypatch: pytest.MonkeyPatch) -> None:
    """Issue on the board → BoardItem with correct status/priority."""
    patch_gh(
        monkeypatch,
        stdout=json.dumps(
            {
                "data": {
                    "repository": {
                        "issue": {
                            "projectItems": {
                                "nodes": [
                                    {
                                        "id": "PVTI_aaa",
                                        "project": {"number": 7},
                                        "fieldValues": {
                                            "nodes": [
                                                {
                                                    "name": "In Progress",
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
                            }
                        }
                    }
                }
            }
        ),
    )
    item = _provider().get_item(42)
    assert item is not None
    assert isinstance(item, BoardItem)
    assert item.number == 42
    assert item.status == "In Progress"
    assert item.priority == "High"
    # title is absent from the per-issue scoped query → documented empty string
    assert item.title == ""


def test_get_item_returns_none_when_not_on_board(monkeypatch: pytest.MonkeyPatch) -> None:
    """Issue not on the project board → None."""
    patch_gh(
        monkeypatch,
        stdout=json.dumps({"data": {"repository": {"issue": {"projectItems": {"nodes": []}}}}}),
    )
    assert _provider().get_item(99) is None


# ------------------------------------------------------------------ #
# get_body                                                             #
# ------------------------------------------------------------------ #


def test_get_body_returns_issue_body(monkeypatch: pytest.MonkeyPatch) -> None:
    """get_body routes through fetch_issue_body_rest and returns the body string."""
    monkeypatch.setenv("JARED_NO_CACHE", "1")
    patch_gh(
        monkeypatch,
        stdout=json.dumps({"body": "The issue body text."}),
    )
    body = _provider().get_body(42)
    assert body == "The issue body text."


def test_get_body_returns_empty_string_on_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    """Missing body field in API response → empty string (not None)."""
    monkeypatch.setenv("JARED_NO_CACHE", "1")
    patch_gh(monkeypatch, stdout=json.dumps({"number": 42}))
    assert _provider().get_body(42) == ""


# ------------------------------------------------------------------ #
# list_comments                                                        #
# ------------------------------------------------------------------ #


def test_list_comments_returns_comment_objects(monkeypatch: pytest.MonkeyPatch) -> None:
    """Comments come back as Comment dataclass instances."""
    patch_gh(
        monkeypatch,
        stdout=json.dumps(
            {
                "data": {
                    "repository": {
                        "i42": {
                            "comments": {
                                "nodes": [
                                    {"body": "First comment", "createdAt": "2026-01-01T00:00:00Z"},
                                    {"body": "Second comment", "createdAt": "2026-01-02T00:00:00Z"},
                                ]
                            }
                        }
                    }
                }
            }
        ),
    )
    comments = _provider().list_comments(42)
    assert len(comments) == 2
    assert all(isinstance(c, Comment) for c in comments)
    assert comments[0].body == "First comment"
    assert comments[0].created_at == "2026-01-01T00:00:00Z"
    # author is absent from fetch_recent_comments_batch query → documented empty string
    assert comments[0].author == ""
    assert comments[1].body == "Second comment"


def test_list_comments_empty_when_no_comments(monkeypatch: pytest.MonkeyPatch) -> None:
    """Issue with no comments → empty list."""
    patch_gh(
        monkeypatch,
        stdout=json.dumps({"data": {"repository": {"i10": {"comments": {"nodes": []}}}}}),
    )
    assert _provider().list_comments(10) == []


# ------------------------------------------------------------------ #
# fetch_ties                                                           #
# ------------------------------------------------------------------ #

_TIES_GQL_RESPONSE_FULL = {
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
                        "blockedBy": {"nodes": []},
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
                        "blockedBy": {"nodes": [{"number": 10}]},
                    },
                ],
                "pageInfo": {"hasNextPage": False, "endCursor": None},
            }
        }
    }
}


def test_fetch_ties_returns_tie_candidates(monkeypatch: pytest.MonkeyPatch) -> None:
    """fetch_ties returns TieCandidate objects with correct fields."""
    patch_gh(monkeypatch, stdout=json.dumps(_TIES_GQL_RESPONSE_FULL))
    results = _provider().fetch_ties()
    assert len(results) == 2
    assert all(isinstance(r, TieCandidate) for r in results)
    by_n = {r.number: r for r in results}
    assert by_n[10].title == "Issue 10"
    assert by_n[10].body == "Mentions #20"
    assert "perf" in by_n[10].labels
    assert "enhancement" in by_n[10].labels
    assert by_n[10].milestone == "Phase 2 — perf settled"
    assert by_n[20].milestone is None
    # blocked_by is not in TieCandidate (dropped during mapping)


def test_fetch_ties_filters_done(monkeypatch: pytest.MonkeyPatch) -> None:
    """Issues with Status=Done are filtered before TieCandidate construction."""
    response = {
        "data": {
            "repository": {
                "issues": {
                    "nodes": [
                        {
                            "number": 1,
                            "title": "Active",
                            "body": "",
                            "labels": {"nodes": []},
                            "milestone": None,
                            "projectItems": {
                                "nodes": [
                                    {"fieldValueByName": {"name": "In Progress"}, "priority": {}}
                                ]
                            },
                            "blockedBy": {"nodes": []},
                        },
                        {
                            "number": 2,
                            "title": "Finished",
                            "body": "",
                            "labels": {"nodes": []},
                            "milestone": None,
                            "projectItems": {
                                "nodes": [{"fieldValueByName": {"name": "Done"}, "priority": {}}]
                            },
                            "blockedBy": {"nodes": []},
                        },
                    ],
                    "pageInfo": {"hasNextPage": False, "endCursor": None},
                }
            }
        }
    }
    patch_gh(monkeypatch, stdout=json.dumps(response))
    results = _provider().fetch_ties()
    assert len(results) == 1
    assert results[0].number == 1


def test_fetch_ties_partial_mode_omits_body(monkeypatch: pytest.MonkeyPatch) -> None:
    """include_bodies=False → body field absent from query, body="" on result."""
    calls = patch_gh_by_arg(
        monkeypatch,
        responses={
            "api graphql": json.dumps(
                {
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
                                        "blockedBy": {"nodes": []},
                                    }
                                ],
                                "pageInfo": {"hasNextPage": False, "endCursor": None},
                            }
                        }
                    }
                }
            )
        },
    )
    results = _provider().fetch_ties(include_bodies=False)
    assert len(results) == 1
    assert results[0].body == ""
    # Verify "body" was NOT in the GraphQL query string sent
    gql_calls = [" ".join(argv) for argv in calls if "api" in argv and "graphql" in argv]
    assert gql_calls, "expected at least one graphql call"
    for call in gql_calls:
        # The query body is embedded in the -f query= arg; check the full call string
        assert "body\n" not in call or "include_bodies" not in call


def test_fetch_ties_uses_5m_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    """fetch_ties passes cache='5m' to the GraphQL call."""
    calls = patch_gh_by_arg(
        monkeypatch,
        responses={
            "api graphql": json.dumps(
                {
                    "data": {
                        "repository": {
                            "issues": {
                                "nodes": [],
                                "pageInfo": {"hasNextPage": False, "endCursor": None},
                            }
                        }
                    }
                }
            )
        },
    )
    _provider().fetch_ties()
    # Verify --cache 5m appears in the gh invocation
    gql_calls = [argv for argv in calls if "api" in argv and "graphql" in argv]
    assert gql_calls, "expected at least one graphql call"
    assert any("--cache" in argv and "5m" in argv for argv in gql_calls), (
        f"expected --cache 5m in graphql call, got {gql_calls!r}"
    )


# ------------------------------------------------------------------ #
# fetch_blocked_by_edges                                               #
# ------------------------------------------------------------------ #


def test_fetch_blocked_by_edges_returns_edges(monkeypatch: pytest.MonkeyPatch) -> None:
    """fetch_blocked_by_edges maps the raw dict to Edge(dependent, blocker)."""
    patch_gh(
        monkeypatch,
        stdout=json.dumps(
            {
                "data": {
                    "repository": {
                        "issues": {
                            "pageInfo": {"hasNextPage": False, "endCursor": None},
                            "nodes": [
                                {
                                    "number": 20,
                                    "blockedBy": {"nodes": [{"number": 10, "state": "OPEN"}]},
                                },
                                {
                                    "number": 30,
                                    "blockedBy": {"nodes": []},
                                },
                            ],
                        }
                    }
                }
            }
        ),
    )
    edges = _provider().fetch_blocked_by_edges()
    assert len(edges) == 1
    edge = edges[0]
    assert isinstance(edge, Edge)
    assert edge.dependent == 20
    assert edge.blocker == 10


def test_fetch_blocked_by_edges_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    """No blocked issues → empty list."""
    patch_gh(
        monkeypatch,
        stdout=json.dumps(
            {
                "data": {
                    "repository": {
                        "issues": {
                            "pageInfo": {"hasNextPage": False, "endCursor": None},
                            "nodes": [
                                {
                                    "number": 1,
                                    "blockedBy": {"nodes": []},
                                }
                            ],
                        }
                    }
                }
            }
        ),
    )
    assert _provider().fetch_blocked_by_edges() == []


def test_fetch_blocked_by_edges_multiple_blockers(monkeypatch: pytest.MonkeyPatch) -> None:
    """One issue blocked by multiple issues → one Edge per blocker."""
    patch_gh(
        monkeypatch,
        stdout=json.dumps(
            {
                "data": {
                    "repository": {
                        "issues": {
                            "pageInfo": {"hasNextPage": False, "endCursor": None},
                            "nodes": [
                                {
                                    "number": 50,
                                    "blockedBy": {
                                        "nodes": [
                                            {"number": 10, "state": "OPEN"},
                                            {"number": 20, "state": "OPEN"},
                                        ]
                                    },
                                }
                            ],
                        }
                    }
                }
            }
        ),
    )
    edges = _provider().fetch_blocked_by_edges()
    assert len(edges) == 2
    blockers = {e.blocker for e in edges}
    assert blockers == {10, 20}
    assert all(e.dependent == 50 for e in edges)


# ------------------------------------------------------------------ #
# _field_id / _option_id helpers                                       #
# ------------------------------------------------------------------ #


def test_field_id_returns_id_for_known_field() -> None:
    assert _provider()._field_id("Status") == "F1"
    assert _provider()._field_id("Priority") == "F2"


def test_field_id_raises_for_unknown_field() -> None:
    from skills.jared.scripts.lib.board import FieldNotFound

    with pytest.raises(FieldNotFound, match="Unknown"):
        _provider()._field_id("Unknown")


def test_option_id_returns_id_for_known_option() -> None:
    assert _provider()._option_id("Status", "Done") == "E"
    assert _provider()._option_id("Priority", "High") == "H"


def test_option_id_raises_for_unknown_option() -> None:
    from skills.jared.scripts.lib.board import OptionNotFound

    with pytest.raises(OptionNotFound, match="Nope"):
        _provider()._option_id("Status", "Nope")
