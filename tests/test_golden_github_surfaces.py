"""Byte-identical GitHub-backend pins for the four batch surfaces.

These exist so the KanbanFlow provider migration (#386/#388/#389/#402) cannot
silently change GitHub output. If one of these fails, the migration regressed
GitHub — that is a defect, not a fixture to update. Update a golden only when
a GitHub-visible change is the deliberate, reviewed intent of the change.

Clock-derived substrings are scrubbed rather than pinned — sweep prints
`Run at: <utc-now>` and ages computed against now, none of which reproduce
across days. See `_SCRUBS`. Every other byte is pinned.

Expected output lives in `tests/golden/*.txt`, not in inline string constants,
so a review diff shows the output change line by line.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

import pytest

from tests.conftest import (
    import_dep,
    import_stage,
    import_sweep,
    patch_gh_by_arg,
    run_script_main,
    write_minimal_board,
)

# write_minimal_board() pins owner=brockamer, project=7, repo=brockamer/findajob.
GOLDEN_ITEMS = [
    {
        "status": "Backlog",
        "priority": "High",
        "content": {"number": 1, "title": "alpha", "repository": "brockamer/findajob"},
    },
    {
        "status": "In Progress",
        "priority": "Medium",
        "content": {"number": 2, "title": "beta", "repository": "brockamer/findajob"},
    },
    {
        "status": "Done",
        "priority": "Low",
        "content": {"number": 3, "title": "gamma", "repository": "brockamer/findajob"},
    },
]

GOLDEN_ISSUES = [
    {
        "number": 1,
        "title": "alpha",
        "createdAt": "2026-01-01T00:00:00Z",
        "updatedAt": "2026-01-01T00:00:00Z",
        "labels": [],
        "body": "",
    },
    {
        "number": 2,
        "title": "beta",
        "createdAt": "2026-01-02T00:00:00Z",
        "updatedAt": "2026-01-02T00:00:00Z",
        "labels": [],
        "body": "",
    },
]

# The session-note freshness check batches comments for In Progress items via
# an aliased GraphQL query (`i<N>: issue(number: N) { comments(last: …) }`),
# and indexes ["data"]["repository"] unguarded. Item #2 is the In Progress one.
GOLDEN_GRAPHQL_COMMENTS: dict[str, Any] = {
    "data": {"repository": {"i2": {"comments": {"nodes": []}}}}
}

# Three classes of non-reproducible output, scrubbed rather than pinned:
#   1. `Run at: <utc-now>` — wall clock.
#   2. `#N: <days>d old` and `no activity in <days>d` — ages computed against
#      now, so a fixed createdAt yields a different integer every day. The
#      *presence* of the line is the regression signal; the integer is not.
# Everything else is pinned byte-for-byte.
_SCRUBS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"^Run at: .*$", re.MULTILINE), "Run at: <SCRUBBED>"),
    (re.compile(r"\b\d+d old\b"), "<N>d old"),
    (re.compile(r"no activity in \d+d"), "no activity in <N>d"),
    # stage.py stamps its header: "/jared-stage — proposals YYYY-MM-DD HH:MM".
    (
        re.compile(r"— proposals \d{4}-\d{2}-\d{2} \d{2}:\d{2}"),
        "— proposals <SCRUBBED>",
    ),
)


def _scrub(out: str) -> str:
    """Replace clock-derived substrings with fixed tokens."""
    for pattern, replacement in _SCRUBS:
        out = pattern.sub(replacement, out)
    return out


GOLDEN_DIR = Path(__file__).parent / "golden"


def assert_matches_golden(name: str, actual: str) -> None:
    """Compare `actual` against tests/golden/<name>, or regenerate it.

    Goldens live in files rather than inline string constants so a review diff
    shows the output change itself, line by line, instead of one unreadable
    multi-kilobyte literal.

    Regenerate deliberately, never reflexively:

        JARED_GOLDEN_REGEN=1 pytest tests/test_golden_github_surfaces.py

    A failure here during the #386/#388/#389/#402 migration means GitHub
    output regressed. That is a defect in the change, not a stale fixture.
    Regenerate only when a GitHub-visible change is the reviewed intent.
    """
    path = GOLDEN_DIR / name
    if os.environ.get("JARED_GOLDEN_REGEN") == "1":
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(actual)
        pytest.skip(f"regenerated golden {name} ({len(actual)} chars)")
    if not path.exists():
        pytest.fail(
            f"missing golden {path}. Generate it from a known-good tree with:\n"
            f"  JARED_GOLDEN_REGEN=1 pytest tests/test_golden_github_surfaces.py"
        )
    assert actual == path.read_text()


# sweep's pre-flight gate calls `gh api rate_limit` and returns 0 early (with
# the message on stderr, so stdout is empty) when the GraphQL budget is below
# --min-budget, which defaults to 200. An unserved probe parses as remaining=0.
GOLDEN_RATE_LIMIT: dict[str, Any] = {
    "resources": {"graphql": {"remaining": 4900, "limit": 5000, "reset": 0}}
}

# The native blocked-by probe (`fetch_native_blocked_by`) indexes
# ["data"]["repository"]["issues"] unguarded, so an empty default {} raises
# KeyError. Serve a well-formed, edge-free page.
GOLDEN_GRAPHQL_BLOCKED_BY: dict[str, Any] = {
    "data": {
        "repository": {
            "issues": {
                "pageInfo": {"hasNextPage": False, "endCursor": None},
                "nodes": [
                    {"number": 1, "blockedBy": {"nodes": []}},
                    # A real edge: #2 is blocked by #1. An edge-free fixture
                    # makes the dependency-graph golden the empty string,
                    # which pins nothing and passes for the wrong reason.
                    {
                        "number": 2,
                        "blockedBy": {"nodes": [{"number": 1, "state": "OPEN"}]},
                    },
                ],
            }
        }
    }
}


# compute_velocity reads closed issues and merged PRs; both are indexed for
# createdAt/closedAt/mergedAt without a guard. Empty lists are the honest
# fixture: this board has no velocity history.
GOLDEN_CLOSED_ISSUES: list[dict[str, object]] = []
GOLDEN_MERGED_PRS: list[dict[str, object]] = []


def _patch_github_calls(monkeypatch: pytest.MonkeyPatch) -> list[list[str]]:
    return patch_gh_by_arg(
        monkeypatch,
        {
            "api rate_limit": json.dumps(GOLDEN_RATE_LIMIT),
            "project item-list": json.dumps({"items": GOLDEN_ITEMS}),
            # Order matters: patch_gh_by_arg returns the FIRST substring match,
            # so the closed/merged velocity queries must be routed before the
            # generic "issue list". compute_velocity indexes closedAt/mergedAt
            # unguarded, and GOLDEN_ISSUES carries neither.
            "--state closed": json.dumps(GOLDEN_CLOSED_ISSUES),
            "--state merged": json.dumps(GOLDEN_MERGED_PRS),
            "issue list": json.dumps(GOLDEN_ISSUES),
            "blockedBy": json.dumps(GOLDEN_GRAPHQL_BLOCKED_BY),
            "comments(last:": json.dumps(GOLDEN_GRAPHQL_COMMENTS),
        },
        default="{}",
    )


def test_sweep_github_stdout_is_pinned(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Full stdout of sweep.py on a github board, pinned."""
    write_minimal_board(tmp_path)
    monkeypatch.setenv("JARED_NO_CACHE", "1")
    _patch_github_calls(monkeypatch)

    rc, out = run_script_main(import_sweep(), ["sweep.py"], tmp_path, monkeypatch, capsys)

    assert rc == 0
    # The banner is the line #386 changes; the headers prove no check was dropped.
    assert "Sweep for https://github.com/users/brockamer/projects/7" in out
    assert "  (also tries /orgs/ URL if that's the project's form)" in out
    assert "== Metadata completeness ==" in out
    assert "== Off-board issues (open in repo, missing from project) ==" in out
    # Pin the whole thing so a reordering or a dropped line fails.
    assert_matches_golden("sweep_github.txt", _scrub(out))


