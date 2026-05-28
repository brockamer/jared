"""Tests for the wrap state-detection table.

The pure function `decide_next_step(git_state, pr_state)` is the spine of the
wrap back-end flow's idempotency: each step inspects state and decides whether
to act, so re-running wrap picks up at the same step.
"""

from skills.jared.scripts.lib.wrap_state import (
    CheckStatus,
    GitState,
    PrState,
    decide_next_step,
)


def _git(dirty: bool = False, ahead: bool = False) -> GitState:
    return GitState(dirty=dirty, branch="feature/100-worktree", ahead_of_remote=ahead)


def _pr(
    *,
    exists: bool = False,
    checks: CheckStatus = "none",
    mergeable: bool | None = None,
    merged: bool = False,
) -> PrState:
    return PrState(
        exists=exists,
        pr_number=42 if exists else None,
        checks_status=checks,
        mergeable=mergeable,
        merged=merged,
    )


def test_decide_dirty_tree_returns_commit() -> None:
    assert decide_next_step(_git(dirty=True), _pr()) == "commit"


def test_decide_ahead_no_pr_returns_push() -> None:
    assert decide_next_step(_git(ahead=True), _pr()) == "push"


def test_decide_clean_no_pr_returns_create_pr() -> None:
    assert decide_next_step(_git(), _pr()) == "create_pr"


def test_decide_pr_checks_pending_returns_wait_checks() -> None:
    assert decide_next_step(_git(), _pr(exists=True, checks="pending")) == "wait_checks"


def test_decide_pr_checks_failed_returns_surface_failure() -> None:
    assert decide_next_step(_git(), _pr(exists=True, checks="failed")) == "surface_failure"


def test_decide_pr_checks_green_not_mergeable_returns_surface_conflict() -> None:
    assert (
        decide_next_step(_git(), _pr(exists=True, checks="passed", mergeable=False))
        == "surface_conflict"
    )


def test_decide_pr_checks_green_mergeable_returns_confirm_merge() -> None:
    assert (
        decide_next_step(_git(), _pr(exists=True, checks="passed", mergeable=True))
        == "confirm_merge"
    )


def test_decide_pr_merged_returns_cleanup() -> None:
    assert decide_next_step(_git(), _pr(exists=True, merged=True)) == "cleanup"


def test_decide_dirty_tree_takes_precedence_over_pr_state() -> None:
    """Dirty working tree must be addressed before any PR-side action."""
    assert (
        decide_next_step(
            _git(dirty=True),
            _pr(exists=True, checks="passed", mergeable=True),
        )
        == "commit"
    )
