"""Behavioral guards for the shell doctrine in `commands/jared-wrap.md`.

The `/jared-wrap` back-end flow is doctrine, not code: `jared wrap-state` names
the next step and the conversation executes it from the stub's fenced bash
blocks. Two P1 findings from the marketplace-readiness review (F71 → #392,
F72 → #393) were defects *in that prose*, so neither had anywhere to regress to
except the stub text.

This module follows `tests/test_autoclose_guard.py`'s shape rather than the
easier one. A text assertion ("`git add -A` is absent") checks form; it cannot
tell a correct replacement from a broken one. So these tests **extract the
stub's bash blocks and run them** against synthetic git repositories, then
assert on the index and on the guard's decision. What is under test is the
behaviour a session actually gets.

Blocks are located by content — the staging block is the one containing
`git add -u`, the precondition guard the one containing
`refs/remotes/origin/HEAD` — so the doctrine carries no marker comment that
exists only for this file.

The guard's `SKIP:` / `PROCEED:` lines are machine-fixed strings in the sense of
`references/voice-ste.md`: an operator reads them, and this module greps them.
Rephrasing one is a doctrine change and fails here first.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
WRAP_STUB = REPO_ROOT / "commands" / "jared-wrap.md"

requires_bash = pytest.mark.skipif(shutil.which("bash") is None, reason="bash not on PATH")
requires_git = pytest.mark.skipif(shutil.which("git") is None, reason="git not on PATH")


def _bash_blocks(text: str) -> list[str]:
    """Every fenced ```bash block in the stub, fence lines stripped."""
    found: list[str] = re.findall(r"```bash\n(.*?)```", text, flags=re.DOTALL)
    return found


def _block_containing(needle: str) -> str:
    """The one fenced bash block in the wrap stub containing `needle`.

    Asserts uniqueness: two blocks matching means the doctrine grew a second
    copy, which is the drift this module exists to catch.
    """
    blocks = [b for b in _bash_blocks(WRAP_STUB.read_text(encoding="utf-8")) if needle in b]
    assert len(blocks) == 1, (
        f"expected exactly one fenced bash block in {WRAP_STUB.name} containing "
        f"{needle!r}, found {len(blocks)}"
    )
    return blocks[0]


def _run(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=30, check=False)


def _git(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    proc = _run(["git", *args], cwd)
    assert proc.returncode == 0, f"git {' '.join(args)} failed: {proc.stderr.strip()}"
    return proc


def _init_repo(path: Path, default_branch: str = "master") -> None:
    """A real repo with one commit, no network, no dependence on user config."""
    path.mkdir(parents=True)
    _git(["init", "-b", default_branch, "--quiet"], path)
    _git(["config", "user.email", "test@example.invalid"], path)
    _git(["config", "user.name", "Wrap Guard Test"], path)
    _git(["config", "commit.gpgsign", "false"], path)
    (path / "tracked.txt").write_text("original\n", encoding="utf-8")
    _git(["add", "tracked.txt"], path)
    _git(["commit", "--quiet", "-m", "initial"], path)


# --------------------------------------------------------------------------
# F71 / #392 — the commit step must not stage untracked paths implicitly
# --------------------------------------------------------------------------


@requires_bash
@requires_git
def test_commit_step_stages_tracked_changes_only(tmp_path: Path) -> None:
    """The defect of #392, reproduced as an assertion on the index.

    A deliberately-untracked path must survive the staging block untouched.
    `git add -A` stages it; `git add -u` does not. Nothing about the operator's
    answer to the commit-message prompt can change that.
    """
    block = _block_containing("git add -u")
    repo = tmp_path / "repo"
    _init_repo(repo)
    (repo / "tracked.txt").write_text("edited in this session\n", encoding="utf-8")
    (repo / "private-notes.md").write_text("client name, salary figures\n", encoding="utf-8")

    proc = _run(["bash", "-c", block], repo)
    assert proc.returncode == 0, f"staging block failed: {proc.stderr.strip()}"

    staged = _git(["diff", "--cached", "--name-only"], repo).stdout.split()
    assert "tracked.txt" in staged, (
        "the staging block did not stage a modification to an already-tracked "
        f"file; index holds {staged}"
    )
    assert "private-notes.md" not in staged, (
        "the staging block put a deliberately-untracked path into the index. "
        "This is F71 (#392): one answer at the commit-message prompt then "
        "publishes it, because the same loop pushes and opens a PR."
    )


@requires_bash
@requires_git
def test_commit_step_reports_untracked_paths_for_the_operator(tmp_path: Path) -> None:
    """Not staging them is half the fix; the operator must still see the list.

    AC#2 of #392 asks for an enumerated list, so the block has to name the
    untracked paths rather than silently drop them.
    """
    block = _block_containing("git add -u")
    repo = tmp_path / "repo"
    _init_repo(repo)
    (repo / "private-notes.md").write_text("client name\n", encoding="utf-8")

    proc = _run(["bash", "-c", block], repo)
    assert "private-notes.md" in proc.stdout, (
        "the staging block neither stages nor lists the untracked path, so the "
        f"operator has no way to opt in. stdout was {proc.stdout!r}"
    )


def test_stub_never_stages_the_whole_tree() -> None:
    """No `git add -A`, `--all`, or bare `git add .` anywhere in the stub.

    The regression guard for F71. A future edit that reintroduces any blanket
    form fails here, including in prose outside a fenced block.
    """
    text = WRAP_STUB.read_text(encoding="utf-8")
    blanket = re.findall(r"git add\s+(?:-A\b|--all\b|\.(?:\s|$))", text)
    assert not blanket, (
        f"{WRAP_STUB.name} stages the whole working tree ({blanket}). "
        "F71 (#392): a blanket add cannot tell a file nobody added yet from "
        "one that must never enter git history."
    )


# --------------------------------------------------------------------------
# F72 / #393 — the precondition guard must derive the default branch and
# confirm `origin` is the repo the board doc records
# --------------------------------------------------------------------------


def _make_guard_repo(
    tmp_path: Path,
    *,
    name: str,
    board_repo: str = "acme/widget",
    origin_url: str = "git@github.com:acme/widget.git",
    default_branch: str = "master",
    current_branch: str | None = None,
    set_origin_head: bool = True,
) -> Path:
    """A repo shaped like a real clone, built offline.

    `origin` is a GitHub-shaped URL that is never contacted: the remote-tracking
    ref and `origin/HEAD` are written directly, which is what `git clone` leaves
    behind and what `git remote add` does not.
    """
    repo = tmp_path / name
    _init_repo(repo, default_branch=default_branch)
    (repo / "docs").mkdir()
    (repo / "docs" / "project-board.md").write_text(
        f"# Project board\n\n- Project: 4\n- Repo: {board_repo}\n", encoding="utf-8"
    )
    _git(["remote", "add", "origin", origin_url], repo)
    head_sha = _git(["rev-parse", "HEAD"], repo).stdout.strip()
    _git(["update-ref", f"refs/remotes/origin/{default_branch}", head_sha], repo)
    if set_origin_head:
        _git(
            ["symbolic-ref", "refs/remotes/origin/HEAD", f"refs/remotes/origin/{default_branch}"],
            repo,
        )
    if current_branch is not None:
        _git(["checkout", "--quiet", "-b", current_branch], repo)
    return repo


@requires_bash
@requires_git
def test_guard_fires_on_a_default_branch_not_named_main(tmp_path: Path) -> None:
    """The first half of #393: a `master` repo used to fall straight through."""
    block = _block_containing("refs/remotes/origin/HEAD")
    repo = _make_guard_repo(tmp_path, name="master-repo", default_branch="master")

    proc = _run(["bash", "-c", block], repo)
    assert proc.stdout.startswith("SKIP:"), (
        "the guard let the back-end flow proceed on `master`, this repo's own "
        "default branch. F72 (#393): the loop then opens a PR from the default "
        f"branch. stdout was {proc.stdout!r}"
    )
    assert "master" in proc.stdout


@requires_bash
@requires_git
def test_guard_fires_when_origin_is_not_the_board_doc_repo(tmp_path: Path) -> None:
    """The second half of #393: a clone of someone else's repo.

    The push would fail with HTTP 403, but the flow must not arrive there by
    trying — `create_pr` is one merged guard away from a PR on a stranger's
    repository.
    """
    block = _block_containing("refs/remotes/origin/HEAD")
    repo = _make_guard_repo(
        tmp_path,
        name="foreign-origin",
        board_repo="acme/widget",
        origin_url="git@github.com:stranger/upstream.git",
        current_branch="feature/1-thing",
    )

    proc = _run(["bash", "-c", block], repo)
    assert proc.stdout.startswith("SKIP:"), (
        "the guard let the back-end flow proceed with `origin` pointing at a "
        f"repo the board doc does not record. stdout was {proc.stdout!r}"
    )
    assert "stranger/upstream" in proc.stdout
    assert "acme/widget" in proc.stdout


@requires_bash
@requires_git
@pytest.mark.parametrize(
    "origin_url",
    [
        "git@github.com:acme/widget.git",
        "https://github.com/acme/widget.git",
        "https://github.com/acme/widget",
        "ssh://git@github.com/acme/widget.git",
    ],
)
def test_guard_proceeds_on_a_feature_branch_of_the_board_doc_repo(
    tmp_path: Path, origin_url: str
) -> None:
    """AC#4 of #393: the normal case is unaffected, whatever URL shape `origin` has.

    Parametrised because the comparison needs the remote URL normalised; an
    over-eager guard that skips a legitimate session is the failure mode that
    would make the whole flow useless.
    """
    block = _block_containing("refs/remotes/origin/HEAD")
    repo = _make_guard_repo(
        tmp_path,
        name="normal-" + re.sub(r"\W+", "-", origin_url),
        origin_url=origin_url,
        default_branch="main",
        current_branch="feature/392-thing",
    )

    proc = _run(["bash", "-c", block], repo)
    assert proc.stdout.startswith("PROCEED"), (
        "the guard refused an ordinary feature-branch session on the repo the "
        f"board doc records, with origin {origin_url!r}. stdout was {proc.stdout!r}"
    )


@requires_bash
@requires_git
def test_guard_skips_rather_than_guesses_when_the_default_branch_is_unresolvable(
    tmp_path: Path,
) -> None:
    """A repo built with `git remote add` has no `origin/HEAD`.

    The guard cannot establish which branch is the default, so it must not fall
    back to the literal `main` — that is the assumption #393 is about. It skips
    and names the one-line remedy.
    """
    block = _block_containing("refs/remotes/origin/HEAD")
    repo = _make_guard_repo(
        tmp_path,
        name="no-origin-head",
        default_branch="trunk",
        current_branch="feature/1-thing",
        set_origin_head=False,
    )

    proc = _run(["bash", "-c", block], repo)
    assert proc.stdout.startswith("SKIP:"), (
        "the guard proceeded without establishing the repo's default branch. "
        f"stdout was {proc.stdout!r}"
    )
    assert "git remote set-head origin -a" in proc.stdout, (
        "the skip message does not tell the operator how to fix it; a guard "
        "that blocks without a remedy gets worked around"
    )


def test_stub_does_not_hardcode_the_default_branch_name() -> None:
    """The regression guard for F72's first half."""
    guard = _block_containing("refs/remotes/origin/HEAD")
    assert '= "main"' not in guard, (
        "the precondition guard compares the current branch against the literal "
        '"main" again. F72 (#393): a repo whose default branch is `master` '
        "falls through that check and runs the PR loop on its default branch."
    )
