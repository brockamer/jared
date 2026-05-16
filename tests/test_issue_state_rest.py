"""Tests for fetch_issue_state_rest — REST migration for per-issue state checks (#54).

These tests cover the unconditional REST path with `JARED_NO_CACHE=1` set so
the FakeResult fixtures return raw JSON bodies (no HTTP status line). The
ETag/conditional GET layer (#147) is covered in test_issue_state_etag.py.
"""

from __future__ import annotations

from typing import Any

import pytest


def test_fetch_issue_state_rest_returns_closed_with_closed_at(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("JARED_NO_CACHE", "1")
    from skills.jared.scripts.lib import board

    captured_args: list[list[str]] = []

    class FakeResult:
        returncode = 0
        stdout = '{"state": "closed", "closed_at": "2026-05-01T12:00:00Z"}'
        stderr = ""

    def fake_run(args: list[str], **kw: Any) -> FakeResult:
        captured_args.append(args)
        return FakeResult()

    monkeypatch.setattr("skills.jared.scripts.lib.board.subprocess.run", fake_run)

    state, closed_at = board.fetch_issue_state_rest("brockamer/jared", 52)

    assert state == "CLOSED"
    assert closed_at == "2026-05-01T12:00:00Z"
    # Critical: must use `gh api` (REST core bucket), not `gh issue view` (GraphQL bucket).
    assert captured_args[0][:2] == ["gh", "api"]
    assert "repos/brockamer/jared/issues/52" in captured_args[0]


def test_fetch_issue_state_rest_returns_open_with_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JARED_NO_CACHE", "1")
    from skills.jared.scripts.lib import board

    class FakeResult:
        returncode = 0
        stdout = '{"state": "open", "closed_at": null}'
        stderr = ""

    monkeypatch.setattr(
        "skills.jared.scripts.lib.board.subprocess.run",
        lambda *a, **kw: FakeResult(),
    )

    state, closed_at = board.fetch_issue_state_rest("brockamer/jared", 99)
    assert state == "OPEN"
    assert closed_at is None


def test_fetch_issue_state_rest_returns_merged_for_merged_pr(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """REST returns state="closed" for merged PRs; the helper must surface
    the merged-vs-closed-unmerged distinction via `pull_request.merged_at`
    so archive-plan's `## Shipped` predicate (merged-only) keeps working."""
    monkeypatch.setenv("JARED_NO_CACHE", "1")
    from skills.jared.scripts.lib import board

    class FakeResult:
        returncode = 0
        stdout = (
            '{"state": "closed", "closed_at": "2026-05-02T15:30:00Z", '
            '"pull_request": {"merged_at": "2026-05-02T15:30:00Z"}}'
        )
        stderr = ""

    monkeypatch.setattr(
        "skills.jared.scripts.lib.board.subprocess.run",
        lambda *a, **kw: FakeResult(),
    )

    state, closed_at = board.fetch_issue_state_rest("brockamer/jared", 415)
    assert state == "MERGED"
    assert closed_at == "2026-05-02T15:30:00Z"


def test_fetch_issue_state_rest_returns_closed_for_unmerged_pr(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A PR that was closed without merging must NOT report as MERGED."""
    monkeypatch.setenv("JARED_NO_CACHE", "1")
    from skills.jared.scripts.lib import board

    class FakeResult:
        returncode = 0
        stdout = (
            '{"state": "closed", "closed_at": "2026-05-02T15:30:00Z", '
            '"pull_request": {"merged_at": null}}'
        )
        stderr = ""

    monkeypatch.setattr(
        "skills.jared.scripts.lib.board.subprocess.run",
        lambda *a, **kw: FakeResult(),
    )

    state, _ = board.fetch_issue_state_rest("brockamer/jared", 999)
    assert state == "CLOSED"


def test_fetch_issue_state_rest_returns_unknown_on_gh_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("JARED_NO_CACHE", "1")
    from skills.jared.scripts.lib import board

    class FakeResult:
        returncode = 1
        stdout = ""
        stderr = "gh: HTTP 404"

    monkeypatch.setattr(
        "skills.jared.scripts.lib.board.subprocess.run",
        lambda *a, **kw: FakeResult(),
    )

    state, closed_at = board.fetch_issue_state_rest("brockamer/jared", 99999)
    assert state == "UNKNOWN"
    assert closed_at is None
