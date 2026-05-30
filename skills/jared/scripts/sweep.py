#!/usr/bin/env python3
"""
sweep.py — audit a GitHub Projects v2 board for drift.

Reads the project via `gh project item-list` and runs the checks from
references/board-sweep.md:

  1. Metadata completeness — every open item has Status + Priority + any
     other required field (e.g., Work Stream if the project uses it —
     detected by whether any open item on the board has Work Stream set).
     Status is checked because GitHub's auto-add-to-project workflow adds
     items without populating Status; items landing as Status=None sort
     below everything and vanish until someone sets it manually.
  2. WIP cap — In Progress within limit, flag stalled items
  3. Up Next queue — size and pullable-top check
  4. Aging — High-priority Backlog items >14 days old
  5. Blocked-status hygiene — items in Blocked column have `## Blocked by` section;
     flag Blocked items >7 days
  6. Native dependency hygiene — blockedBy edges pointing at closed issues
  7. Legacy priority labels — should be stripped
  8. Plan/spec drift — active plans citing closed issues, plans without issues
  9. Session-note freshness — In Progress items without recent Session notes

Usage:
  sweep.py                             # read config from ./docs/project-board.md
  sweep.py --owner X --project N       # explicit owner/project
  sweep.py --repo owner/repo           # explicit repo for issue-level queries
  sweep.py --plan-dir path             # plan/spec directory (default: docs/superpowers/plans)
  sweep.py --wip-limit N               # override WIP limit (default: 4)
  sweep.py --staleness-days N          # aging threshold for High Backlog (default: 14)

Output: prose findings, grouped by check. Exit 0 regardless of findings.

This script is advisory — it does NOT apply fixes. Review and propose to the
user before applying any changes.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys
from fnmatch import fnmatchcase
from pathlib import Path
from typing import Any, cast

# Make sibling lib/ importable regardless of cwd — same pattern as the jared CLI.
# mypy can't follow the sys.path manipulation; types are still enforced inside lib.board.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from lib import cache as board_cache  # type: ignore[import-not-found]  # noqa: E402
from lib.board import (  # type: ignore[import-not-found]  # noqa: E402
    Board,
    GhInvocationError,
)
from lib.board import (
    check_graphql_budget as board_check_graphql_budget,
)
from lib.board import (
    fetch_blocked_by_edges as board_fetch_blocked_by_edges,
)
from lib.board import (
    fetch_recent_closed_prs_with_files as board_fetch_recent_closed_prs_with_files,
)
from lib.board import (
    fetch_recent_comments_batch as board_fetch_recent_comments_batch,
)
from lib.board import (
    graphql_budget as board_graphql_budget,
)
from lib.board import (
    parse_referenced_issues as board_parse_referenced_issues,
)
from lib.board import (
    run_gh as board_run_gh,
)
from lib.board import (
    run_gh_raw as board_run_gh_raw,
)

# ---------- Config discovery ----------


def parse_config(path: Path) -> tuple[str, str]:
    """Extract (owner, project_number) from a convention doc. Handles user + org URLs."""
    text = path.read_text()
    m = re.search(r"https://github\.com/(users|orgs)/([A-Za-z0-9_-]+)/projects/(\d+)", text)
    if not m:
        raise RuntimeError(
            f"{path}: no https://github.com/(users|orgs)/<name>/projects/<N> URL found"
        )
    return m.group(2), m.group(3)


def find_config() -> Path | None:
    """Locate the convention doc using Board's autodiscovery list."""
    # cast: Board imported with `type: ignore[import-not-found]` is opaque to
    # mypy here. The classmethod itself is typed as -> Path | None in lib.board.
    return cast("Path | None", Board.find_default_path())


# ---------- gh wrappers ----------
#
# Uses module-level helpers from lib/board.py (board_run_gh / board_run_gh_raw).
# Higher-level GraphQL calls (paginated blockedBy lookup) live in lib.board so
# dependency-graph.py can share them. sweep.py doesn't need a full Board
# instance — it only extracts owner + project-number from the convention doc
# (see parse_config) and reads field values from gh JSON, not field IDs from
# the convention doc.


