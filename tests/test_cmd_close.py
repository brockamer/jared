import json
from pathlib import Path
from textwrap import dedent

import pytest

from tests.conftest import import_cli, patch_gh_by_arg


def _write_board_with_status(tmp_path: Path) -> Path:
    board_md = tmp_path / "docs" / "project-board.md"
    board_md.parent.mkdir(parents=True)
    board_md.write_text(
        dedent("""\
        - Project URL: https://github.com/users/brockamer/projects/7
        - Project number: 7
        - Project ID: PVT_kwHO_xyz
        - Owner: brockamer
        - Repo: brockamer/findajob

        ### Status
        - Field ID: PVTSSF_status
        - Backlog: OPTION_backlog
        - In Progress: OPTION_in_progress
        - Done: OPTION_done
    """)
    )
    return board_md


def _graphql_item_response(*, project_number: int, status: str, item_id: str = "PVTI_aaa") -> str:
    """Build a repository.issue(number).projectItems graphql payload."""
    return json.dumps(
        {
            "data": {
                "repository": {
                    "issue": {
                        "projectItems": {
                            "nodes": [
                                {
                                    "id": item_id,
                                    "project": {"number": project_number},
                                    "fieldValues": {
                                        "nodes": [
                                            {
                                                "name": status,
                                                "field": {"name": "Status"},
                                            }
                                        ]
                                    },
                                }
                            ]
                        }
                    }
                }
            }
        }
    )


def test_close_always_sets_status_done_defense_in_depth(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """After `jared close <N>`, item-edit Status=Done MUST run unconditionally
    — even when the board's auto-move workflow appears to have already moved
    the item to Done. Defense-in-depth for #137: GitHub's project auto-move
    has an observable false-positive mode where the GraphQL poll claims
    Status=Done but the field hasn't actually changed (#135 reproduction).
    The explicit set after close is the source of truth.
    """
    monkeypatch.setattr("time.sleep", lambda _s: None)
    board_md = _write_board_with_status(tmp_path)
    calls = patch_gh_by_arg(
        monkeypatch,
        {
            "issue close": "",
            # Even if GraphQL says Done, the CLI must still item-edit Status=Done.
            "api graphql": _graphql_item_response(project_number=7, status="Done"),
            "item-edit": "{}",
        },
    )

    mod = import_cli()
    rc = mod.main(["--board", str(board_md), "close", "42"])

    captured = capsys.readouterr()
    assert rc == 0, captured.err
    edit = next((c for c in calls if "item-edit" in c), None)
    assert edit is not None, "expected explicit item-edit even when graphql claims Done"
    joined = " ".join(edit)
    assert "PVTSSF_status" in joined
    assert "OPTION_done" in joined


def test_close_targets_correct_project_when_issue_on_multiple_boards(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Issue may belong to multiple ProjectV2 items; the post-close set
    must resolve to the item on the board configured in project-board.md,
    never a sibling project's item. Scoping happens in `Board.find_item_id`
    → `fetch_item_for_issue` which filters by `project.number`.
    """
    board_md = _write_board_with_status(tmp_path)
    # Same issue attached to two projects: project 99 (unrelated, PVTI_other),
    # project 7 (our board, PVTI_ours). The item-edit must reference PVTI_ours.
    multi_project_response = json.dumps(
        {
            "data": {
                "repository": {
                    "issue": {
                        "projectItems": {
                            "nodes": [
                                {
                                    "id": "PVTI_other",
                                    "project": {"number": 99},
                                    "fieldValues": {
                                        "nodes": [
                                            {
                                                "name": "Done",
                                                "field": {"name": "Status"},
                                            }
                                        ]
                                    },
                                },
                                {
                                    "id": "PVTI_ours",
                                    "project": {"number": 7},
                                    "fieldValues": {
                                        "nodes": [
                                            {
                                                "name": "Backlog",
                                                "field": {"name": "Status"},
                                            }
                                        ]
                                    },
                                },
                            ]
                        }
                    }
                }
            }
        }
    )

    calls = patch_gh_by_arg(
        monkeypatch,
        {
            "issue close": "",
            "api graphql": multi_project_response,
            "item-edit": "{}",
        },
    )

    mod = import_cli()
    rc = mod.main(["--board", str(board_md), "close", "42"])

    captured = capsys.readouterr()
    assert rc == 0, captured.err
    edit = next((c for c in calls if "item-edit" in c), None)
    assert edit is not None, "expected item-edit on board-scoped item"
    joined = " ".join(edit)
    # The mutation must reference our board's item-id, never the sibling project's.
    assert "PVTI_ours" in joined
    assert "PVTI_other" not in joined
