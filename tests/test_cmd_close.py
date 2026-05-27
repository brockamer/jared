import json
import subprocess as _subprocess
from io import StringIO
from pathlib import Path
from textwrap import dedent

import pytest

from tests.conftest import FakeGhResult, import_cli, patch_gh_by_arg


def _write_board_with_status(tmp_path: Path) -> Path:
    """Default board fixture used by the close tests."""
    board_md = tmp_path / "docs" / "project-board.md"
    board_md.parent.mkdir(parents=True)
    board_md.write_text(
        dedent("""\
        - Project URL: https://github.com/users/brockamer/projects/7
        - Project number: 7
        - Project ID: PVT_kwHO_xyz
        - Owner: brockamer
        - Repo: brockamer/findajob

        ### Status
        - Field ID: PVTSSF_status
        - Backlog: OPTION_backlog
        - In Progress: OPTION_in_progress
        - Done: OPTION_done
    """)
    )
    return board_md


def _graphql_item_response(*, project_number: int, status: str, item_id: str = "PVTI_aaa") -> str:
    """Build a repository.issue(number).projectItems graphql payload."""
    return json.dumps(
        {
            "data": {
                "repository": {
                    "issue": {
                        "projectItems": {
                            "nodes": [
                                {
                                    "id": item_id,
                                    "project": {"number": project_number},
                                    "fieldValues": {
                                        "nodes": [
                                            {
                                                "name": status,
                                                "field": {"name": "Status"},
                                            }
                                        ]
                                    },
                                }
                            ]
                        }
                    }
                }
            }
        }
    )


