import importlib.util
import json
from importlib.machinery import SourceFileLoader
from pathlib import Path
from textwrap import dedent
from types import ModuleType

import pytest

SKILL_SCRIPTS = Path(__file__).parents[1] / "skills" / "jared" / "scripts"
CLI_PATH = SKILL_SCRIPTS / "jared"


def _import_cli() -> ModuleType:
    loader = SourceFileLoader("jared_cli", str(CLI_PATH))
    spec = importlib.util.spec_from_loader("jared_cli", loader)
    assert spec is not None
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


def _write_board(tmp_path: Path) -> Path:
    board_md = tmp_path / "docs" / "project-board.md"
    board_md.parent.mkdir(parents=True)
    board_md.write_text(dedent("""\
        - Project URL: https://github.com/users/brockamer/projects/7
        - Project number: 7
        - Project ID: PVT_kwHO_xyz
        - Owner: brockamer
        - Repo: brockamer/findajob
    """))
    return board_md


def test_get_item_prints_json(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    board_md = _write_board(tmp_path)

    class FakeResult:
        returncode = 0
        stdout = (
            '{"items": ['
            '{"id": "PVTI_aaa", "content": {"number": 42}, '
            '"status": "In Progress", "priority": "High"}'
            ']}'
        )
        stderr = ""

    monkeypatch.setattr(
        "skills.jared.scripts.lib.board.subprocess.run",
        lambda *a, **kw: FakeResult(),
    )

    mod = _import_cli()
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
    board_md = _write_board(tmp_path)

    class FakeResult:
        returncode = 0
        stdout = '{"items": []}'
        stderr = ""

    monkeypatch.setattr(
        "skills.jared.scripts.lib.board.subprocess.run",
        lambda *a, **kw: FakeResult(),
    )

    mod = _import_cli()
    rc = mod.main(["--board", str(board_md), "get-item", "999"])

    captured = capsys.readouterr()
    assert rc != 0
    assert "999" in captured.err or "not found" in captured.err.lower()
