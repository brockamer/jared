"""Tests for `jared wrap-state` — collects git + PR state, prints next step name."""

from pathlib import Path
from unittest.mock import patch

import pytest

from tests.conftest import import_cli, write_minimal_board


def test_wrap_state_dirty_tree_prints_commit(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    board_md = write_minimal_board(tmp_path)

    with patch("subprocess.run") as mock_run:
        # `git status --porcelain` returns dirty output.
        # `git rev-parse --abbrev-ref HEAD` returns a branch.
        # `git rev-list --count @{u}..HEAD` returns "0".
        # `gh pr view --json ...` returns no PR.
        def _run(cmd, **kwargs):  # type: ignore[no-untyped-def]
            from subprocess import CompletedProcess

            argv = cmd if isinstance(cmd, list) else cmd.split()
            if argv[:2] == ["git", "status"]:
                return CompletedProcess(argv, 0, " M file.py\n", "")
            if argv[:2] == ["git", "rev-parse"]:
                return CompletedProcess(argv, 0, "feature/100-worktree\n", "")
            if argv[:2] == ["git", "rev-list"]:
                return CompletedProcess(argv, 0, "0\n", "")
            if argv[:2] == ["gh", "pr"]:
                return CompletedProcess(argv, 1, "", "no pull requests found")
            return CompletedProcess(argv, 0, "", "")

        mock_run.side_effect = _run

        mod = import_cli()
        rc = mod.main(["--board", str(board_md), "wrap-state"])

    out = capsys.readouterr().out.strip()
    assert rc == 0
    assert out == "commit"


def _patch_pr_view(pr_json: str):  # type: ignore[no-untyped-def]
    """Start a subprocess.run patch: clean tree, not ahead, with a `gh pr view`
    payload of `pr_json`. Caller is responsible for `.stop()`."""
    from subprocess import CompletedProcess
    from unittest.mock import patch

    def _run(cmd, **kwargs):  # type: ignore[no-untyped-def]
        argv = cmd if isinstance(cmd, list) else cmd.split()
        if argv[:2] == ["git", "status"]:
            return CompletedProcess(argv, 0, "", "")
        if argv[:2] == ["git", "rev-parse"]:
            return CompletedProcess(argv, 0, "feature/100-worktree\n", "")
        if argv[:2] == ["git", "rev-list"]:
            return CompletedProcess(argv, 0, "0\n", "")
        if argv[:2] == ["gh", "pr"]:
            return CompletedProcess(argv, 0, pr_json, "")
        return CompletedProcess(argv, 0, "", "")

    p = patch("subprocess.run")
    mock_run = p.start()
    mock_run.side_effect = _run
    return p


def test_wrap_state_review_required_prints_blocked_on_review(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """reviewDecision=REVIEW_REQUIRED must be plumbed into PrState — proven by
    a CLEAN, MERGEABLE PR resolving to blocked_on_review purely on the review
    signal."""
    board_md = write_minimal_board(tmp_path)
    pr_json = (
        '{"number": 42, "mergeable": "MERGEABLE", "mergeStateStatus": "CLEAN", '
        '"state": "OPEN", "statusCheckRollup": [], "reviewDecision": "REVIEW_REQUIRED"}'
    )
    p = _patch_pr_view(pr_json)
    try:
        mod = import_cli()
        rc = mod.main(["--board", str(board_md), "wrap-state"])
    finally:
        p.stop()

    out = capsys.readouterr().out.strip()
    assert rc == 0
    assert out == "blocked_on_review"


def test_wrap_state_behind_prints_update_branch(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """mergeStateStatus=BEHIND must be plumbed into PrState — proven by a
    MERGEABLE PR with no review block resolving to update_branch."""
    board_md = write_minimal_board(tmp_path)
    pr_json = (
        '{"number": 42, "mergeable": "MERGEABLE", "mergeStateStatus": "BEHIND", '
        '"state": "OPEN", "statusCheckRollup": [], "reviewDecision": null}'
    )
    p = _patch_pr_view(pr_json)
    try:
        mod = import_cli()
        rc = mod.main(["--board", str(board_md), "wrap-state"])
    finally:
        p.stop()

    out = capsys.readouterr().out.strip()
    assert rc == 0
    assert out == "update_branch"
