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
  1b. Closed items not on Done — auto-move sometimes fails to fire;
      closed issues with Status != Done accumulate and pollute queries.
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
  sweep.py --wip-limit N               # override WIP limit (default: 3)
  sweep.py --staleness-days N          # aging threshold for High Backlog (default: 14)

Output: prose findings, grouped by check. Exit 0 regardless of findings.

This script is advisory — it does NOT apply fixes. Review and propose to the
user before applying any changes.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from pathlib import Path
from typing import Any

# Make sibling lib/ importable regardless of cwd — same pattern as the jared CLI.
# mypy can't follow the sys.path manipulation; types are still enforced inside lib.board.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from lib.board import (  # type: ignore[import-not-found]  # noqa: E402
    GhInvocationError,
)
from lib.board import (
    run_gh as board_run_gh,
)
from lib.board import (
    run_gh_raw as board_run_gh_raw,
)
from lib.board import (
    run_graphql as board_run_graphql,
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
    for candidate in (
        "docs/project-board.md",
        "PROJECT_BOARD.md",
        ".github/project-board.md",
    ):
        p = Path(candidate)
        if p.exists():
            return p
    return None


# ---------- gh wrappers ----------
#
# Uses module-level helpers from lib/board.py (board_run_gh / board_run_gh_raw /
# board_run_graphql). These handle subprocess invocation, error raising, and
# JSON parsing uniformly across every jared script — sweep.py doesn't need a
# full Board instance because it only extracts owner + project-number from the
# convention doc (see parse_config). It reads field values from the gh JSON
# response, not field IDs from the convention doc.


def fetch_items(owner: str, project: str) -> list[dict]:
    data = board_run_gh(
        [
            "project",
            "item-list",
            project,
            "--owner",
            owner,
            "--limit",
            "200",
            "--format",
            "json",
        ]
    )
    return data.get("items", [])


def fetch_open_issues_bulk(repo: str) -> list[dict]:
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


def fetch_native_blocked_by(repo: str) -> dict[int, list[dict]]:
    """One GraphQL call to get blockedBy for all open issues. Returns {number: [{number, state}]}.

    Tries 'blockedBy' first; falls back to 'issueDependencies' on schema error.
    """
    owner, name = repo.split("/", 1)
    for field_name in ("blockedBy", "issueDependencies"):
        q = (
            "query($o:String!,$r:String!,$c:String){repository(owner:$o,name:$r){"
            f"issues(first:100,after:$c,states:OPEN){{pageInfo{{hasNextPage endCursor}}"
            f"nodes{{number {field_name}(first:20){{nodes{{number state}}}}}}}}}}}}"
        )
        result: dict[int, list[dict]] = {}
        cursor: str | None = None
        try:
            while True:
                kwargs: dict[str, str] = {"o": owner, "r": name}
                if cursor:
                    kwargs["c"] = cursor
                data = board_run_graphql(q, **kwargs)["data"]["repository"]["issues"]
                for node in data["nodes"]:
                    result[node["number"]] = node[field_name]["nodes"]
                if not data["pageInfo"]["hasNextPage"]:
                    break
                cursor = data["pageInfo"]["endCursor"]
            return result
        except GhInvocationError as e:
            # Schema may expose issueDependencies instead of blockedBy.
            if "Field" in str(e) and "doesn" in str(e):
                continue
            raise
    raise RuntimeError("Neither blockedBy nor issueDependencies field is available")


def fetch_recent_comments(repo: str, number: int, limit: int = 5) -> list[dict]:
    """Get recent comments on an issue (for session-note freshness)."""
    try:
        stdout = board_run_gh_raw(
            [
                "api",
                f"repos/{repo}/issues/{number}/comments",
                "--jq",
                f".[-{limit}:] | .[] | {{body, created_at}}",
            ]
        )
    except GhInvocationError:
        return []
    # jq emits one object per line
    comments = []
    for line in stdout.splitlines():
        line = line.strip()
        if line:
            try:
                comments.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return comments


# ---------- Item helpers ----------


def field(item: dict, *keys: str) -> str | None:
    """Look up a field value across the variant key names gh returns."""
    for k in keys:
        v = item.get(k)
        if v:
            return v
    return None


def guess_repo_from_items(items: list[dict]) -> str | None:
    for i in items:
        content = i.get("content") or {}
        repo = content.get("repository")
        if repo:
            return repo.replace("https://github.com/", "")
    return None


# ---------- Checks ----------


def check_metadata(items: list[dict]) -> list[str]:
    # Detect whether Work Stream is in use on this board. If no open item
    # has Work Stream set, assume the project doesn't define the field and
    # skip the Work Stream check. Projects without a Work Stream field (a
    # valid choice — see references/new-board.md) should not be flagged.
    work_stream_in_use = any(
        field(i, "work Stream", "workStream", "workstream")
        for i in items
        if (i.get("content") or {}).get("state") != "CLOSED"
    )
    missing = []
    for i in items:
        content = i.get("content") or {}
        # gh project item-list sometimes returns content.state == None for closed
        # items, so also skip anything the board has already moved to Done.
        if content.get("state") == "CLOSED" or i.get("status") == "Done":
            continue
        n = content.get("number")
        prio = field(i, "priority")
        ws = field(i, "work Stream", "workStream", "workstream")
        status = i.get("status") or ""
        issues = []
        if not status:
            issues.append("no Status")
        if not prio:
            issues.append("no Priority")
        if work_stream_in_use and not ws:
            issues.append("no Work Stream")
        if issues:
            missing.append(f"#{n}: {', '.join(issues)}")
    return missing


def check_closed_not_done(items: list[dict]) -> list[dict]:
    """Closed issues should auto-move to Done. If they don't, return them.

    Detection-only. Each entry is {number, title, current_status} — callers
    decide the rendering (e.g. sweep's main() adds the `Propose: jared set
    <N> Status Done` remediation suffix in its render loop). Keeping
    format out of the detector means the next sweep-check that needs a
    Propose-style remediation can follow the same pattern at its own
    render site without reinventing the formatter here.

    The drift usually comes from projects whose built-in "Item closed →
    Done" workflow is disabled — paths like `gh issue close` and PR-merge
    auto-close rely on it entirely (only `jared close` has its own
    explicit-Status fallback).
    """
    stuck = []
    for i in items:
        content = i.get("content") or {}
        if content.get("state") != "CLOSED":
            continue
        status = i.get("status") or ""
        if status == "Done":
            continue
        stuck.append(
            {
                "number": content.get("number"),
                "title": (content.get("title") or i.get("title") or "")[:60],
                "current_status": status or "no Status",
            }
        )
    return stuck


def format_closed_not_done_line(entry: dict[str, Any]) -> str:
    """Render a stuck-item entry with its remediation command.

    Format lives at the sweep/groom render site, not in the detector.
    Other sweep checks that want a Propose-style suffix follow this same
    shape — their format helper, their render site.
    """
    n = entry["number"]
    return (
        f"#{n} [{entry['current_status']}]: {entry['title']} — "
        f"Propose: jared set {n} Status Done"
    )


def check_wip(items: list[dict], limit: int) -> list[str]:
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


def check_up_next_size(items: list[dict], limit: int = 3) -> list[str]:
    up_next = [i for i in items if i.get("status") == "Up Next"]
    if len(up_next) > limit:
        return [
            f"Up Next has {len(up_next)} items (recommended cap: {limit}) — "
            "consider moving lower items back to Backlog"
        ]
    return []


def check_stale_high_backlog(
    items: list[dict], issues_by_number: dict[int, dict], days: int
) -> list[str]:
    cutoff = dt.datetime.now(dt.UTC) - dt.timedelta(days=days)
    stale = []
    for i in items:
        content = i.get("content") or {}
        if content.get("state") == "CLOSED":
            continue
        if i.get("status") != "Backlog":
            continue
        if field(i, "priority") != "High":
            continue
        n = content.get("number")
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
    items: list[dict], issues_by_number: dict[int, dict], days: int = 7
) -> list[str]:
    cutoff = dt.datetime.now(dt.UTC) - dt.timedelta(days=days)
    stale = []
    for i in items:
        content = i.get("content") or {}
        if content.get("state") == "CLOSED":
            continue
        if i.get("status") != "In Progress":
            continue
        n = content.get("number")
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
    items: list[dict],
    issues_by_number: dict[int, dict],
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
    blocked_by: dict[int, list[dict]],
    issues_by_number: dict[int, dict],
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


