# /jared-audit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

## Issue

- #169

**Spec:** `docs/superpowers/specs/2026-05-21-jared-audit-design.md`

**Goal:** Ship `/jared-audit` — a skeptical-kanban-manager action that walks the backlog oldest-first, runs a seven-question accuracy/scope/framing checklist per item, and produces operator-approved close / reshape / leave-alone verdicts. v1 covers issues AND milestones. Default staleness threshold and proposed milestone dates calibrate to recent shipping velocity so the action never parks dates 3–6 months out by accident.

**Architecture:** Mirrors the `jared ties` pattern — deterministic Python in `lib/board.py` does the data work (window fetch + open-dependents enrichment + velocity computation), the conversational layer in `commands/jared-audit.md` does the skeptical judgment, and existing `jared close|comment|set` atoms + `gh api` handle mutations. No new `lib/stale_audit.py` module; one helper added to `lib/board.py` plus one thin CLI subcommand. The slash-command markdown owns the seven-question doctrine, the optional `advisor()` pass, calibration pacing, close-reason rubric, and the velocity-derived date anchor formula.

**Tech Stack:** Python 3.11+, pytest, ruff, mypy --strict, gh CLI via `lib/board.py` helpers (`run_gh`, `run_gh_raw`, `run_graphql`). Reuses `fetch_blocked_by_edges` (paginated GraphQL) for open-dependent inversion. Velocity uses `gh search issues --state=closed` + `gh search prs --state=merged` over the last 14 days.

---

## File Structure

**Created:**
- `commands/jared-audit.md` — slash-command doctrine (seven-question checklist, calibration vs batch pacing, optional advisor pass with triggers, close-reason rubric, close-comment minimum, velocity-derived date anchor formula, verdict bucket definitions per entity type)
- `tests/test_cmd_audit.py` — unit tests for velocity computation, audit window fetch, open-dependents enrichment, milestone fetch shape, CLI JSON output

**Modified:**
- `skills/jared/scripts/lib/board.py` — add `compute_velocity(repo, *, days=14, cache=None)` and `fetch_audit_window(board, *, count=None, age_days=None, issues=None, entity_type="issues", cache=None)` (~120 lines)
- `skills/jared/scripts/jared` — add `audit fetch` subcommand: argparse subparser (mutually-exclusive `--count`/`--age-days`/`--issues`, `--type issues|milestones|both`, `--cache`), `_cmd_audit_fetch` handler producing JSON to stdout (~60 lines)
- `skills/jared/SKILL.md` — inventory entry for `/jared-audit`, staleness trigger entries under the existing trigger list (~10 lines)
- `skills/jared/references/operations.md` — one paragraph linking `/jared-audit` to the verdict / mutation atoms it uses (~8 lines)

**Versioning:** Release as v0.21.0 (minor bump — additive feature, no breaking changes). Bump in `.claude-plugin/plugin.json` + `pyproject.toml` as part of the PR.

**Branch:** `feature/169-jared-audit` (already created; spec committed at `a8348b8` and `6298b01`).

---

## Phase 1: Velocity helper

Velocity is the smallest dependency for the whole feature — `fetch_audit_window` needs it for the default staleness threshold, and the slash-command doctrine needs it in fetch output. Ship it first standalone so the rest builds on a known-good base.

### Task 1.1: `compute_velocity` — failing test for closure count

**Files:**
- Modify: `tests/test_cmd_audit.py` (create if missing)

- [ ] **Step 1: Create test file with the first test**

```python
# tests/test_cmd_audit.py
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
        {"state=closed": closed_issues, "state=merged": "[]"},
    )

    velocity = compute_velocity("brockamer/jared")

    assert velocity["closures_last_14d"] == 3
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_cmd_audit.py::test_compute_velocity_closure_count -v`
Expected: `ImportError: cannot import name 'compute_velocity' from 'skills.jared.scripts.lib.board'`

- [ ] **Step 3: Implement minimal `compute_velocity`**

Add at the bottom of `skills/jared/scripts/lib/board.py`:

