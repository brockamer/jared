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
        - Up Next: OPTION_up_next
        - In Progress: OPTION_in_progress
        - Done: OPTION_done
        - Blocked: OPTION_blocked
    """)
    )
    return board_md


def test_move_sets_status_field(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    board_md = _write_board_with_status(tmp_path)
    calls = patch_gh_by_arg(
        monkeypatch,
        {
            "item-list": '{"items": [{"id": "PVTI_aaa", "content": {"number": 42}}]}',
            "item-edit": "{}",
        },
    )

    mod = import_cli()
    rc = mod.main(["--board", str(board_md), "move", "42", "In Progress"])

    captured = capsys.readouterr()
    assert rc == 0, captured.err
    edit = next(c for c in calls if "item-edit" in c)
    joined = " ".join(edit)
    assert "PVTSSF_status" in joined
    assert "OPTION_in_progress" in joined
