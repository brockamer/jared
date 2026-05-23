"""Integration tests for lib/worktree.py — real `git worktree` in tmpdir (#231).

These tests prove the structural isolation between main checkout and worktree
is real: independent HEAD refs, independent branch switches, independent commits.

This is the test that maps to issue #231's acceptance criterion
"trap can no longer fire" — it's not enough to verify the detection logic
correctness; we have to verify the git operation itself produces isolation.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from skills.jared.scripts.lib import worktree


def _git(repo: Path, *args: str) -> str:
    """Run a git command in `repo` and return stdout (stripped)."""
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


@pytest.fixture
def main_repo(tmp_path: Path) -> Path:
    """Create a fresh git repo with one commit on `main`."""
    repo = tmp_path / "main-repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "test")
    (repo / "README.md").write_text("initial\n")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-m", "initial")
    return repo


def test_create_worktree_at_sibling_path(main_repo: Path, tmp_path: Path) -> None:
    target = tmp_path / "main-repo-231"
    branch = "feature/231-test"
    result = worktree.create_worktree(repo=main_repo, target=target, branch=branch, base="main")
    assert result == target
    assert target.exists()
    assert (target / "README.md").exists()
    # The worktree's HEAD should be on the new branch.
    head = _git(target, "rev-parse", "--abbrev-ref", "HEAD")
    assert head == branch


def test_worktree_has_independent_head(main_repo: Path, tmp_path: Path) -> None:
    """The acceptance-criterion test: branch switches in main do not propagate to the worktree."""
    target = tmp_path / "main-repo-231"
    worktree.create_worktree(repo=main_repo, target=target, branch="feature/231-test", base="main")

    # Sanity: both checkouts point at independent ref locations.
    main_git_dir = _git(main_repo, "rev-parse", "--absolute-git-dir")
    worktree_git_dir = _git(target, "rev-parse", "--absolute-git-dir")
    assert main_git_dir != worktree_git_dir

    # Create a second branch in the main checkout. The worktree's HEAD should not move.
    _git(main_repo, "checkout", "-b", "feature/other")
    main_head = _git(main_repo, "rev-parse", "--abbrev-ref", "HEAD")
    worktree_head = _git(target, "rev-parse", "--abbrev-ref", "HEAD")
    assert main_head == "feature/other"
    assert worktree_head == "feature/231-test"


def test_commit_in_worktree_lands_on_worktree_branch(main_repo: Path, tmp_path: Path) -> None:
    target = tmp_path / "main-repo-231"
    worktree.create_worktree(repo=main_repo, target=target, branch="feature/231-test", base="main")

    (target / "worktree-only.txt").write_text("from worktree\n")
    _git(target, "add", "worktree-only.txt")
    _git(target, "commit", "-m", "from worktree")

    # The worktree-only commit must NOT be visible on main.
    main_log = _git(main_repo, "log", "main", "--oneline")
    assert "from worktree" not in main_log

    # But IS visible on the worktree's branch (via the shared object database).
    worktree_log = _git(main_repo, "log", "feature/231-test", "--oneline")
    assert "from worktree" in worktree_log


def test_list_worktrees_includes_main(main_repo: Path) -> None:
    entries = worktree.list_worktrees(repo=main_repo)
    paths = [e.path for e in entries]
    assert main_repo in paths


def test_list_worktrees_includes_added_worktrees(main_repo: Path, tmp_path: Path) -> None:
    target = tmp_path / "main-repo-231"
    worktree.create_worktree(repo=main_repo, target=target, branch="feature/231-test", base="main")
    entries = worktree.list_worktrees(repo=main_repo)
    paths = [e.path for e in entries]
    assert target in paths
    assert main_repo in paths


def test_create_worktree_at_existing_registered_path_returns_existing(
    main_repo: Path, tmp_path: Path
) -> None:
    """Common shape: laptop crashed, ~/Code/jared-231/ still exists and is registered.
    create_worktree returns the existing path rather than failing."""
    target = tmp_path / "main-repo-231"
    worktree.create_worktree(repo=main_repo, target=target, branch="feature/231-test", base="main")

    # Second call — same target, expect to resume.
    result = worktree.create_worktree(
        repo=main_repo,
        target=target,
        branch="feature/231-test",
        base="main",
    )
    assert result == target


def test_create_worktree_at_orphan_path_raises(main_repo: Path, tmp_path: Path) -> None:
    """Path exists but is NOT a registered worktree — error with remediation."""
    target = tmp_path / "main-repo-231"
    target.mkdir()
    (target / "stray.txt").write_text("not a worktree\n")
    with pytest.raises(worktree.WorktreeError) as exc_info:
        worktree.create_worktree(
            repo=main_repo, target=target, branch="feature/231-test", base="main"
        )
    msg = str(exc_info.value)
    assert "not a registered worktree" in msg.lower() or "exists" in msg.lower()
    assert str(target) in msg