```python
def compute_velocity(
    repo: str,
    *,
    days: int = 14,
    cache: str | None = None,
) -> dict[str, Any]:
    """Recent shipping cadence — count + median age-at-close + median PR duration.

    `days` is the lookback window (default 14). Returns:
      - closures_last_14d (int): count of issues closed in window
      - median_age_at_close (float, days): created→closed for those issues
      - median_pr_duration_days (float): created→merged for PRs in the same
        window. Proxy for "time to ship" — used as the anchor for proposed
        milestone due dates in /jared-audit. PR duration is a tighter signal
        than issue creation→close (which folds in backlog dwell time).
    """
    from datetime import datetime, timedelta, timezone
    from statistics import median

    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")
    issues_args = [
        "search", "issues",
        "--repo", repo,
        "--state", "closed",
        "--search", f"closed:>={cutoff}",
        "--json", "number,createdAt,closedAt",
        "--limit", "100",
    ]
    closed = run_gh(issues_args, cache=cache) or []

    prs_args = [
        "search", "prs",
        "--repo", repo,
        "--state", "merged",
        "--search", f"merged:>={cutoff}",
        "--json", "number,createdAt,mergedAt",
        "--limit", "100",
    ]
    merged = run_gh(prs_args, cache=cache) or []

    def _days_between(start: str, end: str) -> float:
        s = datetime.fromisoformat(start.replace("Z", "+00:00"))
        e = datetime.fromisoformat(end.replace("Z", "+00:00"))
        return (e - s).total_seconds() / 86400.0

    ages = [_days_between(i["createdAt"], i["closedAt"]) for i in closed]
    durations = [_days_between(p["createdAt"], p["mergedAt"]) for p in merged]

    return {
        "closures_last_14d": len(closed),
        "median_age_at_close": float(median(ages)) if ages else 0.0,
        "median_pr_duration_days": float(median(durations)) if durations else 0.0,
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_cmd_audit.py::test_compute_velocity_closure_count -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_cmd_audit.py skills/jared/scripts/lib/board.py
git commit -m "feat(audit): add compute_velocity helper (#169)

Lookback over last 14 days returns count + median age-at-close
(issues) + median PR duration (proxy for time-to-ship). Used by
fetch_audit_window for default staleness threshold and by the
slash-command for the date anchor formula.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

### Task 1.2: Velocity — median age-at-close + PR duration tests

**Files:**
- Modify: `tests/test_cmd_audit.py`

- [ ] **Step 1: Add two more tests for the median fields**

Append to `tests/test_cmd_audit.py`:

```python
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
        {"state=closed": closed_issues, "state=merged": "[]"},
    )

    velocity = compute_velocity("brockamer/jared")

    assert velocity["median_age_at_close"] == 10.0


def test_compute_velocity_empty_windows_return_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    """Empty closure / merge windows produce zeros, not crashes."""
    patch_gh_by_arg(monkeypatch, {"state=closed": "[]", "state=merged": "[]"})

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
            {"number": 100, "createdAt": "2026-05-18T00:00:00Z", "mergedAt": "2026-05-20T00:00:00Z"},
            {"number": 101, "createdAt": "2026-05-19T00:00:00Z", "mergedAt": "2026-05-20T00:00:00Z"},
            {"number": 102, "createdAt": "2026-05-15T00:00:00Z", "mergedAt": "2026-05-19T00:00:00Z"},
        ]
    )
    patch_gh_by_arg(
        monkeypatch,
        {"state=closed": closed_issues, "state=merged": merged_prs},
    )

    velocity = compute_velocity("brockamer/jared")

    assert velocity["median_pr_duration_days"] == 2.0
```

- [ ] **Step 2: Run all velocity tests**

Run: `pytest tests/test_cmd_audit.py -v -k compute_velocity`
Expected: all four PASS

- [ ] **Step 3: Type-check + lint**

Run: `ruff check skills/jared/scripts/lib/board.py tests/test_cmd_audit.py && mypy`
Expected: both clean

- [ ] **Step 4: Commit**

```bash
git add tests/test_cmd_audit.py
git commit -m "test(audit): cover compute_velocity medians + empty-window edge (#169)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Phase 2: `fetch_audit_window` — window selection + open-dependents

### Task 2.1: `fetch_audit_window` — `--count` mode (oldest-first)

**Files:**
- Modify: `tests/test_cmd_audit.py`, `skills/jared/scripts/lib/board.py`

- [ ] **Step 1: Write failing test for count mode**

Append to `tests/test_cmd_audit.py`:

```python
def test_fetch_audit_window_count_returns_oldest_first(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """--count N returns the N oldest open issues, oldest first."""
    from tests.conftest import write_minimal_board
    from skills.jared.scripts.lib.board import Board, fetch_audit_window

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
            "state=closed": "[]",
            "state=merged": "[]",
        },
    )

    board = Board.from_root(tmp_path)
    result = fetch_audit_window(board, count=2)

    assert [item["number"] for item in result["items"]] == [51, 50]
    assert "velocity" in result
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_cmd_audit.py::test_fetch_audit_window_count_returns_oldest_first -v`
Expected: `ImportError: cannot import name 'fetch_audit_window'`

- [ ] **Step 3: Implement `fetch_audit_window` count mode**

Append to `skills/jared/scripts/lib/board.py`:

```python
def fetch_audit_window(
    board: "Board",
    *,
    count: int | None = None,
    age_days: int | None = None,
    issues: list[int] | None = None,
    entity_type: str = "issues",
    cache: str | None = None,
) -> dict[str, Any]:
    """Fetch the audit working set + velocity block.

    Exactly one of {count, age_days, issues} must be set when entity_type
    includes issues. entity_type is "issues", "milestones", or "both".
    Items are returned oldest-first. The top-level "velocity" key carries
    the output of compute_velocity (used by the slash-command doctrine for
    the date anchor formula and by callers omitting --age-days for the
    default staleness threshold).
    """
    velocity = compute_velocity(board.repo, cache=cache)
    items: list[dict[str, Any]] = []
    milestones: list[dict[str, Any]] = []

    if entity_type in ("issues", "both"):
        raw = run_gh(
            [
                "issue", "list",
                "--repo", board.repo,
                "--state", "open",
                "--limit", "500",
                "--json", "number,title,body,createdAt,labels,milestone",
            ],
            cache=cache,
        ) or []
        raw_sorted = sorted(raw, key=lambda i: i["createdAt"])
        if issues is not None:
            wanted = set(issues)
            items = [i for i in raw_sorted if i["number"] in wanted]
        elif count is not None:
            items = raw_sorted[:count]
        else:
            # age_days handled in Task 2.2; for now treat None as count=10
            items = raw_sorted[:count if count else 10]

    return {
        "items": items,
        "milestones": milestones,
        "velocity": velocity,
    }
```

Add `fetch_audit_window` to the module's exports — for now no `__all__` is defined; the top-level import in tests works directly.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_cmd_audit.py::test_fetch_audit_window_count_returns_oldest_first -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_cmd_audit.py skills/jared/scripts/lib/board.py
git commit -m "feat(audit): fetch_audit_window — oldest-first --count mode (#169)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

### Task 2.2: `fetch_audit_window` — `--age-days` + default staleness threshold

**Files:**
- Modify: `tests/test_cmd_audit.py`, `skills/jared/scripts/lib/board.py`

- [ ] **Step 1: Write two failing tests**

Append to `tests/test_cmd_audit.py`:

```python
def test_fetch_audit_window_age_days_filters_by_age(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """--age-days N keeps items older than N days from today."""
    from datetime import datetime, timedelta, timezone
    from tests.conftest import write_minimal_board
    from skills.jared.scripts.lib.board import Board, fetch_audit_window

    write_minimal_board(tmp_path)
    now = datetime.now(timezone.utc)
    issues_payload = json.dumps(
        [
            {"number": 10, "title": "ancient", "body": "...",
             "createdAt": (now - timedelta(days=120)).isoformat(),
             "labels": [], "milestone": None},
            {"number": 11, "title": "stale", "body": "...",
             "createdAt": (now - timedelta(days=45)).isoformat(),
             "labels": [], "milestone": None},
            {"number": 12, "title": "fresh", "body": "...",
             "createdAt": (now - timedelta(days=5)).isoformat(),
             "labels": [], "milestone": None},
        ]
    )
    patch_gh_by_arg(
        monkeypatch,
        {"issue list": issues_payload, "state=closed": "[]", "state=merged": "[]"},
    )

    board = Board.from_root(tmp_path)
    result = fetch_audit_window(board, age_days=30)

    assert [item["number"] for item in result["items"]] == [10, 11]


def test_fetch_audit_window_default_staleness_uses_velocity(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """Omitting count + age_days uses 2 * median_age_at_close (floor 14, ceiling 60)."""
    from datetime import datetime, timedelta, timezone
    from tests.conftest import write_minimal_board
    from skills.jared.scripts.lib.board import Board, fetch_audit_window

    write_minimal_board(tmp_path)
    now = datetime.now(timezone.utc)
    # Velocity: median age-at-close of 20 → threshold = 2*20 = 40 (within 14..60 band)
    closed_payload = json.dumps(
        [
            {"number": 1, "createdAt": (now - timedelta(days=20)).isoformat(),
             "closedAt": now.isoformat()},
        ]
    )
    issues_payload = json.dumps(
        [
            {"number": 10, "title": "older-than-40", "body": "...",
             "createdAt": (now - timedelta(days=50)).isoformat(),
             "labels": [], "milestone": None},
            {"number": 11, "title": "newer-than-40", "body": "...",
             "createdAt": (now - timedelta(days=30)).isoformat(),
             "labels": [], "milestone": None},
        ]
    )
    patch_gh_by_arg(
        monkeypatch,
        {"issue list": issues_payload, "state=closed": closed_payload, "state=merged": "[]"},
    )

    board = Board.from_root(tmp_path)
    result = fetch_audit_window(board)

    assert [item["number"] for item in result["items"]] == [10]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_cmd_audit.py -v -k "age_days or default_staleness"`
Expected: both FAIL (age_days returns top-10 not filtered; default-staleness returns top-10 too)

- [ ] **Step 3: Replace the fallback branch in `fetch_audit_window`**

In `skills/jared/scripts/lib/board.py`, replace the `elif count is not None: / else:` branch inside `fetch_audit_window` with:

