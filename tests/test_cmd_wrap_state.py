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
