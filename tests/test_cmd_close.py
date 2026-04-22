from pathlib import Path
from textwrap import dedent

import pytest

from tests.conftest import import_cli, patch_gh_by_arg


def _write_board_with_status(tmp_path: Path) -> Path:
    board_md = tmp_path / "docs" / "project-board.md"
    board_md.parent.mkdir(parents=True)
    board_md.write_text(dedent("""\
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
    """))
    return board_md


def test_close_succeeds_when_board_auto_moves(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    board_md = _write_board_with_status(tmp_path)
    calls = patch_gh_by_arg(
        monkeypatch,
        {
            "issue close": "",
            "item-list": (
                '{"items": [{"id": "PVTI_aaa", "content": {"number": 42}, '
                '"status": "Done"}]}'
            ),
        },
    )

    mod = import_cli()
    rc = mod.main(["--board", str(board_md), "close", "42"])

    captured = capsys.readouterr()
    assert rc == 0, captured.err
    # Must have invoked gh issue close
    assert any("issue" in c and "close" in c for c in calls)
    # Must NOT have invoked item-edit — auto-move handled it
    assert not any("item-edit" in c for c in calls)
    assert "#42" in captured.out


def test_close_falls_back_to_explicit_move_when_auto_move_lags(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # No sleeping in tests — global time.sleep -> no-op for the retry loop.
    monkeypatch.setattr("time.sleep", lambda _s: None)

    board_md = _write_board_with_status(tmp_path)
    # Board never auto-moves to Done.
    calls = patch_gh_by_arg(
        monkeypatch,
        {
            "issue close": "",
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
    # Fallback path: explicit item-edit to Status=Done
    edit = next((c for c in calls if "item-edit" in c), None)
    assert edit is not None, "expected explicit item-edit fallback"
    joined = " ".join(edit)
    assert "PVTSSF_status" in joined
    assert "OPTION_done" in joined
