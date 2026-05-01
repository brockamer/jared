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
    # gh api graphql aliased batch returns comments for every in-flight number
    issue_comments = (
        '{"data": {"repository": {"i65": {"comments": {"nodes": ['
        '{"createdAt": "2026-04-24T10:00:00Z", "body": "## Session 2026-04-24\\n\\n'
        "**Progress:** wired prefilter\\n\\n"
        "**Next action:** decide YAML ordering question and unblock the third test."
        '"}'
        "]}}}}}"
    )
    # gh issue list for recently closed (state=closed, closed within 7d)
    closed_list = '[{"number": 251, "title": "v0.4 release", "closedAt": "2026-04-23T15:00:00Z"}]'

    patch_gh_by_arg(
        monkeypatch,
        responses={
            "item-list": item_list,
            "graphql": issue_comments,
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
    # Section ordering — the slash command depends on this contract
    in_flight_at = out.find("## In flight")
    up_next_at = out.find("## Top of Up Next")
    closed_at = out.find("## Recently closed")
    to_start_at = out.find("## To start")
    assert in_flight_at < up_next_at < closed_at < to_start_at, (
        "Section ordering regressed; slash command depends on this contract."
    )
    # Priority bracket appears in In Progress and Up Next bullets
    assert "[High]" in out
    assert "[Medium]" in out


def test_extract_next_action_handles_empty_body() -> None:
    """When the **Next action:** field has empty/whitespace body and is
    followed by another bold paragraph, the extractor returns None rather
    than slurping the next paragraph as the answer."""
    mod = import_cli()
    body = "## Session 2026-04-24\n\n**Next action:**\n\n**Decisions:** none."
    assert mod._extract_next_action(body) is None


def test_extract_next_action_returns_normal_one_liner() -> None:
    """Sanity check the happy path: a single sentence after **Next action:**
    returns as a stripped, whitespace-collapsed one-liner."""
    mod = import_cli()
    body = "## Session 2026-04-24\n\n**Next action:** decide the   YAML ordering   question."
    assert mod._extract_next_action(body) == "decide the YAML ordering question."


def test_empty_board_renders_placeholders(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    board_md = write_minimal_board(tmp_path)
    patch_gh_by_arg(
        monkeypatch,
        responses={
            "item-list": '{"items": []}',
            "issue list": "[]",
        },
    )
    mod = import_cli()
    rc = mod.main(["--board", str(board_md), "next-session-prompt"])
    out = capsys.readouterr().out

    assert rc == 0
    assert "(nothing in progress)" in out
    assert "(empty queue)" in out
    assert "(none)" in out


def test_in_progress_without_session_notes_skips_one_liner(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    board_md = write_minimal_board(tmp_path)
    item_list = (
        '{"items": ['
        '{"id": "a", "content": {"number": 7, "title": "Cold issue"}, '
        '"status": "In Progress", "priority": "Medium"}'
        "]}"
    )
    # No comments at all — graphql returns an empty nodes list under the alias
    patch_gh_by_arg(
        monkeypatch,
        responses={
            "item-list": item_list,
            "graphql": '{"data": {"repository": {"i7": {"comments": {"nodes": []}}}}}',
            "issue list": "[]",
        },
    )
    mod = import_cli()
    rc = mod.main(["--board", str(board_md), "next-session-prompt"])
    out = capsys.readouterr().out

    assert rc == 0
    assert "#7" in out and "Cold issue" in out
    # No Last session line should be emitted when no Session note exists
    assert "Last session" not in out


def test_session_note_without_next_action_field_skips_one_liner(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    board_md = write_minimal_board(tmp_path)
    item_list = (
        '{"items": ['
        '{"id": "a", "content": {"number": 9, "title": "Half-noted issue"}, '
        '"status": "In Progress", "priority": "Medium"}'
        "]}"
    )
    # Comment matches Session prefix but lacks **Next action:**
    issue_comments = (
        '{"data": {"repository": {"i9": {"comments": {"nodes": [{'
        '"createdAt": "2026-04-24T10:00:00Z",'
        '"body": "## Session 2026-04-24\\n\\n**Progress:** stuff happened.\\n"'
        "}]}}}}}"
    )
    patch_gh_by_arg(
        monkeypatch,
        responses={
            "item-list": item_list,
            "graphql": issue_comments,
            "issue list": "[]",
        },
    )
    mod = import_cli()
    rc = mod.main(["--board", str(board_md), "next-session-prompt"])
    out = capsys.readouterr().out

    assert rc == 0
    assert "#9" in out and "Half-noted issue" in out
    # The Next-action extractor returned None; no Last session line
    assert "Last session" not in out


def test_include_session_checks_emits_health_check_section(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """When the board has Session start checks defined and --include-session-checks
    is passed, the prompt includes a Quick health check section with the
    fenced commands. Without the flag, the section is omitted."""
    from textwrap import dedent

    board_md = tmp_path / "docs" / "project-board.md"
    board_md.parent.mkdir(parents=True)
    board_md.write_text(
        dedent("""\
        - Project URL: https://github.com/users/brockamer/projects/7
        - Project number: 7
        - Project ID: PVT_kwHO_xyz
        - Owner: brockamer
        - Repo: brockamer/findajob

        ## Session start checks

        ```bash
        echo health-check-one
        ```

        ```bash
        echo health-check-two
        ```
        """)
    )
    patch_gh_by_arg(
        monkeypatch,
        responses={
            "item-list": '{"items": []}',
            "issue list": "[]",
        },
    )
    mod = import_cli()
    rc = mod.main(
        [
            "--board",
            str(board_md),
            "next-session-prompt",
            "--include-session-checks",
        ]
    )
    out = capsys.readouterr().out

    assert rc == 0
    assert "## Quick health check on session start" in out
    assert "echo health-check-one" in out
    assert "echo health-check-two" in out


def test_session_checks_omitted_without_flag(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Even with checks defined, omitting the flag leaves the section out."""
    from textwrap import dedent

    board_md = tmp_path / "docs" / "project-board.md"
    board_md.parent.mkdir(parents=True)
    board_md.write_text(
        dedent("""\
        - Project URL: https://github.com/users/brockamer/projects/7
        - Project number: 7
        - Project ID: PVT_kwHO_xyz
        - Owner: brockamer
        - Repo: brockamer/findajob

        ## Session start checks

        ```bash
        echo should-not-appear
        ```
        """)
    )
    patch_gh_by_arg(
        monkeypatch,
        responses={
            "item-list": '{"items": []}',
            "issue list": "[]",
        },
    )
    mod = import_cli()
    rc = mod.main(["--board", str(board_md), "next-session-prompt"])
    out = capsys.readouterr().out

    assert rc == 0
    assert "Quick health check" not in out
    assert "echo should-not-appear" not in out