```python
        elif count is not None:
            items = raw_sorted[:count]
        else:
            # age_days mode (explicit) OR default-staleness mode (omitted).
            from datetime import datetime, timezone

            if age_days is None:
                # Default: 2 * median_age_at_close, clamped to [14, 60].
                threshold = max(14.0, min(60.0, 2.0 * velocity["median_age_at_close"]))
            else:
                threshold = float(age_days)
            now = datetime.now(timezone.utc)
            kept = []
            for i in raw_sorted:
                created = datetime.fromisoformat(i["createdAt"].replace("Z", "+00:00"))
                age = (now - created).total_seconds() / 86400.0
                if age >= threshold:
                    kept.append(i)
            items = kept
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_cmd_audit.py -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_cmd_audit.py skills/jared/scripts/lib/board.py
git commit -m "feat(audit): --age-days + velocity-derived default staleness (#169)

Default threshold clamps to [14, 60] days around 2 * median_age_at_close
so a fast-shipping project gets a tight default and a slow one doesn't
inherit a punishing 14-day floor.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

### Task 2.3: `fetch_audit_window` — `--issues` explicit-list mode

**Files:**
- Modify: `tests/test_cmd_audit.py` (implementation already supports `issues=`)

- [ ] **Step 1: Add coverage for the explicit-issues branch**

Append to `tests/test_cmd_audit.py`:

```python
def test_fetch_audit_window_issues_returns_only_listed(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """--issues N,M,O returns exactly those issues (oldest-first within the set)."""
    from tests.conftest import write_minimal_board
    from skills.jared.scripts.lib.board import Board, fetch_audit_window

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
        {"issue list": issues_payload, "state=closed": "[]", "state=merged": "[]"},
    )

    board = Board.from_root(tmp_path)
    result = fetch_audit_window(board, issues=[52, 51])

    # Oldest-first: 51 (Dec) then 52 (Mar). The explicit list narrows, but order
    # comes from createdAt.
    assert [item["number"] for item in result["items"]] == [51, 52]
```

- [ ] **Step 2: Run test to verify it passes**

Run: `pytest tests/test_cmd_audit.py::test_fetch_audit_window_issues_returns_only_listed -v`
Expected: PASS (the implementation from Task 2.1 already handles `issues=`)

- [ ] **Step 3: Commit**

```bash
git add tests/test_cmd_audit.py
git commit -m "test(audit): cover --issues explicit-list mode (#169)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

### Task 2.4: Open-dependents enrichment

**Files:**
- Modify: `tests/test_cmd_audit.py`, `skills/jared/scripts/lib/board.py`

- [ ] **Step 1: Write failing test**

Append to `tests/test_cmd_audit.py`:

```python
def test_fetch_audit_window_enriches_open_dependents(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """Each item gets an open_dependents list (issues that depend on it, still open)."""
    from tests.conftest import write_minimal_board
    from skills.jared.scripts.lib.board import Board, fetch_audit_window

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
                            {"number": 51, "blockedBy": {"nodes": [{"number": 50, "state": "OPEN"}]}},
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
            "state=closed": "[]",
            "state=merged": "[]",
            "blockedBy": blocked_by_payload,
        },
    )

    board = Board.from_root(tmp_path)
    result = fetch_audit_window(board, count=2)

    # #50 has #51 as an open dependent; #51 has none.
    by_num = {i["number"]: i for i in result["items"]}
    assert by_num[50]["open_dependents"] == [51]
    assert by_num[51]["open_dependents"] == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_cmd_audit.py::test_fetch_audit_window_enriches_open_dependents -v`
Expected: FAIL — items have no `open_dependents` field

- [ ] **Step 3: Add enrichment to `fetch_audit_window`**

In `skills/jared/scripts/lib/board.py`, inside `fetch_audit_window` after `items = ...` and before the `return`, add:

```python
    if items:
        # Invert repo-wide blockedBy edges: who depends on each candidate?
        edges = fetch_blocked_by_edges(board.repo, cache=cache)
        dependents: dict[int, list[int]] = {}
        for dependent_num, blocked_by in edges.items():
            for blocker in blocked_by:
                if blocker.get("state") == "OPEN":
                    dependents.setdefault(blocker["number"], []).append(dependent_num)
        for item in items:
            item["open_dependents"] = sorted(dependents.get(item["number"], []))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_cmd_audit.py -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_cmd_audit.py skills/jared/scripts/lib/board.py
git commit -m "feat(audit): enrich audit window with open-dependents (#169)

Inverts fetch_blocked_by_edges so each candidate item carries the list
of open issues that depend on it. Slash-command doctrine surfaces this
before any close verdict.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

### Task 2.5: Milestone fetch + `--type` switch

**Files:**
- Modify: `tests/test_cmd_audit.py`, `skills/jared/scripts/lib/board.py`

- [ ] **Step 1: Write failing test**

Append to `tests/test_cmd_audit.py`:

```python
def test_fetch_audit_window_milestones_returns_open_milestones(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """entity_type='milestones' returns open milestones with REST field shape."""
    from tests.conftest import write_minimal_board
    from skills.jared.scripts.lib.board import Board, fetch_audit_window

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
            "state=closed": "[]",
            "state=merged": "[]",
        },
    )

    board = Board.from_root(tmp_path)
    result = fetch_audit_window(board, entity_type="milestones")

    assert [m["title"] for m in result["milestones"]] == ["v0.21.0", "v1.0.0"]
    assert result["milestones"][0]["open_issues"] == 5
    assert result["items"] == []
