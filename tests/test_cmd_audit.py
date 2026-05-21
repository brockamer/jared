"""Unit tests for /jared-audit — velocity computation + window fetch + CLI."""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import pytest

from skills.jared.scripts.lib.board import compute_velocity
from tests.conftest import patch_gh_by_arg

EMPTY_BLOCKED_BY_PAYLOAD = json.dumps(
    {
        "data": {
            "repository": {
                "issues": {
                    "pageInfo": {"hasNextPage": False, "endCursor": None},
                    "nodes": [],
                }
            }
        }
    }
)


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
            "blockedBy": EMPTY_BLOCKED_BY_PAYLOAD,
        },
    )

    board = Board.from_default(tmp_path)
    result = fetch_audit_window(board, count=2)

    assert [item["number"] for item in result["items"]] == [51, 50]
    assert "velocity" in result


def test_fetch_audit_window_age_days_filters_by_age(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """--age-days N keeps items older than N days from today."""
    from skills.jared.scripts.lib.board import Board, fetch_audit_window
    from tests.conftest import write_minimal_board

    write_minimal_board(tmp_path)
    now = dt.datetime.now(dt.UTC)
    issues_payload = json.dumps(
        [
            {"number": 10, "title": "ancient", "body": "...",
             "createdAt": (now - dt.timedelta(days=120)).isoformat(),
             "labels": [], "milestone": None},
            {"number": 11, "title": "stale", "body": "...",
             "createdAt": (now - dt.timedelta(days=45)).isoformat(),
             "labels": [], "milestone": None},
            {"number": 12, "title": "fresh", "body": "...",
             "createdAt": (now - dt.timedelta(days=5)).isoformat(),
             "labels": [], "milestone": None},
        ]
    )
    patch_gh_by_arg(
        monkeypatch,
        {
            "issue list": issues_payload,
            "search issues": "[]",
            "search prs": "[]",
            "blockedBy": EMPTY_BLOCKED_BY_PAYLOAD,
        },
    )

    board = Board.from_default(tmp_path)
    result = fetch_audit_window(board, age_days=30)

    assert [item["number"] for item in result["items"]] == [10, 11]


def test_fetch_audit_window_default_staleness_uses_velocity(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Omitting count + age_days uses 2 * median_age_at_close (floor 14, ceiling 60)."""
    from skills.jared.scripts.lib.board import Board, fetch_audit_window
    from tests.conftest import write_minimal_board

    write_minimal_board(tmp_path)
    now = dt.datetime.now(dt.UTC)
    # Velocity: median age-at-close of 20 → threshold = 2*20 = 40 (within 14..60 band)
    closed_payload = json.dumps(
        [
            {"number": 1, "createdAt": (now - dt.timedelta(days=20)).isoformat(),
             "closedAt": now.isoformat()},
        ]
    )
    issues_payload = json.dumps(
        [
            {"number": 10, "title": "older-than-40", "body": "...",
             "createdAt": (now - dt.timedelta(days=50)).isoformat(),
             "labels": [], "milestone": None},
            {"number": 11, "title": "newer-than-40", "body": "...",
             "createdAt": (now - dt.timedelta(days=30)).isoformat(),
             "labels": [], "milestone": None},
        ]
    )
    patch_gh_by_arg(
        monkeypatch,
        {
            "issue list": issues_payload,
            "search issues": closed_payload,
            "search prs": "[]",
            "blockedBy": EMPTY_BLOCKED_BY_PAYLOAD,
        },
    )

    board = Board.from_default(tmp_path)
    result = fetch_audit_window(board)

    assert [item["number"] for item in result["items"]] == [10]


def test_fetch_audit_window_issues_returns_only_listed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """--issues N,M,O returns exactly those issues (oldest-first within the set)."""
    from skills.jared.scripts.lib.board import Board, fetch_audit_window
    from tests.conftest import write_minimal_board

    write_minimal_board(tmp_path)
    issues_payload = json.dumps(
        [
            {"number": 50, "title": "a", "body": "...", "createdAt": "2026-01-01T00:00:00Z",
             "labels": [], "milestone": None},
            {"number": 51, "title": "b", "body": "...", "createdAt": "2025-12-15T00:00:00Z",
             "labels": [], "milestone": None},
            {"number": 52, "title": "c", "body": "...", "createdAt": "2026-03-01T00:00:00Z",
             "labels": [], "milestone": None},
        ]
    )
    patch_gh_by_arg(
        monkeypatch,
        {
            "issue list": issues_payload,
            "search issues": "[]",
            "search prs": "[]",
            "blockedBy": EMPTY_BLOCKED_BY_PAYLOAD,
        },
    )

    board = Board.from_default(tmp_path)
    result = fetch_audit_window(board, issues=[52, 51])

    # Oldest-first: 51 (Dec) then 52 (Mar). The explicit list narrows, but order
    # comes from createdAt.
    assert [item["number"] for item in result["items"]] == [51, 52]


def test_fetch_audit_window_enriches_open_dependents(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Each item gets an open_dependents list (issues that depend on it, still open)."""
    from skills.jared.scripts.lib.board import Board, fetch_audit_window
    from tests.conftest import write_minimal_board

    write_minimal_board(tmp_path)
    issues_payload = json.dumps(
        [
            {"number": 50, "title": "leaf", "body": "...", "createdAt": "2026-01-01T00:00:00Z",
             "labels": [], "milestone": None},
            {"number": 51, "title": "blocks-leaf", "body": "...",
             "createdAt": "2026-01-02T00:00:00Z", "labels": [], "milestone": None},
        ]
    )
    # GraphQL repo-wide blockedBy edges: #51 is blocked by #50, both open
    blocked_by_payload = json.dumps(
        {
            "data": {
                "repository": {
                    "issues": {
                        "pageInfo": {"hasNextPage": False, "endCursor": None},
                        "nodes": [
                            {"number": 50, "blockedBy": {"nodes": []}},
                            {
                                "number": 51,
                                "blockedBy": {"nodes": [{"number": 50, "state": "OPEN"}]},
                            },
                        ],
                    }
                }
            }
        }
    )
    patch_gh_by_arg(
        monkeypatch,
        {
            "issue list": issues_payload,
            "search issues": "[]",
            "search prs": "[]",
            "blockedBy": blocked_by_payload,
        },
    )

    board = Board.from_default(tmp_path)
    result = fetch_audit_window(board, count=2)

    # #50 has #51 as an open dependent; #51 has none.
    by_num = {i["number"]: i for i in result["items"]}
    assert by_num[50]["open_dependents"] == [51]
    assert by_num[51]["open_dependents"] == []


def test_fetch_audit_window_milestones_returns_open_milestones(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """entity_type='milestones' returns open milestones with REST field shape."""
    from skills.jared.scripts.lib.board import Board, fetch_audit_window
    from tests.conftest import write_minimal_board

    write_minimal_board(tmp_path)
    milestones_payload = json.dumps(
        [
            {"number": 1, "title": "v0.21.0", "due_on": "2026-06-01T00:00:00Z",
             "open_issues": 5, "closed_issues": 2, "state": "open"},
            {"number": 2, "title": "v1.0.0", "due_on": None,
             "open_issues": 12, "closed_issues": 0, "state": "open"},
        ]
    )
    patch_gh_by_arg(
        monkeypatch,
        {
            "/milestones": milestones_payload,
            "search issues": "[]",
            "search prs": "[]",
        },
    )

    board = Board.from_default(tmp_path)
    result = fetch_audit_window(board, entity_type="milestones")

    assert [m["title"] for m in result["milestones"]] == ["v0.21.0", "v1.0.0"]
    assert result["milestones"][0]["open_issues"] == 5
    assert result["items"] == []


def test_cli_audit_fetch_count_emits_json(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """`jared audit fetch --count 1` prints a JSON blob with items + velocity to stdout."""
    from tests.conftest import import_cli, write_minimal_board

    write_minimal_board(tmp_path)
    issues_payload = json.dumps(
        [
            {"number": 50, "title": "a", "body": "...", "createdAt": "2026-01-01T00:00:00Z",
             "labels": [], "milestone": None},
        ]
    )
    patch_gh_by_arg(
        monkeypatch,
        {
            "issue list": issues_payload,
            "search issues": "[]",
            "search prs": "[]",
            "blockedBy": EMPTY_BLOCKED_BY_PAYLOAD,
        },
    )

    monkeypatch.chdir(tmp_path)
    cli = import_cli()
    rc = cli.main(["audit", "fetch", "--count", "1"])

    assert rc == 0
    out = capsys.readouterr().out
    payload = json.loads(out)
    assert payload["items"][0]["number"] == 50
    assert "velocity" in payload
