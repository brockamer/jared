"""Session-presence locking for parallel jared sessions (#231, #236, #259).

Every active `/jared-start` writes a JSON lock file at `<repo>/.jared/session-<issue>.lock`
recording the issue, start time, optional `--session N` value, worktree path, and the
writing process's PID (diagnostic only). The lock is keyed by issue, not PID: the
CLI subprocess that writes the lock exits immediately, so a PID-keyed file would be
dead-on-arrival and the B-leg refusal would never fire (the original #231/#236
implementation had this defect — #259 fixes it).

Locks live until explicitly cleared by `/jared-wrap` (or `jared session-lock-clear
--issue N`). A crashed session leaves its lock on disk; the next `/jared-start` will
detect it and refuse with guidance, including the recorded PID so the operator can
verify and force-clear if appropriate.

See docs/superpowers/specs/2026-05-23-multi-session-impl-design.md for original design;
this module's identity model was reworked in #259 after empirical evidence that
PID-keyed locks were stale-on-arrival.
"""

from __future__ import annotations

import contextlib
import enum
import json
import os
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
    # `.resolve()` anchors `.jared/` at the true (absolute) repo root even when
    # the caller passes a relative root — e.g. REPO_ROOT collapsing to '.' in the
    # main checkout (#284). A cwd-relative lock dir breaks cross-session sibling
    # detection. Every lock path flows through here, so this is the single net.
    return repo_root.resolve() / ".jared"


def _lock_path(repo_root: Path, issue: int) -> Path:
    return _lock_dir(repo_root) / f"session-{issue}.lock"


def write_lock(repo_root: Path, lock: Lock) -> Path:
    """Atomically write a lock file for this session. Returns the path."""
    lockdir = _lock_dir(repo_root)
    lockdir.mkdir(parents=True, exist_ok=True)
    path = _lock_path(repo_root, lock.issue)
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


def clear_lock(repo_root: Path, issue: int) -> None:
    """Remove the lock file for this issue. No-op if absent."""
    path = _lock_path(repo_root, issue)
    with contextlib.suppress(FileNotFoundError):
        path.unlink()


def list_active_locks(repo_root: Path) -> list[Lock]:
    """Enumerate all session locks on disk for this repo.

    Walks `<repo>/.jared/session-*.lock` and reads each. Malformed lock files
    are silently skipped — they may be partial writes from a crashed write
    that didn't reach os.replace. Old-style locks left over from the pre-#259
    PID-keyed naming (filename number ≠ recorded `issue` field) are removed
    opportunistically — this is the only automatic migration path for in-place
    upgrades from pre-#259 installs.

    No PID-liveness sweep is performed: the CLI subprocess's PID (only recorded
    diagnostically) is always dead by the time anything reads the file. A
    crashed session leaves its lock on disk; the operator clears it explicitly
    with `jared session-lock-clear --issue N` when the next `/jared-start`
    surfaces the orphan.
    """
    lockdir = _lock_dir(repo_root)
    if not lockdir.exists():
        return []
    active: list[Lock] = []
    for path in sorted(lockdir.glob("session-*.lock")):
        lock = read_lock(path)
        if lock is None:
            continue
        # Migration: pre-#259 lock filenames were session-<pid>.lock; their
        # filename number won't match the lock's `issue` field. Issue-keyed
        # writes (#259 onward) always satisfy filename_number == lock.issue.
        try:
            filename_number = int(path.stem.removeprefix("session-"))
        except ValueError:
            filename_number = -1
        if filename_number != lock.issue:
            with contextlib.suppress(OSError):
                path.unlink()
            continue
        active.append(lock)
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

    # flags.session is not None — multi-session opt-in. Two-pass scan so
    # the refusal reason is deterministic regardless of sibling order.
    # Solo-sibling refusal takes priority: it surfaces the actual trap shape
    # (sibling on shared HEAD) which is more actionable than a flag collision.
    for sib in siblings:
        if sib.session is None:
            return Action.REFUSE_BLEG
    for sib in siblings:
        if sib.session == flags.session:
            return Action.REFUSE_DUP_SESSION_N

    return Action.PROCEED_MULTI