def check_legacy_priority_labels(issues_by_number: dict[int, dict]) -> list[str]:
    findings = []
    for n, issue in issues_by_number.items():
        labels = [lbl["name"] for lbl in issue.get("labels", [])]
        legacy = [lbl for lbl in labels if lbl.startswith("priority:")]
        if legacy:
            findings.append(
                f"#{n}: legacy labels {legacy} — Priority field is canonical, strip labels"
            )
    return findings


def parse_issue_refs(text: str) -> set[int]:
    """Find #N references in a block of text."""
    return {int(m) for m in re.findall(r"#(\d+)", text or "")}


def check_plan_spec_drift(plan_dirs: list[Path], repo: str) -> list[str]:
    """Scan plan/spec directories for orphans and shippable archivals."""
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

            # Look for ## Issue section — support ## Issue, ## Issue(s), ## Issues
            issue_section_match = re.search(
                r"^#{1,3}\s+Issue[s()]*\s*$([\s\S]+?)(?=^#|\Z)",
                text,
                re.MULTILINE,
            )
            if not issue_section_match:
                findings.append(f"  {p}: no ## Issue section — orphaned plan/spec")
                continue

            refs = parse_issue_refs(issue_section_match.group(1))
            if not refs:
                findings.append(f"  {p}: ## Issue section but no #N references")
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


