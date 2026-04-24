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


def _graphql_item_response(
    *, project_number: int, status: str, item_id: str = "PVTI_aaa"
) -> str:
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


def test_close_succeeds_when_board_auto_moves(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    board_md = _write_board_with_status(tmp_path)
    calls = patch_gh_by_arg(
        monkeypatch,
        {
            "issue close": "",
            "api graphql": _graphql_item_response(project_number=7, status="Done"),
        },
    )

    mod = import_cli()
    rc = mod.main(["--board", str(board_md), "close", "42"])

    captured = capsys.readouterr()
    assert rc == 0, captured.err
    # Must have invoked gh issue close
    assert any("issue" in c and "close" in c for c in calls)
    # Polling must use graphql, NOT the wide item-list scan that #22 fixes.
    assert not any("item-list" in " ".join(c) for c in calls)
    # Must NOT have invoked item-edit — auto-move handled it
    assert not any("item-edit" in c for c in calls)
    assert "#42" in captured.out


def test_close_falls_back_to_explicit_move_when_auto_move_lags(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # No sleeping in tests — global time.sleep -> no-op for the retry loop.
    monkeypatch.setattr("time.sleep", lambda _s: None)

    board_md = _write_board_with_status(tmp_path)
    # Board never auto-moves to Done — graphql keeps returning Backlog.
    # _cmd_set fallback then uses item-list (find_item_id) + item-edit; that
    # path is out of scope for #22.
    calls = patch_gh_by_arg(
        monkeypatch,
        {
            "issue close": "",
            "api graphql": _graphql_item_response(project_number=7, status="Backlog"),
            "item-list": (
                '{"items": [{"id": "PVTI_aaa", "content": {"number": 42}, '
                '"status": "Backlog"}]}'
            ),
            "item-edit": "{}",
        },
    )

    mod = import_cli()
    rc = mod.main(["--board", str(board_md), "close", "42"])

    captured = capsys.readouterr()
    assert rc == 0, captured.err
    # Poll retried 3 times then fell back — 3 graphql calls for the polling.
    graphql_calls = [c for c in calls if "graphql" in " ".join(c)]
    assert len(graphql_calls) == 3
    # Fallback path: explicit item-edit to Status=Done
    edit = next((c for c in calls if "item-edit" in c), None)
    assert edit is not None, "expected explicit item-edit fallback"
    joined = " ".join(edit)
    assert "PVTSSF_status" in joined
    assert "OPTION_done" in joined


def test_close_filters_graphql_to_current_project(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Issue may belong to multiple ProjectV2 items; only the one whose
    project.number matches the board counts as the auto-move target."""
    board_md = _write_board_with_status(tmp_path)
    # Same issue attached to two projects: Done on project 99 (unrelated),
    # Backlog on project 7 (our board). Fixture must return Backlog.
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
    monkeypatch.setattr("time.sleep", lambda _s: None)

    calls = patch_gh_by_arg(
        monkeypatch,
        {
            "issue close": "",
            "api graphql": multi_project_response,
            "item-list": (
                '{"items": [{"id": "PVTI_ours", "content": {"number": 42}, '
                '"status": "Backlog"}]}'
            ),
            "item-edit": "{}",
        },
    )

    mod = import_cli()
    rc = mod.main(["--board", str(board_md), "close", "42"])

    captured = capsys.readouterr()
    assert rc == 0, captured.err
    # Must have fallen back — project 99's Done doesn't satisfy the predicate
    # because we scope to project_number=7.
    assert any("item-edit" in c for c in calls)
