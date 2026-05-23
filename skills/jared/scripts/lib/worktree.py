"""git-worktree wrapper for jared (#231).

Creates issue-bound worktrees for parallel Claude sessions per the multi-session
impl spec D1 (path shape) and D5 (collision UX). All functions take an explicit
`repo: Path` argument so they're testable against a tmpdir-scoped git repo
rather than the live working tree.

See docs/superpowers/specs/2026-05-23-multi-session-impl-design.md.
"""

from __future__ import annotations

import subprocess
from pathlib import Path


class WorktreeError(Exception):
    """Raised when git worktree operations fail in an actionable way."""


def create_worktree(repo: Path, target: Path, branch: str, base: str = "main") -> Path:
    """Create a new worktree at `target` checked out on a fresh `branch`.

    Equivalent to `git -C <repo> worktree add <target> -b <branch> <base>`.
    Returns the target path on success; raises WorktreeError on failure.
    """
    cmd = ["git", "-C", str(repo), "worktree", "add", str(target), "-b", branch, base]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise WorktreeError(
            f"git worktree add failed:\n"
            f"  command: {' '.join(cmd)}\n"
            f"  stderr: {result.stderr.strip()}"
        )
    return target
