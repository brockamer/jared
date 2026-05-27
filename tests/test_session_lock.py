"""Unit tests for lib/session_lock.py — session-presence locks (#231, #259)."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from skills.jared.scripts.lib import session_lock


def test_lock_round_trips_through_disk(tmp_path: Path) -> None:
    lock = session_lock.Lock(
        pid=12847,
        started="2026-05-23T14:22:00Z",
        session=1,
        worktree_path="/home/u/Code/jared-231",
        issue=231,
    )
    path = session_lock.write_lock(repo_root=tmp_path, lock=lock)
    assert path == tmp_path / ".jared" / "session-231.lock"
    assert path.exists()

    loaded = session_lock.read_lock(path)
    assert loaded == lock


def test_read_lock_returns_none_when_file_absent(tmp_path: Path) -> None:
    path = tmp_path / ".jared" / "session-99999.lock"
    assert session_lock.read_lock(path) is None


def test_read_lock_returns_none_when_json_corrupted(tmp_path: Path) -> None:
    lockdir = tmp_path / ".jared"
    lockdir.mkdir()
    path = lockdir / "session-231.lock"
    path.write_text("{not json")
    assert session_lock.read_lock(path) is None


def test_write_lock_with_solo_session(tmp_path: Path) -> None:
    lock = session_lock.Lock(
        pid=12847,
        started="2026-05-23T14:22:00Z",
        session=None,
        worktree_path=None,
        issue=231,
    )
    path = session_lock.write_lock(repo_root=tmp_path, lock=lock)
    loaded = session_lock.read_lock(path)
    assert loaded is not None
    assert loaded.session is None
    assert loaded.worktree_path is None


def test_is_alive_returns_true_for_current_process() -> None:
    assert session_lock.is_alive(os.getpid()) is True


def test_is_alive_returns_false_for_dead_pid(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_kill(pid: int, sig: int) -> None:
        raise ProcessLookupError()

    monkeypatch.setattr(os, "kill", fake_kill)
    assert session_lock.is_alive(9999999) is False


def test_is_alive_returns_true_when_permission_denied(monkeypatch: pytest.MonkeyPatch) -> None:
    # init (PID 1) typically gives EPERM rather than ESRCH — the process IS alive.
    def fake_kill(pid: int, sig: int) -> None:
        raise PermissionError()

    monkeypatch.setattr(os, "kill", fake_kill)
    assert session_lock.is_alive(1) is True


def test_list_active_locks_empty_when_no_lockdir(tmp_path: Path) -> None:
    assert session_lock.list_active_locks(repo_root=tmp_path) == []


def test_list_active_locks_returns_existing_locks(tmp_path: Path) -> None:
    lock = session_lock.Lock(
        pid=os.getpid(),
        started="2026-05-23T14:22:00Z",
        session=1,
        worktree_path=None,
        issue=231,
    )
    session_lock.write_lock(repo_root=tmp_path, lock=lock)
    active = session_lock.list_active_locks(repo_root=tmp_path)
    assert len(active) == 1
    assert active[0] == lock


def test_list_active_locks_no_longer_sweeps_by_pid_liveness(tmp_path: Path) -> None:
    """Regression: pre-#259 list_active_locks deleted locks whose JSON PID was dead.

    With issue-keyed locks, the PID is diagnostic only — a dead PID is the norm,
    not a staleness signal. The lock must survive enumeration regardless.
    """
    lock = session_lock.Lock(
        pid=9999999,  # almost certainly dead
        started="2026-05-23T10:00:00Z",
        session=None,
        worktree_path=None,
        issue=200,
    )
    session_lock.write_lock(repo_root=tmp_path, lock=lock)
    lock_path = tmp_path / ".jared" / "session-200.lock"
    assert lock_path.exists()

    active = session_lock.list_active_locks(repo_root=tmp_path)

    assert len(active) == 1
    assert active[0] == lock
    assert lock_path.exists()


def test_list_active_locks_skips_malformed_files(tmp_path: Path) -> None:
    lockdir = tmp_path / ".jared"
    lockdir.mkdir()
    (lockdir / "session-231.lock").write_text("{not json")
    assert session_lock.list_active_locks(repo_root=tmp_path) == []


def test_list_active_locks_migrates_legacy_pid_keyed_locks(tmp_path: Path) -> None:
    """Pre-#259 locks named session-<pid>.lock have filename ≠ issue field; remove.

    An in-place upgrade from a pre-#259 install will leave PID-keyed lock files
    behind. The new code can detect them (filename number doesn't match the
    recorded `issue` field) and clean them up on first read.
    """
    import json

    lockdir = tmp_path / ".jared"
    lockdir.mkdir()
    # Pre-#259 shape: filename = PID, payload's issue = the actual issue.
    legacy_pid = 2047095
    legacy_path = lockdir / f"session-{legacy_pid}.lock"
    legacy_path.write_text(
        json.dumps(
            {
                "pid": legacy_pid,
                "started": "2026-05-23T14:00:00Z",
                "session": 1,
                "worktree_path": None,
                "issue": 231,
            }
        )
    )
    assert legacy_path.exists()

    active = session_lock.list_active_locks(repo_root=tmp_path)

    assert active == []
    assert not legacy_path.exists()


def test_clear_lock_removes_matching_file(tmp_path: Path) -> None:
    lock = session_lock.Lock(
        pid=12847,
        started="2026-05-23T14:22:00Z",
        session=1,
        worktree_path=None,
        issue=231,
    )
    path = session_lock.write_lock(repo_root=tmp_path, lock=lock)
    assert path.exists()
    session_lock.clear_lock(repo_root=tmp_path, issue=231)
    assert not path.exists()


def test_clear_lock_is_noop_when_file_absent(tmp_path: Path) -> None:
    # no lockdir, no file — should not raise
    session_lock.clear_lock(repo_root=tmp_path, issue=231)


def test_clear_lock_leaves_other_sessions_alone(tmp_path: Path) -> None:
    own = session_lock.Lock(
        pid=12847, started="2026-05-23T14:00:00Z", session=1, worktree_path=None, issue=231
    )
    sibling = session_lock.Lock(
        pid=13201, started="2026-05-23T14:30:00Z", session=2, worktree_path=None, issue=235
    )
    session_lock.write_lock(repo_root=tmp_path, lock=own)
    session_lock.write_lock(repo_root=tmp_path, lock=sibling)

    session_lock.clear_lock(repo_root=tmp_path, issue=231)

    own_path = tmp_path / ".jared" / "session-231.lock"
    sibling_path = tmp_path / ".jared" / "session-235.lock"
    assert not own_path.exists()
    assert sibling_path.exists()


def test_lock_lifecycle_survives_subprocess_boundary(tmp_path: Path) -> None:
    """Regression test for #259: write/clear must work across subprocess boundaries.

    Pre-#259, the CLI keyed the lock filename on `os.getpid()`. The subprocess
    that wrote the lock exited immediately, so the lock was named after a
    dead PID and the wrap's clear (running in a *different* subprocess with
    its own getpid()) was a silent no-op. Issue-keyed locks survive both the
    write and the clear correctly.
    """
    cli_path = Path(__file__).parents[1] / "skills" / "jared" / "scripts" / "jared"
    issue = 260

    # Write the lock in subprocess A.
    write_result = subprocess.run(
        [
            sys.executable,
            str(cli_path),
            "session-lock-write",
            "--repo-root",
            str(tmp_path),
            "--issue",
            str(issue),
            "--session",
            "1",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert write_result.returncode == 0, write_result.stderr

    # The file must exist after subprocess A exits — and the filename is the
    # issue, not the (now-dead) writing PID.
    lock_path = tmp_path / ".jared" / f"session-{issue}.lock"
    assert lock_path.exists()

    # list_active_locks (called by a third process) must still see the lock.
    active = session_lock.list_active_locks(repo_root=tmp_path)
    assert len(active) == 1
    assert active[0].issue == issue

    # Clear in subprocess B (different PID from subprocess A).
    clear_result = subprocess.run(
        [
            sys.executable,
            str(cli_path),
            "session-lock-clear",
            "--repo-root",
            str(tmp_path),
            "--issue",
            str(issue),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert clear_result.returncode == 0, clear_result.stderr

    assert not lock_path.exists()
    assert session_lock.list_active_locks(repo_root=tmp_path) == []
