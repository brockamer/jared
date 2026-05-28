"""Wrap back-end state detection — pure function, no I/O.

The wrap slash command collects git state via `git status` and PR state via
`gh pr view --json ...`, hands them to `decide_next_step`, and acts on the
returned `StepName`. Re-running wrap re-evaluates state and picks up at
whichever step is current — no in-flight lock needed; state IS the lock.

See docs/superpowers/specs/2026-05-28-multi-session-back-end-design.md §
"Phase 3 — Wrap back-end" for the full state table and rationale.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

CheckStatus = Literal["pending", "passed", "failed", "none"]
StepName = Literal[
    "commit",
    "push",
    "create_pr",
    "wait_checks",
    "surface_failure",
    "surface_conflict",
    "confirm_merge",
    "cleanup",
]


@dataclass(frozen=True)
class GitState:
    """Working-tree + branch state at wrap entry."""

    dirty: bool
    branch: str
    ahead_of_remote: bool


@dataclass(frozen=True)
class PrState:
    """Pull request state for the current branch."""

    exists: bool
    pr_number: int | None
    checks_status: CheckStatus
    mergeable: bool | None
    merged: bool


def decide_next_step(git_state: GitState, pr_state: PrState) -> StepName:
    """Pick the next wrap step from current state.

    Precedence (highest first):
      1. Dirty tree → commit (must be addressed before any PR action).
      2. PR merged → cleanup (worktree + branch removal).
      3. Branch ahead of remote → push.
      4. No PR → create_pr.
      5. PR checks pending → wait_checks (exit clean; re-run when green).
      6. PR checks failed → surface_failure (exit clean; operator fixes).
      7. PR checks green, not mergeable → surface_conflict (rebase needed).
      8. PR checks green, mergeable → confirm_merge.
    """
    if git_state.dirty:
        return "commit"
    if pr_state.merged:
        return "cleanup"
    if git_state.ahead_of_remote:
        return "push"
    if not pr_state.exists:
        return "create_pr"
    if pr_state.checks_status == "pending":
        return "wait_checks"
    if pr_state.checks_status == "failed":
        return "surface_failure"
    # checks_status == "passed" (or "none" — treated as passed for now)
    if pr_state.mergeable is False:
        return "surface_conflict"
    return "confirm_merge"
