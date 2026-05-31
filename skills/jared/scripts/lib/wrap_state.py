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
    "update_branch",
    "blocked_on_review",
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
    # GitHub's mergeStateStatus (e.g. "CLEAN", "BLOCKED", "BEHIND", "DIRTY")
    # and reviewDecision (e.g. "REVIEW_REQUIRED", "APPROVED", "CHANGES_REQUESTED",
    # or None when the repo has no required reviews). `mergeable` alone can be
    # MERGEABLE while either of these still blocks the merge — see #285.
    merge_state_status: str | None = None
    review_decision: str | None = None


def decide_next_step(git_state: GitState, pr_state: PrState) -> StepName:
    """Pick the next wrap step from current state.

    Precedence (highest first):
      1. Dirty tree → commit (must be addressed before any PR action).
      2. PR merged → cleanup (worktree + branch removal).
      3. Branch ahead of remote → push.
      4. No PR → create_pr.
      5. PR checks pending → wait_checks (exit clean; re-run when green).
      6. PR checks failed → surface_failure (exit clean; operator fixes).
      7. Branch behind base (mergeStateStatus=BEHIND) → update_branch.
      8. Real merge conflict (mergeable=CONFLICTING) → surface_conflict.
      9. Required review not satisfied, or branch protection blocking
         (reviewDecision=REVIEW_REQUIRED or mergeStateStatus=BLOCKED) →
         blocked_on_review. This gates ahead of confirm_merge because GitHub
         reports such a PR as mergeable=MERGEABLE while it cannot actually
         merge — the trap #285 fixes.
      10. Otherwise → confirm_merge.

    `checks_status == "none"` (no CI checks reported) is no longer conflated
    with "passed": it flows to the merge-readiness gates like "passed", so a
    no-CI repo still merges when nothing blocks, but a none-checks PR held by
    review or branch protection is caught by the gates above rather than
    silently confirmed.
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
    if pr_state.merge_state_status == "BEHIND":
        return "update_branch"
    if pr_state.mergeable is False:
        return "surface_conflict"
    if pr_state.review_decision == "REVIEW_REQUIRED" or pr_state.merge_state_status == "BLOCKED":
        return "blocked_on_review"
    return "confirm_merge"
