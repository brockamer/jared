"""git-worktree wrapper for jared (#231).

Creates issue-bound worktrees for parallel Claude sessions per the multi-session
impl spec D1 (path shape) and D5 (collision UX). All functions take an explicit
`repo: Path` argument so they're testable against a tmpdir-scoped git repo
rather than the live working tree.

See docs/superpowers/specs/2026-05-23-multi-session-impl-design.md.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path


class WorktreeError(Exception):
    """Raised when git worktree operations fail in an actionable way."""


@dataclass(frozen=True)
class WorktreeEntry:
    """One worktree as reported by `git worktree list --porcelain`."""

    path: Path
    branch: str | None
    head: str | None


def list_worktrees(repo: Path) -> list[WorktreeEntry]:
    """Parse `git worktree list --porcelain` into structured entries."""
    cmd = ["git", "-C", str(repo), "worktree", "list", "--porcelain"]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise WorktreeError(f"git worktree list failed: {result.stderr.strip()}")

    entries: list[WorktreeEntry] = []
    current: dict[str, str] = {}
    for line in result.stdout.splitlines():
        if not line:
            if current.get("worktree"):
                entries.append(
                    WorktreeEntry(
                        path=Path(current["worktree"]).resolve(),
                        branch=current.get("branch"),
                        head=current.get("HEAD"),
                    )
                )
            current = {}
            continue
        if line.startswith("worktree "):
            current["worktree"] = line[len("worktree ") :]
        elif line.startswith("HEAD "):
            current["HEAD"] = line[len("HEAD ") :]
        elif line.startswith("branch "):
            current["branch"] = line[len("branch ") :]
    if current.get("worktree"):
        entries.append(
            WorktreeEntry(
                path=Path(current["worktree"]).resolve(),
                branch=current.get("branch"),
                head=current.get("HEAD"),
            )
        )
    return entries


def create_worktree(
    repo: Path, target: Path, branch: str, base: str = "origin/main", fetch: bool = False
) -> Path:
    """Create a new worktree at `target` checked out on a fresh `branch`.

    `base` defaults to `origin/main` so session branches are cut from the remote
    tip, not local main — squash-merge leaves local main carrying zombie commits
    that would otherwise ride into every new session branch (#283). When `fetch`
    is true, the base's remote is refreshed before the worktree add so the ref is
    current; callers basing off a remote ref should pass `fetch=True`.

    Handles collisions per spec D5:
    - Path is already a registered worktree → return target (resuming).
    - Path exists but is NOT a registered worktree → raise with remediation.
    - Path does not exist → `git worktree add`.
    """
    target_resolved = target.resolve() if target.exists() else target

    if target.exists():
        registered = {e.path for e in list_worktrees(repo)}
        if target_resolved in registered:
            return target
        raise WorktreeError(
            f"path exists but is not a registered worktree: {target}\n"
            f"  remediation: remove the directory (`rm -rf {target}`) and re-run, "
            f"or run `git -C {repo} worktree remove {target}` if it was once registered."
        )

    if fetch:
        # Refresh the base ref before cutting the branch. Without this, even
        # base=origin/main is only as current as the last fetch (#283).
        remote = base.split("/", 1)[0] if "/" in base else None
        fetch_cmd = ["git", "-C", str(repo), "fetch", *([remote] if remote else [])]
        fetch_result = subprocess.run(fetch_cmd, capture_output=True, text=True)
        if fetch_result.returncode != 0:
            raise WorktreeError(
                f"git fetch failed before worktree add:\n"
                f"  command: {' '.join(fetch_cmd)}\n"
                f"  stderr: {fetch_result.stderr.strip()}"
            )

    cmd = ["git", "-C", str(repo), "worktree", "add", str(target), "-b", branch, base]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise WorktreeError(
            f"git worktree add failed:\n"
            f"  command: {' '.join(cmd)}\n"
            f"  stderr: {result.stderr.strip()}"
        )
    return target
