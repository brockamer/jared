"""Unit tests for lib/session_lock.py — session-presence locks (#231, #259, #376)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from skills.jared.scripts.lib import session_lock


@pytest.fixture
def repo_root(tmp_path: Path) -> Path:
    """A main-checkout root: the directory whose `.git/` is the git common dir.

    Every lock helper takes a `repo_root` that callers derive as
    `dirname(git rev-parse --git-common-dir)`, so `<repo_root>/.git` is the
    common dir by contract (#376). The fixture models that contract.
    """
    (tmp_path / ".git").mkdir()
    return tmp_path


def lockdir_of(repo_root: Path) -> Path:
    return repo_root / ".git" / "jared"


def test_lock_round_trips_through_disk(repo_root: Path) -> None:
    lock = session_lock.Lock(
        pid=12847,
        started="2026-05-23T14:22:00Z",
        session=1,
        worktree_path="/home/u/Code/jared-231",
        issue=231,
    )
    path = session_lock.write_lock(repo_root=repo_root, lock=lock)
    assert path == lockdir_of(repo_root) / "session-231.lock"
    assert path.exists()

    loaded = session_lock.read_lock(path)
    assert loaded == lock


def test_lock_dir_is_under_the_git_common_dir_so_git_cannot_track_it(repo_root: Path) -> None:
    """Regression for #376: a lock inside the working tree can be committed.

    `list_active_locks` does no liveness check, so every lock file on disk counts
    as a live sibling. A committed lock therefore makes `/jared-start` refuse on
    every fresh clone, forever. Anchoring under the git common dir makes the lock
    untrackable by construction — git never stores the contents of its own dir.
    """
    lock = session_lock.Lock(
        pid=4242,
        started="2026-09-17T12:00:00Z",
        session=None,
        worktree_path=None,
        issue=376,
    )
    path = session_lock.write_lock(repo_root=repo_root, lock=lock)

    assert path == repo_root / ".git" / "jared" / "session-376.lock"
    # The working tree stays clean: nothing is written outside `.git/`.
    assert not (repo_root / ".jared").exists()


def test_write_lock_refuses_when_repo_root_has_no_git_dir(tmp_path: Path) -> None:
    """A non-checkout root must fail loudly rather than fabricate a `.git/`.

    `write_lock` does `mkdir(parents=True)`, so without this guard a `repo_root`
    with no `.git` would have one created for it — turning a plain directory into
    something git half-recognises. Reachable: the `/jared-start` stub's REPO_ROOT
    derivation collapses to cwd when `git rev-parse` fails.
    """
    lock = session_lock.Lock(
        pid=4242,
        started="2026-09-17T12:00:00Z",
        session=None,
        worktree_path=None,
        issue=376,
    )
    with pytest.raises(session_lock.NotAGitCheckout):
        session_lock.write_lock(repo_root=tmp_path, lock=lock)

    assert not (tmp_path / ".git").exists()
    assert not (tmp_path / ".jared").exists()


def test_read_lock_returns_none_when_file_absent(repo_root: Path) -> None:
    path = lockdir_of(repo_root) / "session-99999.lock"
    assert session_lock.read_lock(path) is None


def test_read_lock_returns_none_when_json_corrupted(repo_root: Path) -> None:
    lockdir = lockdir_of(repo_root)
    lockdir.mkdir(parents=True)
    path = lockdir / "session-231.lock"
    path.write_text("{not json")
    assert session_lock.read_lock(path) is None


def test_write_lock_with_solo_session(repo_root: Path) -> None:
    lock = session_lock.Lock(
        pid=12847,
        started="2026-05-23T14:22:00Z",
        session=None,
        worktree_path=None,
        issue=231,
    )
    path = session_lock.write_lock(repo_root=repo_root, lock=lock)
    loaded = session_lock.read_lock(path)
    assert loaded is not None
    assert loaded.session is None
    assert loaded.worktree_path is None


def test_write_lock_with_relative_repo_root_anchors_at_true_root(
    repo_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regression for #284: in the main checkout REPO_ROOT collapses to a relative
    '.', so the lock trio receives a relative root. The lock must still land at the
    true (absolute) repo root — a cwd-relative lock breaks the cross-session
    sibling detection the whole multi-session discipline rests on.
    """
    monkeypatch.chdir(repo_root)
    lock = session_lock.Lock(
        pid=4242,
        started="2026-05-30T15:00:00Z",
        session=1,
        worktree_path=None,
        issue=284,
    )
    # The bug shape: caller passes a relative root (REPO_ROOT='.').
    path = session_lock.write_lock(repo_root=Path("."), lock=lock)
    assert path.is_absolute()
    assert path == lockdir_of(repo_root.resolve()) / "session-284.lock"


def test_list_active_locks_empty_when_no_lockdir(repo_root: Path) -> None:
    assert session_lock.list_active_locks(repo_root=repo_root) == []


def test_list_active_locks_empty_when_repo_root_has_no_git_dir(tmp_path: Path) -> None:
    """Reads stay tolerant where writes are strict — absent scope means no siblings."""
    assert session_lock.list_active_locks(repo_root=tmp_path) == []


def test_list_active_locks_ignores_pre_376_working_tree_locks(repo_root: Path) -> None:
    """Acceptance criterion for #376: a leftover `<repo>/.jared/` is not read.

    Locks written before #376 live in the working tree and may be *tracked*
    — a committed one is the exact false-positive this issue removes. Ignoring the
    directory (rather than migrating it) is deliberate: jared must not delete a
    file from a consuming project's working tree, and a tracked lock would come
    straight back on the next checkout anyway.
    """
    legacy_dir = repo_root / ".jared"
    legacy_dir.mkdir()
    legacy_path = legacy_dir / "session-231.lock"
    legacy_path.write_text(
        json.dumps(
            {
                "pid": 12847,
                "started": "2026-05-23T14:00:00Z",
                "session": 1,
                "worktree_path": None,
                "issue": 231,
            }
        )
    )

    assert session_lock.list_active_locks(repo_root=repo_root) == []
    # Ignored, never deleted — it is not jared's file to remove.
    assert legacy_path.exists()


def test_list_active_locks_returns_existing_locks(repo_root: Path) -> None:
    lock = session_lock.Lock(
        pid=os.getpid(),
        started="2026-05-23T14:22:00Z",
        session=1,
        worktree_path=None,
        issue=231,
    )
    session_lock.write_lock(repo_root=repo_root, lock=lock)
    active = session_lock.list_active_locks(repo_root=repo_root)
    assert len(active) == 1
    assert active[0] == lock


def test_list_active_locks_no_longer_sweeps_by_pid_liveness(repo_root: Path) -> None:
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
    session_lock.write_lock(repo_root=repo_root, lock=lock)
    lock_path = lockdir_of(repo_root) / "session-200.lock"
    assert lock_path.exists()

    active = session_lock.list_active_locks(repo_root=repo_root)

    assert len(active) == 1
    assert active[0] == lock
    assert lock_path.exists()


def test_list_active_locks_skips_malformed_files(repo_root: Path) -> None:
    lockdir = lockdir_of(repo_root)
    lockdir.mkdir(parents=True)
    (lockdir / "session-231.lock").write_text("{not json")
    assert session_lock.list_active_locks(repo_root=repo_root) == []


def test_clear_lock_removes_matching_file(repo_root: Path) -> None:
    lock = session_lock.Lock(
        pid=12847,
        started="2026-05-23T14:22:00Z",
        session=1,
        worktree_path=None,
        issue=231,
    )
    path = session_lock.write_lock(repo_root=repo_root, lock=lock)
    assert path.exists()
    session_lock.clear_lock(repo_root=repo_root, issue=231)
    assert not path.exists()


def test_clear_lock_is_noop_when_file_absent(repo_root: Path) -> None:
    # no lockdir, no file — should not raise
    session_lock.clear_lock(repo_root=repo_root, issue=231)


def test_clear_lock_is_noop_when_repo_root_has_no_git_dir(tmp_path: Path) -> None:
    """Clearing is tolerant like reading: wrap must never crash on teardown."""
    session_lock.clear_lock(repo_root=tmp_path, issue=231)


def test_clear_lock_leaves_other_sessions_alone(repo_root: Path) -> None:
    own = session_lock.Lock(
        pid=12847, started="2026-05-23T14:00:00Z", session=1, worktree_path=None, issue=231
    )
    sibling = session_lock.Lock(
        pid=13201, started="2026-05-23T14:30:00Z", session=2, worktree_path=None, issue=235
    )
    session_lock.write_lock(repo_root=repo_root, lock=own)
    session_lock.write_lock(repo_root=repo_root, lock=sibling)

    session_lock.clear_lock(repo_root=repo_root, issue=231)

    own_path = lockdir_of(repo_root) / "session-231.lock"
    sibling_path = lockdir_of(repo_root) / "session-235.lock"
    assert not own_path.exists()
    assert sibling_path.exists()


def test_lock_lifecycle_survives_subprocess_boundary(repo_root: Path) -> None:
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
            str(repo_root),
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
    lock_path = lockdir_of(repo_root) / f"session-{issue}.lock"
    assert lock_path.exists()

    # list_active_locks (called by a third process) must still see the lock.
    active = session_lock.list_active_locks(repo_root=repo_root)
    assert len(active) == 1
    assert active[0].issue == issue

    # Clear in subprocess B (different PID from subprocess A).
    clear_result = subprocess.run(
        [
            sys.executable,
            str(cli_path),
            "session-lock-clear",
            "--repo-root",
            str(repo_root),
            "--issue",
            str(issue),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert clear_result.returncode == 0, clear_result.stderr

    assert not lock_path.exists()
    assert session_lock.list_active_locks(repo_root=repo_root) == []


def test_cli_session_lock_write_exits_1_on_non_checkout_root(tmp_path: Path) -> None:
    """The guard must surface as a clean CLI error, not an escaping traceback."""
    cli_path = Path(__file__).parents[1] / "skills" / "jared" / "scripts" / "jared"
    result = subprocess.run(
        [
            sys.executable,
            str(cli_path),
            "session-lock-write",
            "--repo-root",
            str(tmp_path),
            "--issue",
            "376",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 1, result.stdout
    assert "Traceback" not in result.stderr
    assert result.stderr.startswith("jared: ")
