import json
from pathlib import Path

import pytest

from tests.conftest import (
    graphql_item_response,
    import_cli,
    patch_gh,
    write_minimal_board,
)


def test_get_item_prints_json(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    board_md = write_minimal_board(tmp_path)
    patch_gh(
        monkeypatch,
        stdout=graphql_item_response(
            project_number=7, item_id="PVTI_aaa", status="In Progress", priority="High"
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
    assert out["priority"] == "High"


def test_get_item_issue_not_found_exits_nonzero(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    board_md = write_minimal_board(tmp_path)
    patch_gh(
        monkeypatch,
        stdout='{"data":{"repository":{"issue":{"projectItems":{"nodes":[]}}}}}',
    )

    mod = import_cli()
    rc = mod.main(["--board", str(board_md), "get-item", "999"])

    captured = capsys.readouterr()
    assert rc != 0
    assert "999" in captured.err or "not found" in captured.err.lower()
