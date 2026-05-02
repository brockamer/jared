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

    # Must invoke the three essentials: issue create, item-add, single graphql mutation.
    assert any("issue" in c and "create" in c for c in calls)
    assert any("item-add" in c for c in calls)

    # Field mutations go through a single `gh api graphql` call now — no item-edit.
    graphql_calls = [c for c in calls if "api" in c and "graphql" in c]
    assert len(graphql_calls) >= 1, "expected at least one gh api graphql call for field mutations"
    joined_graphql = " ".join(" ".join(c) for c in graphql_calls)
    assert "PVTSSF_prio" in joined_graphql and "OPTION_high" in joined_graphql
    assert "PVTSSF_status" in joined_graphql and "OPTION_backlog" in joined_graphql
    assert not any("item-edit" in " ".join(c) for c in calls), (
        "item-edit should be replaced by graphql mutation"
    )

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
    # All three fields land in the single graphql mutation; no item-edit calls.
    joined_graphql = " ".join(" ".join(c) for c in calls if "api" in c and "graphql" in c)
    assert "OPTION_up_next" in joined_graphql
    assert "PVTSSF_ws" in joined_graphql and "OPTION_plan" in joined_graphql
    assert not any("item-edit" in " ".join(c) for c in calls), (
        "item-edit should be replaced by graphql mutation"
    )


def test_file_emits_recovery_command_on_post_create_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Regression test for #64: when post-create fails, `jared file` must
    print the literal `jared add-to-board <N> ...` recovery command to
    stderr instead of leaving the user to reverse-engineer gh project calls.

    Simulates `gh project item-add` failing (the real-world trigger was a
    GH_TOKEN-without-project-scope env override, but any failure in the
    post-create chain should surface the same recovery path).
    """
    board_md = _write_full_board(tmp_path)
    body_file = tmp_path / "body.md"
    body_file.write_text("Body content.")

    issue_number = 142

    def fake_run(args: list[str], **kw: object) -> FakeGhResult:
        joined = " ".join(args)
        if "issue create" in joined:
            return FakeGhResult(
                stdout=f"https://github.com/brockamer/findajob/issues/{issue_number}\n"
            )
        if "item-add" in joined:
            return FakeGhResult(
                stdout="",
                returncode=1,
                stderr=(
                    "GraphQL: Resource not accessible by personal "
                    "access token (addProjectV2ItemById)"
                ),
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
            "High",
            "--status",
            "Up Next",
            "--field",
            "Work Stream=Planning",
        ]
    )
    captured = capsys.readouterr()

    # Non-zero exit so the calling shell knows the filing did not complete.
    assert rc != 0, captured.err

    # Recovery command must be in stderr, with the right issue number,
    # priority, status, and any extra --field values the user passed. The
    # binary path is `Path(__file__).resolve()` of the running CLI so the
    # paste-and-run line points at *this* jared, not bare `jared` (which
    # is typically not on PATH).
    assert "/jared add-to-board" in captured.err, captured.err
    assert str(issue_number) in captured.err, captured.err
    assert "--priority High" in captured.err, captured.err
    assert "'Up Next'" in captured.err, captured.err
    assert "'Work Stream=Planning'" in captured.err, captured.err
    # Underlying gh error context is surfaced too.
    assert "Resource not accessible" in captured.err, captured.err


def test_file_emits_recovery_command_on_field_mutation_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Same recovery contract when failure is *after* item-add succeeds.

    Covers the "network blip on field mutation" failure mode: the issue is on
    the board with an item-id, but the single `gh api graphql` mutation for
    setting fields fails. Recovery line still works because `jared add-to-board`
    is idempotent — it'll find the existing item, skip item-add, and retry
    setting fields.
    """
    board_md = _write_full_board(tmp_path)
    body_file = tmp_path / "body.md"
    body_file.write_text("Body content.")

    issue_number = 142

    def fake_run(args: list[str], **kw: object) -> FakeGhResult:
        joined = " ".join(args)
        if "issue create" in joined:
            return FakeGhResult(
                stdout=f"https://github.com/brockamer/findajob/issues/{issue_number}\n"
            )
        if "item-add" in joined:
            return FakeGhResult(stdout='{"id": "PVTI_new"}')
        if "api" in joined and "graphql" in joined and "updateProjectV2" in joined:
            return FakeGhResult(
                stdout="",
                returncode=1,
                stderr="GraphQL: rate limit exceeded (updateProjectV2ItemFieldValue)",
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
            "Medium",
        ]
    )
    captured = capsys.readouterr()
    assert rc != 0, captured.err
    assert "/jared add-to-board" in captured.err, captured.err
    assert str(issue_number) in captured.err, captured.err
    assert "--priority Medium" in captured.err, captured.err
    assert "rate limit exceeded" in captured.err, captured.err


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
    # Expected call ceiling: issue create + item-add + 1 graphql mutation = 3.
    # All field-setting (Priority + Status + extras) is batched into one call.
    # Allow the test to flex by asserting an upper bound rather than equality.
    assert len(calls) <= 4, (
        f"`jared file` made {len(calls)} gh calls; expected ≤4. Calls:\n"
        + "\n".join(" ".join(c) for c in calls)
    )
