"""Scenario tests for session_lock.resolve_action — the six-row detection action table.

Maps directly to docs/superpowers/specs/2026-05-23-multi-session-impl-design.md § D3.
"""

from __future__ import annotations

from skills.jared.scripts.lib import session_lock
from skills.jared.scripts.lib.session_lock import Action, Flags, Lock


def _solo_sibling() -> Lock:
    return Lock(
        pid=12847, started="2026-05-23T14:00:00Z", session=None, worktree_path=None, issue=200
    )


def _multi_sibling(n: int) -> Lock:
    return Lock(
        pid=12847 + n,
        started="2026-05-23T14:00:00Z",
        session=n,
        worktree_path=f"/home/u/Code/jared-{200 + n}",
        issue=200 + n,
    )


def test_no_siblings_solo_flags_proceeds_solo() -> None:
    action = session_lock.resolve_action(siblings=[], flags=Flags(session=None, no_worktree=False))
    assert action == Action.PROCEED_SOLO


def test_no_siblings_multi_flag_proceeds_multi() -> None:
    action = session_lock.resolve_action(siblings=[], flags=Flags(session=1, no_worktree=False))
    assert action == Action.PROCEED_MULTI


def test_conflicting_flags_refused() -> None:
    action = session_lock.resolve_action(
        siblings=[],
        flags=Flags(session=1, no_worktree=True),
    )
    assert action == Action.REFUSE_CONFLICTING_FLAGS


def test_solo_flags_with_any_sibling_refused() -> None:
    action = session_lock.resolve_action(
        siblings=[_solo_sibling()], flags=Flags(session=None, no_worktree=False)
    )
    assert action == Action.REFUSE_BLEG
    action = session_lock.resolve_action(
        siblings=[_multi_sibling(2)], flags=Flags(session=None, no_worktree=False)
    )
    assert action == Action.REFUSE_BLEG


def test_multi_flag_with_solo_sibling_refused() -> None:
    # Solo sibling on shared HEAD is exactly the trap shape — must be refused.
    action = session_lock.resolve_action(
        siblings=[_solo_sibling()],
        flags=Flags(session=2, no_worktree=False),
    )
    assert action == Action.REFUSE_BLEG


def test_multi_flag_with_different_n_sibling_proceeds() -> None:
    action = session_lock.resolve_action(
        siblings=[_multi_sibling(1)],
        flags=Flags(session=2, no_worktree=False),
    )
    assert action == Action.PROCEED_MULTI


def test_multi_flag_with_same_n_sibling_refused() -> None:
    action = session_lock.resolve_action(
        siblings=[_multi_sibling(1)],
        flags=Flags(session=1, no_worktree=False),
    )
    assert action == Action.REFUSE_DUP_SESSION_N


def test_no_worktree_ack_with_any_sibling_proceeds() -> None:
    # Operator explicitly accepted the trap risk.
    action = session_lock.resolve_action(
        siblings=[_solo_sibling()],
        flags=Flags(session=None, no_worktree=True),
    )
    assert action == Action.PROCEED_ACK_RISK
    action = session_lock.resolve_action(
        siblings=[_multi_sibling(2)],
        flags=Flags(session=None, no_worktree=True),
    )
    assert action == Action.PROCEED_ACK_RISK
