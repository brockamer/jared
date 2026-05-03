import subprocess as _subprocess
from io import StringIO
from pathlib import Path

import pytest

from tests.conftest import FakeGhResult, import_cli, write_minimal_board


def _patch_gh_capturing_body_file(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[list[list[str]], list[str | None]]:
    """Patch subprocess.run to:
    1. capture the argv
    2. snapshot the --body-file content at call time (before the CLI's
       `finally` clause deletes the temp file)
    """
    calls: list[list[str]] = []
    bodies: list[str | None] = []

    def fake_run(args: list[str], **kw: object) -> FakeGhResult:
        calls.append(args)
        if "--body-file" in args:
            idx = args.index("--body-file")
            body_path = args[idx + 1]
            try:
                bodies.append(Path(body_path).read_text())
            except FileNotFoundError:
                bodies.append(None)
        return FakeGhResult(stdout="{}")

    monkeypatch.setattr(
        "skills.jared.scripts.lib.board.subprocess.run",
        fake_run,
    )
    return calls, bodies


def test_comment_invokes_issue_comment_with_body_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    board_md = write_minimal_board(tmp_path)
    body_file = tmp_path / "note.md"
    body_file.write_text("## Session note\n\nTook the action.")

    calls, bodies = _patch_gh_capturing_body_file(monkeypatch)

    mod = import_cli()
    rc = mod.main(
        [
            "--board",
            str(board_md),
            "comment",
            "42",
            "--body-file",
            str(body_file),
        ]
    )

    captured = capsys.readouterr()
    assert rc == 0, captured.err
    call = next(c for c in calls if "comment" in c)
    assert "issue" in call and "comment" in call
    assert "42" in call
    assert "brockamer/findajob" in " ".join(call)
    assert bodies == ["## Session note\n\nTook the action."]


def test_comment_from_stdin(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    board_md = write_minimal_board(tmp_path)
    calls, bodies = _patch_gh_capturing_body_file(monkeypatch)
    monkeypatch.setattr("sys.stdin", StringIO("comment from stdin"))

    mod = import_cli()
    rc = mod.main(
        [
            "--board",
            str(board_md),
            "comment",
            "42",
            "--body-file",
            "-",
        ]
    )

    captured = capsys.readouterr()
    assert rc == 0, captured.err
    assert bodies == ["comment from stdin"]


def test_comment_with_inline_body(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """--body <text> on `jared comment` mirrors `gh issue comment --body`."""
    board_md = write_minimal_board(tmp_path)
    _calls, bodies = _patch_gh_capturing_body_file(monkeypatch)

    mod = import_cli()
    rc = mod.main(
        [
            "--board",
            str(board_md),
            "comment",
            "42",
            "--body",
            "## Inline note\n\nFrom argv.",
        ]
    )
    captured = capsys.readouterr()
    assert rc == 0, captured.err
    assert bodies == ["## Inline note\n\nFrom argv."]


def test_comment_rejects_both_body_and_body_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    board_md = write_minimal_board(tmp_path)
    body_file = tmp_path / "note.md"
    body_file.write_text("from file")
    _patch_gh_capturing_body_file(monkeypatch)

    mod = import_cli()
    with pytest.raises(SystemExit) as excinfo:
        mod.main(
            [
                "--board",
                str(board_md),
                "comment",
                "42",
                "--body",
                "from inline",
                "--body-file",
                str(body_file),
            ]
        )
    assert excinfo.value.code != 0
    captured = capsys.readouterr()
    assert "not allowed with" in captured.err or "mutually exclusive" in captured.err, captured.err


def test_comment_handles_plain_text_url_response(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """gh issue comment returns a plain-text URL on stdout, not JSON.

    Regression for #24: _cmd_comment used the JSON-parsing wrapper and every
    successful invocation printed `gh returned non-JSON output: <url>` to
    stderr, making the user think the post failed.
    """
    board_md = write_minimal_board(tmp_path)
    body_file = tmp_path / "note.md"
    body_file.write_text("hello")

    url = "https://github.com/brockamer/findajob/issues/42#issuecomment-4312200024"

    def fake_run(args: list[str], **kw: object) -> FakeGhResult:
        return FakeGhResult(stdout=url)

    monkeypatch.setattr("skills.jared.scripts.lib.board.subprocess.run", fake_run)

    mod = import_cli()
    rc = mod.main(
        [
            "--board",
            str(board_md),
            "comment",
            "42",
            "--body-file",
            str(body_file),
        ]
    )

    captured = capsys.readouterr()
    assert rc == 0
    assert captured.err == ""
    assert "OK:" in captured.out
    assert "42" in captured.out
    assert url in captured.out


def _git_init_with_claude_local(tmp_path: Path, claude_local_content: str) -> None:
    """Same shape as test_cmd_file.py's helper. Duplicated rather than
    extracted because the two files don't share a private helper module
    today and adding one for two callers is over-engineering."""
    _subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    _subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=tmp_path,
        check=True,
    )
    _subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, check=True)
    (tmp_path / "CLAUDE.local.md").write_text(claude_local_content)


def test_cmd_comment_refuses_on_dirty_pre_flight_report(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    board_md = write_minimal_board(tmp_path)
    leaky_phrase = "credentials live at /opt/secrets/foo.json on prod"
    _git_init_with_claude_local(tmp_path, leaky_phrase + "\n")

    monkeypatch.chdir(tmp_path)
    from skills.jared.scripts.lib.board import _clear_pre_flight_cache

    _clear_pre_flight_cache()

    calls, _bodies = _patch_gh_capturing_body_file(monkeypatch)

    mod = import_cli()
    rc = mod.main(
        [
            "--board",
            str(board_md),
            "comment",
            "42",
            "--body",
            f"Note: {leaky_phrase}.",
        ]
    )
    captured = capsys.readouterr()
    assert rc == 2, captured.err
    assert "pre-flight redaction check failed" in captured.err
    assert not any("issue" in c and "comment" in c for c in calls), (
        f"redactor must short-circuit before gh; calls: {calls}"
    )


def test_cmd_comment_proceeds_on_clean_pre_flight_report(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    board_md = write_minimal_board(tmp_path)
    _git_init_with_claude_local(tmp_path, "credentials live at /opt/secrets/foo.json on prod\n")

    monkeypatch.chdir(tmp_path)
    from skills.jared.scripts.lib.board import _clear_pre_flight_cache

    _clear_pre_flight_cache()

    calls, bodies = _patch_gh_capturing_body_file(monkeypatch)

    mod = import_cli()
    rc = mod.main(
        [
            "--board",
            str(board_md),
            "comment",
            "42",
            "--body",
            "perfectly safe note with no overlap",
        ]
    )
    captured = capsys.readouterr()
    assert rc == 0, captured.err
    assert bodies == ["perfectly safe note with no overlap"]


def test_cmd_comment_clean_when_no_claude_local(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Mirror of the test_cmd_file.py guard test: no CLAUDE.local.md → no
    redactor activity → existing tests stay green. Includes monkeypatch.chdir
    + cache clear to isolate from pytest's cwd (Task 8 fix-cycle pattern)."""
    board_md = write_minimal_board(tmp_path)

    monkeypatch.chdir(tmp_path)
    from skills.jared.scripts.lib.board import _clear_pre_flight_cache

    _clear_pre_flight_cache()

    body_file = tmp_path / "note.md"
    body_file.write_text("ordinary session note.")

    _calls, bodies = _patch_gh_capturing_body_file(monkeypatch)

    mod = import_cli()
    rc = mod.main(
        [
            "--board",
            str(board_md),
            "comment",
            "42",
            "--body-file",
            str(body_file),
        ]
    )
    captured = capsys.readouterr()
    assert rc == 0, captured.err
    assert bodies == ["ordinary session note."]
