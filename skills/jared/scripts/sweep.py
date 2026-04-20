#!/usr/bin/env python3
"""
sweep.py — audit a GitHub Projects v2 board for drift.

Reads the project via `gh project item-list` and runs the checks from
references/board-sweep.md:

  1. Metadata completeness — every open item has Priority + any other
     required field (e.g., Work Stream if the project uses it — detected
     by whether any open item on the board has Work Stream set)
  2. WIP cap — In Progress within limit, flag stalled items
  3. Up Next queue — size and pullable-top check
  4. Aging — High-priority Backlog items >14 days old
  5. Blocked hygiene — `blocked` label + `## Blocked by` body section
  6. Legacy priority labels — should be stripped
  7. Plan/spec drift — active plans citing closed issues, plans without issues
  8. Session-note freshness — In Progress items without recent Session notes

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
import subprocess
import sys
from pathlib import Path


# ---------- Config discovery ----------


def parse_config(path: Path) -> tuple[str, str]:
    """Extract (owner, project_number) from a convention doc. Handles user + org URLs."""
    text = path.read_text()
    m = re.search(
        r"https://github\.com/(users|orgs)/([A-Za-z0-9_-]+)/projects/(\d+)", text
    )
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


def run_gh(args: list[str]) -> dict:
    """Run a `gh` command and return parsed JSON stdout. Raises on failure."""
    result = subprocess.run(args, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(f"{' '.join(args)} failed: {result.stderr.strip()}")
    return json.loads(result.stdout) if result.stdout.strip() else {}


def fetch_items(owner: str, project: str) -> list[dict]:
    data = run_gh(
        [
            "gh", "project", "item-list", project,
            "--owner", owner, "--limit", "200", "--format", "json",
        ]
    )
    return data.get("items", [])


def fetch_open_issues_bulk(repo: str) -> list[dict]:
    """One API call to get all open issues with the data we need."""
    result = subprocess.run(
        [
            "gh", "issue", "list", "--repo", repo,
            "--state", "open", "--limit", "500",
            "--json", "number,title,createdAt,updatedAt,labels,body",
        ],
        capture_output=True, text=True, check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"gh issue list failed: {result.stderr}")
    return json.loads(result.stdout)


def fetch_recent_comments(repo: str, number: int, limit: int = 5) -> list[dict]:
    """Get recent comments on an issue (for session-note freshness)."""
    result = subprocess.run(
        [
            "gh", "api", f"repos/{repo}/issues/{number}/comments",
            "--jq", f".[-{limit}:] | .[] | {{body, created_at}}",
        ],
        capture_output=True, text=True, check=False,
    )
    if result.returncode != 0:
        return []
    # jq emits one object per line
    comments = []
    for line in result.stdout.splitlines():
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
        if content.get("state") == "CLOSED":
            continue
        n = content.get("number")
        prio = field(i, "priority")
        ws = field(i, "work Stream", "workStream", "workstream")
        issues = []
        if not prio:
            issues.append("no Priority")
        if work_stream_in_use and not ws:
            issues.append("no Work Stream")
        if issues:
            missing.append(f"#{n}: {', '.join(issues)}")
    return missing


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
        return [f"Up Next has {len(up_next)} items (recommended cap: {limit}) — consider moving lower items back to Backlog"]
    return []


def check_stale_high_backlog(
    items: list[dict], issues_by_number: dict[int, dict], days: int
) -> list[str]:
    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days)
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
            age = (dt.datetime.now(dt.timezone.utc) - created).days
            title = issue["title"][:50]
            stale.append(f"#{n}: {age}d old — {title}")
    return stale


def check_in_progress_staleness(
    items: list[dict], issues_by_number: dict[int, dict], days: int = 7
) -> list[str]:
    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days)
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
            age = (dt.datetime.now(dt.timezone.utc) - updated).days
            title = issue["title"][:50]
            stale.append(f"#{n}: no activity in {age}d — {title}")
    return stale


def check_blocked_hygiene(issues_by_number: dict[int, dict]) -> list[str]:
    findings = []
    for n, issue in issues_by_number.items():
        labels = [l["name"] for l in issue.get("labels", [])]
        if "blocked" in labels:
            body = issue.get("body", "") or ""
            if "## Blocked by" not in body:
                findings.append(f"#{n}: labeled `blocked` but body has no `## Blocked by` section")
    return findings


def check_legacy_priority_labels(issues_by_number: dict[int, dict]) -> list[str]:
    findings = []
    for n, issue in issues_by_number.items():
        labels = [l["name"] for l in issue.get("labels", [])]
        legacy = [l for l in labels if l.startswith("priority:")]
        if legacy:
            findings.append(f"#{n}: legacy labels {legacy} — Priority field is canonical, strip labels")
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
                result = subprocess.run(
                    ["gh", "issue", "view", str(n), "--repo", repo, "--json", "state"],
                    capture_output=True, text=True, check=False,
                )
                if result.returncode == 0:
                    states[n] = json.loads(result.stdout)["state"]
                else:
                    states[n] = "UNKNOWN"

            if all(s == "CLOSED" for s in states.values()):
                findings.append(
                    f"  {p}: all referenced issues closed ({sorted(refs)}) — propose archiving"
                )

    return findings


def check_session_note_freshness(
    items: list[dict], repo: str | None, days: int = 3
) -> list[str]:
    """Look for In Progress issues without a recent Session note comment."""
    if not repo:
        return ["(skipping session-note check — repo not determined)"]
    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days)
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
            c for c in comments
            if re.match(r"^##\s+Session\s+\d{4}-\d{2}-\d{2}", (c.get("body") or "").strip())
        ]
        if not session_notes:
            findings.append(f"#{n}: In Progress with no Session note comment ever")
            continue
        latest = max(
            dt.datetime.fromisoformat(c["created_at"].replace("Z", "+00:00"))
            for c in session_notes
        )
        if latest < cutoff:
            age = (dt.datetime.now(dt.timezone.utc) - latest).days
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
    print(f"  (also tries /orgs/ URL if that's the project's form)")
    print(f"Run at: {dt.datetime.now(dt.timezone.utc).isoformat()}")
    print()

    # Fetch
    try:
        items = fetch_items(owner, project)
    except RuntimeError as e:
        print(f"sweep: {e}", file=sys.stderr)
        return 1

    repo = args.repo or guess_repo_from_items(items)

    issues_by_number = {}
    if repo:
        try:
            for issue in fetch_open_issues_bulk(repo):
                issues_by_number[issue["number"]] = issue
        except RuntimeError as e:
            print(f"sweep: issue fetch failed: {e}", file=sys.stderr)

    total_open = sum(
        1 for i in items if (i.get("content") or {}).get("state") != "CLOSED"
    )
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

    print("== Blocked hygiene ==")
    if not issues_by_number:
        print("  (skipped — no issue data)")
    else:
        for f in check_blocked_hygiene(issues_by_number) or ["None"]:
            print(f"  {f}")
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

    print("== Session-note freshness (In Progress, last 3 days) ==")
    for f in check_session_note_freshness(items, repo) or ["None"]:
        print(f"  {f}")
    print()

    print("Sweep complete. Advisory only — review and propose before applying.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
