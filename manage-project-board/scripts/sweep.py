#!/usr/bin/env python3
"""
sweep.py — audit a GitHub Projects v2 board for drift.

Reads the project via `gh project item-list`, flags items that need attention
per the checklist in references/board-sweep.md:

  1. Items missing Priority or Work Stream
  2. In Progress > 3
  3. High-priority Backlog items > 14 days old
  4. Deprecated `priority: ...` labels still present (legacy)
  5. Closed issues still showing as non-Done on board (race)
  6. Drift between project-board.md field IDs and actual (manual check)

Usage:
  sweep.py                           # read config from ./docs/project-board.md
  sweep.py --owner X --project N     # explicit

Output: prose summary of findings. Exit 0 regardless of findings.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import subprocess
import sys
from pathlib import Path


def parse_config(path: Path) -> tuple[str, str]:
    """Extract owner + project number from a project-board.md file."""
    text = path.read_text()
    m = re.search(r"https://github\.com/users/([A-Za-z0-9_-]+)/projects/(\d+)", text)
    if not m:
        raise RuntimeError(
            f"{path}: no https://github.com/users/<owner>/projects/<N> URL found"
        )
    return m.group(1), m.group(2)


def find_config() -> Path | None:
    for candidate in ("docs/project-board.md", "PROJECT_BOARD.md", ".github/project-board.md"):
        p = Path(candidate)
        if p.exists():
            return p
    return None


def fetch_items(owner: str, project: str) -> list[dict]:
    result = subprocess.run(
        ["gh", "project", "item-list", project, "--owner", owner, "--limit", "200", "--format", "json"],
        capture_output=True, text=True, check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"gh project item-list failed: {result.stderr}")
    return json.loads(result.stdout).get("items", [])


def fetch_issue_created(repo: str, number: int) -> dt.datetime:
    result = subprocess.run(
        ["gh", "issue", "view", str(number), "--repo", repo, "--json", "createdAt"],
        capture_output=True, text=True, check=False,
    )
    if result.returncode != 0:
        return dt.datetime.now(dt.timezone.utc)
    ts = json.loads(result.stdout).get("createdAt", "")
    return dt.datetime.fromisoformat(ts.replace("Z", "+00:00"))


def check_metadata(items: list[dict]) -> list[str]:
    missing = []
    for i in items:
        content = i.get("content", {}) or {}
        if content.get("state") == "CLOSED":
            continue
        n = content.get("number")
        prio = i.get("priority")
        ws = i.get("work Stream") or i.get("workStream")
        issues = []
        if not prio:
            issues.append("no Priority")
        if not ws:
            issues.append("no Work Stream")
        if issues:
            missing.append(f"#{n}: {', '.join(issues)}")
    return missing


def check_wip(items: list[dict]) -> list[str]:
    in_progress = [i for i in items if i.get("status") == "In Progress"]
    if len(in_progress) > 3:
        rows = [
            f"#{i.get('content', {}).get('number')}: {(i.get('title') or '')[:60]}"
            for i in in_progress
        ]
        return [f"In Progress has {len(in_progress)} items (cap is 3):"] + [f"  {r}" for r in rows]
    if len(in_progress) == 0:
        return ["In Progress is empty — consider pulling top of Up Next"]
    return []


def check_stale_high(items: list[dict], repo: str | None, days: int = 14) -> list[str]:
    if not repo:
        return ["(skipping stale-High check — repo not determined)"]
    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days)
    stale = []
    for i in items:
        content = i.get("content", {}) or {}
        if content.get("state") == "CLOSED":
            continue
        if i.get("status") != "Backlog":
            continue
        if i.get("priority") != "High":
            continue
        n = content.get("number")
        try:
            created = fetch_issue_created(repo, n)
            if created < cutoff:
                age_days = (dt.datetime.now(dt.timezone.utc) - created).days
                title = (i.get("title") or "")[:50]
                stale.append(f"#{n}: {age_days}d old — {title}")
        except Exception as e:
            stale.append(f"#{n}: age check failed ({e})")
    return stale


def check_legacy_priority_labels(repo: str | None) -> list[str]:
    if not repo:
        return []
    result = subprocess.run(
        ["gh", "issue", "list", "--repo", repo, "--label", "priority: high,priority: med,priority: low",
         "--state", "open", "--limit", "100", "--json", "number,title,labels"],
        capture_output=True, text=True, check=False,
    )
    if result.returncode != 0:
        return [f"(legacy label check failed: {result.stderr.strip()})"]
    items = json.loads(result.stdout)
    return [
        f"#{i['number']}: {[l['name'] for l in i['labels'] if l['name'].startswith('priority:')]}"
        for i in items
    ]


def guess_repo_from_items(items: list[dict]) -> str | None:
    for i in items:
        content = i.get("content", {}) or {}
        repo = content.get("repository")
        if repo:
            return repo.replace("https://github.com/", "")
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit a GitHub Projects v2 board for drift.")
    parser.add_argument("--owner", help="Project owner")
    parser.add_argument("--project", help="Project number")
    parser.add_argument("--repo", help="Repo slug for age/label checks (e.g., owner/repo)")
    args = parser.parse_args()

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

    print(f"Sweep for https://github.com/users/{owner}/projects/{project}")
    print(f"Run at: {dt.datetime.now(dt.timezone.utc).isoformat()}")
    print()

    try:
        items = fetch_items(owner, project)
    except RuntimeError as e:
        print(f"sweep: {e}", file=sys.stderr)
        return 1

    repo = args.repo or guess_repo_from_items(items)
    total_open = sum(1 for i in items if (i.get("content") or {}).get("state") != "CLOSED")
    print(f"Open items on board: {total_open}")
    print()

    # 1. Metadata
    missing = check_metadata(items)
    print("== Metadata completeness ==")
    if missing:
        for m in missing:
            print(f"  {m}")
    else:
        print("  All open items have Priority + Work Stream")
    print()

    # 2. WIP
    wip = check_wip(items)
    print("== WIP (In Progress cap = 3) ==")
    for line in wip or ["  Healthy"]:
        print(f"  {line}" if not line.startswith(" ") else line)
    print()

    # 3. Stale High in Backlog
    print("== Stale High-priority Backlog (>14d) ==")
    stale = check_stale_high(items, repo)
    for s in stale or ["  None"]:
        print(f"  {s}" if not s.startswith("(") else s)
    print()

    # 4. Legacy priority labels
    print("== Legacy 'priority: *' labels ==")
    legacy = check_legacy_priority_labels(repo)
    for ll in legacy or ["  None"]:
        print(f"  {ll}")
    print()

    print("Sweep complete. Advisory only — review and propose actions before applying.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
