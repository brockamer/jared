"""Tests for `jared next-session-prompt` — the board-derived handoff skeleton.

Covers the deterministic, mechanical output: In Progress section with last
Session note one-liners, Up Next top 3, Recently closed last 7 days, footer.
All gh calls are patched; no network. Slash-command synthesis is not tested
here (it lives in commands/jared-wrap.md, not in code).
"""

from pathlib import Path

import pytest

from tests.conftest import import_cli, patch_gh_by_arg, write_minimal_board


def test_next_session_prompt_renders_basic_sections(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    board_md = write_minimal_board(tmp_path)

    # gh project item-list returns one In Progress, two Up Next, one closed
    item_list = (
        '{"items": ['
        '{"id": "a", "content": {"number": 65, "title": "Buried-gems UI"}, '
        '"status": "In Progress", "priority": "High"},'
        '{"id": "b", "content": {"number": 273, "title": "Filter facets"}, '
        '"status": "Up Next", "priority": "High"},'
        '{"id": "c", "content": {"number": 274, "title": "Indeed diagnostic"}, '
        '"status": "Up Next", "priority": "Medium"}'
        "]}"
    )
    # gh issue view <N> --json comments returns the latest Session note
    issue_comments = (
        '{"comments": ['
        '{"createdAt": "2026-04-24T10:00:00Z", "body": "## Session 2026-04-24\\n\\n'
        "**Progress:** wired prefilter\\n\\n"
        "**Next action:** decide YAML ordering question and unblock the third test."
        '"}'
        "]}"
    )
    # gh issue list for recently closed (state=closed, closed within 7d)
    closed_list = '[{"number": 251, "title": "v0.4 release", "closedAt": "2026-04-23T15:00:00Z"}]'

    patch_gh_by_arg(
        monkeypatch,
        responses={
            "item-list": item_list,
            "issue view 65": issue_comments,
            "issue list": closed_list,
        },
    )

    mod = import_cli()
    rc = mod.main(["--board", str(board_md), "next-session-prompt"])
    out = capsys.readouterr().out

    assert rc == 0
    # Headings
    assert "# Session handoff" in out
    assert "## In flight" in out
    assert "## Top of Up Next" in out
    assert "## Recently closed" in out
    assert "## To start" in out
    # In Progress item
    assert "#65" in out and "Buried-gems UI" in out
    # Last Session note one-liner — Next action sentence
    assert "decide YAML ordering question" in out
    # Up Next top 3 (only 2 in this fixture)
    assert "#273" in out and "#274" in out
    # Recently closed
    assert "#251" in out and "v0.4 release" in out
    # Footer warning
    assert "Regenerated each wrap" in out
