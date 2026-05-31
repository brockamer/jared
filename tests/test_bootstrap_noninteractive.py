"""Tests for bootstrap-project.py's non-interactive flags (#268).

#268: the script prompts via input() for "Create them now?" and for the
work-stream list. Under Claude Code, stdin is not a terminal, so the second
input() raises EOFError. Two flags make the script usable non-interactively:

  --yes              auto-confirm the create prompt (no input() reached)
  --work-streams ... supply the work-stream list without prompting

Both are optional; omitting them leaves the script interactive.
"""

from tests.conftest import import_bootstrap


def test_parser_accepts_yes_and_work_streams() -> None:
    mod = import_bootstrap()
    parser = mod.build_parser()
    args = parser.parse_args(
        ["--url", "U", "--repo", "o/r", "--yes", "--work-streams", "Backend,Frontend"]
    )
    assert args.yes is True
    assert args.work_streams == "Backend,Frontend"


def test_parser_yes_and_work_streams_default_off() -> None:
    mod = import_bootstrap()
    args = mod.build_parser().parse_args(["--url", "U", "--repo", "o/r"])
    assert args.yes is False
    assert args.work_streams is None


def test_parse_work_streams_splits_and_trims() -> None:
    mod = import_bootstrap()
    assert mod.parse_work_streams("Backend, Frontend ,Infra") == ["Backend", "Frontend", "Infra"]


def test_parse_work_streams_empty_is_empty_list() -> None:
    mod = import_bootstrap()
    assert mod.parse_work_streams("") == []
    assert mod.parse_work_streams("  ,  ,") == []
