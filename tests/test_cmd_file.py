from pathlib import Path
from textwrap import dedent

import pytest

from tests.conftest import FakeGhResult, import_cli


def _write_full_board(tmp_path: Path) -> Path:
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

        ### Priority
        - Field ID: PVTSSF_prio
        - High: OPTION_high
        - Medium: OPTION_med
        - Low: OPTION_low

        ### Work Stream
        - Field ID: PVTSSF_ws
        - Perception: OPTION_perc
        - Planning: OPTION_plan
        - Fleet Ops: OPTION_fleet
    """)
    )
    return board_md


def _routed_fake(
    monkeypatch: pytest.MonkeyPatch,
    *,
    verify_status: str = "Backlog",
    verify_number: int = 42,
) -> list[list[str]]:
    """Route gh calls for file's full sequence: create → add → edits → verify."""
    calls: list[list[str]] = []

    def fake_run(args: list[str], **kw: object) -> FakeGhResult:
        calls.append(args)
        joined = " ".join(args)
        if "issue create" in joined:
            return FakeGhResult(
                stdout=f"https://github.com/brockamer/findajob/issues/{verify_number}\n"
            )
        if "item-add" in joined:
            return FakeGhResult(stdout='{"id": "PVTI_new"}')
        if "item-list" in joined:
            # Post-create verification: item is on the project with Status set.
            return FakeGhResult(
                stdout=(
                    f'{{"items": [{{"id": "PVTI_new", '
                    f'"content": {{"number": {verify_number}}}, '
                    f'"status": "{verify_status}"}}]}}'
                )
            )
        # item-edit and everything else
        return FakeGhResult(stdout="{}")

    monkeypatch.setattr(
        "skills.jared.scripts.lib.board.subprocess.run",
        fake_run,
    )
    return calls


