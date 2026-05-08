"""Tests for `jared add-to-board <N>` — the recovery path / standalone-add subcommand.

The subcommand was added alongside #64 to make `jared file` failures
recoverable: when the post-create chain breaks, `_cmd_file` prints a
literal `jared add-to-board <N> ...` line, and the user pastes it back.
The same subcommand also serves the legitimate "I created the issue
manually, now put it on the board" flow.

Idempotency invariant tested below: calling the subcommand on an issue
already on the board should *not* call `gh project item-add` again — it
should reuse the existing item-id discovered by `find_item_id`.
"""

from pathlib import Path
from textwrap import dedent

import pytest

from tests.conftest import FakeGhResult, graphql_item_response, import_cli


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


def test_add_to_board_when_issue_not_on_board(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Issue absent from board → item-list (membership check) → item-add → graphql mutation."""
    board_md = _write_full_board(tmp_path)
    calls: list[list[str]] = []

    def fake_run(args: list[str], **kw: object) -> FakeGhResult:
        calls.append(args)
        joined = " ".join(args)
        if "api" in joined and "graphql" in joined and "item-add" not in joined:
            # fetch_item_for_issue: issue not on board.
            return FakeGhResult(
                stdout='{"data":{"repository":{"issue":{"projectItems":{"nodes":[]}}}}}'
            )
        if "item-add" in joined:
            return FakeGhResult(stdout='{"id": "PVTI_new"}')
        return FakeGhResult(stdout="{}")

    monkeypatch.setattr("skills.jared.scripts.lib.board.subprocess.run", fake_run)

    mod = import_cli()
    rc = mod.main(
        [
            "--board",
            str(board_md),
            "add-to-board",
            "142",
            "--priority",
            "High",
            "--status",
            "Up Next",
            "--field",
            "Work Stream=Planning",
        ]
    )
    captured = capsys.readouterr()
    assert rc == 0, captured.err

    # fetch_item_for_issue: not on board → item-add.
    assert any("item-add" in " ".join(c) for c in calls)

    # Two graphql calls: one fetch_item_for_issue lookup + one batched field mutation.
    graphql_calls = [c for c in calls if "api" in c and "graphql" in c]
    assert len(graphql_calls) == 2, (
        f"expected exactly 2 graphql calls (lookup + mutations), got {len(graphql_calls)}: {calls}"
    )
    mutation_call = " ".join(graphql_calls[1])
    assert "PVTSSF_prio" in mutation_call and "OPTION_high" in mutation_call
    assert "PVTSSF_status" in mutation_call and "OPTION_up_next" in mutation_call
    assert "PVTSSF_ws" in mutation_call and "OPTION_plan" in mutation_call
    assert not any("item-edit" in " ".join(c) for c in calls), (
        "item-edit should be replaced by graphql mutation"
    )


def test_add_to_board_idempotent_when_issue_already_on_board(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Issue already on board → item-list finds it → NO item-add → single graphql mutation.

    Confirms the helper re-uses an existing item-id rather than calling
    `gh project item-add` (which would either error or duplicate). This is
    the safety property that makes the recovery flow re-runnable without
    surprises if the user re-pastes the recovery command after a partial
    re-success.
    """
    board_md = _write_full_board(tmp_path)
    calls: list[list[str]] = []

    def fake_run(args: list[str], **kw: object) -> FakeGhResult:
        calls.append(args)
        joined = " ".join(args)
        if "api" in joined and "graphql" in joined and "item-add" not in joined:
            # fetch_item_for_issue: issue already on board.
            return FakeGhResult(
                stdout=graphql_item_response(project_number=7, item_id="PVTI_existing")
            )
        # If the helper ever calls item-add here, the test should still
        # complete — but the assertion below catches the regression.
        return FakeGhResult(stdout="{}")

    monkeypatch.setattr("skills.jared.scripts.lib.board.subprocess.run", fake_run)

    mod = import_cli()
    rc = mod.main(
        [
            "--board",
            str(board_md),
            "add-to-board",
            "142",
            "--priority",
            "Medium",
            "--status",
            "Backlog",
        ]
    )
    captured = capsys.readouterr()
    assert rc == 0, captured.err

    # The whole point of the idempotency property: no item-add.
    assert not any("item-add" in " ".join(c) for c in calls), (
        f"add-to-board should re-use the existing item-id, not call item-add. Calls: {calls}"
    )

    # Two graphql calls: one fetch_item_for_issue lookup + one batched field mutation.
    graphql_calls = [c for c in calls if "api" in c and "graphql" in c]
    assert len(graphql_calls) == 2, (
        f"expected exactly 2 graphql calls (lookup + mutations), got {len(graphql_calls)}: {calls}"
    )
    mutation_call = " ".join(graphql_calls[1])
    assert "PVTI_existing" in mutation_call, mutation_call
    assert "PVTSSF_prio" in mutation_call and "OPTION_med" in mutation_call
    assert "PVTSSF_status" in mutation_call and "OPTION_backlog" in mutation_call
    assert not any("item-edit" in " ".join(c) for c in calls), (
        "item-edit should be replaced by graphql mutation"
    )


def test_add_to_board_applies_labels_when_provided(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """`--label` translates to `gh issue edit --add-label` (not item-edit)."""
    board_md = _write_full_board(tmp_path)
    calls: list[list[str]] = []

    def fake_run(args: list[str], **kw: object) -> FakeGhResult:
        calls.append(args)
        joined = " ".join(args)
        if "item-list" in joined:
            return FakeGhResult(stdout='{"items": []}')
        if "item-add" in joined:
            return FakeGhResult(stdout='{"id": "PVTI_new"}')
        return FakeGhResult(stdout="{}")

    monkeypatch.setattr("skills.jared.scripts.lib.board.subprocess.run", fake_run)

    mod = import_cli()
    rc = mod.main(
        [
            "--board",
            str(board_md),
            "add-to-board",
            "142",
            "--priority",
            "Low",
            "--label",
            "bug",
            "--label",
            "documentation",
        ]
    )
    captured = capsys.readouterr()
    assert rc == 0, captured.err

    issue_edits = [c for c in calls if "issue" in c and "edit" in c]
    assert len(issue_edits) == 1, issue_edits
    label_call = " ".join(issue_edits[0])
    assert "--add-label bug" in label_call
    assert "--add-label documentation" in label_call


def test_add_to_board_rejects_malformed_field_spec(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """`--field` without `=` → exit 1, matches `_cmd_file` behavior."""
    board_md = _write_full_board(tmp_path)

    def fake_run(args: list[str], **kw: object) -> FakeGhResult:
        return FakeGhResult(stdout="{}")

    monkeypatch.setattr("skills.jared.scripts.lib.board.subprocess.run", fake_run)

    mod = import_cli()
    rc = mod.main(
        [
            "--board",
            str(board_md),
            "add-to-board",
            "142",
            "--priority",
            "Low",
            "--field",
            "no-equals-sign",
        ]
    )
    captured = capsys.readouterr()
    assert rc == 1
    assert "NAME=VALUE" in captured.err
