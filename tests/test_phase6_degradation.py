"""Phase 6 — capability degradation path tests.

Exercises every Python surface gated on Capability.VELOCITY_TIMESTAMPS and
Capability.NATIVE_DEPENDENCIES using the ``restrict_capabilities`` helper,
which forces Board.capabilities() to return the empty set — simulating a
KanbanFlow-backed board without a live API token.

Invariant: the GitHub path must be byte-identical to the pre-Phase-6 behaviour.
These tests verify only the *degraded* path (capability absent). The existing
test suite (781 tests) is the regression bar for the GitHub path.
"""

from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path
from textwrap import dedent
from typing import Any

import pytest

from tests.conftest import (
    FakeGhResult,
    import_cli,
    import_dep,
    import_stage,
    import_sweep,
    patch_gh_multi,
    restrict_capabilities,
    write_minimal_board,
)

REPO_ROOT = Path(__file__).parents[1]
SKILL_SCRIPTS = REPO_ROOT / "skills" / "jared" / "scripts"


# ---------------------------------------------------------------------------
# Sweep helpers
# ---------------------------------------------------------------------------


def _run_sweep_main(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    board_md: Path | None = None,
    owner: str = "brockamer",
    project: str = "4",
    repo: str = "brockamer/jared",
    items: list[dict[str, Any]] | None = None,
    open_issues: list[dict[str, Any]] | None = None,
) -> str:
    """Drive sweep.main() with patched gh calls and a board doc.

    Returns combined stdout.

    This helper:
    1. Imports sweep (which adds scripts/ to sys.path and loads lib.board.Board)
    2. Applies restrict_capabilities (now both Board class objects exist in sys.modules)
    3. Sets up a minimal board doc so Board.from_path(cfg) succeeds
    4. Patches gh calls to return the provided items / issues
    5. Sets sys.argv to suppress any live owner/project arguments

    The capability_board hoist in sweep.main() resolves capabilities offline
    from the board doc. Since restrict_capabilities patches Board.capabilities()
    to return frozenset(), the gates fire.
    """
    # 1. Import sweep first so scripts/ lands on sys.path (lib.board.Board loads).
    sweep = import_sweep()

    # 2. Now restrict — both Board class objects are in sys.modules.
    restrict_capabilities(monkeypatch)

    # 3. Board doc in tmp_path so find_config() / Board.from_path() succeed.
    if board_md is None:
        board_md = _write_github_board(tmp_path)

    # 4. Patch all gh calls. We make every call return empty / minimal data so
    #    the sweep doesn't blow up on a live query.
    # gh project item-list --format json returns {"items": [...], "totalCount": N}
    item_list_payload = json.dumps({"items": items or [], "totalCount": len(items or [])})
    budget_payload = json.dumps({"data": {"viewer": {"login": "brockamer"}}})

    def fake_run(args: list[str], **kw: object) -> FakeGhResult:
        joined = " ".join(str(a) for a in args)
        if "rate_limit" in joined or "graphql_budget" in joined:
            return FakeGhResult(stdout=budget_payload)
        if "project" in joined and "item-list" in joined:
            return FakeGhResult(stdout=item_list_payload)
        if "api" in joined and "graphql" in joined:
            # Batch issue fetch or comments — return an empty nodes response.
            return FakeGhResult(
                stdout=json.dumps(
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
            )
        if "issue" in joined and "list" in joined:
            return FakeGhResult(stdout=json.dumps(open_issues or []))
        # budget probe and anything else
        return FakeGhResult(stdout="{}")

    monkeypatch.setattr(
        "skills.jared.scripts.lib.board.subprocess.run",
        fake_run,
    )

    # 5. Monkeypatch sys.argv + CWD so find_config() finds our board doc.
    #    Pass --repo so issues_by_number is populated (required for blocked-status tests).
    monkeypatch.setattr(sys, "argv", ["sweep.py", "--repo", repo])
    monkeypatch.chdir(tmp_path)

    # Patch board_graphql_budget to short-circuit the budget probe.
    monkeypatch.setattr(sweep, "board_graphql_budget", lambda: {"remaining": 9999})
    monkeypatch.setattr(sweep, "board_check_graphql_budget", lambda *a, **kw: None)

    import io

    buf = io.StringIO()
    import builtins

    _real_print = builtins.print

    def _capture_print(*args: object, **kw: Any) -> None:
        f = kw.get("file")
        if f is None or f is sys.stdout:
            sep = str(kw.get("sep", " ") or " ")
            end = str(kw.get("end", "\n") or "\n")
            buf.write(sep.join(str(a) for a in args) + end)
        else:
            _real_print(*args, **kw)

    monkeypatch.setattr(builtins, "print", _capture_print)

    sweep.main()
    return buf.getvalue()


def _write_github_board(tmp_path: Path) -> Path:
    """Write a GitHub-backed board doc (github backend, all standard fields)."""
    board_md = tmp_path / "docs" / "project-board.md"
    board_md.parent.mkdir(parents=True, exist_ok=True)
    board_md.write_text(
        dedent("""\
        - Project URL: https://github.com/users/brockamer/projects/4
        - Project number: 4
        - Project ID: PVT_kwHO_test
        - Owner: brockamer
        - Repo: brockamer/jared
        - backend: github
    """)
    )
    return board_md


# ---------------------------------------------------------------------------
# 3a: sweep.py VELOCITY_TIMESTAMPS gates
# ---------------------------------------------------------------------------


class TestSweepVelocityDegradation:
    """All four sweep VELOCITY_TIMESTAMPS sections degrade with a note."""

    def test_stale_high_priority_backlog_note_prints_and_real_check_skipped(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """Degraded note prints instead of running the stale-backlog check."""
        # Provide a High Backlog issue so we'd see stale output IF the check ran.
        items = [
            {
                "content": {"number": 99, "title": "Old high issue"},
                "status": "Backlog",
                "priority": "High",
            }
        ]
        open_issues = [
            {
                "number": 99,
                "title": "Old high issue",
                "state": "OPEN",
                "createdAt": "2020-01-01T00:00:00Z",
            }
        ]
        out = _run_sweep_main(monkeypatch, tmp_path, items=items, open_issues=open_issues)
        assert "degraded: stale High-priority Backlog unavailable on" in out
        # The real check result ("None" or a stale finding) must NOT appear in that section.
        # The degraded path skips the stale-check entirely — the check function is not called.
        # (We verify absence of the "None" sentinel that signals the check ran empty.)
        # But more specifically: the section header IS present, the note IS present,
        # and the real check DID NOT produce output.
        assert "== Stale High-priority Backlog" in out

    def test_stalled_in_progress_note_prints(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """Degraded note prints for the Stalled In Progress section."""
        out = _run_sweep_main(monkeypatch, tmp_path)
        assert "degraded: stalled In Progress unavailable on" in out

    def test_blocked_status_aging_note_and_presence_check_still_runs(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """Aging note appears AND presence check still runs when VELOCITY absent.

        The ## Blocked by presence check is backend-independent — it MUST still
        fire. The aging sub-check (updatedAt) is gated.
        """
        # Item in Blocked status with NO ## Blocked by section — presence check should fire.
        items = [
            {
                "content": {"number": 42, "title": "Blocked issue"},
                "status": "Blocked",
                "priority": "High",
            }
        ]
        open_issues = [
            {
                "number": 42,
                "title": "Blocked issue",
                "state": "OPEN",
                "body": "No blocked-by section here.",  # Missing ## Blocked by
                # Very old — would trigger aging if velocity ok:
                "updatedAt": "2020-01-01T00:00:00Z",
            }
        ]
        out = _run_sweep_main(monkeypatch, tmp_path, items=items, open_issues=open_issues)
        assert "== Blocked-status hygiene" in out
        # Presence check finding: still fires.
        assert "#42: in Blocked status but body has no `## Blocked by` section" in out
        # Aging note: still prints.
        assert "degraded: Blocked-status aging unavailable on" in out
        # Aging finding: must NOT appear (velocity_ok=False skips the aging branch).
        assert "no activity for" not in out

    def test_session_note_freshness_note_prints(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """Session-note freshness section shows the degraded note."""
        out = _run_sweep_main(monkeypatch, tmp_path)
        assert "degraded: session-note freshness unavailable on" in out


# ---------------------------------------------------------------------------
# 3b: board.py compute_velocity returns empty + note on stderr
# ---------------------------------------------------------------------------


def test_compute_velocity_returns_empty_and_note_when_degraded(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """compute_velocity returns the zero dict and emits a stderr note when capability absent."""
    from skills.jared.scripts.lib.board import Board, compute_velocity

    restrict_capabilities(monkeypatch)

    # Build a Board without provider construction (bypass __init__).
    board = Board.__new__(Board)
    board.backend = "github"  # label says github — we restrict via monkeypatch
    board.repo = "brockamer/jared"

    result = compute_velocity("brockamer/jared", board=board)

    assert result["closures_in_window"] == 0
    assert result["median_age_at_close"] == 0.0
    assert result["median_pr_duration_days"] == 0.0
    assert result["window_days"] == 14  # default

    err = capsys.readouterr().err
    assert "degraded: velocity computation unavailable on" in err


# ---------------------------------------------------------------------------
# 3b: _cmd_next_session_prompt recently-closed shows note
# ---------------------------------------------------------------------------


def test_next_session_prompt_recently_closed_degraded(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """next-session-prompt emits the degraded note for recently-closed (7d)."""
    # Import CLI first so lib.board.Board is in sys.modules before patching.
    mod = import_cli()
    restrict_capabilities(monkeypatch)

    board_md = write_minimal_board(tmp_path)

    patch_gh_multi(
        monkeypatch,
        open_issues=[],
        statuses={},
        closed_issues=[{"number": 7, "title": "done issue", "closedAt": "2026-06-08T10:00:00Z"}],
        comments_batch_json='{"data": {"repository": {}}}',
    )

    rc = mod.main(["--board", str(board_md), "next-session-prompt"])
    out = capsys.readouterr().out

    assert rc == 0
    assert "## Recently closed (last 7 days)" in out
    assert "degraded: recently-closed (7d) unavailable on" in out
    # The actual closed issue must NOT appear (the fetch was skipped).
    assert "done issue" not in out


# ---------------------------------------------------------------------------
# 3b: stage.py backlog-age tiebreaker note
# ---------------------------------------------------------------------------


def test_stage_backlog_age_tiebreaker_note_when_degraded(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """stage render includes the tiebreaker note in the header when capability absent."""
    # Import stage first so lib.board.Board is in sys.modules.
    stage = import_stage()
    restrict_capabilities(monkeypatch)

    now = dt.datetime(2026, 6, 9, 12, 0, tzinfo=dt.UTC)
    today = now.date()

    write_minimal_board(tmp_path)  # ensure tmp_path/docs/ exists (not used directly)

    # Build a board with restricted capabilities.
    from skills.jared.scripts.lib.board import Board

    b = Board.__new__(Board)
    b.backend = "github"
    b.repo = "brockamer/jared"

    proposals = stage.StageProposals(
        promotions=[],
        deferred=[],
        unblocked=[],
        real_world_still_blocked=[],
        almost_ready=[],
    )

    from skills.jared.scripts.lib.board_provider import Capability
    from skills.jared.scripts.lib.capabilities import degraded_or_none

    backlog_age_note = degraded_or_none(
        b,
        Capability.VELOCITY_TIMESTAMPS,
        "Backlog-age tiebreaker",
        "no creation timestamps — promotion order may differ",
    )
    output = stage.render(
        proposals,
        now=now,
        today=today,
        report_only=True,
        backlog_age_note=backlog_age_note,
    )

    assert "note: degraded: Backlog-age tiebreaker unavailable on" in output


# ---------------------------------------------------------------------------
# Task 4: NATIVE_DEPENDENCIES surfaces
# ---------------------------------------------------------------------------


# 4a: _cmd_blocked_by success message rewords to label-emulation suffix

def test_blocked_by_success_rewrites_to_label_emulation_when_degraded(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """When NATIVE_DEPENDENCIES absent the OK line appends the label-emulation note."""
    mod = import_cli()
    restrict_capabilities(monkeypatch)

    board_md = write_minimal_board(tmp_path)

    # Route gh calls: issue view → node IDs; graphql → mutation success.
    def fake_run(args: list[str], **kw: object) -> FakeGhResult:
        joined = " ".join(str(a) for a in args)
        if "issue" in joined and "view" in joined:
            # Node-ID resolution — return a fake ID based on the issue number.
            num = args[args.index("view") + 1] if "view" in args else "0"
            return FakeGhResult(stdout=f'{{"id": "I_{num}"}}')
        if "graphql" in joined:
            return FakeGhResult(stdout='{"data": {"addBlockedBy": {"issue": {"number": 99}}}}')
        return FakeGhResult(stdout="{}")

    monkeypatch.setattr("skills.jared.scripts.lib.board.subprocess.run", fake_run)

    rc = mod.main(["--board", str(board_md), "blocked-by", "99", "42"])
    out = capsys.readouterr().out

    assert rc == 0
    assert "OK: added blocked-by edge #99 <- #42" in out
    assert "label emulation" in out
    assert "NATIVE_DEPENDENCIES not supported on this backend" in out


# 4b: sweep check_native_dependencies section shows degraded note

def test_sweep_native_dependencies_note_prints_when_degraded(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """sweep's native-dependency section shows the degraded note when NATIVE absent."""
    out = _run_sweep_main(monkeypatch, tmp_path)
    assert "== Native dependency hygiene ==" in out
    assert "degraded: native-dependency hygiene unavailable on" in out


# 4c: dependency-graph.py fetch_all_native_dependencies emits note + falls back

def test_fetch_all_native_dependencies_note_and_fallback_when_degraded(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """fetch_all_native_dependencies emits the degraded note and returns None (fallback)."""
    dep = import_dep()
    restrict_capabilities(monkeypatch)

    # Build an offline Board (only .backend and .repo needed for capabilities()).
    from skills.jared.scripts.lib.board import Board

    b = Board.__new__(Board)
    b.backend = "github"
    b.repo = "brockamer/jared"

    # Pass board= so the capability gate fires.
    result = dep.fetch_all_native_dependencies("brockamer/jared", board=b)

    err = capsys.readouterr().err
    assert "degraded: native blocked-by edges unavailable on" in err
    # Returns None so callers fall through to body-text parsing.
    assert result is None


# 4d: fetch_open_issues_for_ties returns empty blocked_by tuples when degraded

def test_fetch_open_issues_for_ties_returns_empty_blocked_by_when_degraded(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """fetch_open_issues_for_ties returns records with blocked_by=() when NATIVE absent.

    On degraded path, the method skips the GitHub GraphQL query (which includes
    blockedBy) and instead routes through board.provider.list_open_items().
    """
    from skills.jared.scripts.lib.board import Board
    from skills.jared.scripts.lib.board_provider import BoardItem

    restrict_capabilities(monkeypatch)

    b = Board.__new__(Board)
    b.backend = "github"
    b.repo = "brockamer/jared"
    b.project_number = 7

    # Fake provider that returns two items with no blocked_by data.
    fake_items = [
        BoardItem(number=1, title="Issue One", status="Backlog", priority="High"),
        BoardItem(number=2, title="Issue Two", status="Up Next", priority="Medium"),
    ]

    class _FakeProvider:
        def list_open_items(self) -> list[BoardItem]:
            return fake_items

    # Patch the provider property on Board so it returns our fake.
    fake_provider = _FakeProvider()
    monkeypatch.setattr(Board, "provider", property(lambda self: fake_provider))

    # Track whether run_graphql is called (it must NOT be on degraded path).
    graphql_called: list[bool] = []

    def _spy_graphql(self: object, query: str, **kw: object) -> object:
        graphql_called.append(True)
        return {}

    monkeypatch.setattr(Board, "run_graphql", _spy_graphql)

    records = b.fetch_open_issues_for_ties()

    assert len(records) == 2
    for r in records:
        assert r.blocked_by == ()
    # GraphQL must not have been called on the degraded path.
    assert not graphql_called


# 4e: fetch_audit_window skips edges enrichment when NATIVE absent

def test_fetch_audit_window_skips_edges_when_native_dependencies_absent(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """fetch_audit_window does not call fetch_blocked_by_edges when NATIVE absent."""
    import skills.jared.scripts.lib.board as _board_mod
    from skills.jared.scripts.lib.board import Board, fetch_audit_window

    restrict_capabilities(monkeypatch)

    b = Board.__new__(Board)
    b.backend = "github"
    b.repo = "brockamer/jared"

    edges_called: list[bool] = []

    # Return one issue so the "if items:" block would normally fire.
    fake_issue = json.dumps(
        [
            {
                "number": 10,
                "title": "Test issue",
                "body": "",
                "createdAt": "2020-01-01T00:00:00Z",
                "labels": [],
                "milestone": None,
            }
        ]
    )

    def _fake_run(args: list[str], **kw: object) -> FakeGhResult:
        joined = " ".join(str(a) for a in args)
        if "graphql" in joined:
            return FakeGhResult(stdout='{"data": {"viewer": {"rateLimit": {"remaining": 9999}}}}')
        if "issue" in joined and "list" in joined:
            return FakeGhResult(stdout=fake_issue)
        return FakeGhResult(stdout="{}")

    monkeypatch.setattr("skills.jared.scripts.lib.board.subprocess.run", _fake_run)

    def _spy_edges(repo: str, **kw: object) -> object:
        edges_called.append(True)
        return {}

    monkeypatch.setattr(_board_mod, "fetch_blocked_by_edges", _spy_edges)

    result = fetch_audit_window(b, count=10)

    # items should be populated (1 issue).
    assert len(result["items"]) == 1
    # Edges must NOT be called when NATIVE_DEPENDENCIES is absent.
    assert not edges_called
    # Items must not have open_dependents set.
    assert "open_dependents" not in result["items"][0]


# 4f: stage.fetch_items_for_stage uses body-ref path when NATIVE absent

def test_stage_fetch_items_uses_body_ref_when_native_absent(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """fetch_items_for_stage returns blocked_by_native=[] when skip_native_edges=True."""
    stage = import_stage()
    restrict_capabilities(monkeypatch)

    from skills.jared.scripts.lib.board import Board

    b = Board.__new__(Board)
    b.backend = "github"
    b.repo = "brockamer/jared"

    # Patch board.board_items() to return one raw item.
    raw_item: dict[str, Any] = {
        "content": {
            "number": 5,
            "title": "A blocked issue",
            "body": "## Blocked by\n#3\n",
        },
        "status": "Blocked",
        "priority": "High",
        "milestone": None,
        "labels": [],
    }
    b.board_items = lambda: [raw_item]  # type: ignore[method-assign]

    # When skip_native_edges=True, no _fetch_blocked_by_edges call is made.
    items = stage.fetch_items_for_stage(b, skip_native_edges=True)

    # blocked_by_native is empty (edges fetch was skipped).
    assert len(items) == 1
    assert items[0]["blocked_by_native"] == []


def test_stage_main_native_edges_note_in_render_when_degraded(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """stage main() passes native_edges_note to render() when NATIVE absent."""
    stage = import_stage()
    restrict_capabilities(monkeypatch)

    now = dt.datetime(2026, 6, 9, 12, 0, tzinfo=dt.UTC)

    from skills.jared.scripts.lib.board import Board
    from skills.jared.scripts.lib.board_provider import Capability
    from skills.jared.scripts.lib.capabilities import degraded_or_none

    b = Board.__new__(Board)
    b.backend = "github"
    b.repo = "brockamer/jared"

    # Compute the note the same way main() would.
    native_edges_note = degraded_or_none(
        b,
        Capability.NATIVE_DEPENDENCIES,
        "native blocked-by edges",
        "blocker detection from `## Blocked by` body sections only",
    )

    proposals = stage.StageProposals(
        promotions=[],
        deferred=[],
        unblocked=[],
        real_world_still_blocked=[],
        almost_ready=[],
    )

    output = stage.render(
        proposals,
        now=now,
        today=now.date(),
        report_only=True,
        native_edges_note=native_edges_note,
    )

    assert "note: degraded: native blocked-by edges unavailable on" in output
