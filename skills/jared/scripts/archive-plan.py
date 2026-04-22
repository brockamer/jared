#!/usr/bin/env python3
"""
archive-plan.py — archive a plan/spec whose issues have shipped.

Two modes:

  1. Single-file:
       archive-plan.py --plan docs/superpowers/plans/2026-04-17-feature.md --repo owner/repo
     Checks referenced issues, moves to archived/YYYY-MM/, prepends a header.

  2. Scan:
       archive-plan.py --scan --repo owner/repo --dry-run
       archive-plan.py --scan --repo owner/repo
     Scans docs/superpowers/plans/ and docs/superpowers/specs/ for plans whose
     referenced issues are all closed; proposes or applies archival.

By default, prompts before applying. Pass --yes to skip prompts.

Also updates the issue's ## Planning section to point at the archived path.
"""

from __future__ import annotations

import argparse
import datetime as dt
import re
import sys
import tempfile
from pathlib import Path

# Make sibling lib/ importable regardless of cwd — same pattern as the jared CLI.
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

DEFAULT_PLAN_DIRS = [
    Path("docs/superpowers/plans"),
    Path("docs/superpowers/specs"),
]


# ---------- gh helpers ----------


def issue_state(repo: str, number: int) -> tuple[str, str | None]:
    """Return (state, closed_at) for an issue."""
    try:
        data = board_run_gh(
            ["issue", "view", str(number), "--repo", repo, "--json", "state,closedAt"]
        )
        return data.get("state", "UNKNOWN"), data.get("closedAt")
    except GhInvocationError:
        return "UNKNOWN", None


def fetch_issue_body(repo: str, number: int) -> str:
    data = board_run_gh(["issue", "view", str(number), "--repo", repo, "--json", "body"])
    return data.get("body") or ""


def write_issue_body(repo: str, number: int, body: str) -> None:
    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as f:
        f.write(body)
        path = f.name
    try:
        board_run_gh_raw(["issue", "edit", str(number), "--repo", repo, "--body-file", path])
    finally:
        Path(path).unlink(missing_ok=True)


# ---------- Plan parsing ----------


def parse_referenced_issues(plan_text: str) -> list[int]:
    """Extract issue numbers from ## Issue / ## Issues / ## Issue(s) section."""
    m = re.search(
        r"^#{1,3}\s+Issue[s()]*\s*$([\s\S]+?)(?=^#{1,3}\s|\Z)",
        plan_text,
        re.MULTILINE,
    )
    if not m:
        return []
    return [int(n) for n in re.findall(r"#(\d+)", m.group(1))]


def already_archived(path: Path) -> bool:
    return "archived" in path.parts


def archival_header(issues: list[int], ship_date: str) -> str:
    issue_refs = ", ".join(f"#{n}" for n in sorted(issues))
    return (
        f"---\n"
        f"**Shipped in {issue_refs} on {ship_date}. Final decisions captured in issue body.**\n"
        f"---\n\n"
    )


# ---------- Archival operation ----------


