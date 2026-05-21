"""Unit tests for /jared-audit — velocity computation + window fetch + CLI."""
from __future__ import annotations

import json

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
