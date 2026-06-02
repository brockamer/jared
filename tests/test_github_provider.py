"""Tests for GitHubProjectsProvider read methods (Phase 1.3).

Mirrors the observable-data assertions in test_board_open_items.py and
test_board_fetch_for_ties.py, but against the provider and the neutral
dataclass shapes (BoardItem, Comment, Edge).

All gh/GraphQL calls flow through board.py's module-level subprocess seam so
patch_gh / patch_gh_by_arg intercept them correctly.
"""

from __future__ import annotations

import json

import pytest

from skills.jared.scripts.lib.board import GhInvocationError, OptionNotFound
from skills.jared.scripts.lib.board_provider import (
    BoardItem,
    BoardProvider,
    Capability,
    Comment,
    Edge,
    Milestone,
)
from skills.jared.scripts.lib.github_provider import GitHubProjectsProvider
from tests.conftest import FakeGhResult, patch_gh, patch_gh_by_arg


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


def test_list_open_items_routes_extra_single_selects_into_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Single-select fields beyond Status/Priority land in BoardItem.fields.

    `_flatten_project_item_for_project` lowercases every single-select field
    name, so a board with a third field (e.g. Size) surfaces it; the provider's
    `_item_from_flat` routes anything past status/priority into `fields`.
    """
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
                                    "number": 7,
                                    "title": "Sized",
                                    "state": "OPEN",
                                    "labels": {"nodes": []},
                                    "projectItems": {
                                        "nodes": [
                                            {
                                                "id": "PVTI_s",
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
                                                        {
                                                            "name": "Large",
                                                            "field": {"name": "Size"},
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
    assert item.status == "Up Next"
    assert item.priority == "High"
    # Extra single-select keyed by lowercased field name; status/priority and
    # the internal `id` key are NOT leaked into fields.
    assert item.fields == {"size": "Large"}


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


def test_get_item_populates_provider_ref_with_node_id(monkeypatch: pytest.MonkeyPatch) -> None:
    """get_item populates provider_ref with the project-item node-id."""
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
                                        "fieldValues": {"nodes": []},
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
    assert item.provider_ref == "PVTI_aaa"


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


# ------------------------------------------------------------------ #
# WRITE methods (Phase 1.4)                                           #
# ------------------------------------------------------------------ #

# Shared board fixture for write tests: matches the field IDs / option IDs
# used in _provider() so assertions can be exact.
#
# field_ids:    Status → "F1",  Priority → "F2"
# field_options Status: Backlog→"A", Up Next→"B", In Progress→"C",
#                       Blocked→"D", Done→"E"
#               Priority: High→"H", Medium→"M", Low→"L"
# project_id:   "PVT_x"
# project_number: 7
# owner:        "brockamer"
# repo:         "brockamer/findajob"


def _scoped_item_response(item_id: str = "PVTI_aaa") -> str:
    """Minimal GraphQL response for the per-issue projectItems query."""
    return json.dumps(
        {
            "data": {
                "repository": {
                    "issue": {
                        "projectItems": {
                            "nodes": [
                                {
                                    "id": item_id,
                                    "project": {"number": 7},
                                    "fieldValues": {"nodes": []},
                                }
                            ]
                        }
                    }
                }
            }
        }
    )


# ------------------------------------------------------------------ #
# add_to_board                                                         #
# ------------------------------------------------------------------ #


def test_add_to_board_calls_item_add_and_graphql_mutation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """add_to_board emits item-add + one aliased updateProjectV2ItemFieldValue mutation."""
    calls = patch_gh_by_arg(
        monkeypatch,
        {
            "item-add": '{"id": "PVTI_new"}',
            "api graphql": "{}",
        },
    )
    _provider().add_to_board(42, priority="High", status="Backlog")

    assert any("item-add" in " ".join(c) for c in calls), "expected item-add call"
    graphql_calls = [c for c in calls if "api" in c and "graphql" in c]
    assert graphql_calls, "expected graphql call for field mutations"
    joined = " ".join(" ".join(c) for c in graphql_calls)
    # Priority resolved: F2 / H
    assert "F2" in joined and "H" in joined
    # Status resolved: F1 / A (Backlog)
    assert "F1" in joined and "A" in joined
    # updateProjectV2ItemFieldValue mutation present
    assert "updateProjectV2ItemFieldValue" in joined
    # No item-edit (field edits go through graphql in add_to_board path)
    assert not any("item-edit" in " ".join(c) for c in calls)


def test_add_to_board_applies_labels_via_issue_edit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Labels are applied via `gh issue edit --add-label`, not the graphql mutation."""
    calls = patch_gh_by_arg(
        monkeypatch,
        {
            "item-add": '{"id": "PVTI_new"}',
            "api graphql": "{}",
        },
    )
    _provider().add_to_board(42, priority="Low", status="Up Next", labels=["session-1"])

    label_calls = [c for c in calls if "issue" in c and "edit" in c and "--add-label" in c]
    assert label_calls, "expected gh issue edit --add-label call"
    assert any("session-1" in " ".join(c) for c in label_calls)


