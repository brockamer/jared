"""Tests for sweep.py check functions.

Narrow-scope tests for the drift detectors in the batch sweep script. Kept
separate from the full sweep flow (which shells out to gh and reads live
board state) — these only exercise the pure list-processing logic.
"""

import datetime as dt
import json
from pathlib import Path
from textwrap import dedent
from typing import Any

import pytest

from tests.conftest import import_sweep, patch_gh


def _item(number: int, status: str, title: str = "") -> dict[str, Any]:
    """Cold-path item shape: what `gh project item-list --format json` returns.

    Note the deliberate absence of a `content.state` key — `item-list`
    does not populate the GitHub issue state (#189/#223). Sweep's checks
    that run on this snapshot key on the top-level `status` (the Project
    board column), never on `content.state`. A fixture that invented a
    `state` key here is exactly the lie #223 set out to remove: it let a
    state-keyed filter pass in tests while no-op'ing in production.
    """
    return {
        "content": {"number": number, "title": title or f"Issue {number}"},
        "status": status,
    }


def test_check_metadata_flags_missing_status_key() -> None:
    mod = import_sweep()
    items = [{"content": {"number": 999, "title": "x"}, "priority": "Low"}]
    assert mod.check_metadata(items) == ["#999: no Status"]


def test_check_metadata_flags_null_status() -> None:
    mod = import_sweep()
    items = [{"content": {"number": 999, "title": "x"}, "priority": "Low", "status": None}]
    assert mod.check_metadata(items) == ["#999: no Status"]


def test_check_metadata_flags_empty_status() -> None:
    mod = import_sweep()
    items = [{"content": {"number": 999, "title": "x"}, "priority": "Low", "status": ""}]
    assert mod.check_metadata(items) == ["#999: no Status"]


def test_check_metadata_flags_no_status_sentinel_string() -> None:
    """Regression for #85 — `gh project item-list --format json` can surface
    items without a column assignment as the literal display string
    `"No Status"` (or other non-column values). The check must whitelist
    against the known kanban columns, not just test truthiness.
    """
    mod = import_sweep()
    items = [
        {
            "content": {"number": 999, "title": "x"},
            "priority": "Low",
            "status": "No Status",
        }
    ]
    assert mod.check_metadata(items) == ["#999: no Status"]


def test_check_metadata_flags_arbitrary_unknown_status_string() -> None:
    """Any value that isn't one of {Backlog, Up Next, In Progress, Blocked, Done}
    is treated as not-on-the-kanban — including future typos like a status
    accidentally set to a Priority value."""
    mod = import_sweep()
    items = [
        {
            "content": {"number": 999, "title": "x"},
            "priority": "Low",
            "status": "High",  # bogus
        }
    ]
    assert mod.check_metadata(items) == ["#999: no Status"]


def test_check_metadata_passes_known_kanban_columns() -> None:
    mod = import_sweep()
    items = [
        {"content": {"number": 1, "title": "x"}, "priority": "Low", "status": "Backlog"},
        {"content": {"number": 2, "title": "x"}, "priority": "Low", "status": "Up Next"},
        {
            "content": {"number": 3, "title": "x"},
            "priority": "Low",
            "status": "In Progress",
        },
        {"content": {"number": 4, "title": "x"}, "priority": "Low", "status": "Blocked"},
    ]
    assert mod.check_metadata(items) == []