def check_session_note_freshness(items: list[dict], repo: str | None, days: int = 3) -> list[str]:
    """Look for In Progress issues without a recent Session note comment."""
    if not repo:
        return ["(skipping session-note check — repo not determined)"]
    cutoff = dt.datetime.now(dt.UTC) - dt.timedelta(days=days)
    findings = []
    for i in items:
        content = i.get("content") or {}
        if content.get("state") == "CLOSED":
            continue
        if i.get("status") != "In Progress":
            continue
        n = content.get("number")
        if not n:
            continue
        comments = fetch_recent_comments(repo, n, limit=10)
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
            dt.datetime.fromisoformat(c["created_at"].replace("Z", "+00:00")) for c in session_notes
        )
        if latest < cutoff:
            age = (dt.datetime.now(dt.UTC) - latest).days
            findings.append(f"#{n}: latest Session note is {age}d old")
    return findings


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
    parser.add_argument("--wip-limit", type=int, default=3, help="In Progress cap")
    parser.add_argument("--staleness-days", type=int, default=14, help="High Backlog age threshold")
    parser.add_argument(
        "--blocked-aging-days",
        type=int,
        default=7,
        help="Flag Blocked-status items with no activity beyond this (default: 7)",
    )
    args = parser.parse_args()

    # Resolve owner/project
    if not args.owner or not args.project:
        cfg = find_config()
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

    # Fetch
    try:
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

    total_open = sum(1 for i in items if (i.get("content") or {}).get("state") != "CLOSED")
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
    else:
        findings = check_plan_spec_drift(existing_plan_dirs, repo)
        for f in findings or ["  None"]:
            print(f if f.startswith(" ") else f"  {f}")
    print()

    print("== Closed items not on Done ==")
    stuck = check_closed_not_done(items)
    if stuck:
        for entry in stuck:
            print(f"  {format_closed_not_done_line(entry)}")
    else:
        print("  None")
    print()

    print("== Session-note freshness (In Progress, last 3 days) ==")
    for f in check_session_note_freshness(items, repo) or ["None"]:
        print(f"  {f}")
    print()

    print("Sweep complete. Advisory only — review and propose before applying.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