```

Field shape note: the REST `/milestones` endpoint returns `due_on`, `open_issues`, `closed_issues` (snake_case). The test mock matches that shape since the implementation goes through `gh api ... /milestones`.

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_cmd_audit.py::test_fetch_audit_window_milestones_returns_open_milestones -v`
Expected: FAIL — milestones empty list

- [ ] **Step 3: Add milestone fetch branch**

In `skills/jared/scripts/lib/board.py`, inside `fetch_audit_window` add (before the open-dependents enrichment block, after the issues branch):

```python
    if entity_type in ("milestones", "both"):
        owner, name = board.repo.split("/", 1)
        milestones = run_gh(
            [
                "api",
                f"/repos/{owner}/{name}/milestones",
                "--paginate",
                "-X", "GET",
                "-f", "state=open",
                "-f", "sort=due_on",
                "-f", "direction=asc",
            ],
            cache=cache,
        ) or []
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_cmd_audit.py::test_fetch_audit_window_milestones_returns_open_milestones -v`
Expected: PASS

- [ ] **Step 5: Lint + typecheck**

Run: `ruff check skills/jared/scripts/lib/board.py tests/test_cmd_audit.py && mypy`
Expected: both clean

- [ ] **Step 6: Commit**

```bash
git add tests/test_cmd_audit.py skills/jared/scripts/lib/board.py
git commit -m "feat(audit): fetch open milestones via --type switch (#169)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Phase 3: CLI wiring

### Task 3.1: Add `audit fetch` subcommand

**Files:**
- Modify: `skills/jared/scripts/jared`, `tests/test_cmd_audit.py`

- [ ] **Step 1: Write failing CLI integration test**

Append to `tests/test_cmd_audit.py`:

```python
def test_cli_audit_fetch_count_emits_json(
    monkeypatch: pytest.MonkeyPatch, tmp_path, capsys
) -> None:
    """`jared audit fetch --count 1` prints a JSON blob with items + velocity to stdout."""
    from tests.conftest import write_minimal_board, import_cli

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
            "state=closed": "[]",
            "state=merged": "[]",
            "blockedBy": json.dumps({"data": {"repository": {"issues": {
                "pageInfo": {"hasNextPage": False, "endCursor": None}, "nodes": [],
            }}}}),
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_cmd_audit.py::test_cli_audit_fetch_count_emits_json -v`
Expected: FAIL (`argparse` error: invalid subcommand `audit`)

- [ ] **Step 3: Add the argparse wiring**

In `skills/jared/scripts/jared`, locate the section near `_cmd_ties` registration (after `ties_p.set_defaults(...)` around line 247) and add:

```python
    audit_p = sub.add_parser(
        "audit",
        help="Subcommands for /jared-audit (fetch the audit working set).",
    )
    audit_sub = audit_p.add_subparsers(dest="audit_command", required=True)
    audit_fetch = audit_sub.add_parser(
        "fetch",
        help="Emit the audit working set (issues + milestones + velocity) as JSON.",
    )
    group = audit_fetch.add_mutually_exclusive_group()
    group.add_argument("--count", type=int, help="Take the oldest N items.")
    group.add_argument("--age-days", type=int, help="Items older than N days.")
    group.add_argument(
        "--issues",
        type=lambda s: [int(n.strip()) for n in s.split(",")],
        help="Comma-separated explicit issue numbers.",
    )
    audit_fetch.add_argument(
        "--type",
        choices=["issues", "milestones", "both"],
        default="issues",
        dest="entity_type",
    )
    audit_fetch.add_argument("--cache", help="gh cache duration, e.g. '60s'.")
    audit_fetch.set_defaults(func=_cmd_audit_fetch)
```

Then add the handler near the other `_cmd_*` functions:

```python
def _cmd_audit_fetch(args: argparse.Namespace) -> int:
    from lib.board import fetch_audit_window  # type: ignore[import-not-found]

    board = _load_board(args.board)
    result = fetch_audit_window(
        board,
        count=args.count,
        age_days=args.age_days,
        issues=args.issues,
        entity_type=args.entity_type,
        cache=args.cache,
    )
    print(json.dumps(result, indent=2, default=str))
    return 0
```

If `json` isn't already imported at the top of the file, add `import json` to the imports section.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_cmd_audit.py::test_cli_audit_fetch_count_emits_json -v`
Expected: PASS

- [ ] **Step 5: Full test suite + lint + typecheck**

Run: `pytest && ruff check . && mypy`
Expected: all PASS / clean

- [ ] **Step 6: Commit**

