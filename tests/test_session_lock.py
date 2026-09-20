"""Unit tests for lib/session_lock.py — session-presence locks (#231, #259, #376)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from skills.jared.scripts.lib import session_lock
from tests.conftest import import_cli


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


# ---------------------------------------------------------------------------
# Non-git projects (#425) — the three halves of the protocol agree
# ---------------------------------------------------------------------------


def run_cli(argv: list[str], capsys: pytest.CaptureFixture[str]) -> tuple[int, str, str]:
    """Drive the CLI in-process and return (exit code, stdout, stderr)."""
    mod = import_cli()
    rc: int = mod.main(argv)
    captured = capsys.readouterr()
    return rc, captured.out, captured.err


def test_is_git_checkout_true_at_a_checkout_root(repo_root: Path) -> None:
    assert session_lock.is_git_checkout(repo_root) is True


def test_is_git_checkout_false_without_a_git_dir(tmp_path: Path) -> None:
    assert session_lock.is_git_checkout(tmp_path) is False


def test_is_git_checkout_resolves_a_relative_root(
    repo_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The predicate must resolve like `write_lock` does, or the two disagree.

    REPO_ROOT collapses to a relative '.' in the main checkout (#284), so a
    predicate that skipped `.resolve()` would report False where `write_lock`
    succeeds — reintroducing the split this issue closes.
    """
    monkeypatch.chdir(repo_root)
    assert session_lock.is_git_checkout(Path(".")) is True


