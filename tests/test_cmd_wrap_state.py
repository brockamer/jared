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


# --- F7 (#371): token scrub + failure/no-PR disambiguation -------------------


def _patch_pr_view_failure(returncode: int, stderr: str):  # type: ignore[no-untyped-def]
    """Clean tree, not ahead, with `gh pr view` exiting non-zero.

    Returns (patcher, calls) where `calls` accumulates (argv, kwargs) so a
    test can assert on the environment the gh call was given.
    """
    from subprocess import CompletedProcess
    from unittest.mock import patch

    calls: list[tuple[list[str], dict[str, object]]] = []

    def _run(cmd, **kwargs):  # type: ignore[no-untyped-def]
        argv = cmd if isinstance(cmd, list) else cmd.split()
        calls.append((argv, kwargs))
        if argv[:2] == ["git", "status"]:
            return CompletedProcess(argv, 0, "", "")
        if argv[:2] == ["git", "rev-parse"]:
            return CompletedProcess(argv, 0, "feature/100-worktree\n", "")
        if argv[:2] == ["git", "rev-list"]:
            return CompletedProcess(argv, 0, "0\n", "")
        if argv[:2] == ["gh", "pr"]:
            return CompletedProcess(argv, returncode, "", stderr)
        return CompletedProcess(argv, 0, "", "")

    p = patch("subprocess.run")
    p.start().side_effect = _run
    return p, calls


@pytest.mark.parametrize(
    "stderr",
    [
        'no pull requests found for branch "feature/100-worktree"',
        'no open pull requests found for branch "feature/100-worktree"',
        "No pull requests found for branch 'x'",
    ],
)
def test_wrap_state_no_pr_still_prints_create_pr(
    stderr: str,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The genuine no-PR case must keep working across gh's wordings."""
    board_md = write_minimal_board(tmp_path)
    p, _ = _patch_pr_view_failure(1, stderr)
    try:
        mod = import_cli()
        rc = mod.main(["--board", str(board_md), "wrap-state"])
    finally:
        p.stop()

    captured = capsys.readouterr()
    assert rc == 0
    assert captured.out.strip() == "create_pr"


@pytest.mark.parametrize(
    "stderr",
    [
        "gh: Not Found (HTTP 404)",
        "error connecting to api.github.com: dial tcp: lookup api.github.com: no such host",
        "gh: API rate limit exceeded",
        "",
    ],
)
def test_wrap_state_gh_failure_is_not_reported_as_no_pr(
    stderr: str,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A `gh pr view` failure must not collapse into "no PR exists".

    Both cases exit 1, so collapsing them makes wrap tell the operator to
    open a PR that may already exist. Refuse instead of guessing.
    """
    board_md = write_minimal_board(tmp_path)
    p, _ = _patch_pr_view_failure(1, stderr)
    try:
        mod = import_cli()
        rc = mod.main(["--board", str(board_md), "wrap-state"])
    finally:
        p.stop()

    captured = capsys.readouterr()
    assert rc != 0, "a gh failure must exit non-zero"
    assert "create_pr" not in captured.out
    assert "gh pr view" in captured.err
    if stderr:
        assert stderr in captured.err, "the operator needs gh's own message"


def test_wrap_state_gh_call_scrubs_github_tokens(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """The `gh pr view` call must go through the #65 token scrub.

    GH_TOKEN/GITHUB_TOKEN shadow the OAuth session gh auth login established,
    so an operator with a low-scope PAT set gets a confusing failure here
    while every other jared gh call succeeds.
    """
    board_md = write_minimal_board(tmp_path)
    monkeypatch.setenv("GH_TOKEN", "ghp_fake_pat_should_be_scrubbed")
    monkeypatch.setenv("GITHUB_TOKEN", "ghs_fake_should_be_scrubbed")
    monkeypatch.setenv("JARED_SENTINEL", "kept")

    p, calls = _patch_pr_view_failure(1, "no pull requests found for branch x")
    try:
        mod = import_cli()
        mod.main(["--board", str(board_md), "wrap-state"])
    finally:
        p.stop()

    gh_calls = [(argv, kwargs) for argv, kwargs in calls if argv[:2] == ["gh", "pr"]]
    assert gh_calls, "gh pr view was never invoked"
    _, kwargs = gh_calls[0]

    env = kwargs.get("env")
    assert env is not None, "gh pr view was invoked without an explicit env"
    assert "GH_TOKEN" not in env
    assert "GITHUB_TOKEN" not in env
    assert env.get("JARED_SENTINEL") == "kept", "the rest of the env must survive"