```bash
git add skills/jared/scripts/jared tests/test_cmd_audit.py
git commit -m "feat(audit): wire 'jared audit fetch' CLI subcommand (#169)

JSON output to stdout (items + milestones + velocity). Window flags are
mutually exclusive; --type defaults to issues.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Phase 4: Slash-command doctrine

### Task 4.1: Write `commands/jared-audit.md`

**Files:**
- Create: `commands/jared-audit.md`

- [ ] **Step 1: Create the slash-command file**

Create `commands/jared-audit.md` with this exact content:

````markdown
---
description: Skeptical kanban-manager audit — walk the backlog oldest-first, verdict per item (close / reshape / leave-alone), operator-approved mutations. Velocity-aware date heuristics.
---

Invoke the Jared skill to run a skeptical accuracy audit on the board. The action's posture is "expert kanban manager being ruthlessly skeptical" — every item gets pressure-tested before it's left alone, reshaped, or closed.

Operator-triggered. Every mutation is approved before it lands.

Flow:

1. **Pick the working set.** Run:

   ```bash
   ${CLAUDE_PLUGIN_ROOT}/skills/jared/scripts/jared audit fetch \
       [--count N | --age-days N | --issues N,M,…] \
       [--type issues|milestones|both]
   ```

   Window flags are mutually exclusive. Omit them all and the action selects items older than `2 × velocity.median_age_at_close` (clamped to [14, 60] days) — the default calibrates to recent shipping cadence, not a static threshold. `--type` defaults to `issues`; use `milestones` or `both` to include milestones.

   Output is JSON: `items[]` (oldest-first; each carries `number`, `title`, `body`, `createdAt`, `labels`, `milestone`, `open_dependents`), `milestones[]` (when `--type` includes them: `number`, `title`, `due_on`, `open_issues`, `closed_issues`), and a top-level `velocity` block (`closures_last_14d`, `median_age_at_close`, `median_pr_duration_days`).

2. **Run the seven-question skeptical checklist per item.** For each issue (or milestone):

   1. **Necessity** — still needed, or has the need evaporated?
   2. **Scope realism** — has the scope grown into yak-shaving? *(Milestone: still a coherent ship?)*
   3. **YAGNI** — speculative future-proofing? *(Milestone: "Q4 maybe" placeholder?)*
   4. **Antipattern** — premature abstraction, work-avoidance, cargo-cult? *(Milestone: roadmap-theater?)*
   5. **Framing accuracy** — do file paths / function names / numbers in the body still match the codebase today? *(Milestone: description still reflects intent?)*
   6. **Dependency edges** — blockers actually still blocking? Use `open_dependents` from the fetch output. *(Milestone: child issues still aligned with the ship?)*
   7. **Calibration** — priority still right for today's shape? *(Milestone: due date still real, and calibrated to the recent shipping trend rather than parked 3–6 months out?)*

3. **Pacing.** Go deeper on the first item to calibrate depth (full code reconnaissance, careful close-comment drafting). Batch the rest in groups of 3–5 with lighter reconnaissance per item. The asymmetry is deliberate — depth on item one sets the operator's expectations for the rest.

4. **Verdict.** Each item produces one of:

   **Issues:** `close-as-completed` | `close-as-not-planned` | `reshape` | `leave-alone`
   **Milestones:** `close` | `dissolve` | `reshape` | `leave-alone`

   `leave-alone` should dominate on a healthy backlog. Closing for its own sake is not a goal.

   **Close-reason rubric:**
   - `close-as-completed` (issues) / `close` (milestones) — the work was done, decided, or shipped under another ticket. Use when the value the issue tracked has been delivered, even if delivery came from a different abstraction or commit.
   - `close-as-not-planned` (issues) / `dissolve` (milestones) — the value is no longer worth pursuing, OR (for milestones) the work no longer coheres into one ship. Different signal from `completed`; pick deliberately.
   - `reshape` — the work is still real but the body/title/dates/priority need to match today.
   - `leave-alone` — pulled in, no mutation needed.

5. **Optional advisor pass.** Before showing a non-trivial batch to the operator (2+ closes, any milestone reshape), invoke `advisor()`. The advisor sees the full transcript (issue bodies, velocity block, drafted verdicts) and pressure-tests:

   - Wrong-reason closes
   - Missed supersede references
   - Reshape proposals that drop load-bearing nuance
   - Dates miscalibrated against the velocity anchor (too aggressive *or* too lax)
   - Close-comment drafts that fail the trigger-condition / supersede / rationale minimum

   Skip the advisor pass for pure `leave-alone` + light-reframing batches.

6. **Present batch to operator.** For each item: verdict, one-line rationale, proposed mutations (diff for body changes; full new title for renames; specific date for milestone reshapes; full prose for close comments). Operator approves, edits, or rejects per item.

7. **Mutations — date proposals are aggressive.** When proposing a new milestone due date during reshape, anchor to:

   ```
   default_due_date = today + (velocity.median_pr_duration_days × remaining_open_children)
   ```

   Bias toward the near term. Default cadence is weeks, not quarters. If the proposed date pushes past this anchor, include a one-line written rationale (e.g., "external dependency lands week of X") in the operator approval prompt — parking a milestone 3–6 months out without an explicit reason is a smell.

8. **Close comments are non-empty by default.** Before drafting any close comment, prompt the operator for:

   - **Trigger condition** — what would cause re-filing? (esp. for `Not planned`)
   - **Supersede reference** — which open issue (if any) absorbs this work?
   - **Rationale** — why now, why this verdict?

   Then draft prose incorporating those elements. Free-form because the right shape varies; the required elements exist because non-empty closes were the original concern.

9. **Apply approved mutations** using existing atoms:

   ```bash
   ${CLAUDE_PLUGIN_ROOT}/skills/jared/scripts/jared close <N> --comment-file <path>
   ${CLAUDE_PLUGIN_ROOT}/skills/jared/scripts/jared comment <N> --body-file <path>
   ${CLAUDE_PLUGIN_ROOT}/skills/jared/scripts/jared set <N> <field> <value>
   ```

   For body/title edits: `gh api -X PATCH /repos/{owner}/{repo}/issues/{N} -f title=… -f body=…`
   For milestone mutations: `gh api -X PATCH /repos/{owner}/{repo}/milestones/{N} …` (or `DELETE` for `dissolve`).

   Per-issue atomicity is provided by the existing atoms. Batch-level atomicity is out of scope; if item 4 of a batch fails after items 1–3 succeeded, re-run just item 4.

10. **PII pre-flight runs on every proposed body edit and close comment**, same as `jared file`.

11. **Post-run summary.** Print a one-line delta to stdout: "Audited N items: K closed, M reshaped, P left alone."
````

- [ ] **Step 2: Verify the file is well-formed markdown**

Run: `head -3 commands/jared-audit.md`
Expected: shows the `---` frontmatter

- [ ] **Step 3: Commit**

```bash
git add commands/jared-audit.md
git commit -m "feat(audit): add /jared-audit slash command (#169)

