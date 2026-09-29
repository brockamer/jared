"""Tests for `jared next-session-prompt` — the board-derived handoff skeleton.

Covers the deterministic, mechanical output: In Progress section with last
Session note one-liners, Up Next top 3, Recently closed last 7 days, footer.
All gh calls are patched; no network. Slash-command synthesis is not tested
here (it lives in commands/jared-wrap.md, not in code).
"""

from pathlib import Path
from typing import Any

import pytest

from tests.conftest import (
    KfTaskSpec,
    import_cli,
    patch_gh_by_arg,
    patch_gh_multi,
    patch_kf_board_provider,
    write_minimal_board,
    write_minimal_kanbanflow_board,
)


def test_next_session_prompt_renders_basic_sections(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    board_md = write_minimal_board(tmp_path)

    # gh api graphql aliased batch returns comments for every in-flight number
    issue_comments = (
        '{"data": {"repository": {"i65": {"comments": {"nodes": ['
        '{"createdAt": "2026-04-24T10:00:00Z", "body": "## Session 2026-04-24\\n\\n'
        "**Progress:** wired prefilter\\n\\n"
        "**Next action:** decide YAML ordering question and unblock the third test."
        '"}'
        "]}}}}}"
    )

    patch_gh_multi(
        monkeypatch,
        open_issues=[
            {"number": 65, "title": "Buried-gems UI", "state": "OPEN"},
            {"number": 273, "title": "Filter facets", "state": "OPEN"},
            {"number": 274, "title": "Indeed diagnostic", "state": "OPEN"},
        ],
        statuses={
            65: ("In Progress", "High"),
            273: ("Up Next", "High"),
            274: ("Up Next", "Medium"),
        },
        closed_issues=[
            {"number": 251, "title": "v0.4 release", "closedAt": "2026-04-23T15:00:00Z"}
        ],
        comments_batch_json=issue_comments,
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
    # Footer — states the posture is computed live, never a stored file
    assert "Assembled live from board state on each invocation" in out
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


def test_next_session_prompt_renders_session_label_inline_for_in_flight(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Per-session WIP arithmetic symmetry (#235): an In Progress item
    with a `session-N` label shows that tag inline in the handoff's
    "In flight" section, so the next session reading the handoff sees
    the same grouping signal `jared summary` shows."""
    board_md = write_minimal_board(tmp_path)
    patch_gh_multi(
        monkeypatch,
        open_issues=[
            {"number": 235, "title": "Per-session WIP", "state": "OPEN"},
        ],
        statuses={235: ("In Progress", "High")},
        labels_by_number={235: ["session-1", "enhancement"]},
    )

    mod = import_cli()
    rc = mod.main(["--board", str(board_md), "next-session-prompt"])
    out = capsys.readouterr().out

    assert rc == 0
    assert "#235" in out and "Per-session WIP" in out
    assert "(session-1)" in out


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
    patch_gh_multi(
        monkeypatch,
        open_issues=[{"number": 7, "title": "Cold issue", "state": "OPEN"}],
        statuses={7: ("In Progress", "Medium")},
        comments_batch_json='{"data": {"repository": {"i7": {"comments": {"nodes": []}}}}}',
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
    # Comment matches Session prefix but lacks **Next action:**
    issue_comments = (
        '{"data": {"repository": {"i9": {"comments": {"nodes": [{'
        '"createdAt": "2026-04-24T10:00:00Z",'
        '"body": "## Session 2026-04-24\\n\\n**Progress:** stuff happened.\\n"'
        "}]}}}}}"
    )
    patch_gh_multi(
        monkeypatch,
        open_issues=[{"number": 9, "title": "Half-noted issue", "state": "OPEN"}],
        statuses={9: ("In Progress", "Medium")},
        comments_batch_json=issue_comments,
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


def test_next_session_prompt_session_flag_filters_up_next(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """--session N filters Top of Up Next to issues carrying the session-N label."""
    board_md = write_minimal_board(tmp_path)
    patch_gh_multi(
        monkeypatch,
        open_issues=[
            {"number": 100, "title": "Session-1 item A", "state": "OPEN"},
            {"number": 200, "title": "Session-2 item", "state": "OPEN"},
            {"number": 101, "title": "Session-1 item B", "state": "OPEN"},
            {"number": 300, "title": "Unlabeled item", "state": "OPEN"},
        ],
        statuses={
            100: ("Up Next", "High"),
            200: ("Up Next", "High"),
            101: ("Up Next", "Medium"),
            300: ("Up Next", "Medium"),
        },
        labels_by_number={
            100: ["session-1"],
            200: ["session-2"],
            101: ["session-1"],
            300: [],
        },
    )

    mod = import_cli()
    rc = mod.main(["--board", str(board_md), "next-session-prompt", "--session", "1"])
    out = capsys.readouterr().out

    assert rc == 0
    assert "#100" in out
    assert "#101" in out
    assert "#200" not in out
    assert "#300" not in out


def test_next_session_prompt_session_flag_with_no_matches_renders_empty_marker(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """--session N with zero matching items in EITHER Up Next or Backlog
    prints the combined empty marker instead of falling through to
    unlabeled items."""
    board_md = write_minimal_board(tmp_path)
    patch_gh_multi(
        monkeypatch,
        open_issues=[
            {"number": 300, "title": "Unlabeled item", "state": "OPEN"},
        ],
        statuses={300: ("Up Next", "High")},
        labels_by_number={300: []},
    )

    mod = import_cli()
    rc = mod.main(["--board", str(board_md), "next-session-prompt", "--session", "1"])
    out = capsys.readouterr().out

    assert rc == 0
    assert "(none labeled session-1 in Up Next or Backlog)" in out
    assert "#300" not in out  # no silent fall-through


def test_next_session_prompt_session_flag_surfaces_backlog_staged(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """--session N surfaces session-N-labeled Backlog items under a distinct
    `## Session-N staged` subsection, kept separate from the Up Next
    recommendation. Other sessions' Backlog items are excluded (#286)."""
    board_md = write_minimal_board(tmp_path)
    # Four session-1 Backlog items — exceeds Up Next's [:3] cap on purpose:
    # the staged subsection must NOT truncate, since hiding staged work is
    # the exact bug this issue fixes.
    patch_gh_multi(
        monkeypatch,
        open_issues=[
            {"number": 100, "title": "Session-1 up next", "state": "OPEN"},
            {"number": 400, "title": "Session-1 staged A", "state": "OPEN"},
            {"number": 401, "title": "Session-1 staged B", "state": "OPEN"},
            {"number": 402, "title": "Session-1 staged C", "state": "OPEN"},
            {"number": 403, "title": "Session-1 staged D", "state": "OPEN"},
            {"number": 500, "title": "Session-2 staged in backlog", "state": "OPEN"},
        ],
        statuses={
            100: ("Up Next", "High"),
            400: ("Backlog", "Medium"),
            401: ("Backlog", "Medium"),
            402: ("Backlog", "Medium"),
            403: ("Backlog", "Medium"),
            500: ("Backlog", "Medium"),
        },
        labels_by_number={
            100: ["session-1"],
            400: ["session-1"],
            401: ["session-1"],
            402: ["session-1"],
            403: ["session-1"],
            500: ["session-2"],
        },
    )

    mod = import_cli()
    rc = mod.main(["--board", str(board_md), "next-session-prompt", "--session", "1"])
    out = capsys.readouterr().out

    assert rc == 0
    # Up Next recommendation still carries the in-column item
    assert "#100" in out
    # Distinct staged subsection surfaces ALL Backlog items — no [:3] cap
    assert "## Session-1 staged (not yet in Up Next)" in out
    for n in (400, 401, 402, 403):
        assert f"#{n}" in out
    # Other sessions' Backlog work stays hidden
    assert "#500" not in out
    # Staged subsection sits between Up Next and Recently closed
    up_next_at = out.find("## Top of Up Next")
    staged_at = out.find("## Session-1 staged")
    closed_at = out.find("## Recently closed")
    assert up_next_at < staged_at < closed_at


def test_next_session_prompt_session_flag_backlog_only_no_false_empty_marker(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """When Up Next has no session-N items but Backlog does, the combined
    empty marker must NOT fire — the staged Backlog work is real (#286)."""
    board_md = write_minimal_board(tmp_path)
    patch_gh_multi(
        monkeypatch,
        open_issues=[
            {"number": 300, "title": "Unlabeled up next", "state": "OPEN"},
            {"number": 400, "title": "Session-1 staged in backlog", "state": "OPEN"},
        ],
        statuses={
            300: ("Up Next", "High"),
            400: ("Backlog", "Medium"),
        },
        labels_by_number={
            300: [],
            400: ["session-1"],
        },
    )

    mod = import_cli()
    rc = mod.main(["--board", str(board_md), "next-session-prompt", "--session", "1"])
    out = capsys.readouterr().out

    assert rc == 0
    assert "## Session-1 staged (not yet in Up Next)" in out
    assert "#400" in out
    # The lying combined marker must not appear when Backlog has staged work
    assert "(none labeled session-1 in Up Next or Backlog)" not in out
    # Unlabeled Up Next item still excluded — no silent fall-through
    assert "#300" not in out


# --- provider-routed comment fetch (#395) ----------------------------------


def test_latest_session_note_oneliner_reads_neutral_comments() -> None:
    """The one-liner extractor consumes provider Comments, not gh JSON dicts.

    Routing the fetch through `BoardProvider.list_comments_batch` means this
    helper now receives neutral `Comment` dataclasses on every backend; reading
    them as dicts is what made the command GitHub-only.
    """
    from skills.jared.scripts.lib.board_provider import Comment

    mod = import_cli()
    comments = [
        Comment(author="brockamer", body="ordinary reply", created_at="2026-09-15T00:00:00Z"),
        Comment(
            author="brockamer",
            body="## Session 2026-09-16\n\n**Next action:** route the fetch through the provider.",
            created_at="2026-09-16T00:00:00Z",
        ),
    ]
    assert mod._latest_session_note_oneliner(comments) == "route the fetch through the provider."


def test_backend_failure_emits_no_partial_handoff(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A failing comment fetch must abort before the first print.

    The bug this guards (#395) half-emitted the handoff header and `## In
    flight` heading before dying, so a truncated posture looked like a valid
    one. Every backend read now happens above the first emit.
    """
    from tests.conftest import FakeGhResult

    board_md = write_minimal_board(tmp_path)
    patch_gh_multi(
        monkeypatch,
        open_issues=[{"number": 12, "title": "In-flight item", "state": "OPEN"}],
        statuses={12: ("In Progress", "High")},
    )

    # patch_gh_multi set subprocess.run on the shared module object (both Board
    # import paths see the one global `subprocess` — see conftest's docstring),
    # so reading it back here yields that fake, which we delegate to.
    import subprocess

    inner: Any = subprocess.run

    def failing_on_comments(args: list[str], **kw: object) -> object:
        if "comments(last:" in " ".join(args):
            return FakeGhResult(
                stdout="",
                returncode=1,
                stderr="gh: Could not resolve to an Issue with the number of 12.",
            )
        return inner(args, **kw)

    monkeypatch.setattr("skills.jared.scripts.lib.board.subprocess.run", failing_on_comments)

    mod = import_cli()
    rc = mod.main(["--board", str(board_md), "next-session-prompt"])
    captured = capsys.readouterr()

    assert rc == 1
    assert captured.out == "", f"stdout must be empty on backend failure, got: {captured.out!r}"
    assert "Could not resolve" in captured.err


@pytest.mark.parametrize("session", [None, 1])
def test_up_next_follows_board_position_not_creation_order(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    session: int | None,
) -> None:
    """Top of Up Next is the board's top three, with or without --session (#506)."""
    board_md = write_minimal_board(tmp_path)
    numbers = (15, 14, 13, 12, 11)  # repository query order: newest first
    patch_gh_multi(
        monkeypatch,
        open_issues=[{"number": n, "title": f"Up{n}", "state": "OPEN"} for n in numbers],
        statuses={n: ("Up Next", "Medium") for n in numbers},
        labels_by_number={n: ["session-1"] for n in numbers},
        positions=[11, 12, 13, 14, 15],
    )

    argv = ["--board", str(board_md), "next-session-prompt"]
    if session is not None:
        argv += ["--session", str(session)]
    rc = import_cli().main(argv)
    out = capsys.readouterr().out

    assert rc == 0
    section = out.split("## Top of Up Next", 1)[1].split("\n## ", 1)[0]
    shown = [line.split()[1] for line in section.splitlines() if line.startswith("- #")]
    assert shown == ["#11", "#12", "#13"]


# --- --pick: the next item for a bare /jared-start (#516) --------------------

PULLABLE = "A real summary.\n\n## Acceptance criteria\n\n- it works\n"
NO_CRITERIA = "A real summary.\n\n## Decisions\n\n(none yet)\n"


def _git_root(tmp_path: Path) -> Path:
    (tmp_path / ".git").mkdir(exist_ok=True)
    return tmp_path


def _section(out: str, heading: str) -> str:
    return out.split(heading, 1)[1].split("\n## ", 1)[0]


def test_pick_skips_blocked_and_not_pullable_items_on_github(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The pick walks all of Up Next in board order, not only the top three shown."""
    board_md = write_minimal_board(tmp_path)
    patch_gh_multi(
        monkeypatch,
        open_issues=[
            {"number": 11, "title": "Blocked", "body": PULLABLE},
            {"number": 12, "title": "Unshaped", "body": NO_CRITERIA},
            {"number": 13, "title": "Unshaped too", "body": ""},
            {"number": 14, "title": "Ready", "body": PULLABLE},
            {"number": 50, "title": "Blocker", "body": PULLABLE},
        ],
        statuses={
            11: ("Up Next", "High"),
            12: ("Up Next", "High"),
            13: ("Up Next", "High"),
            14: ("Up Next", "High"),
            50: ("Backlog", "Low"),
        },
        positions=[11, 12, 13, 14, 50],
        blocked_by={11: [50]},
    )

    mod = import_cli()
    rc = mod.main(
        [
            "--board",
            str(board_md),
            "next-session-prompt",
            "--pick",
            "--repo-root",
            str(_git_root(tmp_path)),
        ]
    )
    out = capsys.readouterr().out

    assert rc == 0
    pick = _section(out, "## Pick")
    assert "Pick: #14 — rule 2:" in pick
    assert "Skipped: #11 [Up Next] — blocked by open #50" in pick
    assert "Skipped: #12 [Up Next] — not pullable" in pick
    assert "Skipped: #13 [Up Next] — not pullable — empty body" in pick
    assert out.find("## Top of Up Next") < out.find("## Pick") < out.find("## Recently closed")


def test_pick_ignores_a_blocker_that_is_no_longer_open_on_github(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    board_md = write_minimal_board(tmp_path)
    patch_gh_multi(
        monkeypatch,
        open_issues=[{"number": 11, "title": "Was blocked", "body": PULLABLE}],
        statuses={11: ("Up Next", "High")},
        blocked_by={11: [7]},
    )

    mod = import_cli()
    rc = mod.main(
        ["--board", str(board_md), "next-session-prompt", "--pick"]
        + ["--repo-root", str(_git_root(tmp_path))]
    )
    out = capsys.readouterr().out

    assert rc == 0
    assert "Pick: #11 — rule 2:" in out
    assert "Skipped:" not in out


def test_pick_resumes_an_unlocked_in_progress_item(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    board_md = write_minimal_board(tmp_path)
    patch_gh_multi(
        monkeypatch,
        open_issues=[
            {"number": 20, "title": "Half done", "body": PULLABLE},
            {"number": 11, "title": "Ready", "body": PULLABLE},
        ],
        statuses={20: ("In Progress", "High"), 11: ("Up Next", "High")},
    )

    mod = import_cli()
    rc = mod.main(
        ["--board", str(board_md), "next-session-prompt", "--pick"]
        + ["--repo-root", str(_git_root(tmp_path))]
    )
    out = capsys.readouterr().out

    assert rc == 0
    assert "Pick: #20 — rule 1:" in out


def test_pick_skips_an_in_progress_item_that_holds_a_lock(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from skills.jared.scripts.lib import session_lock

    board_md = write_minimal_board(tmp_path)
    repo_root = _git_root(tmp_path)
    session_lock.write_lock(
        repo_root,
        session_lock.Lock(
            pid=1, started="2026-09-29T00:00:00Z", session=None, worktree_path=None, issue=20
        ),
    )
    patch_gh_multi(
        monkeypatch,
        open_issues=[
            {"number": 20, "title": "Held", "body": PULLABLE},
            {"number": 11, "title": "Ready", "body": PULLABLE},
        ],
        statuses={20: ("In Progress", "High"), 11: ("Up Next", "High")},
    )

    mod = import_cli()
    rc = mod.main(
        ["--board", str(board_md), "next-session-prompt", "--pick"]
        + ["--repo-root", str(repo_root)]
    )
    out = capsys.readouterr().out

    assert rc == 0
    assert "Pick: #11 — rule 2:" in out
    assert "Skipped: #20 [In Progress] — held by a session lock" in out
    assert "jared session-lock-clear --issue 20" in out


def test_pick_with_session_reasons_only_over_the_partition(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    board_md = write_minimal_board(tmp_path)
    patch_gh_multi(
        monkeypatch,
        open_issues=[
            {"number": 11, "title": "Other session", "body": PULLABLE},
            {"number": 12, "title": "This session", "body": PULLABLE},
        ],
        statuses={11: ("Up Next", "High"), 12: ("Up Next", "High")},
        labels_by_number={11: ["session-1"], 12: ["session-2"]},
        positions=[11, 12],
    )

    mod = import_cli()
    rc = mod.main(
        ["--board", str(board_md), "next-session-prompt", "--session", "2", "--pick"]
        + ["--repo-root", str(_git_root(tmp_path))]
    )
    out = capsys.readouterr().out

    assert rc == 0
    assert "Pick: #12 — rule 2:" in out
    assert "(session-2 partition)" in out
    assert "Skipped:" not in out


def test_pick_with_nothing_qualifying_points_at_stage(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    board_md = write_minimal_board(tmp_path)
    patch_gh_multi(
        monkeypatch,
        open_issues=[{"number": 11, "title": "Unshaped", "body": NO_CRITERIA}],
        statuses={11: ("Up Next", "High")},
    )

    mod = import_cli()
    rc = mod.main(
        ["--board", str(board_md), "next-session-prompt", "--pick"]
        + ["--repo-root", str(_git_root(tmp_path))]
    )
    out = capsys.readouterr().out

    assert rc == 0
    assert "Pick: none — " in out
    assert "/jared-stage" in _section(out, "## Pick")
    assert "Read the sections above, decide which issue to pull" in _section(out, "## To start")


def test_pick_requires_a_repo_root(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    board_md = write_minimal_board(tmp_path)
    patch_gh_multi(monkeypatch, open_issues=[], statuses={})

    mod = import_cli()
    rc = mod.main(["--board", str(board_md), "next-session-prompt", "--pick"])
    captured = capsys.readouterr()

    assert rc == 2
    assert captured.out == ""
    assert "--repo-root" in captured.err


def test_pick_on_a_non_git_root_reads_no_locks_and_says_so(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """No `.git` means no lock directory (#425): the pick runs without locks."""
    board_md = write_minimal_board(tmp_path)
    patch_gh_multi(
        monkeypatch,
        open_issues=[{"number": 11, "title": "Ready", "body": PULLABLE}],
        statuses={11: ("Up Next", "High")},
    )

    mod = import_cli()
    rc = mod.main(
        ["--board", str(board_md), "next-session-prompt", "--pick", "--repo-root", str(tmp_path)]
    )
    captured = capsys.readouterr()

    assert rc == 0
    assert "Pick: #11 — rule 2:" in captured.out
    assert ".git" in captured.err


def test_pick_read_failure_emits_no_partial_handoff(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The pick's reads sit above the first print, as the posture's do (#395)."""
    from tests.conftest import FakeGhResult

    board_md = write_minimal_board(tmp_path)
    patch_gh_multi(
        monkeypatch,
        open_issues=[{"number": 11, "title": "Ready", "body": PULLABLE}],
        statuses={11: ("Up Next", "High")},
    )
    import subprocess

    inner: Any = subprocess.run

    def failing_on_edges(args: list[str], **kw: object) -> object:
        if "blockedBy(first:20)" in " ".join(args):
            return FakeGhResult(stdout="", returncode=1, stderr="gh: edge fetch failed")
        return inner(args, **kw)

    monkeypatch.setattr("skills.jared.scripts.lib.board.subprocess.run", failing_on_edges)

    mod = import_cli()
    rc = mod.main(
        ["--board", str(board_md), "next-session-prompt", "--pick"]
        + ["--repo-root", str(_git_root(tmp_path))]
    )
    captured = capsys.readouterr()

    assert rc == 1
    assert captured.out == ""
    assert "edge fetch failed" in captured.err


def _run_kf_pick(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tasks: list[KfTaskSpec],
) -> tuple[int, str]:
    board_md = write_minimal_kanbanflow_board(tmp_path)
    monkeypatch.setenv("JARED_NO_CACHE", "1")
    mod = import_cli()  # before the patch — see patch_kf_board_provider's ORDERING note
    patch_kf_board_provider(monkeypatch, tmp_path, tasks)
    rc = mod.main(
        ["--board", str(board_md), "next-session-prompt", "--pick"]
        + ["--repo-root", str(_git_root(tmp_path))]
    )
    return rc, capsys.readouterr().out


def test_pick_skips_an_emulated_open_blocker_on_kanbanflow(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    rc, out = _run_kf_pick(
        tmp_path,
        monkeypatch,
        capsys,
        [
            {
                "number": 1,
                "name": "blocked",
                "column": "Up Next",
                "priority": "High",
                "description": PULLABLE,
                "labels": ["blocked-by:3"],
            },
            {
                "number": 2,
                "name": "ready",
                "column": "Up Next",
                "priority": "High",
                "description": PULLABLE,
            },
            {"number": 3, "name": "blocker", "column": "Backlog", "priority": "Low"},
        ],
    )

    assert rc == 0
    assert "Pick: #2 — rule 2:" in out
    assert "Skipped: #1 [Up Next] — blocked by open #3" in out


def test_pick_ignores_a_blocker_in_done_on_kanbanflow(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    rc, out = _run_kf_pick(
        tmp_path,
        monkeypatch,
        capsys,
        [
            {
                "number": 1,
                "name": "was blocked",
                "column": "Up Next",
                "priority": "High",
                "description": PULLABLE,
                "labels": ["blocked-by:3"],
            },
            {"number": 3, "name": "finished blocker", "column": "Done", "priority": "Low"},
        ],
    )

    assert rc == 0
    assert "Pick: #1 — rule 2:" in out
    assert "Skipped:" not in out
