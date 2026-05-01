import subprocess
import sys
from pathlib import Path
from textwrap import dedent

import pytest

from tests.conftest import import_cli, patch_gh, patch_gh_by_arg

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
        {"item-list": '{"items": [{"id": "PVTI_aaa", "content": {"number": 42}}]}'},
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
        {"item-list": '{"items": [{"id": "PVTI_aaa", "content": {"number": 42}}]}'},
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
    patch_gh_by_arg(monkeypatch, {"item-list": '{"items": []}'})
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