Seven-question skeptical checklist + four verdict buckets + opt-in
advisor pass + velocity-aware date heuristics. Doctrine lives here
rather than in a separate references/ file.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

### Task 4.2: Update SKILL.md + operations.md

**Files:**
- Modify: `skills/jared/SKILL.md`, `skills/jared/references/operations.md`

- [ ] **Step 1: Add `/jared-audit` to SKILL.md inventory**

In `skills/jared/SKILL.md`, find the slash-command inventory section. Add an entry for `/jared-audit` adjacent to `/jared-groom`:

```markdown
- `/jared-audit` — Skeptical kanban-manager audit. Walks the backlog oldest-first, runs a seven-question per-item checklist (necessity, scope realism, YAGNI, antipattern, framing accuracy, dependency edges, calibration), produces operator-approved close / reshape / leave-alone verdicts. Velocity-aware date heuristics so proposed milestone dates calibrate to recent shipping cadence. Use when the backlog has aged, when reviewing a body of work before a milestone close, or when the operator wants confidence before pulling from old items.
```

Also add staleness triggers to the existing trigger list:

```markdown
- Backlog has aged (oldest items 60+ days untouched) → trigger `/jared-audit`
- About to pull from a Backlog item that hasn't been touched in weeks → trigger `/jared-audit --issues <N>` for a single-item accuracy check
- Reviewing a milestone before its due date → trigger `/jared-audit --type milestones`
```

(Insert at the appropriate position in the existing trigger list — match the surrounding indentation and bullet style.)

- [ ] **Step 2: Add one paragraph to operations.md**

In `skills/jared/references/operations.md`, add a new section:

```markdown
### `/jared-audit`

Skeptical per-item accuracy audit. Fetches a working set (oldest-first issues, optionally milestones) with each item's open-dependents and a velocity block (recent closure rate + median age-at-close + median PR duration). The conversation runs a seven-question checklist per item, optionally invokes `advisor()` to pressure-test non-trivial batches before the operator sees them, and applies approved mutations via the existing atoms (`jared close`, `jared comment`, `jared set`) plus `gh api` for body / title / milestone changes. See `commands/jared-audit.md` for the full doctrine. The CLI side is just `jared audit fetch [--count N | --age-days N | --issues N,M,…] [--type issues|milestones|both]` — verdicts and mutation orchestration live in the conversational layer.
```

- [ ] **Step 3: Commit**

```bash
git add skills/jared/SKILL.md skills/jared/references/operations.md
git commit -m "docs(audit): inventory /jared-audit in SKILL.md + operations.md (#169)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Phase 5: End-to-end smoke + version bump + PR

### Task 5.1: Smoke `jared audit fetch` against the live jared board

**Files:**
- *(none modified — live verification)*

- [ ] **Step 1: Run the action against the jared board itself**

Run: `${CLAUDE_PLUGIN_ROOT}/skills/jared/scripts/jared audit fetch --count 5 | head -100`

Expected:
- Exit code 0
- JSON with `items` (5 oldest open issues, oldest-first), `milestones` ([] since `--type` defaults to issues), `velocity` block with non-zero `closures_last_14d` (per the recent ship cadence captured in #163, #170, #172, etc.)
- Each item has `open_dependents` field (list, may be empty)

If anything fails: fix the issue, re-run, then proceed.

- [ ] **Step 2: Spot-check the velocity numbers**

Compare against ground truth:

```bash
gh search issues --repo brockamer/jared --state=closed \
    --search "closed:>=$(date -d '14 days ago' +%Y-%m-%d)" --limit 100 --json number | jq length
