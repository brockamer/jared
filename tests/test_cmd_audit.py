"""Unit tests for /jared-audit — velocity computation + window fetch + CLI."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from skills.jared.scripts.lib.board import compute_velocity
from tests.conftest import patch_gh_by_arg


def test_compute_velocity_closure_count(monkeypatch: pytest.MonkeyPatch) -> None:
    """closures_last_14d reflects the count of issues returned by gh search."""
    closed_issues = json.dumps(
        [
            {"number": 1, "createdAt": "2026-05-10T00:00:00Z", "closedAt": "2026-05-20T00:00:00Z"},
            {"number": 2, "createdAt": "2026-05-15T00:00:00Z", "closedAt": "2026-05-19T00:00:00Z"},
            {"number": 3, "createdAt": "2026-05-01T00:00:00Z", "closedAt": "2026-05-18T00:00:00Z"},
        ]
    )
    patch_gh_by_arg(
        monkeypatch,
        {"search issues": closed_issues, "search prs": "[]"},
    )

    velocity = compute_velocity("brockamer/jared")

    assert velocity["closures_last_14d"] == 3


def test_compute_velocity_median_age_at_close(monkeypatch: pytest.MonkeyPatch) -> None:
    """median_age_at_close = median of (closedAt - createdAt) across closed issues."""
    closed_issues = json.dumps(
        [
            # 10 days, 4 days, 17 days → median 10
            {"number": 1, "createdAt": "2026-05-10T00:00:00Z", "closedAt": "2026-05-20T00:00:00Z"},
            {"number": 2, "createdAt": "2026-05-15T00:00:00Z", "closedAt": "2026-05-19T00:00:00Z"},
            {"number": 3, "createdAt": "2026-05-01T00:00:00Z", "closedAt": "2026-05-18T00:00:00Z"},
        ]
    )
    patch_gh_by_arg(
        monkeypatch,
        {"search issues": closed_issues, "search prs": "[]"},
    )

    velocity = compute_velocity("brockamer/jared")

    assert velocity["median_age_at_close"] == 10.0


def test_compute_velocity_empty_windows_return_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    """Empty closure / merge windows produce zeros, not crashes."""
    patch_gh_by_arg(monkeypatch, {"search issues": "[]", "search prs": "[]"})

    velocity = compute_velocity("brockamer/jared")

    assert velocity == {
        "closures_last_14d": 0,
        "median_age_at_close": 0.0,
        "median_pr_duration_days": 0.0,
    }


def test_compute_velocity_pr_duration(monkeypatch: pytest.MonkeyPatch) -> None:
    """median_pr_duration_days = median of (mergedAt - createdAt) across PRs."""
    closed_issues = "[]"
    merged_prs = json.dumps(
        [
            # 2 days, 1 day, 4 days → median 2
            {"number": 100, "createdAt": "2026-05-18T00:00:00Z",
             "mergedAt": "2026-05-20T00:00:00Z"},
            {"number": 101, "createdAt": "2026-05-19T00:00:00Z",
             "mergedAt": "2026-05-20T00:00:00Z"},
            {"number": 102, "createdAt": "2026-05-15T00:00:00Z",
             "mergedAt": "2026-05-19T00:00:00Z"},
        ]
    )
    patch_gh_by_arg(
        monkeypatch,
        {"search issues": closed_issues, "search prs": merged_prs},
    )

    velocity = compute_velocity("brockamer/jared")

    assert velocity["median_pr_duration_days"] == 2.0


def test_fetch_audit_window_count_returns_oldest_first(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """--count N returns the N oldest open issues, oldest first."""
    from skills.jared.scripts.lib.board import Board, fetch_audit_window
    from tests.conftest import write_minimal_board

    write_minimal_board(tmp_path)
    issues_payload = json.dumps(
        [
            {"number": 50, "title": "old", "body": "...", "createdAt": "2026-01-01T00:00:00Z",
             "labels": [], "milestone": None},
            {"number": 51, "title": "older", "body": "...", "createdAt": "2025-12-15T00:00:00Z",
             "labels": [], "milestone": None},
            {"number": 52, "title": "newest", "body": "...", "createdAt": "2026-03-01T00:00:00Z",
             "labels": [], "milestone": None},
        ]
    )
    patch_gh_by_arg(
        monkeypatch,
        {
            "issue list": issues_payload,
            "search issues": "[]",
            "search prs": "[]",
        },
    )

    board = Board.from_default(tmp_path)
    result = fetch_audit_window(board, count=2)

    assert [item["number"] for item in result["items"]] == [51, 50]
    assert "velocity" in result