def test_check_plan_spec_drift_recognizes_bare_hash_issue_refs(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Regression for #48 — the section-body terminator used `^#` which in
    MULTILINE mode matched bare `#229`-style issue references at column zero,
    so the body capture group came back empty and the file got reported
    as `## Issue section but no #N references`. Fixed by tightening the
    terminator to `^#{1,3}\\s` (a real heading shape).
    """
    mod = import_sweep()

    # Plan whose Issue section uses bare `#N` refs — the broken regex
    # would terminate the body match at the `#229` line and report the
    # file as having no refs.
    plan_dir = tmp_path / "plans"
    plan_dir.mkdir()
    bare_form = plan_dir / "metric-layer-c0.md"
    bare_form.write_text(
        dedent("""\
        # Some plan

        ## Issue(s)
        #229 — Metric Layer C.0
        #230 — follow-up

        ## Approach

        Words.
        """)
    )
    # Same plan, but with the user's old workaround (- prefix).
    listed_form = plan_dir / "feature-x.md"
    listed_form.write_text(
        dedent("""\
        # Other plan

        ## Issue
        - #301 — Feature X

        ## Approach

        Words.
        """)
    )

    # Stub gh issue view so we don't hit the network — every referenced
    # issue is reported open. The check only emits "no #N references" or
    # "no ## Issue section" findings if the regex breaks; a working regex
    # produces *no* findings for these well-formed plans.
    class FakeResult:
        returncode = 0
        stdout = '{"state": "OPEN"}'
        stderr = ""

    monkeypatch.setattr(
        "skills.jared.scripts.lib.board.subprocess.run",
        lambda *a, **kw: FakeResult(),
    )

    findings = mod.check_plan_spec_drift([plan_dir], "brockamer/jared")

    # The two false-positives the broken regex used to emit:
    bug_messages = [f for f in findings if "no #N references" in f or "no ## Issue section" in f]
    assert bug_messages == [], (
        f"Plan files with bare #N refs should NOT be reported as missing — got {bug_messages}"
    )


def test_check_plan_spec_drift_accepts_bold_line_issue_form(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Regression for #88 — sweep used a stricter parser than archive-plan,
    so plans using the legacy `**Issue:** #N` bold-line form (no `## Issue`
    heading) were reported as orphaned. The shared parser in lib/board.py
    accepts the bold-line fallback; sweep now inherits that behavior.
    """
    mod = import_sweep()

    plan_dir = tmp_path / "plans"
    plan_dir.mkdir()
    (plan_dir / "legacy-bold-line.md").write_text(
        dedent("""\
        # An older plan

        **Spec:** path/to/spec.md
        **Issue:** brockamer/jared#339

        ## Approach

        Words.
        """)
    )

    class FakeResult:
        returncode = 0
        stdout = '{"state": "OPEN"}'
        stderr = ""

    monkeypatch.setattr(
        "skills.jared.scripts.lib.board.subprocess.run",
        lambda *a, **kw: FakeResult(),
    )

    findings = mod.check_plan_spec_drift([plan_dir], "brockamer/jared")
    bug_messages = [f for f in findings if "no ## Issue section" in f or "no #N references" in f]
    assert bug_messages == [], (
        "Plans using **Issue:** bold-line fallback should NOT be reported as "
        f"orphaned — got {bug_messages}"
    )


def test_check_plan_spec_drift_ignores_inline_prose_refs(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Sweep must not query issue state for stray prose `#NNN` mentions
    inside the `## Issue` section — only list-item / line-start refs count.
    """
    mod = import_sweep()
    plan_dir = tmp_path / "plans"
    plan_dir.mkdir()
    (plan_dir / "with-prose.md").write_text(
        dedent("""\
        # Plan

        ## Issue

        - #408
        - #310

        > agentic-workers note...

        **Goal:** ...closes #310...

        **Issue:** [#408](...); spawns [#410](...), [#411](...).

        ## Approach

        Words.
        """)
    )

    seen_numbers: list[str] = []

    class FakeResult:
        returncode = 0
        stdout = '{"state": "OPEN"}'
        stderr = ""

    def fake_run(*args: Any, **kwargs: Any) -> FakeResult:
        cmd = args[0] if args else kwargs.get("args", [])
        for tok in cmd or []:
            if isinstance(tok, str) and tok.isdigit():
                seen_numbers.append(tok)
        return FakeResult()

    monkeypatch.setattr("skills.jared.scripts.lib.board.subprocess.run", fake_run)

    mod.check_plan_spec_drift([plan_dir], "brockamer/jared")
    assert sorted(set(seen_numbers)) == ["310", "408"], (
        f"sweep should only query refs from list-item lines, not inline prose; "
        f"got {sorted(set(seen_numbers))}"
    )


def test_check_plan_spec_drift_still_flags_genuinely_orphaned_plans(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The fix must not silence the legitimate orphan-plan finding: a plan
    file with no `## Issue` section at all should still be reported."""
    mod = import_sweep()

    plan_dir = tmp_path / "plans"
    plan_dir.mkdir()
    (plan_dir / "no-issue-section.md").write_text(
        dedent("""\
        # Plan with no Issue section

        ## Approach

        We just start writing without filing.
        """)
    )

    findings = mod.check_plan_spec_drift([plan_dir], "brockamer/jared")
    assert any("no ## Issue section" in f for f in findings)


def _open_issue(number: int, title: str = "") -> dict[str, Any]:
    """Shape matches what `gh issue list --json number,title,...` returns."""
    return {"number": number, "title": title or f"Issue {number}", "labels": []}


def test_check_off_board_issues_returns_empty_when_all_on_board() -> None:
    """Healthy case: every open repo issue has a project item."""
    mod = import_sweep()
    items = [
        _item(1, "In Progress"),
        _item(2, "Up Next"),
        _item(3, "Backlog"),
    ]
    issues_by_number = {
        1: _open_issue(1),
        2: _open_issue(2),
        3: _open_issue(3),
    }
    assert mod.check_off_board_issues(items, issues_by_number) == []


def test_check_off_board_issues_flags_repo_issue_missing_from_project() -> None:
    """The whole point of this check (#100): an issue exists on the repo but
    isn't on the board — Status is null, Priority is null, the operator can't
    see it without a sweep. Surface it with a `jared add-to-board` recovery."""
    mod = import_sweep()
    items = [
        _item(1, "In Progress"),
        _item(2, "Up Next"),
    ]
    issues_by_number = {
        1: _open_issue(1),
        2: _open_issue(2),
        # 99 is open on the repo but absent from the project.
        99: _open_issue(99, title="Ghost issue from gh fallback"),
    }
    findings = mod.check_off_board_issues(items, issues_by_number)
    assert len(findings) == 1
    assert "#99" in findings[0]
    assert "Ghost issue from gh fallback" in findings[0]
    # Recovery line must be paste-and-run for the operator.
    assert "jared add-to-board 99" in findings[0]
    assert "--priority" in findings[0]


def test_check_off_board_issues_handles_multiple_ghosts() -> None:
    mod = import_sweep()
    items = [_item(1, "Backlog")]
    issues_by_number = {
        1: _open_issue(1),
        50: _open_issue(50, title="ghost A"),
        51: _open_issue(51, title="ghost B"),
    }
    findings = mod.check_off_board_issues(items, issues_by_number)
    nums = sorted(int(f.split("#")[1].split(":")[0]) for f in findings)
    assert nums == [50, 51]


def test_check_off_board_issues_ignores_closed_repo_issues() -> None:
    """The repo issue list is already filtered to --state open by
    fetch_open_issues_bulk, so closed issues don't appear in
    issues_by_number. But document the contract: this check trusts the
    caller to pass open issues only — it doesn't re-filter.
    """
    mod = import_sweep()
    items = [_item(1, "Backlog")]
    # Caller already filtered; only pass open ones in.
    issues_by_number = {1: _open_issue(1)}
    assert mod.check_off_board_issues(items, issues_by_number) == []


def test_check_off_board_issues_ignores_done_board_items() -> None:
    """A board item sitting in the Done column still 'covers' a repo-open
    issue with the same number — the off-board check is a pure number
    intersection and doesn't care which column the item is in. This check
    only flags repo-open issues that have NO project item at all.
    """
    mod = import_sweep()
    items = [
        _item(1, "Backlog"),
        _item(99, "Done"),  # board has it, parked in Done
    ]
    issues_by_number = {1: _open_issue(1), 99: _open_issue(99)}
    # 99 is on the board — not flagged here.
    findings = mod.check_off_board_issues(items, issues_by_number)
    assert findings == []


def test_check_doc_sync_gate_flags_code_only_pr() -> None:
    """A closed PR that touched the project's code surface (src/**) without
    touching any operator doc emits an advisory line naming the PR + the
    untouched doc list."""
    from tests.conftest import import_sweep

    sweep = import_sweep()

    prs = [
        {
            "number": 100,
            "closedAt": "2026-05-20T10:00:00Z",
            "files": ["src/foo.py", "tests/test_foo.py"],
        },
    ]
    operator_docs = ["CLAUDE.md", "docs/PRD.md"]
    code_surface = ["src/**"]

    findings = sweep.check_doc_sync_gate(prs, operator_docs, code_surface)
    assert len(findings) == 1
    assert "#100" in findings[0]
    assert "CLAUDE.md" in findings[0] or "docs/PRD.md" in findings[0]


def test_check_doc_sync_gate_no_finding_when_both_touched() -> None:
    """A closed PR that touched both code surface and an operator doc is
    correctly synced — no advisory."""
    from tests.conftest import import_sweep

    sweep = import_sweep()

    prs = [
        {
            "number": 101,
            "closedAt": "2026-05-20T10:00:00Z",
            "files": ["src/foo.py", "CLAUDE.md"],
        },
    ]
    operator_docs = ["CLAUDE.md", "docs/PRD.md"]
    code_surface = ["src/**"]

    findings = sweep.check_doc_sync_gate(prs, operator_docs, code_surface)
    assert findings == []


def test_check_doc_sync_gate_no_finding_when_only_doc_touched() -> None:
    """A docs-only PR (no code-surface paths) is not flagged. The gate fires
    only when code was touched without a corresponding doc update."""
    from tests.conftest import import_sweep

    sweep = import_sweep()

    prs = [
        {
            "number": 102,
            "closedAt": "2026-05-20T10:00:00Z",
            "files": ["docs/PRD.md", "README.md"],
        },
    ]
    operator_docs = ["CLAUDE.md", "docs/PRD.md"]
    code_surface = ["src/**"]

    findings = sweep.check_doc_sync_gate(prs, operator_docs, code_surface)
    assert findings == []


def test_check_doc_sync_gate_skips_when_operator_docs_empty() -> None:
    """Empty operator_docs (block absent on this project's convention doc)
    short-circuits the check — never iterates PRs."""
    from tests.conftest import import_sweep

    sweep = import_sweep()

    prs = [
        {"number": 103, "closedAt": "2026-05-20T10:00:00Z", "files": ["src/foo.py"]},
    ]
    findings = sweep.check_doc_sync_gate(prs, operator_docs=[], code_surface=[])
    assert findings == []


def test_check_doc_sync_gate_honors_glob_patterns() -> None:
    """Globs in both lists are matched via fnmatch. `lib/**` matches `lib/foo.py`
    and `lib/sub/bar.py`; `docs/architecture/**` matches files under that dir."""
    from tests.conftest import import_sweep

    sweep = import_sweep()

    prs = [
        {
            "number": 104,
            "closedAt": "2026-05-20T10:00:00Z",
            "files": ["lib/sub/bar.py"],
        },
        {
            "number": 105,
            "closedAt": "2026-05-20T10:00:00Z",
            "files": ["lib/sub/baz.py", "docs/architecture/diagrams/x.md"],
        },
    ]
    operator_docs = ["docs/architecture/**", "CLAUDE.md"]
    code_surface = ["lib/**"]

    findings = sweep.check_doc_sync_gate(prs, operator_docs, code_surface)
    assert len(findings) == 1
    assert "#104" in findings[0]


def test_check_doc_sync_gate_tolerates_missing_files_key() -> None:
    """A PR dict without a `files` key is silently skipped (defensive against
    unexpected gh payloads). The check does not raise KeyError."""
    from tests.conftest import import_sweep

    sweep = import_sweep()

    prs = [
        {"number": 106, "closedAt": "2026-05-20T10:00:00Z"},  # no `files` key
    ]
    operator_docs = ["CLAUDE.md"]
    code_surface = ["src/**"]

    findings = sweep.check_doc_sync_gate(prs, operator_docs, code_surface)
    assert findings == []


def test_check_release_changelog_gate_flags_merged_release_pr_missing_changelog() -> None:
    """A merged PR on a `release/v*` branch whose diff didn't touch CHANGELOG.md
    emits an advisory line naming the PR + the shipped version."""
    from tests.conftest import import_sweep

    sweep = import_sweep()

    prs = [
        {
            "number": 200,
            "closedAt": "2026-05-22T22:26:37Z",
            "mergedAt": "2026-05-22T22:26:37Z",
            "headRefName": "release/v0.22.0",
            "files": [".claude-plugin/plugin.json", "pyproject.toml"],
        },
    ]
    findings = sweep.check_release_changelog_gate(prs)
    assert len(findings) == 1
    assert "#200" in findings[0]
    assert "v0.22.0" in findings[0]
    assert "CHANGELOG.md" in findings[0]


def test_check_release_changelog_gate_no_finding_when_changelog_touched() -> None:
    """A merged release PR that did touch CHANGELOG.md is correctly disciplined —
    no advisory."""
    from tests.conftest import import_sweep

    sweep = import_sweep()

    prs = [
        {
            "number": 201,
            "closedAt": "2026-05-22T22:26:37Z",
            "mergedAt": "2026-05-22T22:26:37Z",
            "headRefName": "release/v0.22.0",
            "files": [".claude-plugin/plugin.json", "pyproject.toml", "CHANGELOG.md"],
        },
    ]
    findings = sweep.check_release_changelog_gate(prs)
    assert findings == []


def test_check_release_changelog_gate_ignores_non_release_branches() -> None:
    """A merged feature-branch PR is not a release — never flagged regardless of
    whether it touched CHANGELOG.md."""
    from tests.conftest import import_sweep

    sweep = import_sweep()

    prs = [
        {
            "number": 202,
            "closedAt": "2026-05-22T10:00:00Z",
            "mergedAt": "2026-05-22T10:00:00Z",
            "headRefName": "feature/220-changelog-advisory",
            "files": ["skills/jared/scripts/sweep.py"],
        },
    ]
    findings = sweep.check_release_changelog_gate(prs)
    assert findings == []


def test_check_release_changelog_gate_ignores_closed_without_merge() -> None:
    """A release-shaped PR that was closed without merging never shipped a tag,
    so a missing CHANGELOG entry there is not a discipline drift — skip."""
    from tests.conftest import import_sweep

    sweep = import_sweep()

    prs = [
        {
            "number": 203,
            "closedAt": "2026-05-22T22:00:00Z",
            "mergedAt": None,  # closed-without-merge
            "headRefName": "release/v0.99.0-abandoned",
            "files": [".claude-plugin/plugin.json"],
        },
    ]
    findings = sweep.check_release_changelog_gate(prs)
    assert findings == []


def test_check_release_changelog_gate_handles_empty_pr_list() -> None:
    """No closed PRs in the window — no findings, no exceptions."""
    from tests.conftest import import_sweep

    sweep = import_sweep()

    assert sweep.check_release_changelog_gate([]) == []


def test_check_release_changelog_gate_tolerates_missing_keys() -> None:
    """Defensive: PR dicts missing `mergedAt`, `headRefName`, or `files` keys are
    silently skipped (advisory path, never fails the sweep)."""
    from tests.conftest import import_sweep

    sweep = import_sweep()

    prs = [
        {"number": 204, "closedAt": "2026-05-22T10:00:00Z"},  # bare minimum
        {
            "number": 205,
            "closedAt": "2026-05-22T10:00:00Z",
            "mergedAt": "2026-05-22T10:00:00Z",
            # no headRefName
        },
        {
            "number": 206,
            "closedAt": "2026-05-22T10:00:00Z",
            "mergedAt": "2026-05-22T10:00:00Z",
            "headRefName": "release/v0.1.0",
            # no `files` key — treated as empty list, advisory fires (changelog absent)
        },
    ]
    findings = sweep.check_release_changelog_gate(prs)
    assert len(findings) == 1
    assert "#206" in findings[0]


def test_check_release_changelog_gate_accepts_custom_branch_pattern() -> None:
    """Branch pattern is overridable for projects that don't use `release/v*`
    (e.g., `releases/*`, `hotfix/v*`). Caller passes the alternative."""
    from tests.conftest import import_sweep

    sweep = import_sweep()

    prs = [
        {
            "number": 207,
            "closedAt": "2026-05-22T10:00:00Z",
            "mergedAt": "2026-05-22T10:00:00Z",
            "headRefName": "releases/v2.0.0",
            "files": ["src/foo.py"],
        },
    ]
    findings = sweep.check_release_changelog_gate(prs, branch_pattern="releases/*")
    assert len(findings) == 1
    assert "#207" in findings[0]


def test_sweep_fetch_items_raises_when_limit_reached(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """sweep.py's parallel `gh project item-list` pull has the same silent
    truncation cliff as Board.board_items() (#185 AC #2). sweep is the more
    dangerous site because it's what genuinely scales with total board
    size — `check_off_board_issues` needs the full snapshot. Add the same
    `len == limit` guard, raising GhInvocationError loudly rather than
    producing a wrong off-board-ghost report from a truncated snapshot.
    """
    monkeypatch.setenv("JARED_NO_CACHE", "1")
    sweep = import_sweep()

    items_payload = [
        {"id": f"item{i}", "content": {"number": i, "title": f"T{i}"}} for i in range(2000)
    ]
    patch_gh(monkeypatch, stdout=json.dumps({"items": items_payload}))

    with pytest.raises(sweep.GhInvocationError, match="truncat"):
        sweep.fetch_items("brockamer", "7")


# ---------- fetch_items_with_closed_cache (#186) ----------


def test_merge_open_with_closed_dedup_open_wins() -> None:
    """When an issue appears in both the open pull and the closed-cache
    (external reopen race), the open-items entry wins. Closed-cache entries
    matching an open number are dropped.
    """
    sweep = import_sweep()

    # Open items come from Board.open_items() (warm/GraphQL path), which DOES
    # populate content.state — and only ever with "OPEN" (the query filters to
    # open issues). Closed-cache items are warmed from the cold-path
    # `gh project item-list` subset, which omits content.state entirely.
    open_items = [
        {"content": {"number": 10, "state": "OPEN"}, "status": "In Progress"},
        {"content": {"number": 11, "state": "OPEN"}, "status": "Backlog"},
    ]
    closed_items = [
        # #10 was reopened externally — stale closed entry should be dropped.
        {"content": {"number": 10}, "status": "Done"},
        {"content": {"number": 99}, "status": "Done"},
    ]

    merged = sweep.merge_open_with_closed(open_items, closed_items)
    numbers: list[int] = [
        n for i in merged if isinstance(n := (i.get("content") or {}).get("number"), int)
    ]
    assert sorted(numbers) == [10, 11, 99]
    # The merged #10 must reflect the OPEN snapshot, not the closed cache.
    item_10 = next(i for i in merged if (i.get("content") or {}).get("number") == 10)
    assert item_10["status"] == "In Progress"
    assert item_10["content"]["state"] == "OPEN"


def test_merge_open_with_closed_handles_missing_numbers() -> None:
    """Items without a content.number key are kept on both sides — defensive
    against unexpected payload shapes from gh."""
    sweep = import_sweep()

    open_items = [{"content": {"number": 10}}, {"content": {}}]
    closed_items = [{"content": {"number": 99}}, {}]

    merged = sweep.merge_open_with_closed(open_items, closed_items)
    assert len(merged) == 4


def test_fetch_items_with_closed_cache_warm_hit_returns_merged(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """When the closed-cache is warm, fetch_items_with_closed_cache must
    call board.open_items() for fresh open items and merge with the cached
    closed subset. No `gh project item-list` call is made — that's the
    whole point of the optimization."""
    import os

    from skills.jared.scripts.lib import cache
    from skills.jared.scripts.lib.board import Board

    sweep = import_sweep()

    cache_dir = Path(os.environ["JARED_CACHE_DIR"])
    cache.set_closed_items(
        project_number=7,
        items=[
            # Closed-cache shape: cold-path-derived, no content.state key.
            {"content": {"number": 50}, "status": "Done"},
            {"content": {"number": 51}, "status": "Done"},
        ],
        cache_dir=cache_dir,
    )

    board_md = tmp_path / "docs" / "project-board.md"
    board_md.parent.mkdir(parents=True)
    board_md.write_text(
        dedent("""\
        - Project URL: https://github.com/users/brockamer/projects/7
        - Project number: 7
        - Project ID: PVT_kwHO_xyz
        - Owner: brockamer
        - Repo: brockamer/findajob
    """)
    )
    board = Board.from_path(board_md)

    # Patch run_graphql to return the open-items query result; assert no
    # `gh project item-list` is called (that's the cost we're avoiding).
    seen_args: list[list[str]] = []

    class FakeResult:
        returncode = 0
        stderr = ""

        def __init__(self, stdout: str) -> None:
            self.stdout = stdout

    def fake_run(args: list[str], **_kw: object) -> object:
        seen_args.append(args)
        if args[1:3] == ["api", "graphql"]:
            return FakeResult(
                json.dumps(
                    {
                        "data": {
                            "repository": {
                                "issues": {
                                    "pageInfo": {"hasNextPage": False},
                                    "nodes": [
                                        {
                                            "number": 60,
                                            "title": "fresh open",
                                            "state": "OPEN",
                                            "projectItems": {
                                                "nodes": [
                                                    {
                                                        "id": "PVTI_open60",
                                                        "project": {"number": 7},
                                                        "fieldValues": {
                                                            "nodes": [
                                                                {
                                                                    "name": "Up Next",
                                                                    "field": {"name": "Status"},
                                                                }
                                                            ]
                                                        },
                                                    }
                                                ]
                                            },
                                        }
                                    ],
                                }
                            }
                        }
                    }
                )
            )
        raise AssertionError(f"Unexpected gh call: {args}")

    monkeypatch.setattr("skills.jared.scripts.lib.board.subprocess.run", fake_run)

    items = sweep.fetch_items_with_closed_cache(board, "brockamer", "7")

    # No `gh project item-list` invocation — that's the regression guard.
    assert all("project" not in a or "item-list" not in a for a in seen_args), (
        f"Warm closed-cache path must not call `gh project item-list`; saw: {seen_args}"
    )
    numbers: list[int] = sorted(
        n for i in items if isinstance(n := (i.get("content") or {}).get("number"), int)
    )
    assert numbers == [50, 51, 60]


def test_fetch_items_with_closed_cache_cold_miss_warms_cache(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """On closed-cache miss, fall back to the full board pull, then warm
    the closed-cache from the closed subset. Next call within TTL must hit
    the warm path."""
    import os

    from skills.jared.scripts.lib import cache
    from skills.jared.scripts.lib.board import Board

    sweep = import_sweep()

    cache_dir = Path(os.environ["JARED_CACHE_DIR"])
    # Ensure no closed-cache pre-seeded.
    assert cache.get_closed_items(project_number=7, cache_dir=cache_dir) is None

    board_md = tmp_path / "docs" / "project-board.md"
    board_md.parent.mkdir(parents=True)
    board_md.write_text(
        dedent("""\
        - Project URL: https://github.com/users/brockamer/projects/7
        - Project number: 7
        - Project ID: PVT_kwHO_xyz
        - Owner: brockamer
        - Repo: brockamer/findajob
    """)
    )
    board = Board.from_path(board_md)

    # Cold-path `gh project item-list` output: no content.state on any item
    # (open or closed) — only the top-level Project `status` column.
    full_items = [
        {"content": {"number": 70}, "status": "In Progress"},
        {"content": {"number": 80}, "status": "Done"},
        {"content": {"number": 81}, "status": "Done"},
    ]
    patch_gh(monkeypatch, stdout=json.dumps({"items": full_items}))

    items = sweep.fetch_items_with_closed_cache(board, "brockamer", "7")
    assert len(items) == 3
    # Cache was warmed from the Done subset only — opens go to next live pull.
    # (#189: filter on top-level `status`, not `content.state` — the latter
    # is not populated by `gh project item-list`.)
    warmed = cache.get_closed_items(project_number=7, cache_dir=cache_dir)
    assert warmed is not None
    warmed_numbers: list[int] = sorted(
        n for i in warmed if isinstance(n := (i.get("content") or {}).get("number"), int)
    )
    assert warmed_numbers == [80, 81]


def test_fetch_items_with_closed_cache_falls_back_when_open_items_paginates(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Board.open_items() raises GhInvocationError when >100 open issues exist
    (pagination not implemented). The warm path must catch this and fall back
    to the full-pull cold path so sweep doesn't break silently when an active
    project crosses the threshold."""
    import os

    from skills.jared.scripts.lib import cache

    sweep = import_sweep()
    # Use the Board class from sweep's import path — the dual-import gotcha
    # (see top of conftest.py) means lib.board.Board and
    # skills.jared.scripts.lib.board.Board are distinct class objects, and
    # the sweep code catches the former. Same applies to GhInvocationError.
    Board = sweep.Board  # noqa: N806
    GhInvocationError = sweep.GhInvocationError  # noqa: N806

    cache_dir = Path(os.environ["JARED_CACHE_DIR"])
    cache.set_closed_items(
        project_number=7,
        # Closed-cache shape: cold-path-derived, no content.state key.
        items=[{"content": {"number": 50}, "status": "Done"}],
        cache_dir=cache_dir,
    )

    board_md = tmp_path / "docs" / "project-board.md"
    board_md.parent.mkdir(parents=True)
    board_md.write_text(
        dedent("""\
        - Project URL: https://github.com/users/brockamer/projects/7
        - Project number: 7
        - Project ID: PVT_kwHO_xyz
        - Owner: brockamer
        - Repo: brockamer/findajob
    """)
    )
    board = Board.from_path(board_md)

    def fake_open_items(self: Any) -> list[dict[str, Any]]:
        raise GhInvocationError("open_items() query returned hasNextPage=true; >100 open issues")

    monkeypatch.setattr(Board, "open_items", fake_open_items)

    # Cold path returns the full board pull, then re-warms the cache.
    # `gh project item-list` shape: no content.state key.
    full_items = [
        {"content": {"number": 10}, "status": "In Progress"},
        {"content": {"number": 50}, "status": "Done"},
    ]
    patch_gh(monkeypatch, stdout=json.dumps({"items": full_items}))

    items = sweep.fetch_items_with_closed_cache(board, "brockamer", "7")
    # Must not propagate the pagination error; must return the cold-path result.
    assert len(items) == 2
    numbers: list[int] = sorted(
        n for i in items if isinstance(n := (i.get("content") or {}).get("number"), int)
    )
    assert numbers == [10, 50]


def test_fetch_items_with_closed_cache_respects_jared_no_cache(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """JARED_NO_CACHE=1 bypasses both the open-items and closed-items caches,
    forcing a full pull every call."""
    import os

    from skills.jared.scripts.lib import cache
    from skills.jared.scripts.lib.board import Board

    sweep = import_sweep()

    cache_dir = Path(os.environ["JARED_CACHE_DIR"])
    # Pre-seed the closed-cache; JARED_NO_CACHE should ignore it.
    # Closed-cache shape: cold-path-derived, no content.state key.
    cache.set_closed_items(
        project_number=7,
        items=[{"content": {"number": 999}, "status": "Done"}],
        cache_dir=cache_dir,
    )

    board_md = tmp_path / "docs" / "project-board.md"
    board_md.parent.mkdir(parents=True)
    board_md.write_text(
        dedent("""\
        - Project URL: https://github.com/users/brockamer/projects/7
        - Project number: 7
        - Project ID: PVT_kwHO_xyz
        - Owner: brockamer
        - Repo: brockamer/findajob
    """)
    )
    board = Board.from_path(board_md)

    monkeypatch.setenv("JARED_NO_CACHE", "1")

    # Cold-path `gh project item-list` shape: no content.state key.
    full_items = [{"content": {"number": 1}, "status": "Backlog"}]
    patch_gh(monkeypatch, stdout=json.dumps({"items": full_items}))

    items = sweep.fetch_items_with_closed_cache(board, "brockamer", "7")
    # Should reflect the fresh full-pull, not the (ignored) stale closed-cache.
    numbers = [(i.get("content") or {}).get("number") for i in items]
    assert numbers == [1]


# ---------- Regression: realistic `gh project item-list` shape (#189) ----------


def test_fetch_items_with_closed_cache_filters_by_status_on_realistic_shape(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Regression for #189. `gh project item-list --format json` does NOT
    populate `content.state` — only top-level `status` is reliable across
    the cold path. The closed_subset filter must use `status == "Done"`,
    not `content.state == "CLOSED"`. Fixture uses the realistic shape:
    content carries body/number/title/url but no `state` key, and `status`
    sits at the top level of each item.
    """
    import os

    from skills.jared.scripts.lib import cache
    from skills.jared.scripts.lib.board import Board

    sweep = import_sweep()

    cache_dir = Path(os.environ["JARED_CACHE_DIR"])
    assert cache.get_closed_items(project_number=7, cache_dir=cache_dir) is None

    board_md = tmp_path / "docs" / "project-board.md"
    board_md.parent.mkdir(parents=True)
    board_md.write_text(
        dedent("""\
        - Project URL: https://github.com/users/brockamer/projects/7
        - Project number: 7
        - Project ID: PVT_kwHO_xyz
        - Owner: brockamer
        - Repo: brockamer/findajob
    """)
    )
    board = Board.from_path(board_md)

    # Realistic shape: no `content.state` key, `status` at top level.
    realistic_items = [
        {"content": {"number": 10, "title": "T10"}, "status": "Backlog"},
        {"content": {"number": 11, "title": "T11"}, "status": "In Progress"},
        {"content": {"number": 20, "title": "T20"}, "status": "Done"},
        {"content": {"number": 21, "title": "T21"}, "status": "Done"},
    ]
    patch_gh(monkeypatch, stdout=json.dumps({"items": realistic_items}))

    items = sweep.fetch_items_with_closed_cache(board, "brockamer", "7")
    assert len(items) == 4

    # The pre-fix filter (`content.state == "CLOSED"`) would warm an empty
    # cache because `content.state` is absent from every realistic item.
    # The fix filters on top-level `status` so only the two Done items are
    # cached.
    warmed = cache.get_closed_items(project_number=7, cache_dir=cache_dir)
    assert warmed is not None
    warmed_numbers: list[int] = sorted(
        n for i in warmed if isinstance(n := (i.get("content") or {}).get("number"), int)
    )
    assert warmed_numbers == [20, 21]

    # Counter math derived from the same fixture: items with status != Done.
    # This is the "Open items on board: N" preamble logic in main().
    total_open = sum(1 for i in realistic_items if i.get("status") != "Done")
    assert total_open == 2  # #10 Backlog + #11 In Progress; #20 / #21 Done are excluded


# ---------------------------------------------------------------------------
# Date-math + body-parsing checks (#305).
#
# Five checks combine `fromisoformat`/`.replace("Z", "+00:00")` parsing with
# `## Blocked by` / `## Session` body matching — tz handling, missing keys, and
# regex drift are the cheap-to-catch failure modes these positive+negative
# pairs lock down. All offline; the one check that fans out for comments has
# its board helper monkeypatched.
# ---------------------------------------------------------------------------


def _iso_days_ago(days: int) -> str:
    """A UTC ISO timestamp ``days`` in the past, with a literal ``Z`` suffix.

    The checks all do ``.replace("Z", "+00:00")`` before ``fromisoformat`` —
    emitting the ``Z`` form (what gh actually returns) exercises that path
    honestly, rather than feeding a pre-normalised ``+00:00`` that would skip it.
    """
    ts = dt.datetime.now(dt.UTC) - dt.timedelta(days=days)
    return ts.isoformat().replace("+00:00", "Z")


def _item_pri(number: int, status: str, priority: str, title: str = "") -> dict[str, Any]:
    """`_item` plus the top-level `priority` key that `field(item, "priority")` reads."""
    item = _item(number, status, title)
    item["priority"] = priority
    return item


# --- check_stale_high_backlog ---------------------------------------------


def test_check_stale_high_backlog_flags_old_high_backlog_item() -> None:
    sweep = import_sweep()
    items = [_item_pri(1, "Backlog", "High")]
    issues = {1: {"createdAt": _iso_days_ago(30), "title": "Ancient High item"}}
    findings = sweep.check_stale_high_backlog(items, issues, days=14)
    assert len(findings) == 1
    assert findings[0].startswith("#1:")
    assert "d old" in findings[0]


def test_check_stale_high_backlog_passes_recent_and_non_high_items() -> None:
    sweep = import_sweep()
    items = [
        _item_pri(1, "Backlog", "High"),  # recent → not stale
        _item_pri(2, "Backlog", "Medium"),  # old but not High → skipped
        _item_pri(3, "In Progress", "High"),  # High + old but not Backlog → skipped
    ]
    issues = {
        1: {"createdAt": _iso_days_ago(2), "title": "Fresh High"},
        2: {"createdAt": _iso_days_ago(90), "title": "Old Medium"},
        3: {"createdAt": _iso_days_ago(90), "title": "Old In-Progress High"},
    }
    assert sweep.check_stale_high_backlog(items, issues, days=14) == []


# --- check_in_progress_staleness ------------------------------------------


def test_check_in_progress_staleness_flags_inactive_item() -> None:
    sweep = import_sweep()
    items = [_item(1, "In Progress")]
    issues = {1: {"updatedAt": _iso_days_ago(10), "title": "Stalled work"}}
    findings = sweep.check_in_progress_staleness(items, issues, days=7)
    assert len(findings) == 1
    assert findings[0].startswith("#1:")
    assert "no activity" in findings[0]


def test_check_in_progress_staleness_passes_recently_touched_item() -> None:
    sweep = import_sweep()
    items = [_item(1, "In Progress")]
    issues = {1: {"updatedAt": _iso_days_ago(1), "title": "Active work"}}
    assert sweep.check_in_progress_staleness(items, issues, days=7) == []


# --- check_blocked_status_hygiene -----------------------------------------


def test_check_blocked_status_hygiene_flags_missing_section() -> None:
    sweep = import_sweep()
    items = [_item(1, "Blocked")]
    # Recently updated so the aging branch stays quiet — isolates the
    # missing-`## Blocked by` finding.
    issues = {1: {"body": "Some body, no blocked-by section.", "updatedAt": _iso_days_ago(0)}}
    findings = sweep.check_blocked_status_hygiene(items, issues, blocked_aging_days=7)
    assert len(findings) == 1
    assert "no `## Blocked by` section" in findings[0]


def test_check_blocked_status_hygiene_flags_aging_blocked_item() -> None:
    sweep = import_sweep()
    items = [_item(1, "Blocked")]
    # Has the section, so only the aging branch should fire.
    issues = {1: {"body": "## Blocked by\n- #9", "updatedAt": _iso_days_ago(30)}}
    findings = sweep.check_blocked_status_hygiene(items, issues, blocked_aging_days=7)
    assert len(findings) == 1
    assert "no activity for" in findings[0]


def test_check_blocked_status_hygiene_passes_healthy_blocked_item() -> None:
    sweep = import_sweep()
    items = [_item(1, "Blocked")]
    issues = {1: {"body": "## Blocked by\n- #9", "updatedAt": _iso_days_ago(0)}}
    assert sweep.check_blocked_status_hygiene(items, issues, blocked_aging_days=7) == []


# --- check_native_dependencies --------------------------------------------


def test_check_native_dependencies_flags_edge_to_closed_blocker() -> None:
    sweep = import_sweep()
    blocked_by = {1: [{"number": 2, "state": "CLOSED"}]}
    issues = {1: {"title": "Dependent"}}
    findings = sweep.check_native_dependencies(blocked_by, issues)
    assert len(findings) == 1
    assert "#1" in findings[0] and "#2" in findings[0]
    assert "closed" in findings[0]


def test_check_native_dependencies_passes_edge_to_open_blocker() -> None:
    sweep = import_sweep()
    blocked_by = {1: [{"number": 2, "state": "OPEN"}]}
    issues = {1: {"title": "Dependent"}}
    assert sweep.check_native_dependencies(blocked_by, issues) == []


# --- check_session_note_freshness -----------------------------------------


def test_check_session_note_freshness_flags_in_progress_without_note(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sweep = import_sweep()
    items = [_item(1, "In Progress")]
    monkeypatch.setattr(sweep, "board_fetch_recent_comments_batch", lambda *a, **k: {1: []})
    findings = sweep.check_session_note_freshness(items, repo="owner/repo", days=3)
    assert len(findings) == 1
    assert "no Session note comment ever" in findings[0]


def test_check_session_note_freshness_flags_stale_note(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sweep = import_sweep()
    items = [_item(1, "In Progress")]
    comments = {1: [{"body": "## Session 2020-01-01\nold note", "createdAt": _iso_days_ago(30)}]}
    monkeypatch.setattr(sweep, "board_fetch_recent_comments_batch", lambda *a, **k: comments)
    findings = sweep.check_session_note_freshness(items, repo="owner/repo", days=3)
    assert len(findings) == 1
    assert "d old" in findings[0]


def test_check_session_note_freshness_passes_recent_note(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sweep = import_sweep()
    items = [_item(1, "In Progress")]
    comments = {1: [{"body": "## Session 2026-06-09\nfresh note", "createdAt": _iso_days_ago(0)}]}
    monkeypatch.setattr(sweep, "board_fetch_recent_comments_batch", lambda *a, **k: comments)
    assert sweep.check_session_note_freshness(items, repo="owner/repo", days=3) == []
