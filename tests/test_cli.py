import os
import subprocess
import sys
from pathlib import Path
from textwrap import dedent

import pytest

from tests.conftest import (
    FakeGhResult,
    git_cmd,
    graphql_item_response,
    import_cli,
    patch_gh,
    patch_gh_by_arg,
)

CLI = Path(__file__).parents[1] / "skills" / "jared" / "scripts" / "jared"


def _write_board_with_priority(tmp_path: Path) -> Path:
    board_md = tmp_path / "docs" / "project-board.md"
    board_md.parent.mkdir(parents=True)
    board_md.write_text(
        dedent("""\
        - Project URL: https://github.com/users/brockamer/projects/7
        - Project number: 7
        - Project ID: PVT_kwHO_xyz
        - Owner: brockamer
        - Repo: brockamer/findajob

        ### Priority
        - Field ID: PVTSSF_prio
        - High: OPTION_high
        - Medium: OPTION_med
        - Low: OPTION_low
    """)
    )
    return board_md


def test_cli_help_lists_subcommands() -> None:
    result = subprocess.run(
        [sys.executable, str(CLI), "--help"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    for cmd in [
        "file",
        "move",
        "set",
        "close",
        "comment",
        "blocked-by",
        "get-item",
        "summary",
    ]:
        assert cmd in result.stdout, f"subcommand {cmd!r} missing from --help"


def test_cli_unknown_subcommand_exits_nonzero() -> None:
    result = subprocess.run(
        [sys.executable, str(CLI), "bogus"],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0


# Error-surface invariants: each of the five typed exceptions from lib.board
# must reach the CLI as a clean one-line stderr message with the `jared:`
# prefix and a non-zero exit. No Python traceback should ever leak for these
# known error cases — that's the contract CLAUDE.md describes, and main()'s
# top-level except handles all five uniformly so every subcommand's error
# output looks the same to the user.


def _assert_clean_error(out: str, err: str, expected_in_stderr: str) -> None:
    assert out == "", f"stdout should be empty on error, got: {out!r}"
    assert "Traceback" not in err, f"stderr leaked a traceback:\n{err}"
    assert expected_in_stderr in err, f"expected {expected_in_stderr!r} in stderr, got:\n{err}"
    # Every typed-exception error goes through main()'s uniform prefix.
    assert "jared:" in err, (
        f"expected 'jared:' prefix in stderr (uniform error format), got:\n{err}"
    )


def test_cli_board_config_error_is_clean(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """BoardConfigError reaches main()'s top-level handler (no subcommand catches it)."""
    missing = tmp_path / "docs" / "project-board.md"  # does not exist
    mod = import_cli()

    rc = mod.main(["--board", str(missing), "summary"])

    assert rc == 1
    captured = capsys.readouterr()
    _assert_clean_error(captured.out, captured.err, "Missing")


def test_cli_field_not_found_is_clean(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    board_md = _write_board_with_priority(tmp_path)
    patch_gh_by_arg(
        monkeypatch,
        {"api graphql": graphql_item_response(project_number=7, item_id="PVTI_aaa")},
    )
    mod = import_cli()

    rc = mod.main(["--board", str(board_md), "set", "42", "Nonexistent", "Anything"])

    assert rc == 1
    captured = capsys.readouterr()
    _assert_clean_error(captured.out, captured.err, "Nonexistent")


def test_cli_option_not_found_is_clean(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    board_md = _write_board_with_priority(tmp_path)
    patch_gh_by_arg(
        monkeypatch,
        {"api graphql": graphql_item_response(project_number=7, item_id="PVTI_aaa")},
    )
    mod = import_cli()

    rc = mod.main(["--board", str(board_md), "set", "42", "Priority", "Urgent"])

    assert rc == 1
    captured = capsys.readouterr()
    _assert_clean_error(captured.out, captured.err, "Urgent")


def test_cli_item_not_found_is_clean(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    board_md = _write_board_with_priority(tmp_path)
    patch_gh_by_arg(
        monkeypatch,
        {"api graphql": '{"data":{"repository":{"issue":{"projectItems":{"nodes":[]}}}}}'},
    )
    mod = import_cli()

    rc = mod.main(["--board", str(board_md), "get-item", "999"])

    assert rc == 1
    captured = capsys.readouterr()
    _assert_clean_error(captured.out, captured.err, "999")


def test_cli_gh_invocation_error_is_clean(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    board_md = _write_board_with_priority(tmp_path)
    patch_gh(monkeypatch, stdout="", returncode=1, stderr="HTTP 500 from github")
    mod = import_cli()

    rc = mod.main(["--board", str(board_md), "summary"])

    assert rc == 1
    captured = capsys.readouterr()
    _assert_clean_error(captured.out, captured.err, "gh")


# ---------------------------------------------------------------------------
# session-resolve / session-lock-write / session-lock-clear / worktree-add
# ---------------------------------------------------------------------------


def test_session_resolve_proceeds_solo_when_no_siblings(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # A checkout root, so this tests "no siblings" rather than the non-git skip
    # path — which yields PROCEED_SOLO too, and would make the assertion pass for
    # the wrong reason (#425). The non-git behaviour is covered explicitly in
    # tests/test_session_lock.py.
    (tmp_path / ".git").mkdir()
    mod = import_cli()
    result = mod.main(["session-resolve", "--repo-root", str(tmp_path)])
    assert result == 0
    captured = capsys.readouterr()
    assert "PROCEED_SOLO" in captured.out


def test_session_resolve_proceeds_multi_with_flag(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # `--session N` promises a worktree, so PROCEED_MULTI is only reachable from a
    # checkout root; on a non-git root it is downgraded to PROCEED_SOLO (#425).
    (tmp_path / ".git").mkdir()
    mod = import_cli()
    result = mod.main(["session-resolve", "--repo-root", str(tmp_path), "--session", "1"])
    assert result == 0
    captured = capsys.readouterr()
    assert "PROCEED_MULTI" in captured.out


def test_session_resolve_refuses_when_sibling_present(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from skills.jared.scripts.lib import session_lock

    # Locks anchor under `<repo_root>/.git/jared/` (#376), so the root must be a
    # checkout root.
    (tmp_path / ".git").mkdir()
    # Write a sibling lock with the current PID (alive).
    session_lock.write_lock(
        repo_root=tmp_path,
        lock=session_lock.Lock(
            pid=os.getpid(),
            started="2026-05-23T14:00:00Z",
            session=1,
            worktree_path="/fake",
            issue=200,
        ),
    )
    mod = import_cli()
    result = mod.main(["session-resolve", "--repo-root", str(tmp_path)])
    assert result == 1
    captured = capsys.readouterr()
    assert "REFUSE_BLEG" in captured.out or "REFUSE_BLEG" in captured.err


def test_session_lock_write_creates_file(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    mod = import_cli()
    result = mod.main(
        [
            "session-lock-write",
            "--repo-root",
            str(tmp_path),
            "--issue",
            "231",
            "--session",
            "1",
            "--worktree-path",
            "/home/u/Code/jared-231",
        ]
    )
    assert result == 0
    lock_path = tmp_path / ".git" / "jared" / "session-231.lock"
    assert lock_path.exists()


def test_session_lock_clear_removes_file(tmp_path: Path) -> None:
    from skills.jared.scripts.lib import session_lock

    (tmp_path / ".git").mkdir()
    session_lock.write_lock(
        repo_root=tmp_path,
        lock=session_lock.Lock(
            pid=os.getpid(),
            started="2026-05-23T14:00:00Z",
            session=None,
            worktree_path=None,
            issue=231,
        ),
    )
    mod = import_cli()
    result = mod.main(["session-lock-clear", "--repo-root", str(tmp_path), "--issue", "231"])
    assert result == 0
    lock_path = tmp_path / ".git" / "jared" / "session-231.lock"
    assert not lock_path.exists()


def _add_origin(main_repo: Path, *, set_head: bool = True) -> None:
    # worktree-add fetches origin (#283) and bases the new branch on the
    # branch `origin/HEAD` names (#465), so the repo needs a reachable origin
    # carrying main and, like a real clone, an `origin/HEAD`.
    origin = main_repo.parent / "origin.git"
    git_cmd(main_repo, "init", "--bare", "-b", "main", str(origin))
    git_cmd(main_repo, "remote", "add", "origin", str(origin))
    git_cmd(main_repo, "push", "origin", "main")
    if set_head:
        git_cmd(main_repo, "remote", "set-head", "origin", "-a")


def _clone_with_default_branch(tmp_path: Path, default_branch: str) -> tuple[Path, str]:
    """An upstream on `default_branch` and a clone of it; upstream then advances.

    Returns (clone, upstream tip). The clone's remote-tracking ref is stale
    until something fetches, so a branch cut at the upstream tip proves the
    fetch ran and the base was the default branch.
    """
    upstream = tmp_path / "upstream"
    upstream.mkdir()
    git_cmd(upstream, "init", "-b", default_branch)
    git_cmd(upstream, "config", "user.email", "u@example.com")
    git_cmd(upstream, "config", "user.name", "u")
    (upstream / "README.md").write_text("initial\n")
    git_cmd(upstream, "add", "README.md")
    git_cmd(upstream, "commit", "-m", "initial")

    clone = tmp_path / "widget"
    git_cmd(tmp_path, "clone", str(upstream), str(clone))

    (upstream / "later.txt").write_text("upstream advance\n")
    git_cmd(upstream, "add", "later.txt")
    git_cmd(upstream, "commit", "-m", "advance")
    return clone, git_cmd(upstream, "rev-parse", default_branch)


def _patch_gh_title(
    monkeypatch: pytest.MonkeyPatch, *, title: str = "", fail: bool = False
) -> None:
    """Fake only `gh issue view` (the worktree-add title fetch); delegate every
    other subprocess call to the real `subprocess.run`.

    The standard `patch_gh*` helpers replace `subprocess.run` wholesale, which
    would also break the real `git fetch`/`git worktree add` this command needs
    on disk. worktree-add is the one command that must run real git but fake gh.
    """
    real_run = subprocess.run

    def fake_run(args: list[str], **kw: object) -> object:
        if "issue" in args and "view" in args:
            if fail:
                return FakeGhResult(stdout="", returncode=1, stderr="HTTP 404")
            return FakeGhResult(stdout=f'{{"title": "{title}"}}')
        return real_run(args, **kw)  # type: ignore[call-overload]

    monkeypatch.setattr("skills.jared.scripts.lib.board.subprocess.run", fake_run)


def test_worktree_add_creates_at_sibling_path(
    main_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _add_origin(main_repo)
    # Empty title from gh → branch falls back to -worktree.
    _patch_gh_title(monkeypatch, title="")

    mod = import_cli()
    result = mod.main(
        [
            "worktree-add",
            "--repo-root",
            str(main_repo),
            "--issue",
            "231",
        ]
    )
    assert result == 0
    captured = capsys.readouterr()
    expected_target = main_repo.parent / f"{main_repo.name}-231"
    assert str(expected_target) in captured.out
    assert expected_target.exists()
    assert git_cmd(expected_target, "rev-parse", "--abbrev-ref", "HEAD") == "feature/231-worktree"


def test_worktree_add_derives_branch_slug_from_issue_title(
    main_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _add_origin(main_repo)
    _patch_gh_title(monkeypatch, title="Derive slug from issue title")

    mod = import_cli()
    result = mod.main(["worktree-add", "--repo-root", str(main_repo), "--issue", "278"])
    assert result == 0
    target = main_repo.parent / f"{main_repo.name}-278"
    branch = git_cmd(target, "rev-parse", "--abbrev-ref", "HEAD")
    assert branch == "feature/278-derive-slug-from-issue-title"


def test_worktree_add_title_flag_is_slugified(
    main_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _add_origin(main_repo)
    _patch_gh_title(monkeypatch, title="Should Not Be Used")

    mod = import_cli()
    result = mod.main(
        [
            "worktree-add",
            "--repo-root",
            str(main_repo),
            "--issue",
            "278",
            "--title",
            "Fix the Thing!",
        ]
    )
    assert result == 0
    target = main_repo.parent / f"{main_repo.name}-278"
    branch = git_cmd(target, "rev-parse", "--abbrev-ref", "HEAD")
    assert branch == "feature/278-fix-the-thing"


def test_worktree_add_falls_back_to_worktree_when_title_unavailable(
    main_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _add_origin(main_repo)
    # gh errors → fetch raises → branch falls back to -worktree, not a crash.
    _patch_gh_title(monkeypatch, fail=True)

    mod = import_cli()
    result = mod.main(["worktree-add", "--repo-root", str(main_repo), "--issue", "278"])
    assert result == 0
    target = main_repo.parent / f"{main_repo.name}-278"
    branch = git_cmd(target, "rev-parse", "--abbrev-ref", "HEAD")
    assert branch == "feature/278-worktree"


def test_worktree_add_bases_the_branch_on_a_master_default_branch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """#465: worktree-add passed `origin/main` on every repo, so on a repo
    whose default branch is `master` the `git worktree add` failed."""
    clone, upstream_tip = _clone_with_default_branch(tmp_path, "master")
    _patch_gh_title(monkeypatch, title="")

    mod = import_cli()
    result = mod.main(
        ["worktree-add", "--repo-root", str(clone), "--issue", "465", "--title", "Wrap"]
    )

    assert result == 0
    assert git_cmd(clone, "rev-parse", "feature/465-wrap") == upstream_tip


def test_worktree_add_refuses_when_origin_head_is_unset(
    main_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """No `origin/HEAD` means the default branch is unknown. Refuse and name
    the fix, the same as the /jared-wrap guard, rather than guess `main`."""
    _add_origin(main_repo, set_head=False)
    _patch_gh_title(monkeypatch, title="")

    mod = import_cli()
    result = mod.main(["worktree-add", "--repo-root", str(main_repo), "--issue", "465"])

    assert result == 1
    assert "git remote set-head origin -a" in capsys.readouterr().err
    assert not (main_repo.parent / f"{main_repo.name}-465").exists()


def test_slugify_normalizes_and_truncates() -> None:
    mod = import_cli()
    assert mod._slugify("Derive slug from issue title") == "derive-slug-from-issue-title"
    assert mod._slugify("Fix the Thing!") == "fix-the-thing"
    assert mod._slugify("  Leading/trailing -- punctuation.  ") == "leading-trailing-punctuation"
    assert mod._slugify("") == ""
    # Truncates at the length cap without a trailing hyphen.
    long = mod._slugify("a" * 30 + " " + "b" * 30, max_len=40)
    assert len(long) <= 40
    assert not long.endswith("-")


def test_session_resolve_refuse_bleg_renders_solo_sibling_mode(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """When a solo sibling triggers REFUSE_BLEG, the rendered message
    must say 'solo (on shared .git/HEAD)' — the trap-shape framing."""
    import tests.conftest as conftest
    from skills.jared.scripts.lib import session_lock

    (tmp_path / ".git").mkdir()
    session_lock.write_lock(
        repo_root=tmp_path,
        lock=session_lock.Lock(
            pid=os.getpid(),
            started="2026-05-23T14:00:00Z",
            session=None,  # SOLO sibling
            worktree_path=None,
            issue=200,
        ),
    )
    mod = conftest.import_cli()
    result = mod.main(["session-resolve", "--repo-root", str(tmp_path)])
    assert result == 1
    captured = capsys.readouterr()
    # action.name on stdout
    assert "REFUSE_BLEG" in captured.out
    # rendered refusal on stderr must call out the solo / shared-HEAD shape
    assert "solo" in captured.err.lower()
    assert "shared" in captured.err.lower() or ".git" in captured.err.lower()
