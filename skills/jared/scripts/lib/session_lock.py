"""Session-presence locking for parallel jared sessions (#231, #236).

Every active `/jared-start` writes a JSON lock file at `<repo>/.jared/session-<pid>.lock`
recording the session's PID, start time, and (if multi-session) the `--session N` value
plus worktree path. This makes the B-leg refusal real: a later `/jared-start` reads
existing locks, checks PID-liveness, and refuses-with-guidance when a sibling is
detected and the operator hasn't opted into multi-session.

See docs/superpowers/specs/2026-05-23-multi-session-impl-design.md for design.
"""

from __future__ import annotations

import contextlib
import enum
import json
import os
import sys
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True)
class Lock:
    """A session-presence record on disk."""

    pid: int
    started: str
    session: int | None
    worktree_path: str | None
    issue: int


def _lock_dir(repo_root: Path) -> Path:
    return repo_root / ".jared"


def _lock_path(repo_root: Path, pid: int) -> Path:
    return _lock_dir(repo_root) / f"session-{pid}.lock"


def write_lock(repo_root: Path, lock: Lock) -> Path:
    """Atomically write a lock file for this session. Returns the path."""
    lockdir = _lock_dir(repo_root)
    lockdir.mkdir(parents=True, exist_ok=True)
    path = _lock_path(repo_root, lock.pid)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(asdict(lock)))
    os.replace(tmp, path)
    return path


def read_lock(path: Path) -> Lock | None:
    """Read and parse a lock file. Returns None if absent or malformed."""
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    try:
        raw_session = payload["session"]
        raw_wt = payload["worktree_path"]
        return Lock(
            pid=int(payload["pid"]),
            started=str(payload["started"]),
            session=None if raw_session is None else int(raw_session),
            worktree_path=None if raw_wt is None else str(raw_wt),
            issue=int(payload["issue"]),
        )
    except (KeyError, TypeError, ValueError):
        return None


def is_alive(pid: int) -> bool:
    """Check whether a process with this PID exists.

    Uses `os.kill(pid, 0)`: ProcessLookupError (ESRCH) means dead;
    PermissionError (EPERM) means alive but not signalable (e.g., init).
    """
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def clear_lock(repo_root: Path, pid: int) -> None:
    """Remove the lock file for this PID. No-op if absent."""
    path = _lock_path(repo_root, pid)
    with contextlib.suppress(FileNotFoundError):
        path.unlink()


def list_active_locks(repo_root: Path) -> list[Lock]:
    """Enumerate all live session locks for this repo. Clears stale entries.

    Walks `<repo>/.jared/session-*.lock`, reads each, drops any with a dead
    PID (deleting the stale file and emitting a one-line stderr warning).
    Malformed lock files are silently skipped — they may be partial writes
    from a crashed write that didn't reach os.replace.
    """
    lockdir = _lock_dir(repo_root)
    if not lockdir.exists():
        return []
    active: list[Lock] = []
    for path in sorted(lockdir.glob("session-*.lock")):
        lock = read_lock(path)
        if lock is None:
            continue
        if is_alive(lock.pid):
            active.append(lock)
        else:
            with contextlib.suppress(OSError):
                path.unlink()
            print(
                f"warning: cleared stale lock for PID {lock.pid} (no longer running): {path}",
                file=sys.stderr,
            )
    return active


class Action(enum.Enum):
    """Resolution outcome for a `/jared-start` invocation."""

    PROCEED_SOLO = "proceed_solo"
    PROCEED_MULTI = "proceed_multi"
    PROCEED_ACK_RISK = "proceed_ack_risk"
    REFUSE_BLEG = "refuse_bleg"
    REFUSE_DUP_SESSION_N = "refuse_dup_session_n"
    REFUSE_CONFLICTING_FLAGS = "refuse_conflicting_flags"


@dataclass(frozen=True)
class Flags:
    """Operator-supplied flags to `/jared-start`."""

    session: int | None
    no_worktree: bool


def resolve_action(siblings: list[Lock], flags: Flags) -> Action:
    """Decide what `/jared-start` should do given current sibling locks and flags.

    Maps to the six-row action table in
    docs/superpowers/specs/2026-05-23-multi-session-impl-design.md § D3.
    Pure function — no I/O, no side effects.
    """
    # --session and --no-worktree are mutually exclusive: one says "isolate me",
    # the other says "I'm accepting the shared-HEAD risk".
    if flags.session is not None and flags.no_worktree:
        return Action.REFUSE_CONFLICTING_FLAGS

    if not siblings:
        if flags.session is not None:
            return Action.PROCEED_MULTI
        return Action.PROCEED_SOLO

    # At least one live sibling.
    if flags.no_worktree:
        # Operator acknowledged the trap explicitly.
        return Action.PROCEED_ACK_RISK

    if flags.session is None:
        # Sibling exists, no flag → refuse with guidance.
        return Action.REFUSE_BLEG

    # flags.session is not None — multi-session opt-in.
    for sib in siblings:
        if sib.session is None:
            # Solo sibling on shared HEAD: this session would be safe in its
            # worktree, but the solo sibling is still on shared HEAD and can
            # still hit the trap. Refuse so the operator handles the sibling first.
            return Action.REFUSE_BLEG
        if sib.session == flags.session:
            return Action.REFUSE_DUP_SESSION_N

    return Action.PROCEED_MULTI