def test_session_resolve_keeps_stdout_to_the_action_on_a_non_git_root(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The `/jared-start` stub parses this stdout, so the notice belongs on stderr."""
    rc, out, err = run_cli(["session-resolve", "--repo-root", str(tmp_path)], capsys)

    assert rc == 0
    assert out.strip() == "PROCEED_SOLO"
    assert session_lock.non_git_notice(tmp_path) in err


def test_session_resolve_downgrades_proceed_multi_on_a_non_git_root(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """#425: `--session N` asks for worktree isolation, which needs a git checkout.

    Left alone, `resolve_action` returns PROCEED_MULTI (no siblings can ever exist
    on a non-git root, since no lock is written), and `/jared-start` step 1b then
    calls `worktree-add`, which dies on `fatal: not a git repository`. Downgrading
    here keeps the failure out of the stub entirely.
    """
    rc, out, err = run_cli(
        ["session-resolve", "--repo-root", str(tmp_path), "--session", "1"], capsys
    )

    assert rc == 0
    assert out.strip() == "PROCEED_SOLO"
    assert session_lock.non_git_notice(tmp_path) in err
    assert session_lock.non_git_session_downgrade_notice(1) in err


def test_session_resolve_still_refuses_conflicting_flags_on_a_non_git_root(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A flag contradiction is an operator error, independent of git.

    The downgrade must not swallow it — `--session N` with `--no-worktree` is
    incoherent whether or not a checkout exists.
    """
    rc, out, err = run_cli(
        ["session-resolve", "--repo-root", str(tmp_path), "--session", "1", "--no-worktree"],
        capsys,
    )

    assert rc == 1
    assert out.strip() == "REFUSE_CONFLICTING_FLAGS"
    assert "mutually exclusive" in err


def test_session_resolve_keeps_proceed_multi_on_a_real_checkout(
    repo_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The downgrade is scoped to non-git roots — real checkouts are untouched."""
    rc, out, err = run_cli(
        ["session-resolve", "--repo-root", str(repo_root), "--session", "1"], capsys
    )

    assert rc == 0
    assert out.strip() == "PROCEED_MULTI"
    assert err == ""


def test_session_lock_write_skips_with_a_notice_on_a_non_git_root(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """#425: the write half used to exit 1 where resolve returned PROCEED_SOLO.

    `/jared-start` step 1b calls this unconditionally, so a hard failure left every
    session on a non-git project ending its board-mutation phase with a red error
    the operator had to learn to ignore.
    """
    rc, _out, err = run_cli(
        ["session-lock-write", "--repo-root", str(tmp_path), "--issue", "425"], capsys
    )

    assert rc == 0
    assert session_lock.non_git_notice(tmp_path) in err
    assert "Traceback" not in err
    # The guard's whole purpose: never fabricate a `.git/` in a plain directory.
    assert not (tmp_path / ".git").exists()


def test_session_lock_clear_announces_the_skip_rather_than_exiting_0_silently(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """#425 (2026-09-19 field report): a silent exit 0 is not an explicit skip.

    `/jared-wrap` runs lock-clear unconditionally. A bare exit 0 is indistinguishable
    from "a lock existed and was removed", so wrap reported a clean close-out for a
    protocol that never engaged at either end.
    """
    rc, _out, err = run_cli(
        ["session-lock-clear", "--repo-root", str(tmp_path), "--issue", "425"], capsys
    )

    assert rc == 0
    assert session_lock.non_git_notice(tmp_path) in err


def test_non_git_lock_protocol_end_to_end(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The #425 acceptance criterion: resolve, write, list, clear on a non-git root.

    No step exits non-zero, every step names the skip, no lock is written, and no
    `.git` directory is conjured along the way.
    """
    issue = "425"
    notice = session_lock.non_git_notice(tmp_path)

    for argv in (
        ["session-resolve", "--repo-root", str(tmp_path)],
        ["session-lock-write", "--repo-root", str(tmp_path), "--issue", issue],
        ["session-lock-clear", "--repo-root", str(tmp_path), "--issue", issue],
    ):
        rc, _out, err = run_cli(argv, capsys)
        assert rc == 0, f"{argv[0]} exited {rc}"
        assert notice in err, f"{argv[0]} did not report the skip"

    assert session_lock.list_active_locks(repo_root=tmp_path) == []
    assert not (tmp_path / ".git").exists()
    assert not (tmp_path / ".jared").exists()


def test_cli_session_lock_write_still_succeeds_on_a_real_checkout(
    repo_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The skip is scoped to non-git roots — the ordinary path is untouched."""
    rc, _out, err = run_cli(
        ["session-lock-write", "--repo-root", str(repo_root), "--issue", "425"], capsys
    )

    assert rc == 0
    assert err == ""
    assert (lockdir_of(repo_root) / "session-425.lock").exists()


def test_cli_renders_not_a_git_checkout_as_a_clean_error_not_a_traceback(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """`NotAGitCheckout` must render as `jared: …`, never as an escaping traceback.

    No CLI *input* can reach the guard any more: the handler skips on
    `is_git_checkout`, and `write_lock` raises on the negation of that same
    predicate, so the two cannot disagree (#425). That is the point of unifying
    them — and it means the property worth pinning here is the top-level handler's
    rendering, exercised by raising the exception directly. The guard itself stays
    covered at library level by
    `test_write_lock_refuses_when_repo_root_has_no_git_dir`.

    Patches `lib.session_lock` — the module object the CLI imported. Per the
    dual-import-path note atop conftest.py, `skills.jared.scripts.lib.session_lock`
    is a different object and patching it would not affect the CLI.
    """
    mod = import_cli()
    cli_session_lock = sys.modules["lib.session_lock"]
    (tmp_path / ".git").mkdir()

    def raise_guard(**_kwargs: object) -> None:
        raise cli_session_lock.NotAGitCheckout(
            f"not a git checkout root (no .git directory): {tmp_path}"
        )

    monkeypatch.setattr(cli_session_lock, "write_lock", raise_guard)

    rc: int = mod.main(["session-lock-write", "--repo-root", str(tmp_path), "--issue", "425"])
    captured = capsys.readouterr()

    assert rc == 1
    assert "Traceback" not in captured.err
    assert captured.err.startswith("jared: ")
