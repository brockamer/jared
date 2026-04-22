from pathlib import Path

import pytest

from tests.conftest import import_cli, patch_gh, write_minimal_board


def test_summary_groups_by_status(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    board_md = write_minimal_board(tmp_path)
    patch_gh(
        monkeypatch,
        stdout=(
            '{"items": ['
            '{"id": "a", "content": {"number": 1, "title": "Issue one"}, '
            '"status": "In Progress", "priority": "High"},'
            '{"id": "b", "content": {"number": 2, "title": "Issue two"}, '
            '"status": "Up Next", "priority": "Medium"},'
            '{"id": "c", "content": {"number": 3, "title": "Issue three"}, '
            '"status": "Backlog", "priority": "Low"}'
            "]}"
        ),
    )

    mod = import_cli()
    rc = mod.main(["--board", str(board_md), "summary"])
    out = capsys.readouterr().out

    assert rc == 0
    assert "In Progress" in out
    assert "Up Next" in out
    assert "Issue one" in out
    assert "Issue two" in out
    # Backlog items should NOT show in the fast summary
    assert "Issue three" not in out


def test_summary_shows_blocked_section(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    board_md = write_minimal_board(tmp_path)
    patch_gh(
        monkeypatch,
        stdout=(
            '{"items": ['
            '{"id": "a", "content": {"number": 6, "title": "Stuck thing"}, '
            '"status": "Blocked", "priority": "High"}'
            "]}"
        ),
    )

    mod = import_cli()
    rc = mod.main(["--board", str(board_md), "summary"])
    out = capsys.readouterr().out

    assert rc == 0
    assert "Blocked" in out
    assert "Stuck thing" in out
    assert "#6" in out


def test_summary_up_next_truncates_to_three(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    board_md = write_minimal_board(tmp_path)
    # Five Up Next items; summary should show only 3
    items = []
    for i in range(1, 6):
        items.append(
            f'{{"id": "x{i}", "content": {{"number": {i}, "title": "Up{i}"}}, '
            f'"status": "Up Next", "priority": "Medium"}}'
        )
    patch_gh(monkeypatch, stdout=f'{{"items": [{",".join(items)}]}}')

    mod = import_cli()
    rc = mod.main(["--board", str(board_md), "summary"])
    out = capsys.readouterr().out

    assert rc == 0
    # Up1..Up3 should appear; Up4 and Up5 should not
    assert "Up1" in out and "Up2" in out and "Up3" in out
    assert "Up4" not in out and "Up5" not in out
    # Header should indicate the full count
    assert "of 5" in out
