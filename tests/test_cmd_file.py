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

    # Must invoke the three essentials: issue create, item-add, field edits.
    assert any("issue" in c and "create" in c for c in calls)
    assert any("item-add" in c for c in calls)

    edits = [c for c in calls if "item-edit" in c]
    assert len(edits) >= 2, "expected at least Priority + Status item-edit calls"
    joined_edits = " ".join(" ".join(c) for c in edits)
    assert "PVTSSF_prio" in joined_edits and "OPTION_high" in joined_edits
    assert "PVTSSF_status" in joined_edits and "OPTION_backlog" in joined_edits

    # No item-list in the filing path — that's the #4 regression we guard
    # against. See test_file_makes_no_item_list_calls for the explicit pin.
    assert not any("item-list" in " ".join(c) for c in calls)


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


def test_file_makes_no_item_list_calls(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Regression test for #4: `jared file` must not call `gh project item-list`.

    Before the fix, `_cmd_file` re-read the whole project (up to 500 items, up
    to 3 times via poll-with-backoff) to verify the item landed and Status was
    set. That scan drained the 5,000/hr GraphQL budget inside ~11 issues during
    batch filing. Removing the verify entirely drops the filing cost to just
    the writes (item-add + N field-edits); gh's exit-0 on each mutation is the
    proof the write landed.
    """
    board_md = _write_full_board(tmp_path)
    body_file = tmp_path / "body.md"
    body_file.write_text("Body.")
    calls: list[list[str]] = []

    def fake_run(args: list[str], **kw: object) -> FakeGhResult:
        calls.append(args)
        joined = " ".join(args)
        if "issue create" in joined:
            return FakeGhResult(stdout="https://github.com/brockamer/findajob/issues/42\n")
        if "item-add" in joined:
            return FakeGhResult(stdout='{"id": "PVTI_new"}')
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
    # Nothing in the call stream should scan the project via `item-list`.
    for c in calls:
        joined = " ".join(c)
        assert "item-list" not in joined, f"`jared file` should not call item-list; got: {joined!r}"
    # Expected call ceiling: issue create + item-add + item-edit × 2 (Status,
    # Priority) = 4. Gives AC headroom of 1 for an extra --field if present.
    # Allow the test to flex by asserting an upper bound rather than equality,
    # since argparse or gh version changes could introduce an extra query we
    # haven't noticed.
    assert len(calls) <= 5, (
        f"`jared file` made {len(calls)} gh calls; expected ≤5. Calls:\n"
        + "\n".join(" ".join(c) for c in calls)
    )