def test_file_sequences_create_add_status_priority(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    board_md = _write_full_board(tmp_path)
    body_file = tmp_path / "body.md"
    body_file.write_text("Body content.")
    calls = _routed_fake(monkeypatch)

    mod = import_cli()
    rc = mod.main(
        [
            "--board",
            str(board_md),
            "file",
            "--title",
            "Test issue",
            "--body-file",
            str(body_file),
            "--priority",
            "High",
        ]
    )
    captured = capsys.readouterr()
    assert rc == 0, captured.err

    # Must invoke all four essentials (plus verification item-list).
    assert any("issue" in c and "create" in c for c in calls)
    assert any("item-add" in c for c in calls)

    edits = [c for c in calls if "item-edit" in c]
    assert len(edits) >= 2, "expected at least Priority + Status item-edit calls"
    joined_edits = " ".join(" ".join(c) for c in edits)
    assert "PVTSSF_prio" in joined_edits and "OPTION_high" in joined_edits
    assert "PVTSSF_status" in joined_edits and "OPTION_backlog" in joined_edits

    # Verification item-list was made AFTER the edits (enforce ordering).
    assert "item-list" in " ".join(calls[-1]), "last call should be verification item-list"


def test_file_with_custom_status_and_extra_field(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    board_md = _write_full_board(tmp_path)
    body_file = tmp_path / "body.md"
    body_file.write_text("Body.")
    calls = _routed_fake(monkeypatch, verify_status="Up Next")

    mod = import_cli()
    rc = mod.main(
        [
            "--board",
            str(board_md),
            "file",
            "--title",
            "Test",
            "--body-file",
            str(body_file),
            "--priority",
            "Medium",
            "--status",
            "Up Next",
            "--field",
            "Work Stream=Planning",
        ]
    )
    captured = capsys.readouterr()
    assert rc == 0, captured.err
    joined_edits = " ".join(" ".join(c) for c in calls if "item-edit" in c)
    assert "OPTION_up_next" in joined_edits
    assert "PVTSSF_ws" in joined_edits and "OPTION_plan" in joined_edits


def test_file_verification_failure_exits_nonzero(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # No real sleeping — the verify-retry loop now iterates a few times
    # with a sleep between attempts.
    monkeypatch.setattr("time.sleep", lambda _s: None)
    board_md = _write_full_board(tmp_path)
    body_file = tmp_path / "body.md"
    body_file.write_text("Body.")

    def fake_run(args: list[str], **kw: object) -> FakeGhResult:
        joined = " ".join(args)
        if "issue create" in joined:
            return FakeGhResult(stdout="https://github.com/brockamer/findajob/issues/42\n")
        if "item-add" in joined:
            return FakeGhResult(stdout='{"id": "PVTI_new"}')
        if "item-list" in joined:
            # Simulated regression: issue is on the board but Status is null
            return FakeGhResult(stdout='{"items": [{"id": "PVTI_new", "content": {"number": 42}}]}')
        return FakeGhResult(stdout="{}")

    monkeypatch.setattr(
        "skills.jared.scripts.lib.board.subprocess.run",
        fake_run,
    )

    mod = import_cli()
    rc = mod.main(
        [
            "--board",
            str(board_md),
            "file",
            "--title",
            "Test",
            "--body-file",
            str(body_file),
            "--priority",
            "Low",
        ]
    )
    captured = capsys.readouterr()
    assert rc == 2
    # This test simulates the specific null-Status regression (item present
    # on the board but Status never got set) — distinct from propagation lag.
    # The error message must name the regression, not the generic "may still
    # be on the board" wording used for stale-read failures.
    assert "null" in captured.err.lower()
    assert "regression" in captured.err.lower()


def test_file_verification_retries_through_eventual_consistency(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A stale first item-list followed by a fresh one must succeed.

    Models the real flake observed when filing #9: item-add succeeded, but the
    immediate item-list hadn't propagated yet. With retries, the second poll
    returns the fresh state and the file-command reports success.
    """
    sleep_calls: list[float] = []
    monkeypatch.setattr("time.sleep", lambda s: sleep_calls.append(s))

    board_md = _write_full_board(tmp_path)
    body_file = tmp_path / "body.md"
    body_file.write_text("Body.")

    item_list_calls = 0

    def fake_run(args: list[str], **kw: object) -> FakeGhResult:
        nonlocal item_list_calls
        joined = " ".join(args)
        if "issue create" in joined:
            return FakeGhResult(stdout="https://github.com/brockamer/findajob/issues/42\n")
        if "item-add" in joined:
            return FakeGhResult(stdout='{"id": "PVTI_new"}')
        if "item-list" in joined:
            item_list_calls += 1
            if item_list_calls == 1:
                # Stale first read — item-add hasn't propagated yet.
                return FakeGhResult(stdout='{"items": []}')
            # Second read: propagation caught up, Status is set.
            return FakeGhResult(
                stdout=(
                    '{"items": [{"id": "PVTI_new", '
                    '"content": {"number": 42}, "status": "Backlog"}]}'
                )
            )
        return FakeGhResult(stdout="{}")

    monkeypatch.setattr("skills.jared.scripts.lib.board.subprocess.run", fake_run)

    mod = import_cli()
    rc = mod.main(
        [
            "--board",
            str(board_md),
            "file",
            "--title",
            "Test",
            "--body-file",
            str(body_file),
            "--priority",
            "Low",
        ]
    )
    captured = capsys.readouterr()
    assert rc == 0, captured.err
    assert item_list_calls == 2, (
        f"expected exactly 2 polls (stale, fresh); got {item_list_calls}"
    )
    # Exactly one sleep between the two attempts.
    assert sleep_calls == [1.0], f"expected one 1.0s sleep, got {sleep_calls}"
    assert "OK:" in captured.out


def test_file_verification_failure_message_is_honest_about_ambiguity(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """When all polls are stale, the error message must acknowledge the ambiguity.

    The original bug (#10) shipped a misleading "could not find it on project"
    message that implied the issue wasn't there — when in fact the file call
    succeeded and the propagation lag was the only problem. The new message
    must say "may still be on the board" and point the user at `jared get-item`.
    """
    monkeypatch.setattr("time.sleep", lambda _s: None)
    board_md = _write_full_board(tmp_path)
    body_file = tmp_path / "body.md"
    body_file.write_text("Body.")

    def fake_run(args: list[str], **kw: object) -> FakeGhResult:
        joined = " ".join(args)
        if "issue create" in joined:
            return FakeGhResult(stdout="https://github.com/brockamer/findajob/issues/42\n")
        if "item-add" in joined:
            return FakeGhResult(stdout='{"id": "PVTI_new"}')
        if "item-list" in joined:
            # Never propagates within the retry window.
            return FakeGhResult(stdout='{"items": []}')
        return FakeGhResult(stdout="{}")

    monkeypatch.setattr("skills.jared.scripts.lib.board.subprocess.run", fake_run)

    mod = import_cli()
    rc = mod.main(
        [
            "--board",
            str(board_md),
            "file",
            "--title",
            "Test",
            "--body-file",
            str(body_file),
            "--priority",
            "Low",
        ]
    )
    captured = capsys.readouterr()
    assert rc == 2
    assert "may still be on the board" in captured.err
    assert "jared get-item 42" in captured.err
    # The old misleading "could not find it on project" phrasing must be gone.
    assert "could not find it" not in captured.err