def archive_one(
    plan_path: Path,
    repo: str,
    dry_run: bool = False,
    yes: bool = False,
    update_issues: bool = True,
) -> str | None:
    """Archive a single plan file. Returns the archived path or None."""
    text = plan_path.read_text()
    refs = parse_referenced_issues(text)
    if not refs:
        return f"{plan_path}: no ## Issue section; skipping"

    # Check all referenced issue states
    states = {n: issue_state(repo, n) for n in refs}
    if not all(s[0] == "CLOSED" for s in states.values()):
        open_ones = [n for n, (s, _) in states.items() if s != "CLOSED"]
        return f"{plan_path}: not all issues closed (open: {open_ones}); skipping"

    # Determine ship date from latest closedAt
    closed_dates = [s[1] for s in states.values() if s[1]]
    if closed_dates:
        latest = max(closed_dates)
        ship_date = latest[:10]  # YYYY-MM-DD
        year_month = latest[:7]  # YYYY-MM
    else:
        today = dt.date.today().isoformat()
        ship_date = today
        year_month = today[:7]

    # Compute archive destination
    # If plan is in docs/superpowers/plans/foo.md, archived goes to
    # docs/superpowers/plans/archived/YYYY-MM/foo.md
    parent = plan_path.parent
    archive_dir = parent / "archived" / year_month
    dest = archive_dir / plan_path.name

    # Prepare new content with header
    if text.startswith("---\n**Shipped in"):
        return f"{plan_path}: already has archival header; skipping"
    new_content = archival_header(refs, ship_date) + text

    # Show what will happen
    print(f"\n=== {plan_path} ===")
    print(f"  Referenced issues: {sorted(refs)} (all closed)")
    print(f"  Ship date: {ship_date}")
    print(f"  Destination: {dest}")

    if dry_run:
        print("  (dry-run — no changes)")
        return str(dest)

    if not yes:
        ans = input("  Archive this plan? [Y/n] ").strip().lower()
        if ans and not ans.startswith("y"):
            print("  Skipped.")
            return None

    # Apply: create dir, write content to new location, remove original
    archive_dir.mkdir(parents=True, exist_ok=True)
    dest.write_text(new_content)
    plan_path.unlink()
    print(f"  Archived -> {dest}")

    # Update each issue's ## Planning section
    if update_issues:
        for n in refs:
            try:
                update_planning_section(repo, n, plan_path, dest)
                print(f"  Updated #{n} ## Planning section")
            except Exception as e:
                print(f"  Warning: couldn't update #{n} Planning section: {e}")

    return str(dest)


def update_planning_section(repo: str, number: int, old_path: Path, new_path: Path) -> None:
    """Update the issue's ## Planning section to point at the archived path."""
    body = fetch_issue_body(repo, number)
    # Replace old path references with new path
    old = str(old_path)
    new = str(new_path)
    # Try both possible formats: bare path, markdown link
    if old in body:
        new_body = body.replace(old, new)
        if new_body != body:
            write_issue_body(repo, number, new_body)
            return
    # If not found, add a note to Planning section
    # (Plan reference wasn't there; not strictly an error, but worth noting)


def scan_and_archive(
    plan_dirs: list[Path],
    repo: str,
    dry_run: bool = False,
    yes: bool = False,
) -> None:
    """Walk plan_dirs, archive anything shippable."""
    for base in plan_dirs:
        if not base.exists():
            continue
        for p in base.rglob("*.md"):
            if already_archived(p):
                continue
            if p.name.startswith("README") or p.name.startswith("_"):
                continue
            result = archive_one(p, repo, dry_run=dry_run, yes=yes)
            if isinstance(result, str) and "skipping" in result:
                print(result)


# ---------- Main ----------


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--plan", help="Single plan file to archive")
    parser.add_argument(
        "--scan",
        action="store_true",
        help="Scan plan/spec dirs and archive shippable ones",
    )
    parser.add_argument("--repo", required=True, help="Repo slug (owner/repo)")
    parser.add_argument(
        "--plan-dir",
        action="append",
        help="Plan dir to scan (can pass multiple). Default: docs/superpowers/plans + specs",
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--yes", action="store_true", help="Skip confirmation prompts")
    args = parser.parse_args()

    if not args.plan and not args.scan:
        print("archive-plan: pass --plan <path> or --scan", file=sys.stderr)
        return 1

    if args.plan:
        archive_one(Path(args.plan), args.repo, dry_run=args.dry_run, yes=args.yes)

    if args.scan:
        plan_dirs = [Path(p) for p in (args.plan_dir or [])] or DEFAULT_PLAN_DIRS
        scan_and_archive(plan_dirs, args.repo, dry_run=args.dry_run, yes=args.yes)

    return 0


if __name__ == "__main__":
    sys.exit(main())
