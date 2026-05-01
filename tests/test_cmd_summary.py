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


def test_summary_excludes_stuck_closed_from_in_progress_count(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Closed items still sitting at Status=In Progress (PR-merge auto-close
    drift) must not inflate the In Progress (N) count that /jared-start
    parses for its WIP-cap check. They surface separately under
    'Stuck closed' so the operator can see the truth without breaking flow.
    Regression test for #43.
    """
    board_md = write_minimal_board(tmp_path)
    patch_gh(
        monkeypatch,
        stdout=(
            '{"items": ['
            # One legitimately In Progress (open + Status=In Progress)
            '{"id": "a", "content": {"number": 100, "title": "Real in-progress",'
            ' "state": "OPEN"}, "status": "In Progress", "priority": "High"},'
            # Two stuck-closed: state=CLOSED, Status still In Progress
            '{"id": "b", "content": {"number": 101, "title": "Closed stuck one",'
            ' "state": "CLOSED"}, "status": "In Progress", "priority": "Medium"},'
            '{"id": "c", "content": {"number": 102, "title": "Closed stuck two",'
            ' "state": "CLOSED"}, "status": "In Progress", "priority": "Low"}'
            "]}"
        ),
    )

    mod = import_cli()
    rc = mod.main(["--board", str(board_md), "summary"])
    out = capsys.readouterr().out

    assert rc == 0
    # The In Progress count must reflect ONLY the truly-open item.
    assert "In Progress (1):" in out, (
        "stuck-closed items must not count toward In Progress, "
        "or /jared-start's WIP check will silently miscount"
    )
    # The stuck-closed section appears with the right total + members.
    assert "Stuck closed (2)" in out
    assert "#101" in out and "#102" in out
    assert "Closed stuck one" in out and "Closed stuck two" in out
    # Only the truly-open item appears in the In Progress block — verify
    # by checking the legitimate item is rendered and the stuck ones are
    # NOT in the In Progress portion (they are in Stuck closed instead).
    assert "Real in-progress" in out
    in_progress_at = out.find("In Progress (1):")
    stuck_at = out.find("Stuck closed")
    assert in_progress_at < stuck_at
    # In Progress section spans from `In Progress (1):` to `Stuck closed`.
    in_progress_section = out[in_progress_at:stuck_at]
    assert "#101" not in in_progress_section
    assert "#102" not in in_progress_section
    # Remediation hint is shown.
    assert "jared set" in out and "Status Done" in out


def test_summary_no_stuck_closed_section_when_clean(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """When nothing is stuck-closed, the section is omitted entirely so
    the common case stays terse."""
    board_md = write_minimal_board(tmp_path)
    patch_gh(
        monkeypatch,
        stdout=(
            '{"items": ['
            '{"id": "a", "content": {"number": 1, "title": "Open thing", "state": "OPEN"}, '
            '"status": "In Progress", "priority": "High"}'
            "]}"
        ),
    )

    mod = import_cli()
    rc = mod.main(["--board", str(board_md), "summary"])
    out = capsys.readouterr().out

    assert rc == 0
    assert "Stuck closed" not in out


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
