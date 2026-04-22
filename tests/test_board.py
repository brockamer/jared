from pathlib import Path
from textwrap import dedent

import pytest


def test_parse_project_board_md(tmp_path: Path) -> None:
    from skills.jared.scripts.lib.board import Board

    board_md = tmp_path / "docs" / "project-board.md"
    board_md.parent.mkdir(parents=True)
    board_md.write_text(dedent("""\
        # Project board

        - Project URL: https://github.com/users/brockamer/projects/7
        - Project number: 7
        - Project ID: PVT_kwHO_xyz
        - Owner: brockamer
        - Repo: brockamer/findajob

        ## Fields

        - Status (field ID: PVTSSF_status): Backlog, Up Next, In Progress, Done, Blocked
        - Priority (field ID: PVTSSF_prio): High, Medium, Low
        """))

    board = Board.from_path(board_md)

    assert board.project_number == 7
    assert board.project_id == "PVT_kwHO_xyz"
    assert board.owner == "brockamer"
    assert board.repo == "brockamer/findajob"


def test_missing_file_raises_board_config_error(tmp_path: Path) -> None:
    from skills.jared.scripts.lib.board import Board, BoardConfigError

    with pytest.raises(BoardConfigError) as exc:
        Board.from_path(tmp_path / "missing.md")

    assert "project-board.md" in str(exc.value) or "missing.md" in str(exc.value)


def test_field_and_option_lookup(tmp_path: Path) -> None:
    from skills.jared.scripts.lib.board import Board

    board_md = tmp_path / "docs" / "project-board.md"
    board_md.parent.mkdir(parents=True)
    board_md.write_text(dedent("""\
        - Project URL: https://github.com/users/brockamer/projects/7
        - Project number: 7
        - Project ID: PVT_kwHO_xyz
        - Owner: brockamer
        - Repo: brockamer/findajob

        ## Fields

        ### Status
        - Field ID: PVTSSF_status
        - Backlog: OPTION_backlog
        - Up Next: OPTION_up_next
        - In Progress: OPTION_in_progress
        - Done: OPTION_done
        - Blocked: OPTION_blocked

        ### Priority
        - Field ID: PVTSSF_prio
        - High: OPTION_high
        - Medium: OPTION_med
        - Low: OPTION_low
        """))

    board = Board.from_path(board_md)

    assert board.field_id("Status") == "PVTSSF_status"
    assert board.field_id("Priority") == "PVTSSF_prio"
    assert board.option_id("Status", "In Progress") == "OPTION_in_progress"
    assert board.option_id("Priority", "High") == "OPTION_high"


def test_unknown_field_raises(tmp_path: Path) -> None:
    from skills.jared.scripts.lib.board import Board, FieldNotFound

    board_md = tmp_path / "docs" / "project-board.md"
    board_md.parent.mkdir(parents=True)
    board_md.write_text(dedent("""\
        - Project URL: https://github.com/users/brockamer/projects/7
        - Project number: 7
        - Project ID: PVT_kwHO_xyz
        - Owner: brockamer
        - Repo: brockamer/findajob
        """))

    board = Board.from_path(board_md)
    with pytest.raises(FieldNotFound):
        board.field_id("Nonexistent")


def test_unknown_option_raises(tmp_path: Path) -> None:
    from skills.jared.scripts.lib.board import Board, OptionNotFound

    board_md = tmp_path / "docs" / "project-board.md"
    board_md.parent.mkdir(parents=True)
    board_md.write_text(dedent("""\
        - Project URL: https://github.com/users/brockamer/projects/7
        - Project number: 7
        - Project ID: PVT_kwHO_xyz
        - Owner: brockamer
        - Repo: brockamer/findajob

        ### Priority
        - Field ID: PVTSSF_prio
        - High: OPTION_high
        """))

    board = Board.from_path(board_md)
    with pytest.raises(OptionNotFound):
        board.option_id("Priority", "Urgent")
