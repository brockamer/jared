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
    rc = mod.main([
        "--board", str(board_md),
        "comment", "42",
        "--body-file", str(body_file),
    ])

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
    rc = mod.main([
        "--board", str(board_md),
        "comment", "42",
        "--body-file", "-",
    ])

    captured = capsys.readouterr()
    assert rc == 0, captured.err
    assert bodies == ["comment from stdin"]