def test_add_to_board_find_existing_item_when_not_assume_new(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When the issue is already on the board, item-add must be skipped (uses find_item_id)."""
    calls = patch_gh_by_arg(
        monkeypatch,
        {
            "api graphql": _scoped_item_response("PVTI_existing"),
            "item-edit": "{}",
        },
    )
    _provider().add_to_board(42, priority="Medium", status="Backlog")

    assert not any("item-add" in " ".join(c) for c in calls), (
        "item-add must not fire when issue is already on the board"
    )
    # The graphql mutation for field-setting still fires
    graphql_calls = [c for c in calls if "api" in c and "graphql" in c]
    assert graphql_calls


def test_add_to_board_extra_fields_emit_aliased_setextra_mutation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Extra single-select fields are appended as setExtra<i> aliases in the mutation.

    Pins the `setExtra{i}` enumeration in `_add_existing`'s aliased-mutation
    builder: the first extra field resolves to its field-id/option-id and rides
    the same single GraphQL round-trip as Priority/Status.
    """
    provider = GitHubProjectsProvider(
        project_number=7,
        project_id="PVT_x",
        owner="brockamer",
        repo="brockamer/findajob",
        field_ids={"Status": "F1", "Priority": "F2", "Size": "F3"},
        field_options={
            "Status": {"Backlog": "A"},
            "Priority": {"High": "H"},
            "Size": {"Large": "SL"},
        },
    )
    calls = patch_gh_by_arg(
        monkeypatch,
        {
            "item-add": '{"id": "PVTI_new"}',
            "api graphql": "{}",
        },
    )
    provider.add_to_board(42, priority="High", status="Backlog", fields=[("Size", "Large")])

    graphql_calls = [c for c in calls if "api" in c and "graphql" in c]
    assert graphql_calls, "expected graphql call for field mutations"
    joined = " ".join(" ".join(c) for c in graphql_calls)
    # Priority/Status/Size all ride one mutation; Size is the setExtra0 alias.
    assert "setPriority" in joined
    assert "setStatus" in joined
    assert "setExtra0" in joined
    # Size resolved: field-id F3 / option-id SL
    assert "F3" in joined and "SL" in joined


# ------------------------------------------------------------------ #
# file                                                                  #
# ------------------------------------------------------------------ #


def test_file_sequences_create_add_graphql(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """file emits gh issue create → item-add → graphql mutation (same as _cmd_file)."""
    calls = patch_gh_by_arg(
        monkeypatch,
        {
            "issue create": "https://github.com/brockamer/findajob/issues/99\n",
            "item-add": '{"id": "PVTI_new"}',
            "api graphql": "{}",
        },
    )
    result = _provider().file(
        title="New issue",
        body="Body content.",
        priority="High",
        status="Backlog",
    )

    # issue create happened
    assert any("issue" in c and "create" in c for c in calls)
    # item-add happened
    assert any("item-add" in " ".join(c) for c in calls)
    # graphql mutation happened with correct field IDs
    graphql_calls = [c for c in calls if "api" in c and "graphql" in c]
    joined = " ".join(" ".join(c) for c in graphql_calls)
    assert "updateProjectV2ItemFieldValue" in joined
    assert "F2" in joined and "H" in joined  # Priority=High
    assert "F1" in joined and "A" in joined  # Status=Backlog
    # no item-edit (field mutations go through graphql)
    assert not any("item-edit" in " ".join(c) for c in calls)

    # Returns BoardItem with correct fields
    assert isinstance(result, BoardItem)
    assert result.number == 99
    assert result.title == "New issue"
    assert result.status == "Backlog"
    assert result.priority == "High"


def test_file_passes_milestone_to_gh_create(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When milestone is given, --milestone is passed to gh issue create."""
    calls = patch_gh_by_arg(
        monkeypatch,
        {
            "issue create": "https://github.com/brockamer/findajob/issues/10\n",
            "item-add": '{"id": "PVTI_new"}',
            "api graphql": "{}",
        },
    )
    _provider().file(
        title="T",
        body="B",
        priority="Low",
        status="Backlog",
        milestone="v1.0",
    )

    create_calls = [c for c in calls if "issue" in c and "create" in c]
    assert len(create_calls) == 1
    argv = create_calls[0]
    assert "--milestone" in argv
    idx = argv.index("--milestone")
    assert argv[idx + 1] == "v1.0"


def test_file_passes_labels_to_gh_create(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Labels are forwarded to gh issue create via --label."""
    calls = patch_gh_by_arg(
        monkeypatch,
        {
            "issue create": "https://github.com/brockamer/findajob/issues/11\n",
            "item-add": '{"id": "PVTI_new"}',
            "api graphql": "{}",
        },
    )
    _provider().file(
        title="T",
        body="B",
        priority="Low",
        status="Backlog",
        labels=["enhancement"],
    )

    create_calls = [c for c in calls if "issue" in c and "create" in c]
    assert any("--label" in " ".join(c) for c in create_calls)
    assert any("enhancement" in " ".join(c) for c in create_calls)


def test_file_returns_board_item_with_correct_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """file returns a BoardItem with the right number/title/status/priority."""
    patch_gh_by_arg(
        monkeypatch,
        {
            "issue create": "https://github.com/brockamer/findajob/issues/55\n",
            "item-add": '{"id": "PVTI_x"}',
            "api graphql": "{}",
        },
    )
    item = _provider().file(
        title="Check fields",
        body="B",
        priority="Medium",
        status="Up Next",
    )

    assert isinstance(item, BoardItem)
    assert item.number == 55
    assert item.title == "Check fields"
    assert item.status == "Up Next"
    assert item.priority == "Medium"
    assert item.labels == []
    assert item.milestone is None


def test_file_unknown_priority_raises_before_any_gh_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A misconfigured Priority must fail BEFORE `gh issue create` — no ghost issue.

    This is the off-board-ghost fence (the invariant `jared file` exists to
    protect): if `file()` created the issue and only THEN discovered the bad
    field, you'd be left with a created-but-not-on-board issue.

    The load-bearing assertion is `calls == []`, NOT merely that OptionNotFound
    is raised. `_add_existing` (the post-create board-setup step) re-resolves the
    same Priority/Status names and is wrapped in `except OptionNotFound` — so a
    `pytest.raises(OptionNotFound)`-only check would pass against BOTH the correct
    pre-create ordering AND a broken ordering that resolved after creating the
    issue. Only "zero gh calls" discriminates: pre-resolution is the very first
    thing `file()` does, before even temp-file staging, so a clean fence means
    nothing — not even `gh issue create` — was invoked.

    `issue create` is mapped to a valid URL so that if the fence were removed,
    this test would go red precisely on the recorded create call (a clean
    demonstration of the ordering), not on an unrelated FileCreateError path.
    """
    calls = patch_gh_by_arg(
        monkeypatch,
        {
            "issue create": "https://github.com/brockamer/findajob/issues/99\n",
            "item-add": '{"id": "PVTI_new"}',
            "api graphql": "{}",
        },
    )

    with pytest.raises(OptionNotFound):
        _provider().file(
            title="Ghost candidate",
            body="Body content.",
            priority="Critical",  # not in {High, Medium, Low}
            status="Backlog",
        )

    # The fence: zero gh calls. The issue was never created.
    assert calls == [], f"file() must fail before any gh call; got: {calls}"


def test_file_unknown_status_raises_before_any_gh_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Symmetric to the Priority fence: a bad Status also fails before create.

    Status is the second required field; both must be resolvable before the
    issue is created. Same `calls == []` discriminator as the Priority case.
    """
    calls = patch_gh_by_arg(
        monkeypatch,
        {
            "issue create": "https://github.com/brockamer/findajob/issues/99\n",
            "item-add": '{"id": "PVTI_new"}',
            "api graphql": "{}",
        },
    )

    with pytest.raises(OptionNotFound):
        _provider().file(
            title="Ghost candidate",
            body="Body content.",
            priority="High",
            status="Shipped",  # not a valid Status column
        )

    assert calls == [], f"file() must fail before any gh call; got: {calls}"


# ------------------------------------------------------------------ #
# set_field                                                             #
# ------------------------------------------------------------------ #


def test_set_field_emits_item_edit_with_resolved_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """set_field resolves item-id then emits `gh project item-edit` (NOT a graphql mutation).

    Oracle: mirrors test_cmd_set.py::test_set_invokes_item_edit_with_resolved_ids.
    project_id="PVT_x", item_id="PVTI_aaa", field_id="F2", option_id="H".
    """
    calls = patch_gh_by_arg(
        monkeypatch,
        {
            "api graphql": _scoped_item_response("PVTI_aaa"),
            "item-edit": "{}",
        },
    )
    _provider().set_field(42, "Priority", "High")

    edit_calls = [c for c in calls if "item-edit" in c]
    assert edit_calls, "expected gh project item-edit call"
    joined = " ".join(edit_calls[0])
    assert "PVT_x" in joined  # project_id
    assert "PVTI_aaa" in joined  # item_id
    assert "F2" in joined  # field_id for Priority
    assert "H" in joined  # option_id for High


def test_set_field_emits_item_edit_not_graphql_mutation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """set_field must use item-edit, not the aliased updateProjectV2 mutation."""
    calls = patch_gh_by_arg(
        monkeypatch,
        {
            "api graphql": _scoped_item_response(),
            "item-edit": "{}",
        },
    )
    _provider().set_field(42, "Status", "Done")

    # item-edit present
    assert any("item-edit" in " ".join(c) for c in calls)
    # The graphql call is only the item-lookup, NOT a mutation
    graphql_calls = [c for c in calls if "api" in c and "graphql" in c]
    assert not any("updateProjectV2ItemFieldValue" in " ".join(c) for c in graphql_calls), (
        "set_field must not emit the aliased mutation — that belongs to add_to_board/file"
    )


# ------------------------------------------------------------------ #
# move                                                                  #
# ------------------------------------------------------------------ #


def test_move_delegates_to_set_field(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """move(ref, status) delegates to set_field(ref, 'Status', status)."""
    calls = patch_gh_by_arg(
        monkeypatch,
        {
            "api graphql": _scoped_item_response("PVTI_mv"),
            "item-edit": "{}",
        },
    )
    _provider().move(42, "In Progress")

    edit_calls = [c for c in calls if "item-edit" in c]
    assert edit_calls
    joined = " ".join(edit_calls[0])
    assert "F1" in joined  # Status field_id
    assert "C" in joined  # In Progress option_id


# ------------------------------------------------------------------ #
# close                                                                 #
# ------------------------------------------------------------------ #


def test_close_emits_gh_issue_close_then_sets_status_done(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """close emits `gh issue close` then always sets Status=Done via set_field (#137)."""
    calls = patch_gh_by_arg(
        monkeypatch,
        {
            # item-lookup for set_field's find_item_id
            "api graphql": _scoped_item_response("PVTI_cl"),
            "issue close": "",
            "item-edit": "{}",
        },
    )
    _provider().close(42)

    close_calls = [c for c in calls if "issue" in c and "close" in c]
    assert close_calls, "expected gh issue close"
    assert "brockamer/findajob" in " ".join(close_calls[0])

    edit_calls = [c for c in calls if "item-edit" in c]
    assert edit_calls, "expected gh project item-edit for Status=Done"
    joined = " ".join(edit_calls[0])
    assert "F1" in joined  # Status field_id
    assert "E" in joined  # Done option_id


def test_close_with_comment_emits_comment_before_close(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When comment is given, `gh issue comment` fires before `gh issue close`."""
    calls = patch_gh_by_arg(
        monkeypatch,
        {
            "api graphql": _scoped_item_response("PVTI_cl"),
            "issue comment": "https://github.com/brockamer/findajob/issues/42#comment-1",
            "issue close": "",
            "item-edit": "{}",
        },
    )
    _provider().close(42, comment="Session note text")

    comment_calls = [c for c in calls if "issue" in c and "comment" in c]
    assert comment_calls, "expected gh issue comment call"
    assert "--body-file" in comment_calls[0]

    # comment must precede close in the call order
    comment_idx = next(i for i, c in enumerate(calls) if "issue" in c and "comment" in c)
    close_idx = next(i for i, c in enumerate(calls) if "issue" in c and "close" in c)
    assert comment_idx < close_idx, "comment must fire before close"


def test_close_always_sets_status_done_no_poll(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """close always emits item-edit for Status=Done; it does NOT poll first."""
    calls = patch_gh_by_arg(
        monkeypatch,
        {
            "api graphql": _scoped_item_response("PVTI_cl"),
            "issue close": "",
            "item-edit": "{}",
        },
    )
    _provider().close(42)

    # The graphql call is only the item-lookup for set_field, not a poll
    graphql_calls = [c for c in calls if "api" in c and "graphql" in c]
    # Only one graphql call allowed: the item-id lookup
    assert len(graphql_calls) == 1, (
        f"close must not poll; expected only the item-id lookup, "
        f"got {len(graphql_calls)} graphql calls"
    )


# ------------------------------------------------------------------ #
# set_body                                                              #
# ------------------------------------------------------------------ #


def test_set_body_emits_issue_edit_body_file(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """set_body emits `gh issue edit <n> --repo <repo> --body-file <path>`.

    Oracle: mirrors capture-context.py write_body.
    """
    calls = patch_gh_by_arg(monkeypatch, {"issue edit": ""})
    _provider().set_body(42, "New body text")

    edit_calls = [c for c in calls if "issue" in c and "edit" in c]
    assert edit_calls, "expected gh issue edit call"
    argv = edit_calls[0]
    joined = " ".join(argv)
    assert "42" in joined
    assert "brockamer/findajob" in joined
    assert "--body-file" in argv


# ------------------------------------------------------------------ #
# comment                                                               #
# ------------------------------------------------------------------ #


def test_comment_emits_issue_comment_body_file(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """comment emits `gh issue comment <n> --repo <repo> --body-file <path>` and returns the URL.

    Oracle: mirrors _cmd_comment's gh invocation.
    """
    url = "https://github.com/brockamer/findajob/issues/42#comment-1"
    calls = patch_gh_by_arg(
        monkeypatch,
        {"issue comment": url},
    )
    result = _provider().comment(42, "A comment body")

    comment_calls = [c for c in calls if "issue" in c and "comment" in c]
    assert comment_calls, "expected gh issue comment call"
    argv = comment_calls[0]
    assert "--body-file" in argv
    assert "42" in argv
    assert "brockamer/findajob" in " ".join(argv)
    # comment() returns the URL string from gh
    assert result == url


# ------------------------------------------------------------------ #
# add_label / remove_label                                             #
# ------------------------------------------------------------------ #


def test_add_label_emits_issue_edit_add_label(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """add_label emits `gh issue edit <n> --repo <repo> --add-label <name>`."""
    calls = patch_gh_by_arg(monkeypatch, {"issue edit": "{}"})
    _provider().add_label(42, "enhancement")

    edit_calls = [c for c in calls if "issue" in c and "edit" in c]
    assert edit_calls
    argv = edit_calls[0]
    assert "--add-label" in argv
    assert "enhancement" in argv
    assert "brockamer/findajob" in " ".join(argv)


def test_remove_label_emits_issue_edit_remove_label(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """remove_label emits `gh issue edit <n> --repo <repo> --remove-label <name>`."""
    calls = patch_gh_by_arg(monkeypatch, {"issue edit": "{}"})
    _provider().remove_label(42, "session-1")

    edit_calls = [c for c in calls if "issue" in c and "edit" in c]
    assert edit_calls
    argv = edit_calls[0]
    assert "--remove-label" in argv
    assert "session-1" in argv


# ------------------------------------------------------------------ #
# add_blocked_by / remove_blocked_by                                   #
# ------------------------------------------------------------------ #


def test_add_blocked_by_emits_addBlockedBy_mutation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """add_blocked_by resolves node IDs then emits addBlockedBy mutation.

    Oracle: mirrors test_cmd_blocked_by.py::test_blocked_by_add_edge.
    Two issue-view calls + one graphql call with addBlockedBy and both node IDs.
    """

    def fake_run(args: list[str], **kw: object) -> object:
        from tests.conftest import FakeGhResult

        joined = " ".join(args)
        if "issue" in args and "view" in args:
            idx = args.index("view")
            num = int(args[idx + 1])
            node_ids = {99: "I_blockee", 42: "I_blocker"}
            return FakeGhResult(stdout=f'{{"id": "{node_ids[num]}"}}')
        if "graphql" in joined:
            return FakeGhResult(stdout='{"data": {"addBlockedBy": {"issue": {"number": 99}}}}')
        return FakeGhResult(stdout="{}")

    calls: list[list[str]] = []

    def recording_fake(args: list[str], **kw: object) -> object:
        calls.append(args)
        return fake_run(args, **kw)

    monkeypatch.setattr("skills.jared.scripts.lib.board.subprocess.run", recording_fake)

    _provider().add_blocked_by(99, 42)

    view_calls = [c for c in calls if "view" in c]
    assert len(view_calls) == 2, "expected two issue-view calls for node-id resolution"

    gql = next(c for c in calls if "graphql" in " ".join(c))
    query_arg = next(a for a in gql if a.startswith("query="))
    assert "addBlockedBy" in query_arg
    assert "removeBlockedBy" not in query_arg
    assert any("issueId=I_blockee" in a for a in gql)
    assert any("blockingIssueId=I_blocker" in a for a in gql)


def test_remove_blocked_by_emits_removeBlockedBy_mutation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """remove_blocked_by emits removeBlockedBy mutation.

    Oracle: mirrors test_cmd_blocked_by.py::test_blocked_by_remove_edge.
    """

    def fake_run(args: list[str], **kw: object) -> object:
        from tests.conftest import FakeGhResult

        joined = " ".join(args)
        if "issue" in args and "view" in args:
            idx = args.index("view")
            num = int(args[idx + 1])
            node_ids = {99: "I_blockee", 42: "I_blocker"}
            return FakeGhResult(stdout=f'{{"id": "{node_ids[num]}"}}')
        if "graphql" in joined:
            return FakeGhResult(stdout='{"data": {"removeBlockedBy": {"issue": {"number": 99}}}}')
        return FakeGhResult(stdout="{}")

    calls: list[list[str]] = []

    def recording_fake(args: list[str], **kw: object) -> object:
        calls.append(args)
        return fake_run(args, **kw)

    monkeypatch.setattr("skills.jared.scripts.lib.board.subprocess.run", recording_fake)

    _provider().remove_blocked_by(99, 42)

    gql = next(c for c in calls if "graphql" in " ".join(c))
    query_arg = next(a for a in gql if a.startswith("query="))
    assert "removeBlockedBy" in query_arg
    assert "addBlockedBy" not in query_arg


# ------------------------------------------------------------------ #
# set_milestone                                                         #
# ------------------------------------------------------------------ #


def test_set_milestone_emits_issue_edit_milestone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """set_milestone emits `gh issue edit <n> --repo <repo> --milestone <name>`."""
    calls = patch_gh_by_arg(monkeypatch, {"issue edit": "{}"})
    _provider().set_milestone(42, "v2.0")

    edit_calls = [c for c in calls if "issue" in c and "edit" in c]
    assert edit_calls
    argv = edit_calls[0]
    assert "--milestone" in argv
    idx = argv.index("--milestone")
    assert argv[idx + 1] == "v2.0"
    assert "brockamer/findajob" in " ".join(argv)


# ------------------------------------------------------------------ #
# list_milestones                                                       #
# ------------------------------------------------------------------ #


def test_list_milestones_emits_correct_api_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """list_milestones uses query-string form, not -f form (#254 regression guard)."""
    import json as _json

    calls = patch_gh_by_arg(
        monkeypatch,
        {
            "milestones": _json.dumps(
                [
                    {
                        "title": "v1.0",
                        "description": "First release",
                        "state": "open",
                        "due_on": "2026-06-30",
                    }
                ]
            )
        },
    )
    milestones = _provider().list_milestones()

    assert len(milestones) == 1
    assert isinstance(milestones[0], Milestone)
    assert milestones[0].name == "v1.0"
    assert milestones[0].state == "open"

    milestone_calls = [c for c in calls if "milestones" in " ".join(c)]
    assert milestone_calls, "expected a milestones API call"
    argv = milestone_calls[0]

    # Must use query-string form (not -f filters which would POST-create)
    url_arg = next((a for a in argv if "milestones" in a), "")
    assert "state=open" in url_arg, (
        "milestone URL must carry state=open in query string to avoid hitting POST endpoint; "
        f"got: {url_arg!r}"
    )
    # No bare -f state= without --method GET
    f_fields = [argv[i + 1] for i, t in enumerate(argv) if t == "-f" and i + 1 < len(argv)]
    for field in f_fields:
        assert not field.startswith("state="), (
            f"`-f {field}` without --method GET would POST to milestones; use query string"
        )


# ------------------------------------------------------------------ #
# _item_add retry safeguard (jared#112, Phase 1.10 regression port)  #
# ------------------------------------------------------------------ #


def test_item_add_retries_when_id_missing_on_first_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """gh project item-add occasionally returns a body with no id on the first
    call but succeeds immediately on retry (jared#112). _item_add must retry
    once and return the id from the second call.
    """
    call_count = 0

    def fake_run(args: list[str], **kw: object) -> FakeGhResult:
        nonlocal call_count
        if "item-add" in " ".join(args):
            call_count += 1
            if call_count == 1:
                return FakeGhResult(stdout="{}")  # id absent on first call
            return FakeGhResult(stdout='{"id": "PVTI_retry_ok"}')
        return FakeGhResult(stdout="{}")

    monkeypatch.setattr("skills.jared.scripts.lib.board.subprocess.run", fake_run)

    item_id = _provider()._item_add(99)
    assert item_id == "PVTI_retry_ok"
    assert call_count == 2, "expected exactly 2 item-add calls (first miss + retry)"


def test_item_add_raises_after_retry_still_missing_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If both the first and retry item-add calls return no id, raise GhInvocationError."""

    def fake_run(args: list[str], **kw: object) -> FakeGhResult:
        if "item-add" in " ".join(args):
            return FakeGhResult(stdout="{}")  # id always absent
        return FakeGhResult(stdout="{}")

    monkeypatch.setattr("skills.jared.scripts.lib.board.subprocess.run", fake_run)

    with pytest.raises(GhInvocationError, match="no id.*after retry"):
        _provider()._item_add(99)
