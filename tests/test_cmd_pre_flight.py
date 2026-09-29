"""Tests for `jared pre-flight` — the standalone PII check (#443).

`/jared-groom` and `/jared-audit` write body edits through `gh` directly, so
`jared file` / `comment` / `close` never see those bodies. This subcommand is
how those flows run the same check before the operator approves a write.
Every test runs from a directory with no project-board.md: the check must
not need a board.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from tests.conftest import SHORT_PRIVATE_TERMS, import_cli, write_short_line_private_file

PHRASE = "the deploy host is internal-foo-7.corp.example"


@pytest.fixture(autouse=True)
def _fresh_cache() -> None:
    from skills.jared.scripts.lib.board import _clear_pre_flight_cache

    _clear_pre_flight_cache()


def _repo_with_private_source(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    (tmp_path / "CLAUDE.local.md").write_text(PHRASE + "\n")


def test_pre_flight_clean_exits_0_and_reports_the_scan(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _repo_with_private_source(tmp_path)
    monkeypatch.chdir(tmp_path)
    rc = import_cli().main(["pre-flight", "--body", "Nothing private in here at all."])
    captured = capsys.readouterr()
    assert rc == 0, captured.err
    assert "scanned 1 private file" in captured.out
    assert captured.err == ""


def test_pre_flight_hit_exits_2_with_the_diff(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _repo_with_private_source(tmp_path)
    monkeypatch.chdir(tmp_path)
    body_file = tmp_path / "draft.md"
    body_file.write_text(f"Draft: {PHRASE} is flaky.\n")
    rc = import_cli().main(["pre-flight", "--body-file", str(body_file)])
    captured = capsys.readouterr()
    assert rc == 2
    assert "pre-flight redaction check failed" in captured.err
    assert "line 1:" in captured.err


def test_pre_flight_vacuous_exits_3_with_the_warning(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A git repo with no private source: nothing was checked, and the exit
    code says so, distinct from both a clean scan and a hit."""
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    monkeypatch.chdir(tmp_path)
    rc = import_cli().main(["pre-flight", "--body", "Any body."])
    captured = capsys.readouterr()
    assert rc == 3
    assert "warning: pre-flight scanned 0 private files" in captured.err
    assert captured.out == ""


def test_pre_flight_short_lines_only_exits_3_with_the_rule(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """#526: a private file of short terms gives no phrase to compare. The
    draft repeats both terms, but nothing was compared, so the exit is 3,
    not the 0 of a real clean scan."""
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    write_short_line_private_file(tmp_path)
    monkeypatch.chdir(tmp_path)
    body = f"{SHORT_PRIVATE_TERMS[0]} lives on {SHORT_PRIVATE_TERMS[1]}."
    rc = import_cli().main(["pre-flight", "--body", body])
    captured = capsys.readouterr()
    assert rc == 3, captured.err
    assert "private-notes.md" in captured.err
    assert "20+ characters" in captured.err
    assert captured.out == ""
