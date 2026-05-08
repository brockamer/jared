from types import ModuleType

import pytest

from tests.conftest import import_cli


@pytest.fixture(scope="module")
def cli() -> ModuleType:
    return import_cli()


@pytest.mark.parametrize(
    "raw, expected",
    [
        # canonical forms pass through unchanged
        ("High", "High"),
        ("Medium", "Medium"),
        ("Low", "Low"),
        # lowercase normalized
        ("high", "High"),
        ("medium", "Medium"),
        ("low", "Low"),
        # uppercase normalized
        ("HIGH", "High"),
        ("MEDIUM", "Medium"),
        ("LOW", "Low"),
        # med alias
        ("med", "Medium"),
        ("Med", "Medium"),
        ("MED", "Medium"),
        # leading/trailing whitespace stripped
        (" high ", "High"),
        (" med ", "Medium"),
    ],
)
def test_normalize_priority(cli: ModuleType, raw: str, expected: str) -> None:
    assert cli._normalize_priority(raw) == expected


def test_file_parser_accepts_lowercase(cli: ModuleType) -> None:
    """argparse rejects invalid choices before calling type=, so test via parser."""
    parser = cli.build_parser()
    args = parser.parse_args(
        ["--board", "x", "file", "--title", "t", "--body", "b", "--priority", "high"]
    )
    assert args.priority == "High"


def test_file_parser_accepts_med_alias(cli: ModuleType) -> None:
    parser = cli.build_parser()
    args = parser.parse_args(
        ["--board", "x", "file", "--title", "t", "--body", "b", "--priority", "med"]
    )
    assert args.priority == "Medium"


def test_add_to_board_parser_accepts_lowercase(cli: ModuleType) -> None:
    parser = cli.build_parser()
    args = parser.parse_args(
        ["--board", "x", "add-to-board", "42", "--priority", "low"]
    )
    assert args.priority == "Low"


def test_invalid_priority_rejected(cli: ModuleType) -> None:
    parser = cli.build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(
            ["--board", "x", "file", "--title", "t", "--body", "b", "--priority", "urgent"]
        )
