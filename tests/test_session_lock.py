"""Unit tests for lib/session_lock.py — session-presence locks (#231)."""

from __future__ import annotations

from pathlib import Path

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
