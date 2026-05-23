"""Session-presence locking for parallel jared sessions (#231, #236).

Every active `/jared-start` writes a JSON lock file at `<repo>/.jared/session-<pid>.lock`
recording the session's PID, start time, and (if multi-session) the `--session N` value
plus worktree path. This makes the B-leg refusal real: a later `/jared-start` reads
existing locks, checks PID-liveness, and refuses-with-guidance when a sibling is
detected and the operator hasn't opted into multi-session.

See docs/superpowers/specs/2026-05-23-multi-session-impl-design.md for design.
"""

from __future__ import annotations

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