def test_close_always_sets_status_done_defense_in_depth(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """After `jared close <N>`, item-edit Status=Done MUST run unconditionally
    — even when the board's auto-move workflow appears to have already moved
    the item to Done. Defense-in-depth for #137: GitHub's project auto-move
    has an observable false-positive mode where the GraphQL poll claims
    Status=Done but the field hasn't actually changed (#135 reproduction).
    The explicit set after close is the source of truth.
    """
    monkeypatch.setattr("time.sleep", lambda _s: None)
    board_md = _write_board_with_status(tmp_path)
    calls = patch_gh_by_arg(
        monkeypatch,
        {
            "issue close": "",
            # Even if GraphQL says Done, the CLI must still item-edit Status=Done.
            "api graphql": _graphql_item_response(project_number=7, status="Done"),
            "item-edit": "{}",
        },
    )

    mod = import_cli()
    rc = mod.main(["--board", str(board_md), "close", "42"])

    captured = capsys.readouterr()
    assert rc == 0, captured.err
    edit = next((c for c in calls if "item-edit" in c), None)
    assert edit is not None, "expected explicit item-edit even when graphql claims Done"
    joined = " ".join(edit)
    assert "PVTSSF_status" in joined
    assert "OPTION_done" in joined


def test_close_targets_correct_project_when_issue_on_multiple_boards(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Issue may belong to multiple ProjectV2 items; the post-close set
    must resolve to the item on the board configured in project-board.md,
    never a sibling project's item. Scoping happens in `Board.find_item_id`
    → `fetch_item_for_issue` which filters by `project.number`.
    """
    board_md = _write_board_with_status(tmp_path)
    # Same issue attached to two projects: project 99 (unrelated, PVTI_other),
    # project 7 (our board, PVTI_ours). The item-edit must reference PVTI_ours.
    multi_project_response = json.dumps(
        {
            "data": {
                "repository": {
                    "issue": {
                        "projectItems": {
                            "nodes": [
                                {
                                    "id": "PVTI_other",
                                    "project": {"number": 99},
                                    "fieldValues": {
                                        "nodes": [
                                            {
                                                "name": "Done",
                                                "field": {"name": "Status"},
                                            }
                                        ]
                                    },
                                },
                                {
                                    "id": "PVTI_ours",
                                    "project": {"number": 7},
                                    "fieldValues": {
                                        "nodes": [
                                            {
                                                "name": "Backlog",
                                                "field": {"name": "Status"},
                                            }
                                        ]
                                    },
                                },
                            ]
                        }
                    }
                }
            }
        }
    )

    calls = patch_gh_by_arg(
        monkeypatch,
        {
            "issue close": "",
            "api graphql": multi_project_response,
            "item-edit": "{}",
        },
    )

    mod = import_cli()
    rc = mod.main(["--board", str(board_md), "close", "42"])

    captured = capsys.readouterr()
    assert rc == 0, captured.err
    edit = next((c for c in calls if "item-edit" in c), None)
    assert edit is not None, "expected item-edit on board-scoped item"
    joined = " ".join(edit)
    # The mutation must reference our board's item-id, never the sibling project's.
    assert "PVTI_ours" in joined
    assert "PVTI_other" not in joined


# ---------- close --body / --body-file (#184) ----------


def _patch_gh_capture_close_with_body(
    monkeypatch: pytest.MonkeyPatch,
    *,
    project_number: int = 7,
    status: str = "In Progress",
) -> tuple[list[list[str]], list[str | None]]:
    """Patch subprocess.run for `jared close --body*` tests.

    Routes by argv shape:
      - `issue comment` → snapshot --body / --body-file content, return URL
      - `issue close`   → empty stdout
      - `api graphql`   → projectItems response (find_item_id path)
      - `item-edit`     → "{}"

    Returns (calls, bodies) where `bodies` is the snapshot of every
    comment's body content (either --body inline or --body-file path
    contents) in call order. The CLI's `finally` deletes the temp file
    before the test can read it later, so snapshots happen at call time.
    """
    calls: list[list[str]] = []
    bodies: list[str | None] = []

    graphql_response = _graphql_item_response(project_number=project_number, status=status)
    comment_url = "https://github.com/brockamer/findajob/issues/42#issuecomment-9999"

    def fake_run(args: list[str], **_: object) -> FakeGhResult:
        calls.append(args)
        joined = " ".join(args)
        if "issue" in args and "comment" in args:
            if "--body-file" in args:
                idx = args.index("--body-file")
                try:
                    bodies.append(Path(args[idx + 1]).read_text())
                except FileNotFoundError:
                    bodies.append(None)
            elif "--body" in args:
                idx = args.index("--body")
                bodies.append(args[idx + 1])
            return FakeGhResult(stdout=comment_url)
        if "issue" in args and "close" in args:
            return FakeGhResult(stdout="")
        if "api graphql" in joined:
            return FakeGhResult(stdout=graphql_response)
        if "item-edit" in joined:
            return FakeGhResult(stdout="{}")
        return FakeGhResult(stdout="{}")

    monkeypatch.setattr(
        "skills.jared.scripts.lib.board.subprocess.run",
        fake_run,
    )
    return calls, bodies


def _call_kinds(calls: list[list[str]]) -> list[str]:
    """Classify each captured argv to its conceptual gh action.

    Used to assert call ORDER (comment must precede close), which is
    the #184 invariant: a close failure must not leave a closed issue
    with no Session note.
    """
    out: list[str] = []
    for c in calls:
        joined = " ".join(c)
        if "issue" in c and "comment" in c:
            out.append("comment")
        elif "issue" in c and "close" in c:
            out.append("close")
        elif "api graphql" in joined:
            out.append("graphql")
        elif "item-edit" in joined:
            out.append("item-edit")
        else:
            out.append("other")
    return out


def test_close_with_body_file_posts_comment_then_closes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """`jared close 42 --body-file note.md` MUST post the comment before the
    close, and the comment body MUST be what the file contained. Ordering is
    the #184 invariant — closing first then failing to comment would leave a
    closed issue without a Session note.
    """
    board_md = _write_board_with_status(tmp_path)
    note = tmp_path / "session.md"
    note.write_text("## Session 2026-05-22\n\nClosed as resolved.")

    calls, bodies = _patch_gh_capture_close_with_body(monkeypatch)

    mod = import_cli()
    rc = mod.main(["--board", str(board_md), "close", "42", "--body-file", str(note)])

    captured = capsys.readouterr()
    assert rc == 0, captured.err
    kinds = _call_kinds(calls)
    assert "comment" in kinds, f"expected an issue comment call; got {kinds}"
    assert "close" in kinds, f"expected an issue close call; got {kinds}"
    assert kinds.index("comment") < kinds.index("close"), (
        f"comment must precede close, got order: {kinds}"
    )
    assert bodies == ["## Session 2026-05-22\n\nClosed as resolved."]
    # Defense-in-depth set still runs.
    assert "item-edit" in kinds
    # Comment URL surfaced to the user.
    assert "OK: commented on #42" in captured.out
    assert "OK: closed #42, Status=Done" in captured.out


def test_close_with_inline_body(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """`--body <text>` mirrors `jared comment --body`: inline string, no path."""
    board_md = _write_board_with_status(tmp_path)
    _calls, bodies = _patch_gh_capture_close_with_body(monkeypatch)

    mod = import_cli()
    rc = mod.main(
        ["--board", str(board_md), "close", "42", "--body", "## Inline close note\n\nDone."]
    )

    captured = capsys.readouterr()
    assert rc == 0, captured.err
    assert bodies == ["## Inline close note\n\nDone."]


def test_close_with_body_file_stdin(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """`--body-file -` reads stdin, consistent with `jared comment` / `jared file`."""
    board_md = _write_board_with_status(tmp_path)
    _calls, bodies = _patch_gh_capture_close_with_body(monkeypatch)
    monkeypatch.setattr("sys.stdin", StringIO("piped close comment"))

    mod = import_cli()
    rc = mod.main(["--board", str(board_md), "close", "42", "--body-file", "-"])

    captured = capsys.readouterr()
    assert rc == 0, captured.err
    assert bodies == ["piped close comment"]


def test_close_without_body_does_not_post_comment(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Bare `jared close <N>` MUST NOT invoke `issue comment` — preserves the
    plain-close path for callers that want only the close behavior."""
    board_md = _write_board_with_status(tmp_path)
    calls, _bodies = _patch_gh_capture_close_with_body(monkeypatch)

    mod = import_cli()
    rc = mod.main(["--board", str(board_md), "close", "42"])

    captured = capsys.readouterr()
    assert rc == 0, captured.err
    kinds = _call_kinds(calls)
    assert "comment" not in kinds, f"plain close must skip comment; got {kinds}"
    assert "close" in kinds


def test_close_rejects_both_body_and_body_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """argparse mutex group on close mirrors the one on comment/file."""
    board_md = _write_board_with_status(tmp_path)
    note = tmp_path / "n.md"
    note.write_text("x")
    _patch_gh_capture_close_with_body(monkeypatch)

    mod = import_cli()
    with pytest.raises(SystemExit) as excinfo:
        mod.main(
            [
                "--board",
                str(board_md),
                "close",
                "42",
                "--body",
                "inline",
                "--body-file",
                str(note),
            ]
        )
    assert excinfo.value.code != 0
    captured = capsys.readouterr()
    assert "not allowed with" in captured.err or "mutually exclusive" in captured.err, captured.err


def _git_init_with_claude_local(tmp_path: Path, claude_local_content: str) -> None:
    """Mirrors test_cmd_comment.py / test_cmd_file.py — duplicated rather than
    extracted because the three files don't share a private helper module and
    adding one for three callers is over-engineering."""
    _subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    _subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=tmp_path,
        check=True,
    )
    _subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, check=True)
    (tmp_path / "CLAUDE.local.md").write_text(claude_local_content)