```

The output should match `velocity.closures_last_14d` exactly. If they differ, the cutoff arithmetic in `compute_velocity` is wrong — fix and re-run.

- [ ] **Step 3: Try the milestone branch**

Run: `${CLAUDE_PLUGIN_ROOT}/skills/jared/scripts/jared audit fetch --type milestones`

Expected: JSON with `milestones[]` listing open milestones (if any exist on the jared board) — empty list is also valid output.

- [ ] **Step 4: Try the default-staleness branch**

Run: `${CLAUDE_PLUGIN_ROOT}/skills/jared/scripts/jared audit fetch`

Expected: items list filtered by `2 × velocity.median_age_at_close` (clamped to [14, 60] days). On the jared board with recent shipping, expect the threshold near the 14-day floor and only a handful of items.

- [ ] **Step 5: Note results in the issue session note**

Append a one-line smoke summary as a session note on #169:

```bash
${CLAUDE_PLUGIN_ROOT}/skills/jared/scripts/jared comment 169 --body-file - <<'EOF'
## Session 2026-05-21 — Smoke results

`jared audit fetch --count 5`: PASS (oldest-first, velocity block populated, open_dependents enriched).
`jared audit fetch --type milestones`: PASS (returns N open milestones).
`jared audit fetch` (default-staleness): PASS (threshold computed from velocity, filtered correctly).

Ground-truth velocity matches `gh search` closure count.
EOF
```

### Task 5.2: Version bump

**Files:**
- Modify: `.claude-plugin/plugin.json`, `pyproject.toml`

- [ ] **Step 1: Bump version to 0.21.0 in plugin.json**

Read current version in `.claude-plugin/plugin.json` and bump the `"version"` field to `"0.21.0"`.

- [ ] **Step 2: Bump version to 0.21.0 in pyproject.toml**

Update the `version = "..."` line in `[project]` to `version = "0.21.0"`.

- [ ] **Step 3: Commit**

```bash
git add .claude-plugin/plugin.json pyproject.toml
git commit -m "chore(release): bump version to 0.21.0 (#169)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

### Task 5.3: Open PR

**Files:**
- *(none)*

- [ ] **Step 1: Push the branch**

Run: `git push -u origin feature/169-jared-audit`

- [ ] **Step 2: Open the PR**

Run:

```bash
gh pr create --title "feat(audit): /jared-audit — skeptical backlog accuracy audit (#169)" --body "$(cat <<'EOF'
## Summary

- Adds `/jared-audit` — skeptical kanban-manager action. Walks the backlog oldest-first, runs a seven-question per-item checklist (necessity, scope realism, YAGNI, antipattern, framing accuracy, dependency edges, calibration), produces operator-approved verdicts (`close-as-completed` / `close-as-not-planned` / `reshape` / `leave-alone` for issues; `close` / `dissolve` / `reshape` / `leave-alone` for milestones).
- Velocity-aware: default staleness threshold is `2 × median_age_at_close` clamped to [14, 60] days; proposed milestone dates anchor to `median_pr_duration_days × remaining_open_children` so dates don't drift 3–6 months out.
- Opt-in `advisor()` pass between batch drafting and operator presentation for non-trivial batches.

## Test plan

- [ ] `pytest tests/test_cmd_audit.py -v` — all green
- [ ] `pytest && ruff check . && mypy` — full suite + lint + typecheck clean
- [ ] `jared audit fetch --count 5` against this repo — JSON shape correct, velocity populated, oldest-first
- [ ] `jared audit fetch --type milestones` — milestone branch works
- [ ] `jared audit fetch` (default-staleness) — uses velocity-derived threshold

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

Resulting PR URL is the deliverable; copy it into the issue body's `Linked PR:` row.

---

## Self-review (run after all tasks complete)

- **Spec coverage:** every spec section has a task. Posture / Scope / Checklist / Verdict buckets / Shape / Pacing / Optional advisor pass / Velocity-aware dates / Atomicity / Close comments / Files touched / Acceptance criteria — all touched by Phase 4.1's doctrine + Phases 1–3's code.
- **Placeholder scan:** no "TBD" / "implement later" / "similar to Task N" — every step has the actual code or command.
- **Type consistency:** `fetch_audit_window`'s signature in tests matches Task 2.1's implementation; `compute_velocity` returns the same three-key dict throughout.
- **Self-correction triggers:** if `--age-days` arithmetic returns wrong counts in smoke (Task 5.1.2), the bug is in the cutoff formula; if `open_dependents` enrichment yields empty when it shouldn't, the `state == "OPEN"` filter is wrong (GitHub may return lowercase from REST vs uppercase from GraphQL — confirm shape).
