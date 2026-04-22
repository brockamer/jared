import json
from pathlib import Path

import pytest

from tests.conftest import import_cli, patch_gh, write_minimal_board


def test_get_item_prints_json(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    board_md = write_minimal_board(tmp_path)
    patch_gh(
        monkeypatch,
        stdout=(
            '{"items": ['
            '{"id": "PVTI_aaa", "content": {"number": 42}, '
            '"status": "In Progress", "priority": "High"}'
            "]}"
        ),
    )

    mod = import_cli()
    rc = mod.main(["--board", str(board_md), "get-item", "42"])

    captured = capsys.readouterr()
    assert rc == 0, captured.err
    out = json.loads(captured.out)
    assert out["issue_number"] == 42
    assert out["item_id"] == "PVTI_aaa"
    assert out["status"] == "In Progress"


def test_get_item_issue_not_found_exits_nonzero(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    board_md = write_minimal_board(tmp_path)
    patch_gh(monkeypatch, stdout='{"items": []}')

    mod = import_cli()
    rc = mod.main(["--board", str(board_md), "get-item", "999"])

    captured = capsys.readouterr()
    assert rc != 0
    assert "999" in captured.err or "not found" in captured.err.lower()