def fetch_items(owner: str, project: str) -> list[dict[str, Any]]:
    """Fetch project items, consulting the on-disk snapshot cache (#52).

    `JARED_NO_CACHE=1` bypasses the cache; `JARED_CACHE_TTL_SECONDS` overrides
    the default 60s TTL.
    """
    project_number = int(project)
    no_cache = os.environ.get("JARED_NO_CACHE") == "1"
    if not no_cache:
        ttl = int(os.environ.get("JARED_CACHE_TTL_SECONDS", "60"))
        cached = board_cache.get_item_list(project_number, ttl_seconds=ttl)
        if cached is not None:
            return cast(list[dict[str, Any]], cached)
    limit = 2000
    data = board_run_gh(
        [
            "project",
            "item-list",
            project,
            "--owner",
            owner,
            "--limit",
            str(limit),
            "--format",
            "json",
        ]
    )
    items = cast(list[dict[Any, Any]], data.get("items", []))
    if len(items) == limit:
        raise GhInvocationError(
            f"gh project item-list returned exactly {limit} items — "
            f"likely truncated. sweep flows (off-board ghost detection, "
            f"stuck-closed) depend on a complete snapshot; do not trust "
            f"this one. Raise the --limit or paginate."
        )
    if not no_cache:
        board_cache.set_item_list(project_number, items=items)
    return items


