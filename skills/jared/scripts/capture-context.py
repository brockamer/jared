#!/usr/bin/env python3
"""
capture-context.py — update an issue's ## Current state / ## Decisions sections.

Preserves all other sections exactly. Idempotent: calling twice with the same
--current-state is a no-op. Decisions are appended with a date header.

Usage:
  capture-context.py --issue 14 --repo owner/repo \
    --current-state "Implemented X. Two of three tests pass. Next: decide Y."

  capture-context.py --issue 14 --repo owner/repo \
    --decision "Chose Redis over Memcached; already running Redis for sessions."

  capture-context.py --issue 14 --repo owner/repo \
    --current-state "..." \
    --decision "..." \
    --decision "..."

  capture-context.py --issue 14 --repo owner/repo --show
    # Print current body sections without modifying

Each invocation prepares a diff and confirms before applying unless --yes.
"""
from __future__ import annotations

import argparse
import datetime as dt
import difflib
import json
import re
import subprocess
import sys


SECTION_ORDER = [
    "Current state",
    "Decisions",
    "Acceptance criteria",
    "Depends on",
    "Blocks",
    "Planning",
]


def fetch_body(repo: str, number: int) -> str:
    result = subprocess.run(
        ["gh", "issue", "view", str(number), "--repo", repo, "--json", "body"],
        capture_output=True, text=True, check=True,
    )
    return json.loads(result.stdout)["body"] or ""


def write_body(repo: str, number: int, body: str) -> None:
    # Use --body-file with stdin via a temp file for safety
    import tempfile, os
    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as f:
        f.write(body)
        path = f.name
    try:
        subprocess.run(
            ["gh", "issue", "edit", str(number), "--repo", repo, "--body-file", path],
            check=True,
        )
    finally:
        os.unlink(path)


# ---------- Body parsing ----------


def split_sections(body: str) -> tuple[str, dict[str, str], list[str]]:
    """
    Return (preamble, sections_by_name, section_order_in_file).

    preamble is text before the first ## heading.
    sections_by_name maps section title (without ##) to full contents INCLUDING trailing blank lines
    section_order_in_file preserves the order headings appeared, useful when no reorder is wanted.
    """
    lines = body.splitlines(keepends=True)
    preamble_lines = []
    sections: dict[str, str] = {}
    order: list[str] = []
    current_name: str | None = None
    current_lines: list[str] = []

    heading_re = re.compile(r"^##\s+(.+?)\s*$")

    for line in lines:
        m = heading_re.match(line)
        if m:
            # Close previous section
            if current_name is not None:
                sections[current_name] = "".join(current_lines)
            else:
                preamble_lines = current_lines
            current_name = m.group(1).strip()
            order.append(current_name)
            current_lines = [line]
        else:
            current_lines.append(line)

    # Close final section
    if current_name is not None:
        sections[current_name] = "".join(current_lines)
    else:
        preamble_lines = current_lines

    preamble = "".join(preamble_lines)
    return preamble, sections, order


def replace_section_body(
    section_text: str, new_body_lines: str
) -> str:
    """Replace everything after the ## heading line with new_body_lines."""
    lines = section_text.splitlines(keepends=True)
    if not lines:
        return section_text
    # lines[0] is the heading
    return lines[0] + new_body_lines


def update_current_state(sections: dict[str, str], text: str) -> None:
    heading = "## Current state\n"
    new_body = f"\n{text.strip()}\n\n"
    if "Current state" in sections:
        sections["Current state"] = replace_section_body(sections["Current state"], new_body)
    else:
        sections["Current state"] = heading + new_body


def append_decision(sections: dict[str, str], text: str) -> None:
    heading = "## Decisions\n"
    today = dt.date.today().isoformat()
    entry = f"\n### {today}\n{text.strip()}\n\n"

    if "Decisions" in sections:
        current = sections["Decisions"]
        # If the section body is just "(none yet)", replace it
        body_without_heading = current.split("\n", 1)[1] if "\n" in current else ""
        if body_without_heading.strip() in ("(none yet)", "(none)", "None", ""):
            sections["Decisions"] = heading + entry
        else:
            # Check idempotency — don't duplicate the exact same entry
            if entry.strip() in current:
                return
            if current.endswith("\n\n"):
                sections["Decisions"] = current + entry.lstrip("\n")
            else:
                sections["Decisions"] = current.rstrip() + "\n" + entry
    else:
        sections["Decisions"] = heading + entry


def reassemble(preamble: str, sections: dict[str, str], original_order: list[str]) -> str:
    """Reassemble the body, using preferred order for known sections but preserving unknowns."""
    out_parts = [preamble.rstrip("\n") + "\n\n" if preamble.strip() else ""]

    placed = set()

    # First, place known sections in preferred order
    for name in SECTION_ORDER:
        if name in sections:
            out_parts.append(sections[name])
            if not sections[name].endswith("\n"):
                out_parts.append("\n")
            placed.add(name)

    # Then place any other sections in their original order (preserves custom user sections)
    for name in original_order:
        if name in placed:
            continue
        if name in sections:
            out_parts.append(sections[name])
            if not sections[name].endswith("\n"):
                out_parts.append("\n")

    result = "".join(out_parts)
    # Trim excessive trailing whitespace
    return result.rstrip() + "\n"


# ---------- Main ----------


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--issue", type=int, required=True)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--current-state", help="Replace ## Current state section body")
    parser.add_argument("--decision", action="append", default=[], help="Append a Decision (can pass multiple)")
    parser.add_argument("--show", action="store_true", help="Print current Current state / Decisions and exit")
    parser.add_argument("--yes", action="store_true", help="Skip confirmation prompt")
    parser.add_argument("--dry-run", action="store_true", help="Show diff without writing")
    args = parser.parse_args()

    body = fetch_body(args.repo, args.issue)
    preamble, sections, order = split_sections(body)

    if args.show:
        print(f"=== Issue #{args.issue} ({args.repo}) ===\n")
        for name in ("Current state", "Decisions"):
            if name in sections:
                print(sections[name])
            else:
                print(f"## {name}\n(not present)\n")
        return 0

    if not args.current_state and not args.decision:
        print("capture-context: nothing to do. Pass --current-state and/or --decision.", file=sys.stderr)
        return 1

    if args.current_state:
        update_current_state(sections, args.current_state)
    for d in args.decision:
        append_decision(sections, d)

    new_body = reassemble(preamble, sections, order)

    if new_body == body:
        print("(no changes — already up to date)")
        return 0

    # Show diff
    diff = "".join(difflib.unified_diff(
        body.splitlines(keepends=True),
        new_body.splitlines(keepends=True),
        fromfile=f"#{args.issue} (current)",
        tofile=f"#{args.issue} (new)",
    ))
    print(diff)

    if args.dry_run:
        print("(dry-run — no changes written)")
        return 0

    if not args.yes:
        ans = input("Apply? [Y/n] ").strip().lower()
        if ans and not ans.startswith("y"):
            print("Aborted.")
            return 1

    write_body(args.repo, args.issue, new_body)
    print(f"Updated #{args.issue}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
