import subprocess
import sys
from pathlib import Path

CLI = Path(__file__).parents[1] / "skills" / "jared" / "scripts" / "jared"


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
