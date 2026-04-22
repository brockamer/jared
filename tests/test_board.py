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


def _minimal_board(tmp_path: Path) -> Path:
    board_md = tmp_path / "docs" / "project-board.md"
    board_md.parent.mkdir(parents=True)
    board_md.write_text(dedent("""\
        - Project URL: https://github.com/users/brockamer/projects/7
        - Project number: 7
        - Project ID: PVT_kwHO_xyz
        - Owner: brockamer
        - Repo: brockamer/findajob
    """))
    return board_md


def test_run_gh_parses_json(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from skills.jared.scripts.lib.board import Board

    b = Board.from_path(_minimal_board(tmp_path))

    class FakeResult:
        returncode = 0
        stdout = '{"hello": "world"}'
        stderr = ""

    called_args: list[list[str]] = []

    def fake_run(args: list[str], **kw: object) -> FakeResult:
        called_args.append(args)
        return FakeResult()

    monkeypatch.setattr("skills.jared.scripts.lib.board.subprocess.run", fake_run)

    result = b.run_gh(["api", "user"])
    assert result == {"hello": "world"}
    assert called_args == [["gh", "api", "user"]]


def test_run_gh_non_zero_raises(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from skills.jared.scripts.lib.board import Board, GhInvocationError

    b = Board.from_path(_minimal_board(tmp_path))

    class FakeResult:
        returncode = 1
        stdout = ""
        stderr = "HTTP 401: Bad credentials"

    monkeypatch.setattr(
        "skills.jared.scripts.lib.board.subprocess.run",
        lambda *a, **kw: FakeResult(),
    )

    with pytest.raises(GhInvocationError) as exc:
        b.run_gh(["api", "user"])
    assert "401" in str(exc.value)


def test_find_item_id_finds_match(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from skills.jared.scripts.lib.board import Board, ItemNotFound

    b = Board.from_path(_minimal_board(tmp_path))

    class FakeResult:
        returncode = 0
        stdout = (
            '{"items": ['
            '{"id": "PVTI_aaa", "content": {"number": 42}},'
            '{"id": "PVTI_bbb", "content": {"number": 99}}'
            ']}'
        )
        stderr = ""

    monkeypatch.setattr(
        "skills.jared.scripts.lib.board.subprocess.run",
        lambda *a, **kw: FakeResult(),
    )

    assert b.find_item_id(42) == "PVTI_aaa"
    assert b.find_item_id(99) == "PVTI_bbb"

    with pytest.raises(ItemNotFound):
        b.find_item_id(123456)