def test_close_with_body_when_close_fails_after_comment_posts(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """If `gh issue close` fails AFTER the comment posts, the comment is
    durable, the CLI exits non-zero, and the user can re-run `jared close <N>`
    without `--body*` to retry just the close. This pins the recovery contract
    documented in `references/jared-cli.md`.

    No silent rollback (comments are append-only by GitHub semantics — removing
    one would be worse than orphaning), but the comment URL MUST be printed
    BEFORE the error so the operator knows what landed.
    """
    board_md = _write_board_with_status(tmp_path)
    note = tmp_path / "n.md"
    note.write_text("## Session 2026-05-22\n\nDone — but close will fail.")
    comment_url = "https://github.com/brockamer/findajob/issues/42#issuecomment-1111"

    calls: list[list[str]] = []

    def fake_run(args: list[str], **kw: object) -> FakeGhResult:
        calls.append(args)
        if "issue" in args and "comment" in args:
            return FakeGhResult(stdout=comment_url)
        if "issue" in args and "close" in args:
            # gh non-zero exit propagates as GhInvocationError from run_gh.
            return FakeGhResult(stdout="", returncode=1, stderr="gh: API rate limit")
        return FakeGhResult(stdout="{}")

    monkeypatch.setattr(
        "skills.jared.scripts.lib.board.subprocess.run",
        fake_run,
    )

    mod = import_cli()
    rc = mod.main(["--board", str(board_md), "close", "42", "--body-file", str(note)])

    captured = capsys.readouterr()
    # main() catches GhInvocationError and returns 1.
    assert rc == 1, (
        f"expected non-zero on close failure; stdout={captured.out} stderr={captured.err}"
    )
    kinds = _call_kinds(calls)
    assert kinds.index("comment") < kinds.index("close"), (
        f"comment must precede close, got: {kinds}"
    )
    # No item-edit (defense-in-depth Status=Done) should run when close fails.
    assert "item-edit" not in kinds, f"item-edit must not run when close fails; kinds={kinds}"
    # Comment URL surfaced — the operator knows what landed before the error.
    assert "OK: commented on #42" in captured.out
    assert comment_url in captured.out
    # Error visible.
    assert "rate limit" in captured.err or "gh" in captured.err.lower()


def test_close_with_body_refuses_on_dirty_pre_flight_report(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Pre-flight redaction (#102) MUST short-circuit before any gh call when
    --body contains content from a gitignored claude-shaped local file.
    Neither the comment nor the close should run."""
    board_md = _write_board_with_status(tmp_path)
    leaky_phrase = "credentials live at /opt/secrets/foo.json on prod"
    _git_init_with_claude_local(tmp_path, leaky_phrase + "\n")

    monkeypatch.chdir(tmp_path)
    from skills.jared.scripts.lib.board import _clear_pre_flight_cache

    _clear_pre_flight_cache()

    calls, _bodies = _patch_gh_capture_close_with_body(monkeypatch)

    mod = import_cli()
    rc = mod.main(
        [
            "--board",
            str(board_md),
            "close",
            "42",
            "--body",
            f"Note: {leaky_phrase}.",
        ]
    )

    captured = capsys.readouterr()
    assert rc == 2, captured.err
    assert "pre-flight redaction check failed" in captured.err
    kinds = _call_kinds(calls)
    assert "comment" not in kinds, f"redactor must short-circuit before gh; calls: {kinds}"
    assert "close" not in kinds, f"redactor must block close too; calls: {kinds}"
