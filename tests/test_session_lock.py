"""Unit tests for lib/session_lock.py — session-presence locks (#231)."""

from __future__ import annotations

import os
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
    assert path == tmp_path / ".jared" / "session-12847.lock"
    assert path.exists()

    loaded = session_lock.read_lock(path)
    assert loaded == lock


def test_read_lock_returns_none_when_file_absent(tmp_path: Path) -> None:
    path = tmp_path / ".jared" / "session-99999.lock"
    assert session_lock.read_lock(path) is None


def test_read_lock_returns_none_when_json_corrupted(tmp_path: Path) -> None:
    lockdir = tmp_path / ".jared"
    lockdir.mkdir()
    path = lockdir / "session-12847.lock"
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

    monkeypatch.setattr(session_lock.os, "kill", fake_kill)  # type: ignore[attr-defined]
    assert session_lock.is_alive(9999999) is False


def test_is_alive_returns_true_when_permission_denied(monkeypatch: pytest.MonkeyPatch) -> None:
    # init (PID 1) typically gives EPERM rather than ESRCH — the process IS alive.
    def fake_kill(pid: int, sig: int) -> None:
        raise PermissionError()

    monkeypatch.setattr(session_lock.os, "kill", fake_kill)  # type: ignore[attr-defined]
    assert session_lock.is_alive(1) is True


def test_list_active_locks_empty_when_no_lockdir(tmp_path: Path) -> None:
    assert session_lock.list_active_locks(repo_root=tmp_path) == []


def test_list_active_locks_returns_alive_locks(tmp_path: Path) -> None:
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


def test_list_active_locks_clears_stale_locks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    stale = session_lock.Lock(
        pid=9999999,
        started="2026-05-23T10:00:00Z",
        session=None,
        worktree_path=None,
        issue=200,
    )
    session_lock.write_lock(repo_root=tmp_path, lock=stale)
    stale_path = tmp_path / ".jared" / "session-9999999.lock"
    assert stale_path.exists()

    original_kill = os.kill

    def fake_kill(pid: int, sig: int) -> None:
        if pid == 9999999:
            raise ProcessLookupError()
        original_kill(pid, sig)

    monkeypatch.setattr(session_lock.os, "kill", fake_kill)  # type: ignore[attr-defined]
    active = session_lock.list_active_locks(repo_root=tmp_path)

    assert active == []
    assert not stale_path.exists()
    captured = capsys.readouterr()
    assert "stale lock" in captured.err.lower()
    assert "9999999" in captured.err


def test_list_active_locks_skips_malformed_files(tmp_path: Path) -> None:
    lockdir = tmp_path / ".jared"
    lockdir.mkdir()
    (lockdir / "session-12847.lock").write_text("{not json")
    assert session_lock.list_active_locks(repo_root=tmp_path) == []


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
    session_lock.clear_lock(repo_root=tmp_path, pid=12847)
    assert not path.exists()


def test_clear_lock_is_noop_when_file_absent(tmp_path: Path) -> None:
    # no lockdir, no file — should not raise
    session_lock.clear_lock(repo_root=tmp_path, pid=12847)


def test_clear_lock_leaves_other_sessions_alone(tmp_path: Path) -> None:
    own = session_lock.Lock(
        pid=12847, started="2026-05-23T14:00:00Z", session=1, worktree_path=None, issue=231
    )
    sibling = session_lock.Lock(
        pid=13201, started="2026-05-23T14:30:00Z", session=2, worktree_path=None, issue=235
    )
    session_lock.write_lock(repo_root=tmp_path, lock=own)
    session_lock.write_lock(repo_root=tmp_path, lock=sibling)

    session_lock.clear_lock(repo_root=tmp_path, pid=12847)

    own_path = tmp_path / ".jared" / "session-12847.lock"
    sibling_path = tmp_path / ".jared" / "session-13201.lock"
    assert not own_path.exists()
    assert sibling_path.exists()
