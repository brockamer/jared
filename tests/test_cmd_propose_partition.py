"""Tests for `jared propose-partition`."""

import json
from pathlib import Path

import pytest

from tests.conftest import import_cli, patch_gh_multi, write_minimal_board


def test_propose_partition_human_format_renders_proposal(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    board_md = write_minimal_board(tmp_path)
    patch_gh_multi(
        monkeypatch,
        open_issues=[
            {
                "number": 1,
                "title": "A",
                "state": "OPEN",
                "body": "Edits `lib/board.py`.",
            },
            {
                "number": 2,
                "title": "B",
                "state": "OPEN",
                "body": "Edits `commands/jared-wrap.md`.",
            },
        ],
        statuses={1: ("Up Next", "High"), 2: ("Up Next", "Medium")},
        labels_by_number={1: [], 2: []},
    )

    mod = import_cli()
    rc = mod.main(
        ["--board", str(board_md), "propose-partition", "--sessions", "2"]
    )
    out = capsys.readouterr().out

    assert rc == 0
    assert "session-1" in out
    assert "session-2" in out
    assert "#1" in out and "#2" in out


def test_propose_partition_json_format_returns_structured_proposal(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    board_md = write_minimal_board(tmp_path)
    patch_gh_multi(
        monkeypatch,
        open_issues=[
            {"number": 1, "title": "A", "state": "OPEN", "body": "Edits `x/y.py`."},
        ],
        statuses={1: ("Up Next", "High")},
        labels_by_number={1: []},
    )

    mod = import_cli()
    rc = mod.main(
        [
            "--board",
            str(board_md),
            "propose-partition",
            "--sessions",
            "2",
            "--format",
            "json",
        ]
    )
    out = capsys.readouterr().out

    assert rc == 0
    payload = json.loads(out)
    assert "keep" in payload
    assert "add" in payload
    assert "floats" in payload
    # Issue 1 has file paths and no existing label → should be in `add`.
    assert any(a["issue"] == 1 for a in payload["add"])
