#!/usr/bin/env python3
"""
bootstrap-project.py — pair Jared with a GitHub Projects v2 board.

Introspects a board via `gh project view` and `gh project field-list`, then
emits a filled-in convention doc at docs/project-board.md (or a user-specified
path). Offers to create any missing standard fields (Status / Priority /
Work Stream) interactively.

Usage:
  bootstrap-project.py --url https://github.com/users/brockamer/projects/1 --repo brockamer/findajob
  bootstrap-project.py --url <url> --repo <repo> --output docs/project-board.md
  bootstrap-project.py --url <url> --repo <repo> --no-create  # don't offer to create missing fields

The output file will not be overwritten if it already exists unless --force is
passed; instead, the script writes to <output>.new and shows a diff.
"""
from __future__ import annotations

import argparse
import datetime as dt
import difflib
import json
import re
import subprocess
import sys
from pathlib import Path


STANDARD_FIELDS = {
    "Status": ["Backlog", "Up Next", "In Progress", "Done"],
    "Priority": ["High", "Medium", "Low"],
    "Work Stream": [],  # User-defined
}


# ---------- gh helpers ----------


def run_gh(args: list[str]) -> dict | list:
    """Run a gh command and return parsed JSON."""
    result = subprocess.run(args, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(f"{' '.join(args)} failed: {result.stderr.strip()}")
    return json.loads(result.stdout) if result.stdout.strip() else {}


def parse_url(url: str) -> tuple[str, str, str]:
    """Return (owner_type, owner, project_number) from a projects v2 URL."""
    m = re.match(
        r"https://github\.com/(users|orgs)/([A-Za-z0-9_-]+)/projects/(\d+)/?", url
    )
    if not m:
        raise RuntimeError(f"URL must be like https://github.com/(users|orgs)/<n>/projects/<N>: got {url}")
    return m.group(1), m.group(2), m.group(3)


# ---------- Introspection ----------


def fetch_project(owner: str, number: str) -> dict:
    return run_gh(["gh", "project", "view", number, "--owner", owner, "--format", "json"])


def fetch_fields(owner: str, number: str) -> list[dict]:
    data = run_gh(["gh", "project", "field-list", number, "--owner", owner, "--format", "json"])
    return data.get("fields", [])


def find_single_select_field(fields: list[dict], name: str) -> dict | None:
    """Case-insensitive, space-insensitive match on field name."""
    target = name.lower().replace(" ", "")
    for f in fields:
        fname = f.get("name", "").lower().replace(" ", "")
        if fname == target and f.get("type") == "ProjectV2SingleSelectField":
            return f
    return None


# ---------- Field creation ----------


def prompt_yes_no(question: str, default: bool = True) -> bool:
    suffix = " [Y/n] " if default else " [y/N] "
    ans = input(question + suffix).strip().lower()
    if not ans:
        return default
    return ans.startswith("y")


def prompt_work_streams() -> list[str]:
    print()
    print("The Work Stream field has no standard options — you define them per project.")
    print("Examples:")
    print("  - Software project: Backend, Frontend, Infrastructure")
    print("  - findajob-style: Job Search, Generalization, Infrastructure")
    print("  - House renovation: Demo, Rough-in, Finish")
    print()
    raw = input("Enter work streams as a comma-separated list: ").strip()
    streams = [s.strip() for s in raw.split(",") if s.strip()]
    if not streams:
        print("  (No work streams entered — you can add them later.)")
    return streams


def create_single_select_field(
    project_id: str, name: str, options: list[str]
) -> dict:
    """
    Create a single-select field with the given options via GraphQL.
    Returns the created field's details.
    """
    if not options:
        raise RuntimeError(f"Can't create {name!r} field with zero options")

    options_arg = json.dumps([{"name": o, "color": "GRAY", "description": ""} for o in options])

    query = """
    mutation($projectId: ID!, $name: String!, $options: [ProjectV2SingleSelectFieldOptionInput!]!) {
      createProjectV2Field(input: {
        projectId: $projectId,
        dataType: SINGLE_SELECT,
        name: $name,
        singleSelectOptions: $options
      }) {
        projectV2Field {
          ... on ProjectV2SingleSelectField {
            id
            name
            options { id name }
          }
        }
      }
    }
    """
    result = run_gh([
        "gh", "api", "graphql",
        "-f", f"query={query}",
        "-F", f"projectId={project_id}",
        "-F", f"name={name}",
        "-F", f"options={options_arg}",
    ])
    field = (
        result.get("data", {})
        .get("createProjectV2Field", {})
        .get("projectV2Field", {})
    )
    if not field:
        raise RuntimeError(f"Field creation for {name!r} returned no data: {result}")
    return field


# ---------- Doc generation ----------


TEMPLATE = """\
# Project Board — How It Works

The GitHub Projects v2 board at [{project_title}]({project_url}) is the **single source of truth for what is being worked on and why**. No markdown tracking files, no separate backlog lists, no TODO.md. If it isn't on the board, it isn't on the roadmap.

This document describes the conventions so anyone (human or Claude session) can triage, prioritize, and move work consistently.

**Bootstrapped by Jared on {bootstrap_date}.** If you rename fields or add options, re-run `scripts/bootstrap-project.py --url {project_url} --repo {repo}` or edit this file directly.

## Columns (Status field)

{status_columns_table}

**Rules:**

- In Progress stays small. More than ~{wip_limit} items means focus is scattered.
- Up Next is ordered — top item is what gets worked next. Priority field breaks ties.
- Nothing in In Progress without Priority and Work Stream set.
- When an issue closes, it moves to Done automatically.

## Priority field

{priority_table}

**Rules:**

- Every open issue must have a Priority set.
- High is scarce by design — if everything is High, nothing is.
- Two High items in In Progress at once should be rare and deliberate.

## Work Stream field

{work_stream_table}

**Rules:**

- Work streams are project-specific and describe the kind of work, not its priority or status.
- Every open issue should belong to exactly one work stream.

## Labels

Labels describe **what kind of issue it is**, not where it lives on the board. Status and priority come from board fields, not labels.

Suggested defaults (create via `gh label create` as needed):

| Label | Meaning |
|---|---|
| `bug` | Something isn't working |
| `enhancement` | New capability |
| `refactor` | Restructuring without behavior change |
| `documentation` | Docs-only change |
| `blocked` | Waiting on a dependency (must pair with `## Blocked by` in body) |

Project-specific scope labels (e.g., `infra`, `frontend`, `customer-facing`) belong here too — add them as needed.

## Triage checklist — new issue

When a new issue is filed:

1. **Auto-add to board.** `gh issue create` does not auto-add; use `gh project item-add {project_number} --owner {owner} --url <issue-url>`.
2. **Set Priority** — High / Medium / Low.
3. **Set Work Stream** — per the fields above.
4. **Leave Status as Backlog** unless explicitly scheduling.
5. **Apply labels** for issue type and scope.

An issue without Priority and Work Stream sorts to the bottom and disappears.

## Fields quick reference (for gh project CLI)

```
Project ID:          {project_id}

Status field ID:     {status_field_id}
{status_options_block}
Priority field ID:   {priority_field_id}
{priority_options_block}
Work Stream ID:      {work_stream_field_id}
{work_stream_options_block}```

## Example — move an item to Up Next

```bash
gh project item-edit \\
  --project-id {project_id} \\
  --id <ITEM_ID> \\
  --field-id {status_field_id} \\
  --single-select-option-id {up_next_option_id}
```

## Further conventions

This file is the minimum. See the skill's references for:

- `references/human-readable-board.md` — title/body templates
- `references/board-sweep.md` — grooming checklist
- `references/plan-spec-integration.md` — if this project uses plan/spec artifacts
- `references/session-continuity.md` — Session note format
"""


def options_block(field: dict | None) -> str:
    if not field:
        return "  (field not present)\n"
    lines = []
    for opt in field.get("options", []):
        lines.append(f"  {opt['name']}: {' ' * max(0, 20 - len(opt['name']))}{opt['id']}")
    return "\n".join(lines) + "\n"


def status_table(field: dict | None) -> str:
    if not field:
        return "_(Status field not present — see bootstrap output.)_"
    rows = ["| Column | Meaning |", "|---|---|"]
    default_meanings = {
        "Backlog": "Captured but not yet scheduled.",
        "Up Next": "Scheduled to be picked up next. The on-deck queue.",
        "In Progress": "Actively being worked on right now.",
        "Done": "Closed issues. Auto-populated when an issue closes.",
    }
    for opt in field.get("options", []):
        meaning = default_meanings.get(opt["name"], "(describe)")
        rows.append(f"| **{opt['name']}** | {meaning} |")
    return "\n".join(rows)


def priority_table(field: dict | None) -> str:
    if not field:
        return "_(Priority field not present.)_"
    rows = ["| Value | Meaning |", "|---|---|"]
    default_meanings = {
        "High": "Directly advances the current strategic goal. Addressed before Medium.",
        "Medium": "Quality, efficiency, or reliability improvement. Important but not urgent.",
        "Low": "Nice-to-have, future-facing, or optional. Safe to defer indefinitely.",
    }
    for opt in field.get("options", []):
        meaning = default_meanings.get(opt["name"], "(describe)")
        rows.append(f"| **{opt['name']}** | {meaning} |")
    return "\n".join(rows)


def work_stream_table(field: dict | None) -> str:
    if not field or not field.get("options"):
        return (
            "_(Work Stream field has no options defined yet. Add options describing "
            "the kinds of work this project tracks — e.g., 'Backend', 'Frontend', "
            "'Infrastructure'.)_"
        )
    rows = ["| Stream | Scope |", "|---|---|"]
    for opt in field["options"]:
        rows.append(f"| **{opt['name']}** | (describe scope) |")
    return "\n".join(rows)


def option_id(field: dict | None, name: str) -> str:
    if not field:
        return "<unset>"
    for opt in field.get("options", []):
        if opt["name"].lower() == name.lower():
            return opt["id"]
    return "<unset>"


# ---------- Main ----------


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--url", required=True, help="GitHub Project v2 URL")
    parser.add_argument("--repo", required=True, help="Repo slug (owner/repo) this board is paired with")
    parser.add_argument("--output", default="docs/project-board.md", help="Output path (default: docs/project-board.md)")
    parser.add_argument("--wip-limit", type=int, default=3)
    parser.add_argument("--no-create", action="store_true", help="Don't offer to create missing fields")
    parser.add_argument("--force", action="store_true", help="Overwrite existing output file")
    parser.add_argument("--non-interactive", action="store_true", help="Skip prompts (for automation)")
    args = parser.parse_args()

    try:
        owner_type, owner, number = parse_url(args.url)
    except RuntimeError as e:
        print(f"bootstrap: {e}", file=sys.stderr)
        return 1

    print(f"Introspecting {args.url}...")
    try:
        project = fetch_project(owner, number)
        fields = fetch_fields(owner, number)
    except RuntimeError as e:
        print(f"bootstrap: {e}", file=sys.stderr)
        return 1

    project_id = project.get("id")
    project_title = project.get("title", f"Project {number}")
    print(f"  Project: {project_title}")
    print(f"  Fields found: {', '.join(f['name'] for f in fields)}")

    # Identify or create standard fields
    status = find_single_select_field(fields, "Status")
    priority = find_single_select_field(fields, "Priority")
    work_stream = find_single_select_field(fields, "Work Stream")

    missing = []
    if not status:
        missing.append(("Status", STANDARD_FIELDS["Status"]))
    if not priority:
        missing.append(("Priority", STANDARD_FIELDS["Priority"]))
    if not work_stream:
        missing.append(("Work Stream", None))  # Prompt for options

    if missing and not args.no_create and not args.non_interactive:
        print()
        print(f"Missing standard fields: {[m[0] for m in missing]}")
        if prompt_yes_no("Create them now?", default=True):
            for name, options in missing:
                if options is None:
                    options = prompt_work_streams()
                if not options:
                    print(f"  Skipping {name} — no options provided")
                    continue
                print(f"  Creating {name} with options {options}...")
                try:
                    created = create_single_select_field(project_id, name, options)
                    print(f"    Created: {created['id']}")
                    # Re-fetch fields so the new ones show up
                    fields = fetch_fields(owner, number)
                    status = find_single_select_field(fields, "Status") or status
                    priority = find_single_select_field(fields, "Priority") or priority
                    work_stream = find_single_select_field(fields, "Work Stream") or work_stream
                except RuntimeError as e:
                    print(f"    Failed: {e}")
    elif missing:
        print(f"  Note: {[m[0] for m in missing]} missing — skipped creation.")

    # Generate convention doc
    content = TEMPLATE.format(
        project_title=project_title,
        project_url=args.url,
        project_number=number,
        project_id=project_id,
        owner=owner,
        repo=args.repo,
        bootstrap_date=dt.date.today().isoformat(),
        wip_limit=args.wip_limit,
        status_columns_table=status_table(status),
        priority_table=priority_table(priority),
        work_stream_table=work_stream_table(work_stream),
        status_field_id=status.get("id", "<unset>") if status else "<unset>",
        priority_field_id=priority.get("id", "<unset>") if priority else "<unset>",
        work_stream_field_id=work_stream.get("id", "<unset>") if work_stream else "<unset>",
        status_options_block=options_block(status),
        priority_options_block=options_block(priority),
        work_stream_options_block=options_block(work_stream),
        up_next_option_id=option_id(status, "Up Next"),
    )

    # Write
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)

    if output.exists() and not args.force:
        existing = output.read_text()
        if existing == content:
            print(f"\n{output}: already up to date.")
            return 0
        # Show diff
        print(f"\n{output} already exists. Diff (existing → new):\n")
        for line in difflib.unified_diff(
            existing.splitlines(keepends=True),
            content.splitlines(keepends=True),
            fromfile=f"{output} (existing)",
            tofile=f"{output} (new)",
        ):
            sys.stdout.write(line)
        new_path = output.with_suffix(output.suffix + ".new")
        new_path.write_text(content)
        print(f"\nNew content written to {new_path}")
        print(f"Review, then: mv {new_path} {output}   (or re-run with --force)")
        return 0

    output.write_text(content)
    print(f"\nWrote {output}")
    print()
    print("Next steps:")
    print(f"  1. Review {output} and fill in work-stream scope descriptions if needed.")
    print(f"  2. Run `scripts/sweep.py` to see any existing drift.")
    print(f"  3. If this project uses plan/spec artifacts, see references/plan-spec-integration.md.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
