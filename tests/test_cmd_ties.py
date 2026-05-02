"""Tests for the `jared ties` CLI subcommand."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from tests.conftest import import_cli


def _board_doc(tmp_path: Path) -> Path:
    doc = tmp_path / "project-board.md"
    doc.write_text(
        "# X\n\n"
        "- Project URL: https://github.com/users/x/projects/1\n"
        "- Project number: 1\n"
        "- Project ID: PVT_x\n"
        "- Owner: x\n"
        "- Repo: x/y\n\n"
        "### Status\n- Field ID: F1\n- Backlog: A\n- Up Next: B\n"
        "- In Progress: C\n- Blocked: D\n- Done: E\n\n"
        "### Priority\n- Field ID: F2\n- High: H\n- Medium: M\n- Low: L\n"
    )
    return doc


def _stub_open_issues() -> list[Any]:
    from skills.jared.scripts.lib.ties import OpenIssueForTies

    return [
        OpenIssueForTies(
            number=42,
            title="related issue",
            body="see #1",
            labels=("perf",),
            milestone="Phase 2",
            status="Backlog",
            priority="Medium",
            blocked_by=(),
        )
    ]


def _stub_target() -> Any:
    from skills.jared.scripts.lib.ties import OpenIssueForTies

    return OpenIssueForTies(
        number=1,
        title="target issue",
        body="references #42",
        labels=("perf",),
        milestone="Phase 2",
        status="In Progress",
        priority="High",
        blocked_by=(),
    )


def test_ties_smoke_renders_block(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    cli = import_cli()
    doc = _board_doc(tmp_path)

    with (
        patch.object(cli.Board, "graphql_budget", lambda self: (5000, 5000, 0)),
        patch.object(
            cli.Board,
            "fetch_open_issues_for_ties",
            lambda self, **kw: _stub_open_issues(),
        ),
        patch.object(cli.Board, "get_issue", lambda self, n: _stub_target()),
        patch.object(cli.Board, "tie_stop_words", lambda self: frozenset()),
    ):
        rc = cli.main(["--board", str(doc), "ties", "1"])

    assert rc == 0
    out = capsys.readouterr().out
    assert "Ties to consider:" in out
    assert "#42" in out


def test_ties_budget_exhausted_emits_skip_line(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    cli = import_cli()
    doc = _board_doc(tmp_path)
    with (
        patch.object(cli.Board, "graphql_budget", lambda self: (25, 5000, 0)),
        patch.object(cli.Board, "get_issue", lambda self, n: _stub_target()),
    ):
        rc = cli.main(["--board", str(doc), "ties", "1"])
    assert rc == 0
    out = capsys.readouterr().out.strip()
    assert out == "(GraphQL budget exhausted — ties analysis skipped)"


def test_ties_partial_mode_emits_diagnostic(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    cli = import_cli()
    doc = _board_doc(tmp_path)
    captured_calls: list[dict[str, Any]] = []

    def fake_fetch(self: Any, **kw: Any) -> list[Any]:
        captured_calls.append(dict(kw))
        return _stub_open_issues()

    with (
        patch.object(cli.Board, "graphql_budget", lambda self: (100, 5000, 0)),
        patch.object(cli.Board, "fetch_open_issues_for_ties", fake_fetch),
        patch.object(cli.Board, "get_issue", lambda self, n: _stub_target()),
        patch.object(cli.Board, "tie_stop_words", lambda self: frozenset()),
    ):
        rc = cli.main(["--board", str(doc), "ties", "1"])

    assert rc == 0
    out = capsys.readouterr().out
    assert "low GraphQL budget" in out
    # _cmd_ties calls fetch_open_issues_for_ties twice in partial mode:
    # once via get_issue (always include_bodies=True) and once for the
    # actual partial-mode analysis (include_bodies=False). Verify the
    # second call is the partial-mode one.
    assert captured_calls[-1] == {"include_bodies": False}


def test_ties_target_closed_returns_1(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    cli = import_cli()
    doc = _board_doc(tmp_path)
    with patch.object(cli.Board, "get_issue", lambda self, n: None):
        rc = cli.main(["--board", str(doc), "ties", "1"])
    assert rc == 1


def test_ties_json_format(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    cli = import_cli()
    doc = _board_doc(tmp_path)
    with (
        patch.object(cli.Board, "graphql_budget", lambda self: (5000, 5000, 0)),
        patch.object(
            cli.Board,
            "fetch_open_issues_for_ties",
            lambda self, **kw: _stub_open_issues(),
        ),
        patch.object(cli.Board, "get_issue", lambda self, n: _stub_target()),
        patch.object(cli.Board, "tie_stop_words", lambda self: frozenset()),
    ):
        rc = cli.main(["--board", str(doc), "ties", "1", "--format", "json"])
    assert rc == 0
    out = capsys.readouterr().out
    parsed = json.loads(out)
    assert isinstance(parsed, list)
    assert parsed[0]["related_n"] == 42