def merge_open_with_closed(
    open_items: list[dict[str, Any]],
    closed_items: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Merge a fresh open-items pull with the cached closed-items snapshot.

    Dedup rule: open-items wins on number collision. Handles the external-
    reopen race where an issue was closed (still in closed-cache) but has
    since been reopened (now in open-items). The fresh open snapshot is
    authoritative for current state.

    Items without a content.number key are kept on both sides — sweep's
    checks tolerate that shape via defensive None-guards.
    """
    open_numbers = {
        (i.get("content") or {}).get("number")
        for i in open_items
        if (i.get("content") or {}).get("number") is not None
    }
    deduped_closed = [
        i for i in closed_items if (i.get("content") or {}).get("number") not in open_numbers
    ]
    return open_items + deduped_closed


def fetch_items_with_closed_cache(board: Board, owner: str, project: str) -> list[dict[str, Any]]:
    """Fetch a sweep-shaped item snapshot, exploiting the closed-items cache (#186).

    Warm path: pull open items via `Board.open_items()` (cost scales with
    open count, not total board size) and merge with the persistent
    closed-items cache. No `gh project item-list` call is made — that's
    the whole point of the optimization.

    Cold path: fall back to the full `fetch_items` pull (which has the
    `len == limit` truncation guard #185 added), then warm the closed
    cache from the closed subset for future calls.

    `Board.open_items()` currently raises `GhInvocationError` when the repo
    has >100 open issues (pagination not implemented). Without a fallback
    here, sweep would break silently when an active project crosses that
    threshold. Catch + fall through to the cold path — slower but correct.

    `JARED_NO_CACHE=1` bypasses both layers — every call hits the network.
    """
    no_cache = os.environ.get("JARED_NO_CACHE") == "1"
    if not no_cache:
        cached_closed = board_cache.get_closed_items(board.project_number)
        if cached_closed is not None:
            try:
                open_items = board.open_items()
            except GhInvocationError:
                # >100 open issues or transient open-items failure — fall
                # through to the cold path rather than break sweep.
                pass
            else:
                return merge_open_with_closed(open_items, cached_closed)
    # Cold-cache fallback: full-board pull (truncation-guarded). Warm the
    # closed-cache from the result so subsequent sweeps take the warm path.
    # Filter on top-level `status` rather than `content.state`: `gh project
    # item-list --format json` does not populate `content.state`, so the
    # earlier `state == "CLOSED"` check was a no-op and the cache never
    # warmed. `status` is populated by both fetch paths.
    items = fetch_items(owner, project)
    if not no_cache:
        closed_subset = [i for i in items if i.get("status") == "Done"]
        board_cache.set_closed_items(project_number=board.project_number, items=closed_subset)
    return items


def fetch_open_issues_bulk(repo: str) -> list[dict[str, Any]]:
    """One API call to get all open issues with the data we need."""
    stdout = board_run_gh_raw(
        [
            "issue",
            "list",
            "--repo",
            repo,
            "--state",
            "open",
            "--limit",
            "500",
            "--json",
            "number,title,createdAt,updatedAt,labels,body",
        ]
    )
    return json.loads(stdout) if stdout else []


def fetch_native_blocked_by(repo: str) -> dict[int, list[dict[str, Any]]]:
    """Thin wrapper around lib.board.fetch_blocked_by_edges with a 60s cache.

    Kept as a free function so existing sweep tests / callers don't need to
    rewire imports — the real implementation lives in lib/board.py and is
    shared with dependency-graph.py.
    """
    return cast(
        dict[int, list[dict[str, Any]]],
        board_fetch_blocked_by_edges(repo, cache="60s"),
    )


# ---------- Item helpers ----------


def field(item: dict[str, Any], *keys: str) -> str | None:
    """Look up a field value across the variant key names gh returns."""
    for k in keys:
        v = item.get(k)
        if v:
            return cast(str, v)
    return None


def guess_repo_from_items(items: list[dict[str, Any]]) -> str | None:
    for i in items:
        content = i.get("content") or {}
        repo = content.get("repository")
        if repo:
            return cast(str, repo.replace("https://github.com/", ""))
    return None


# ---------- Checks ----------


# Items can land on the board with no column assignment (auto-add-to-project
# workflow, manual API call without a Status set). `gh project item-list
# --format json` surfaces those as missing-key, None, "", or — depending on
# gh version and field configuration — as a display string like "No Status".
# Whitelist-validate against the known kanban column names so all four
# shapes get flagged uniformly. (#85)
VALID_STATUSES = frozenset({"Backlog", "Up Next", "In Progress", "Blocked", "Done"})


def check_metadata(items: list[dict[str, Any]]) -> list[str]:
    # Detect whether Work Stream is in use on this board. If no open item
    # has Work Stream set, assume the project doesn't define the field and
    # skip the Work Stream check. Projects without a Work Stream field (a
    # valid choice — see references/new-board.md) should not be flagged.
    work_stream_in_use = any(
        field(i, "work Stream", "workStream", "workstream")
        for i in items
        if i.get("status") != "Done"
    )
    missing = []
    for i in items:
        content = i.get("content") or {}
        # Skip Done items — no point enforcing metadata on a closed item.
        # `gh project item-list --format json` does not populate
        # `content.state`, so filter on the reliable top-level Project Status.
        if i.get("status") == "Done":
            continue
        n = content.get("number")
        prio = field(i, "priority")
        ws = field(i, "work Stream", "workStream", "workstream")
        status = i.get("status")
        issues = []
        if status not in VALID_STATUSES:
            issues.append("no Status")
        if not prio:
            issues.append("no Priority")
        if work_stream_in_use and not ws:
            issues.append("no Work Stream")
        if issues:
            missing.append(f"#{n}: {', '.join(issues)}")
    return missing


def check_wip(items: list[dict[str, Any]], limit: int) -> list[str]:
    in_progress = [i for i in items if i.get("status") == "In Progress"]
    findings = []
    if len(in_progress) > limit:
        findings.append(f"In Progress has {len(in_progress)} items (cap is {limit}):")
        for i in in_progress:
            n = (i.get("content") or {}).get("number")
            t = (i.get("title") or "")[:60]
            findings.append(f"  #{n}: {t}")
    elif len(in_progress) == 0:
        findings.append("In Progress is empty — consider pulling the top of Up Next")
    return findings


def check_up_next_size(items: list[dict[str, Any]], limit: int = 8) -> list[str]:
    up_next = [i for i in items if i.get("status") == "Up Next"]
    if len(up_next) > limit:
        return [
            f"Up Next has {len(up_next)} items (recommended cap: {limit}) — "
            "consider moving lower items back to Backlog"
        ]
    return []


def check_stale_high_backlog(
    items: list[dict[str, Any]], issues_by_number: dict[int, dict[str, Any]], days: int
) -> list[str]:
    cutoff = dt.datetime.now(dt.UTC) - dt.timedelta(days=days)
    stale = []
    for i in items:
        content = i.get("content") or {}
        if i.get("status") == "Done":
            continue
        if i.get("status") != "Backlog":
            continue
        if field(i, "priority") != "High":
            continue
        n = content.get("number")
        if n is None:
            continue
        issue = issues_by_number.get(n)
        if not issue:
            continue
        created = dt.datetime.fromisoformat(issue["createdAt"].replace("Z", "+00:00"))
        if created < cutoff:
            age = (dt.datetime.now(dt.UTC) - created).days
            title = issue["title"][:50]
            stale.append(f"#{n}: {age}d old — {title}")
    return stale


def check_in_progress_staleness(
    items: list[dict[str, Any]], issues_by_number: dict[int, dict[str, Any]], days: int = 7
) -> list[str]:
    cutoff = dt.datetime.now(dt.UTC) - dt.timedelta(days=days)
    stale = []
    for i in items:
        content = i.get("content") or {}
        if i.get("status") == "Done":
            continue
        if i.get("status") != "In Progress":
            continue
        n = content.get("number")
        if n is None:
            continue
        issue = issues_by_number.get(n)
        if not issue:
            continue
        updated = dt.datetime.fromisoformat(issue["updatedAt"].replace("Z", "+00:00"))
        if updated < cutoff:
            age = (dt.datetime.now(dt.UTC) - updated).days
            title = issue["title"][:50]
            stale.append(f"#{n}: no activity in {age}d — {title}")
    return stale


def check_blocked_status_hygiene(
    items: list[dict[str, Any]],
    issues_by_number: dict[int, dict[str, Any]],
    blocked_aging_days: int,
) -> list[str]:
    """Items in Blocked Status must have ## Blocked by; flag ones stuck >N days."""
    findings: list[str] = []
    today = dt.date.today()
    for item in items:
        if (item.get("status") or "").strip() != "Blocked":
            continue
        content = item.get("content") or {}
        n = content.get("number")
        if not n or n not in issues_by_number:
            continue
        issue = issues_by_number[n]
        body = issue.get("body") or ""
        if "## Blocked by" not in body:
            findings.append(f"#{n}: in Blocked status but body has no `## Blocked by` section")
        updated = issue.get("updatedAt", "")
        if updated:
            updated_date = dt.datetime.fromisoformat(updated.replace("Z", "+00:00")).date()
            age = (today - updated_date).days
            if age > blocked_aging_days:
                findings.append(f"#{n}: in Blocked status with no activity for {age} days")
    return findings


def check_native_dependencies(
    blocked_by: dict[int, list[dict[str, Any]]],
    issues_by_number: dict[int, dict[str, Any]],
) -> list[str]:
    """Flag native blockedBy edges pointing at closed issues — propose removing."""
    findings: list[str] = []
    for n, blockers in blocked_by.items():
        if n not in issues_by_number:
            continue
        for b in blockers:
            if b.get("state") == "CLOSED":
                findings.append(
                    f"#{n}: blockedBy #{b['number']} which is closed — propose removing edge"
                )
    return findings


def check_off_board_issues(
    items: list[dict[str, Any]],
    issues_by_number: dict[int, dict[str, Any]],
) -> list[str]:
    """Flag open repo issues that have no corresponding project item.

    The "off-board ghost" pattern (#100): an issue is created on the repo
    via raw `gh issue create` (or any path that bypasses `jared file` /
    `jared add-to-board`), so it never lands on the project board. The
    operator can't see it in the kanban view; Status and Priority are
    null; it sorts to the bottom and disappears.

    `_cmd_file` makes this hard to produce on purpose, but the fallback
    path is real: when `jared file` errors opaquely, sessions sometimes
    drop to plain `gh issue create` to keep moving — leaving an orphan
    behind. This check is the durable backstop.

    Caller passes `issues_by_number` already filtered to repo-open
    issues (see `fetch_open_issues_bulk` which uses `--state open`).
    A board item with Status=Done still counts as "on the board" — it's
    on the project, just in a different column.
    """
    on_board = {
        (i.get("content") or {}).get("number")
        for i in items
        if (i.get("content") or {}).get("number") is not None
    }
    findings = []
    for n, issue in sorted(issues_by_number.items()):
        if n in on_board:
            continue
        title = (issue.get("title") or "")[:80]
        findings.append(
            f"#{n}: {title} — Propose: jared add-to-board {n} --priority Medium "
            "(adjust priority as needed)"
        )
    return findings


def check_legacy_priority_labels(issues_by_number: dict[int, dict[str, Any]]) -> list[str]:
    findings = []
    for n, issue in issues_by_number.items():
        labels = [lbl["name"] for lbl in issue.get("labels", [])]
        legacy = [lbl for lbl in labels if lbl.startswith("priority:")]
        if legacy:
            findings.append(
                f"#{n}: legacy labels {legacy} — Priority field is canonical, strip labels"
            )
    return findings


def check_plan_spec_drift(plan_dirs: list[Path], repo: str) -> list[str]:
    """Scan plan/spec directories for orphans and shippable archivals.

    Issue refs are extracted via the shared `parse_referenced_issues` helper
    in `lib.board`, so sweep and archive-plan can't disagree on what counts
    as a referenced issue (#88). The helper accepts both the canonical
    `## Issue` heading form (with list-item refs) and the legacy
    `**Issue:** #N` bold-line fallback.
    """
    if not repo:
        return ["(skipping plan/spec check — repo not determined)"]

    findings = []

    for base in plan_dirs:
        if not base.exists():
            continue
        # Skip archived/
        for p in base.rglob("*.md"):
            if "archived" in p.parts:
                continue
            text = p.read_text(errors="replace")

            refs = set(board_parse_referenced_issues(text))
            if not refs:
                findings.append(f"  {p}: no ## Issue section — orphaned plan/spec")
                continue

            # Check state of each referenced issue
            states = {}
            for n in refs:
                try:
                    data = board_run_gh(
                        ["issue", "view", str(n), "--repo", repo, "--json", "state"]
                    )
                    states[n] = data["state"]
                except GhInvocationError:
                    states[n] = "UNKNOWN"

            if all(s == "CLOSED" for s in states.values()):
                findings.append(
                    f"  {p}: all referenced issues closed ({sorted(refs)}) — propose archiving"
                )

    return findings


def check_session_note_freshness(
    items: list[dict[str, Any]], repo: str | None, days: int = 3
) -> list[str]:
    """Look for In Progress issues without a recent Session note comment."""
    if not repo:
        return ["(skipping session-note check — repo not determined)"]
    cutoff = dt.datetime.now(dt.UTC) - dt.timedelta(days=days)
    in_progress_numbers: list[int] = []
    for i in items:
        content = i.get("content") or {}
        if i.get("status") == "Done":
            continue
        if i.get("status") != "In Progress":
            continue
        n = content.get("number")
        if isinstance(n, int):
            in_progress_numbers.append(n)
    # Single GraphQL round-trip for all in-progress issues, replacing the
    # per-issue REST fan-out that used to live here.
    comments_by_number = board_fetch_recent_comments_batch(
        repo, in_progress_numbers, limit=10, cache="60s"
    )
    findings = []
    for n in in_progress_numbers:
        comments = comments_by_number.get(n, [])
        # A Session note starts with "## Session YYYY-MM-DD"
        session_notes = [
            c
            for c in comments
            if re.match(r"^##\s+Session\s+\d{4}-\d{2}-\d{2}", (c.get("body") or "").strip())
        ]
        if not session_notes:
            findings.append(f"#{n}: In Progress with no Session note comment ever")
            continue
        latest = max(
            dt.datetime.fromisoformat(c["createdAt"].replace("Z", "+00:00")) for c in session_notes
        )
        if latest < cutoff:
            age = (dt.datetime.now(dt.UTC) - latest).days
            findings.append(f"#{n}: latest Session note is {age}d old")
    return findings


def check_doc_sync_gate(
    prs: list[dict[str, Any]],
    operator_docs: list[str],
    code_surface: list[str],
) -> list[str]:
    """Flag closed PRs that touched code surface without touching any operator doc.

    Each PR is a dict of {number, closedAt, files} matching the shape returned
    by lib.board.fetch_recent_closed_prs_with_files. Glob matching uses fnmatchcase over
    `**`-expanded patterns: `src/**` matches `src/foo.py` and `src/a/b.py`.

    Returns one finding line per flagged PR. Empty operator_docs short-
    circuits — no operator-docs config means the check is disabled.
    """
    if not operator_docs:
        return []

    findings: list[str] = []
    for pr in prs:
        files = pr.get("files") or []
        if not files:
            continue
        touched_code = any(_matches_any(f, code_surface) for f in files)
        if not touched_code:
            continue
        touched_doc = any(_matches_any(f, operator_docs) for f in files)
        if touched_doc:
            continue
        number = pr.get("number")
        closed_at = (pr.get("closedAt") or "").split("T")[0]
        docs_list = ", ".join(operator_docs)
        findings.append(
            f"PR #{number} closed {closed_at} touched code surface without an operator doc — "
            f"review whether {docs_list} need an update"
        )
    return findings


# Defaults for the release/CHANGELOG gate (#220). Hardcoded rather than
# project-configurable because the existing operator-docs config is dormant
# on jared's own board, and requiring config here would ship the same dead-
# feature shape — guardrail that doesn't fire on the project most likely to
# need it. Projects with a different release convention can override later
# via a sibling config block; today this is single-purpose by design.
RELEASE_BRANCH_PATTERN = "release/v*"
CHANGELOG_FILE = "CHANGELOG.md"


def check_release_changelog_gate(
    prs: list[dict[str, Any]],
    branch_pattern: str = RELEASE_BRANCH_PATTERN,
    changelog_file: str = CHANGELOG_FILE,
) -> list[str]:
    """Flag merged release PRs that didn't touch CHANGELOG.md.

    A release PR is identified by its `headRefName` matching `branch_pattern`
    (default `release/v*` — jared's verified convention, verified against
    `release/v0.18.1`, `release/v0.22.0`, `release/v0.24.0`, …).

    Only merged PRs are flagged — closed-without-merge release branches don't
    ship a tag, so a missing CHANGELOG entry there is not a release-discipline
    drift. `mergedAt` truthiness gates the check.

    Each PR is a dict matching the shape returned by
    lib.board.fetch_recent_closed_prs_with_files: `number`, `closedAt`,
    `mergedAt`, `headRefName`, and `files`.
    """
    findings: list[str] = []
    for pr in prs:
        if not pr.get("mergedAt"):
            continue
        head = pr.get("headRefName") or ""
        if not fnmatchcase(head, branch_pattern):
            continue
        files = pr.get("files") or []
        if changelog_file in files:
            continue
        number = pr.get("number")
        # Extract the version from `release/v<x.y.z>` for the advisory.
        version = head.split("/", 1)[1] if "/" in head else head
        findings.append(
            f"release PR #{number} shipped {version} without a "
            f"{changelog_file} entry — add one in a follow-up"
        )
    return findings


def _matches_any(path: str, patterns: list[str]) -> bool:
    """fnmatchcase against patterns, with `**` treated as recursive wildcard.

    We rewrite `**` → `*`; `fnmatch`'s `*` crosses `/`, so `src/*` already
    matches `src/foo.py`, `src/a/b/c.py`, etc. This is the opposite of
    `pathlib.PurePath.match` semantics — important to remember when reading
    user-supplied patterns from `docs/project-board.md`.
    """
    for raw in patterns:
        pat = raw.replace("**", "*")
        if fnmatchcase(path, pat):
            return True
    return False


# ---------- Main ----------


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--owner", help="Project owner (user or org)")
    parser.add_argument("--project", help="Project number")
    parser.add_argument("--repo", help="Repo slug for issue-level checks")
    parser.add_argument(
        "--plan-dir",
        action="append",
        help="Plan/spec directory to scan (can pass multiple times). "
        "Default: docs/superpowers/plans and docs/superpowers/specs if they exist.",
    )
    parser.add_argument("--wip-limit", type=int, default=4, help="In Progress cap")
    parser.add_argument("--staleness-days", type=int, default=14, help="High Backlog age threshold")
    parser.add_argument(
        "--blocked-aging-days",
        type=int,
        default=7,
        help="Flag Blocked-status items with no activity beyond this (default: 7)",
    )
    parser.add_argument(
        "--doc-sync-days",
        type=int,
        default=7,
        help="Window (in days) of closed PRs to scan for operator-doc sync (default: 7). "
        "Matches the next-session-prompt 'recently closed' window.",
    )
    parser.add_argument(
        "--min-budget",
        type=int,
        default=200,
        help="Skip the sweep if remaining GraphQL budget is below this (default: 200)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Run the sweep even if GraphQL budget is below --min-budget",
    )
    args = parser.parse_args()

    # Pre-flight GraphQL budget gate. The sweep makes many GraphQL-billed
    # calls; bailing out early with a useful message beats crashing with
    # `API rate limit exceeded` partway through producing output.
    try:
        budget = board_graphql_budget()
    except (RuntimeError, GhInvocationError) as e:
        print(f"sweep: budget probe failed ({e}); proceeding anyway", file=sys.stderr)
    else:
        warning = board_check_graphql_budget(budget, min_required=args.min_budget, force=args.force)
        if warning:
            print(f"sweep: {warning}", file=sys.stderr)
            return 0

    # Resolve owner/project — and the convention doc, if there is one,
    # so we can instantiate a Board for the closed-cache optimization path.
    cfg = find_config()
    if not args.owner or not args.project:
        if not cfg:
            print("sweep: no project-board.md found and no --owner/--project", file=sys.stderr)
            return 1
        try:
            owner, project = parse_config(cfg)
        except RuntimeError as e:
            print(f"sweep: {e}", file=sys.stderr)
            return 1
    else:
        owner, project = args.owner, args.project

    # Resolve plan dirs
    if args.plan_dir:
        plan_dirs = [Path(p) for p in args.plan_dir]
    else:
        plan_dirs = [
            Path("docs/superpowers/plans"),
            Path("docs/superpowers/specs"),
        ]

    print(f"Sweep for https://github.com/users/{owner}/projects/{project}")
    print("  (also tries /orgs/ URL if that's the project's form)")
    print(f"Run at: {dt.datetime.now(dt.UTC).isoformat()}")
    print()

    # Fetch — prefer the closed-cache optimization (#186) when the
    # convention doc *is* what's selecting the project. If the operator
    # explicitly passed --owner/--project, take the cold path: the cfg-
    # derived Board could be a different project, and writing the explicit
    # project's closed items to cfg's cache file would corrupt subsequent
    # cfg-default runs.
    explicit_args = bool(args.owner and args.project)
    try:
        if cfg and not explicit_args:
            board = Board.from_path(cfg)
            items = fetch_items_with_closed_cache(board, owner, project)
        else:
            items = fetch_items(owner, project)
    except (RuntimeError, GhInvocationError) as e:
        print(f"sweep: {e}", file=sys.stderr)
        return 1

    repo = args.repo or guess_repo_from_items(items)

    issues_by_number = {}
    if repo:
        try:
            for issue in fetch_open_issues_bulk(repo):
                issues_by_number[issue["number"]] = issue
        except (RuntimeError, GhInvocationError) as e:
            print(f"sweep: issue fetch failed: {e}", file=sys.stderr)

    # Filter on top-level `status` rather than `content.state`: `gh project
    # item-list --format json` does not populate `content.state`, so the
    # earlier `state != "CLOSED"` filter was a no-op and the counter equalled
    # total board size. See #189.
    total_open = sum(1 for i in items if i.get("status") != "Done")
    print(f"Open items on board: {total_open}")
    if repo:
        print(f"Open issues in {repo}: {len(issues_by_number)}")
    print()

    # ---- Run checks ----

    print("== Metadata completeness ==")
    missing = check_metadata(items)
    for m in missing or ["  All open items have required metadata"]:
        print(f"  {m}" if not m.startswith(" ") else m)
    print()

    print(f"== WIP (In Progress cap = {args.wip_limit}) ==")
    for line in check_wip(items, args.wip_limit) or ["Healthy"]:
        print(f"  {line}" if not line.startswith("  ") else line)
    print()

    print("== Up Next size ==")
    for line in check_up_next_size(items) or ["Healthy"]:
        print(f"  {line}")
    print()

    print(f"== Stale High-priority Backlog (>{args.staleness_days}d) ==")
    if not issues_by_number:
        print("  (skipped — no issue data)")
    else:
        stale = check_stale_high_backlog(items, issues_by_number, args.staleness_days)
        for s in stale or ["None"]:
            print(f"  {s}")
    print()

    print("== Stalled In Progress (>7d no activity) ==")
    if not issues_by_number:
        print("  (skipped — no issue data)")
    else:
        stalled = check_in_progress_staleness(items, issues_by_number)
        for s in stalled or ["None"]:
            print(f"  {s}")
    print()

    print(f"== Blocked-status hygiene (>{args.blocked_aging_days}d) ==")
    if not issues_by_number:
        print("  (skipped — no issue data)")
    else:
        findings = check_blocked_status_hygiene(
            items, issues_by_number, args.blocked_aging_days
        ) or ["None"]
        for f in findings:
            print(f"  {f}")
    print()

    print("== Native dependency hygiene ==")
    if not repo:
        print("  (skipped — repo not determined)")
    else:
        try:
            native_blocked_by = fetch_native_blocked_by(repo)
            for f in check_native_dependencies(native_blocked_by, issues_by_number) or ["None"]:
                print(f"  {f}")
        except (RuntimeError, GhInvocationError) as e:
            print(f"  (skipped — {e})")
    print()

    print("== Legacy 'priority: *' labels ==")
    if not issues_by_number:
        print("  (skipped — no issue data)")
    else:
        for f in check_legacy_priority_labels(issues_by_number) or ["None"]:
            print(f"  {f}")
    print()

    print("== Plan/spec drift ==")
    existing_plan_dirs = [p for p in plan_dirs if p.exists()]
    if not existing_plan_dirs:
        print("  (no plan/spec directories found — skipping)")
    elif not repo:
        print("  (skipped — repo not determined)")
    else:
        findings = check_plan_spec_drift(existing_plan_dirs, repo)
        for f in findings or ["  None"]:
            print(f if f.startswith(" ") else f"  {f}")
    print()

    # Both the doc-sync gate and the release/CHANGELOG gate scan the same
    # window of recently-closed PRs. Fetch once, share between sections.
    prs_cache: list[dict[str, Any]] | None = None

    print("== Doc-sync gate (operator docs not updated alongside code) ==")
    if not repo:
        print("  (skipped — repo not determined)")
    else:
        # The doc-sync config lives on the Board dataclass. find_config()
        # already located the convention doc above; load Board lazily here
        # so older boards without the section parse fine (they yield
        # operator_docs=[], which short-circuits the check).
        try:
            board = Board.from_default()
            operator_docs = board.operator_docs
            code_surface = board.code_surface
        except Exception as e:  # noqa: BLE001 — advisory path, never fail the sweep
            print(f"  (skipped — board load failed: {e})")
            operator_docs = []
            code_surface = []
        if not operator_docs:
            print("  (skipped — no ### Current-state operator docs block on this board)")
        else:
            try:
                prs_cache = board_fetch_recent_closed_prs_with_files(repo, days=args.doc_sync_days)
                findings = check_doc_sync_gate(prs_cache, operator_docs, code_surface)
                for line in findings or ["None"]:
                    print(f"  {line}")
            except (RuntimeError, GhInvocationError) as e:
                print(f"  (skipped — {e})")
    print()

    print("== Release/CHANGELOG gate (release PRs that skipped CHANGELOG.md) ==")
    if not repo:
        print("  (skipped — repo not determined)")
    else:
        try:
            if prs_cache is None:
                prs_cache = board_fetch_recent_closed_prs_with_files(repo, days=args.doc_sync_days)
            findings = check_release_changelog_gate(prs_cache)
            for line in findings or ["None"]:
                print(f"  {line}")
        except (RuntimeError, GhInvocationError) as e:
            print(f"  (skipped — {e})")
    print()

    print("== Off-board issues (open in repo, missing from project) ==")
    if not issues_by_number:
        print("  (skipped — no issue data)")
    else:
        for f in check_off_board_issues(items, issues_by_number) or ["None"]:
            print(f"  {f}")
    print()

    print("== Session-note freshness (In Progress, last 3 days) ==")
    for f in check_session_note_freshness(items, repo) or ["None"]:
        print(f"  {f}")
    print()

    print("Sweep complete. Advisory only — review and propose before applying.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