def test_stage_github_stdout_is_pinned(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Full stdout of stage.py on a github board, pinned.

    stage.main() DOES take argv, unlike sweep and dependency-graph, so it is
    called directly; only cwd has to be staged for doc autodiscovery.
    """
    write_minimal_board(tmp_path)
    monkeypatch.setenv("JARED_NO_CACHE", "1")
    _patch_github_calls(monkeypatch)
    monkeypatch.chdir(tmp_path)

    rc = import_stage().main([])
    out = capsys.readouterr().out

    assert rc == 0
    assert_matches_golden("stage_github.txt", _scrub(out))


def test_dependency_graph_github_stdout_is_pinned(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Full stdout of dependency-graph.py on a github board, pinned.

    --repo is required today; #389 makes it optional. Pinning the current
    behaviour with it supplied is what proves that change is additive.
    """
    write_minimal_board(tmp_path)
    monkeypatch.setenv("JARED_NO_CACHE", "1")
    _patch_github_calls(monkeypatch)

    rc, out = run_script_main(
        import_dep(),
        ["dependency-graph.py", "--repo", "brockamer/findajob"],
        tmp_path,
        monkeypatch,
        capsys,
        include_stderr=True,  # the whole report goes to stderr
    )

    assert rc == 0
    # Guard against the empty-golden trap: the fixture has a real #2 -> #1
    # edge, so the report must actually mention it.
    assert "#2" in out and "#1" in out
    assert_matches_golden("dependency_graph_github.txt", _scrub(out))


def test_audit_fetch_github_structure_is_pinned(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """fetch_audit_window's GitHub result, pinned by structure.

    The JSON *structure* is pinned (keys present, item numbers, ordering),
    not the raw string — JSON key order is not a contract, and the velocity
    block carries clock-derived values.
    """
    from skills.jared.scripts.lib.board import Board, fetch_audit_window

    board = Board.from_path(write_minimal_board(tmp_path))
    monkeypatch.setenv("JARED_NO_CACHE", "1")
    _patch_github_calls(monkeypatch)

    result = fetch_audit_window(board, count=5, entity_type="issues")

    assert set(result) >= {"items", "milestones", "velocity"}
    assert [i["number"] for i in result["items"]] == [1, 2]
    # Every item carries the fields /jared-audit reads.
    for item in result["items"]:
        assert {"number", "title", "body", "labels"} <= set(item)
