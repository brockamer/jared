from pathlib import Path
from textwrap import dedent

import pytest

from tests.conftest import import_cli, patch_gh_by_arg


def _write_board_with_priority(tmp_path: Path) -> Path:
    board_md = tmp_path / "docs" / "project-board.md"
    board_md.parent.mkdir(parents=True)
    board_md.write_text(
        dedent("""\
        - Project URL: https://github.com/users/brockamer/projects/7
        - Project number: 7
        - Project ID: PVT_kwHO_xyz
        - Owner: brockamer
        - Repo: brockamer/findajob

        ### Priority
        - Field ID: PVTSSF_prio
        - High: OPTION_high
        - Medium: OPTION_med
        - Low: OPTION_low
    """)
    )
    return board_md


def test_set_invokes_item_edit_with_resolved_ids(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    board_md = _write_board_with_priority(tmp_path)
    calls = patch_gh_by_arg(
        monkeypatch,
        {
            "item-list": '{"items": [{"id": "PVTI_aaa", "content": {"number": 42}}]}',
            "item-edit": "{}",
        },
    )

    mod = import_cli()
    rc = mod.main(["--board", str(board_md), "set", "42", "Priority", "High"])

    captured = capsys.readouterr()
    assert rc == 0, captured.err

    edit = next(c for c in calls if "item-edit" in c)
    joined = " ".join(edit)
    assert "PVT_kwHO_xyz" in joined
    assert "PVTI_aaa" in joined
    assert "PVTSSF_prio" in joined
    assert "OPTION_high" in joined


def test_set_unknown_field_exits_nonzero(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    board_md = _write_board_with_priority(tmp_path)
    patch_gh_by_arg(
        monkeypatch,
        {"item-list": '{"items": [{"id": "PVTI_aaa", "content": {"number": 42}}]}'},
    )

    mod = import_cli()
    rc = mod.main(["--board", str(board_md), "set", "42", "Nonexistent", "Anything"])

    captured = capsys.readouterr()
    assert rc != 0
    assert "Nonexistent" in captured.err or "not found" in captured.err.lower()


def test_set_unknown_option_exits_nonzero(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    board_md = _write_board_with_priority(tmp_path)
    patch_gh_by_arg(
        monkeypatch,
        {"item-list": '{"items": [{"id": "PVTI_aaa", "content": {"number": 42}}]}'},
    )

    mod = import_cli()
    rc = mod.main(["--board", str(board_md), "set", "42", "Priority", "Urgent"])

    captured = capsys.readouterr()
    assert rc != 0
    assert "Urgent" in captured.err or "not found" in captured.err.lower()
