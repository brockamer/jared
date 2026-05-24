from pathlib import Path

import pytest

from tests.conftest import (
    import_cli,
    patch_gh_by_arg,
    patch_gh_multi,
    write_minimal_board,
)


def test_summary_groups_by_status(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    board_md = write_minimal_board(tmp_path)
    patch_gh_multi(
        monkeypatch,
        open_issues=[
            {"number": 1, "title": "Issue one", "state": "OPEN"},
            {"number": 2, "title": "Issue two", "state": "OPEN"},
            {"number": 3, "title": "Issue three", "state": "OPEN"},
        ],
        statuses={
            1: ("In Progress", "High"),
            2: ("Up Next", "Medium"),
            3: ("Backlog", "Low"),
        },
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
    patch_gh_multi(
        monkeypatch,
        open_issues=[{"number": 6, "title": "Stuck thing", "state": "OPEN"}],
        statuses={6: ("Blocked", "High")},
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
    Regression test for #43 (post-#185 — stuck-closed comes from recently-
    closed lookback, not the in-snapshot CLOSED items the old detector
    needed).
    """
    board_md = write_minimal_board(tmp_path)
    patch_gh_multi(
        monkeypatch,
        # Only the truly-open item shows up in `gh issue list --state open`.
        open_issues=[{"number": 100, "title": "Real in-progress", "state": "OPEN"}],
        statuses={100: ("In Progress", "High")},
        # Stuck-closed are now surfaced via the recently-closed lookback;
        # both still have Status=In Progress (the drift the detector exists for).
        closed_issues=[
            {"number": 101, "title": "Closed stuck one", "closedAt": "2026-05-20T10:00:00Z"},
            {"number": 102, "title": "Closed stuck two", "closedAt": "2026-05-19T10:00:00Z"},
        ],
        closed_statuses={
            101: ("In Progress", "Medium"),
            102: ("In Progress", "Low"),
        },
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
    the common case stays terse. Recently-closed list empty = no drift."""
    board_md = write_minimal_board(tmp_path)
    patch_gh_multi(
        monkeypatch,
        open_issues=[{"number": 1, "title": "Open thing", "state": "OPEN"}],
        statuses={1: ("In Progress", "High")},
    )

    mod = import_cli()
    rc = mod.main(["--board", str(board_md), "summary"])
    out = capsys.readouterr().out

    assert rc == 0
    assert "Stuck closed" not in out


def test_summary_collapses_same_session_in_progress_into_one_workstream(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Per-session WIP arithmetic (#235): two In Progress items sharing
    `session-1` plus one with `session-2` render as 2 workstreams · 3 items,
    not as a flat count of 3. The leading number is what /jared-start's
    WIP-cap check reads; the parenthetical item count keeps the operator
    oriented on what they're actually looking at.
    """
    board_md = write_minimal_board(tmp_path)
    patch_gh_multi(
        monkeypatch,
        open_issues=[
            {"number": 1, "title": "A in session-1", "state": "OPEN"},
            {"number": 2, "title": "B in session-1", "state": "OPEN"},
            {"number": 3, "title": "C in session-2", "state": "OPEN"},
        ],
        statuses={
            1: ("In Progress", "High"),
            2: ("In Progress", "High"),
            3: ("In Progress", "Medium"),
        },
        labels_by_number={
            1: ["session-1", "enhancement"],
            2: ["session-1"],
            3: ["session-2"],
        },
    )

    mod = import_cli()
    rc = mod.main(["--board", str(board_md), "summary"])
    out = capsys.readouterr().out

    assert rc == 0
    assert "In Progress (2 workstreams · 3 items)" in out
    # Each item renders its session tag so the grouping is legible.
    assert "(session-1)" in out
    assert "(session-2)" in out


def test_summary_unlabeled_in_progress_counts_as_own_workstream(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """An In Progress item with no `session-N` label is its own workstream.
    Two session-1 items + one unlabeled = 2 workstreams · 3 items.
    """
    board_md = write_minimal_board(tmp_path)
    patch_gh_multi(
        monkeypatch,
        open_issues=[
            {"number": 1, "title": "A in session-1", "state": "OPEN"},
            {"number": 2, "title": "B in session-1", "state": "OPEN"},
            {"number": 3, "title": "C solo", "state": "OPEN"},
        ],
        statuses={
            1: ("In Progress", "High"),
            2: ("In Progress", "High"),
            3: ("In Progress", "Medium"),
        },
        labels_by_number={
            1: ["session-1"],
            2: ["session-1"],
            # #3 has no labels → its own workstream
        },
    )

    mod = import_cli()
    rc = mod.main(["--board", str(board_md), "summary"])
    out = capsys.readouterr().out

    assert rc == 0
    assert "In Progress (2 workstreams · 3 items)" in out


def test_summary_no_collapse_when_no_session_labels_present(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Common case — no parallel-session labels in play. Header stays as
    `In Progress (N):`. Workstream-count parenthetical is the *changed*
    shape; it must not leak into the no-collapse path."""
    board_md = write_minimal_board(tmp_path)
    patch_gh_multi(
        monkeypatch,
        open_issues=[
            {"number": 1, "title": "Alone", "state": "OPEN"},
            {"number": 2, "title": "Also alone", "state": "OPEN"},
        ],
        statuses={
            1: ("In Progress", "High"),
            2: ("In Progress", "High"),
        },
        labels_by_number={
            1: ["enhancement"],
            # #2 has no labels at all
        },
    )

    mod = import_cli()
    rc = mod.main(["--board", str(board_md), "summary"])
    out = capsys.readouterr().out

    assert rc == 0
    assert "In Progress (2):" in out
    assert "workstreams" not in out
    assert "(session-" not in out


def test_summary_up_next_truncates_to_three(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    board_md = write_minimal_board(tmp_path)
    open_issues = [{"number": i, "title": f"Up{i}", "state": "OPEN"} for i in range(1, 6)]
    statuses = {i: ("Up Next", "Medium") for i in range(1, 6)}
    patch_gh_multi(monkeypatch, open_issues=open_issues, statuses=statuses)

    mod = import_cli()
    rc = mod.main(["--board", str(board_md), "summary"])
    out = capsys.readouterr().out

    assert rc == 0
    # Up1..Up3 should appear; Up4 and Up5 should not
    assert "Up1" in out and "Up2" in out and "Up3" in out
    assert "Up4" not in out and "Up5" not in out
    # Header should indicate the full count
    assert "of 5" in out


def test_summary_routes_through_open_items_not_full_project_pull(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """`jared summary` is a hot path that on mature boards used to bill
    GraphQL proportional to total board size via `gh project item-list`
    (#185). After migration, it must not pull items via item-list.

    Implementation detail (one batched GraphQL via `repository.issues`)
    can change without breaking this test; the regression target is the
    no-item-list contract.
    """
    board_md = write_minimal_board(tmp_path)

    empty_issues_response = (
        '{"data": {"repository": {"issues": {"pageInfo": {"hasNextPage": false}, "nodes": []}}}}'
    )
    calls = patch_gh_by_arg(
        monkeypatch,
        responses={
            "api graphql": empty_issues_response,
            "--state closed": "[]",  # empty recently-closed list (no stuck-closed lookup needed)
        },
    )

    mod = import_cli()
    rc = mod.main(["--board", str(board_md), "summary"])
    assert rc == 0

    joined = [" ".join(argv) for argv in calls]
    assert not any("project item-list" in c for c in joined), (
        f"summary must NOT call `gh project item-list`; saw {joined!r}"
    )
