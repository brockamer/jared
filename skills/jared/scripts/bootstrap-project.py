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
import sys
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
    run_graphql as board_run_graphql,
)

STANDARD_FIELDS = {
    "Status": ["Backlog", "Up Next", "In Progress", "Blocked", "Done"],
    "Priority": ["High", "Medium", "Low"],
    "Work Stream": [],  # User-defined
}


# ---------- gh helpers ----------


def parse_url(url: str) -> tuple[str, str, str]:
    """Return (owner_type, owner, project_number) from a projects v2 URL."""
    m = re.match(r"https://github\.com/(users|orgs)/([A-Za-z0-9_-]+)/projects/(\d+)/?", url)
    if not m:
        raise RuntimeError(
            f"URL must be like https://github.com/(users|orgs)/<n>/projects/<N>: got {url}"
        )
    return m.group(1), m.group(2), m.group(3)


# ---------- Introspection ----------


def fetch_project(owner: str, number: str) -> dict:
    return board_run_gh(["project", "view", number, "--owner", owner, "--format", "json"])


def fetch_fields(owner: str, number: str) -> list[dict]:
    data = board_run_gh(["project", "field-list", number, "--owner", owner, "--format", "json"])
    return data.get("fields", [])


def fetch_workflows(owner_type: str, owner: str, number: str) -> list[dict]:
    """Return [{name, enabled, number}, ...] for the project's built-in workflows.

    Returns an empty list (not an error) if the response shape is unexpected
    — workflow queries are part of GitHub's evolving Projects v2 API surface,
    and we'd rather degrade to "can't detect" than halt bootstrap. The caller
    warns when `Item closed` is present-but-disabled; it skips the warning
    silently when we can't query at all.
    """
    root = "organization" if owner_type == "orgs" else "user"
    query = (
        "query($owner: String!, $number: Int!) {"
        f"  {root}(login: $owner) {{"
        "    projectV2(number: $number) {"
        "      workflows(first: 30) {"
        "        nodes { name enabled number }"
        "      }"
        "    }"
        "  }"
        "}"
    )
    try:
        data = board_run_graphql(query, owner=owner, number=int(number))
    except GhInvocationError:
        return []
    try:
        nodes = data["data"][root]["projectV2"]["workflows"]["nodes"]
    except (KeyError, TypeError):
        return []
    return nodes if isinstance(nodes, list) else []


def link_project_to_repo(project_id: str, repo_slug: str) -> tuple[bool, str]:
    """Link a ProjectV2 to a repository so it appears under <repo> → Projects tab.

    GitHub's `linkProjectV2ToRepository` mutation is idempotent — re-running
    against an already-linked pair returns the same node and no error. Per
    #25, callers should always attempt the link when both IDs are in scope
    and treat failures as warnings (permissions, transient network), not
    aborts.

    Returns (ok, message). ok=True on successful link (including no-op
    re-link). ok=False with a diagnostic when the repo can't be resolved or
    the mutation errors.
    """
    if "/" not in repo_slug:
        return False, f"invalid repo slug (expected owner/repo): {repo_slug}"
    owner, name = repo_slug.split("/", 1)

    try:
        repo_data = board_run_graphql(
            "query($owner: String!, $name: String!) {"
            " repository(owner: $owner, name: $name) { id }"
            " }",
            owner=owner,
            name=name,
        )
    except GhInvocationError as e:
        return False, f"could not resolve repo id for {repo_slug}: {e}"

    repo_node = ((repo_data or {}).get("data") or {}).get("repository")
    repo_id = (repo_node or {}).get("id")
    if not isinstance(repo_id, str):
        return False, f"repo id not found for {repo_slug}"

    mutation = (
        "mutation($projectId: ID!, $repositoryId: ID!) {"
        " linkProjectV2ToRepository("
        " input: {projectId: $projectId, repositoryId: $repositoryId}"
        " ) { repository { id } }"
        " }"
    )
    try:
        board_run_graphql(mutation, projectId=project_id, repositoryId=repo_id)
    except GhInvocationError as e:
        return False, str(e)

    return True, f"linked project to {repo_slug}"


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


def create_single_select_field(project_id: str, name: str, options: list[str]) -> dict:
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
    # Use board_run_gh directly (not board_run_graphql) because the options
    # variable is a JSON-typed list — it must go through `-F` so gh parses it
    # as a structured value. board_run_graphql's simple kwargs flag-picker
    # sends non-primitive strings through `-f`, which would pass it as a raw
    # string literal and fail the GraphQL type check.
    result = board_run_gh(
        [
            "api",
            "graphql",
            "-f",
            f"query={query}",
            "-F",
            f"projectId={project_id}",
            "-F",
            f"name={name}",
            "-F",
            f"options={options_arg}",
        ]
    )
    field = result.get("data", {}).get("createProjectV2Field", {}).get("projectV2Field", {})
    if not field:
        raise RuntimeError(f"Field creation for {name!r} returned no data: {result}")
    return field


# ---------- Doc generation ----------


TEMPLATE = """\
# Project Board — How It Works

<!-- Machine-readable metadata — jared scripts parse this. Do not reorder or
     rename the fields below. The narrative docs after the field blocks are
     for humans; jared ignores them. Re-run bootstrap-project.py after any
     schema change to keep this file in sync. -->

- Project URL: {project_url}
- Project number: {project_number}
- Project ID: {project_id}
- Owner: {owner}
- Repo: {repo}

### Status
- Field ID: {status_field_id}
{status_options_kv}

### Priority
- Field ID: {priority_field_id}
{priority_options_kv}

### Work Stream
- Field ID: {work_stream_field_id}
{work_stream_options_kv}

<!-- End machine-readable block — narrative docs follow. -->

The GitHub Projects v2 board at [{project_title}]({project_url}) is the **single source of
truth for what is being worked on and why**. No markdown tracking files, no separate
backlog lists, no TODO.md. If it isn't on the board, it isn't on the roadmap.

This document describes the conventions so anyone (human or Claude session) can triage,
prioritize, and move work consistently.

**Bootstrapped by Jared on {bootstrap_date}.** If you rename fields or add options,
re-run `scripts/bootstrap-project.py --url {project_url} --repo {repo}` or edit this
file directly.

## Columns (Status field)

{status_columns_table}

**Rules:**

- In Progress stays small. More than ~{wip_limit} items means focus is scattered.
- Up Next is ordered — top item is what gets worked next. Priority field breaks ties.
- {in_progress_rule}
- When an issue closes, it moves to Done automatically.

## Priority field

{priority_table}

**Rules:**

- Every open issue must have a Priority set.
- High is scarce by design — if everything is High, nothing is.
- Two High items in In Progress at once should be rare and deliberate.

## Work Stream field

{work_stream_section}

## Labels

Labels describe **what kind of issue it is**, not where it lives on the board. Status
and priority come from board fields, not labels.

Suggested defaults (create via `gh label create` as needed):

| Label | Meaning |
|---|---|
| `bug` | Something isn't working |
| `enhancement` | New capability |
| `refactor` | Restructuring without behavior change |
| `documentation` | Docs-only change |

**Do not** create a `blocked` label. Blocked is a Status column on this
board, not a label — see Status above.

Project-specific scope labels (e.g., `infra`, `frontend`, `customer-facing`) belong here
too — add them as needed.

## Triage checklist — new issue

When a new issue is filed:

{triage_checklist}

{triage_disappears}

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


# ---------- Legacy-doc detection and patching ----------
#
# Some projects (e.g. findajob) have a `docs/project-board.md` that predates
# the machine-readable bullet block: the URL lives in a markdown link, the
# Project ID is buried in a code fence, and the other three fields aren't
# written down at all. `lib/board.py` tolerates that shape at parse-time via
# fallbacks (see #9), but we still want the convention doc itself to be
# canonicalized when the user opts in. Instead of rewriting the whole doc
# (which destroys custom prose), we detect the missing bullets and offer a
# minimal patch that inserts the bullet block near the top, preserving the
# rest verbatim.


HEADER_BULLETS = ["Project URL", "Project number", "Project ID", "Owner", "Repo"]


def detect_missing_header_bullets(text: str) -> list[str]:
    """Return the bullet-field names that aren't present as `- <field>: <val>` lines.

    A bullet is "present" only when it appears as a list item with a non-empty
    value — e.g., `- Project URL: https://github.com/users/.../projects/1`.
    Code-fence occurrences (`Project ID:          PVT_...`) don't count
    because the jared CLI's parser only consults the bullet form; the fallback
    from #9 handles inference from prose but doesn't make the convention doc
    canonical. Returned list preserves HEADER_BULLETS' order.
    """
    missing: list[str] = []
    for field_name in HEADER_BULLETS:
        pattern = rf"^\s*-\s*{re.escape(field_name)}:\s*\S+"
        if not re.search(pattern, text, flags=re.MULTILINE):
            missing.append(field_name)
    return missing


def render_header_block(
    *, project_url: str, project_number: int, project_id: str, owner: str, repo: str
) -> str:
    """Render the five machine-readable bullets exactly as the full template emits."""
    return (
        f"- Project URL: {project_url}\n"
        f"- Project number: {project_number}\n"
        f"- Project ID: {project_id}\n"
        f"- Owner: {owner}\n"
        f"- Repo: {repo}\n"
    )


def find_header_insertion_point(text: str) -> int:
    """Return a char offset where the header bullet block should land.

    Heuristic: just after the first H1 heading (and a trailing blank line if
    present). No H1? Insert at the top. This keeps the block near the file's
    start — where the jared parser's regex scans hit it first — without
    displacing a document's leading title or intro paragraph.
    """
    m = re.search(r"^#[^\n]*\n", text, flags=re.MULTILINE)
    if m is None:
        return 0
    end = m.end()
    # If the line after the H1 is blank, skip past it so we don't produce
    # `# Title\n- Project URL: ...`.
    if end < len(text) and text[end] == "\n":
        end += 1
    return end


def patch_legacy_doc(existing: str, header_block: str) -> str:
    """Insert `header_block` into `existing` at the computed insertion point.

    The inserted content is bracketed by blank lines so the bullets never
    butt up against surrounding prose or headings. All original prose,
    headings, code fences, and links are preserved verbatim.
    """
    pos = find_header_insertion_point(existing)
    before = existing[:pos]
    after = existing[pos:]
    # Trailing blank line ensures separation from whatever prose follows.
    separator = "" if after.startswith("\n") else "\n"
    return f"{before}{header_block}{separator}{after}"


# ---------- Full-doc template rendering ----------


def options_block(field: dict | None) -> str:
    if not field:
        return "  (field not present)\n"
    lines = []
    for opt in field.get("options", []):
        lines.append(f"  {opt['name']}: {' ' * max(0, 20 - len(opt['name']))}{opt['id']}")
    return "\n".join(lines) + "\n"


def options_kv_block(field: dict | None) -> str:
    """Render a field's options as `- <name>: <id>` lines, one per option.

    This is the machine-readable form Board._parse_field_blocks consumes:
    any line matching ``- <name>: <non-whitespace-token>`` inside a
    ``### FieldName`` section becomes a (name → option_id) entry.
    """
    if not field:
        return "- (field not present)"
    lines = [f"- {opt['name']}: {opt['id']}" for opt in field.get("options", [])]
    return "\n".join(lines) if lines else "- (no options defined)"


def status_table(field: dict | None) -> str:
    if not field:
        return "_(Status field not present — see bootstrap output.)_"
    rows = ["| Column | Meaning |", "|---|---|"]
    default_meanings = {
        "Backlog": "Captured but not yet scheduled.",
        "Up Next": "Scheduled to be picked up next. The on-deck queue.",
        "In Progress": "Actively being worked on right now.",
        "Blocked": (
            "Waiting on a dependency. Pair with a `## Blocked by` section "
            "in the issue body, or use `jared blocked-by` to record a native "
            "GitHub issue dependency."
        ),
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


def work_stream_section(field: dict | None) -> str:
    """Render the body of the `## Work Stream field` section.

    When no Work Stream field exists on the board, jared treats the concept as
    unused: the section survives as a marker (to flag projects that later want
    to add one) but carries no rules or table.
    """
    if field is None:
        return "_Not used on this project._"
    return (
        f"{work_stream_table(field)}\n"
        "\n"
        "**Rules:**\n"
        "\n"
        "- Work streams are project-specific and describe the kind of work, "
        "not its priority or status.\n"
        "- Every open issue should belong to exactly one work stream."
    )


def in_progress_rule(has_work_stream: bool) -> str:
    """The In Progress rule bullet. Drops Work Stream when the field is absent."""
    if has_work_stream:
        return "Nothing in In Progress without Priority and Work Stream set."
    return "Nothing in In Progress without Priority set."


def triage_checklist(has_work_stream: bool, project_number: str, owner: str) -> str:
    """Numbered triage checklist. Drops step 3 (Set Work Stream) when absent."""
    steps = [
        (
            "**Auto-add to board.** `gh issue create` does not auto-add; use\n"
            f"   `gh project item-add {project_number} --owner {owner} --url <issue-url>`."
        ),
        "**Set Priority** — High / Medium / Low.",
    ]
    if has_work_stream:
        steps.append("**Set Work Stream** — per the fields above.")
    steps.extend(
        [
            "**Leave Status as Backlog** unless explicitly scheduling.",
            "**Apply labels** for issue type and scope.",
        ]
    )
    return "\n".join(f"{i}. {step}" for i, step in enumerate(steps, 1))


def triage_disappears(has_work_stream: bool) -> str:
    """Final footer line of the triage section. Drops Work Stream when absent."""
    required = "Priority and Work Stream" if has_work_stream else "Priority"
    return f"An issue without {required} sorts to the bottom and disappears."


def option_id(field: dict | None, name: str) -> str:
    if not field:
        return "<unset>"
    for opt in field.get("options", []):
        if opt["name"].lower() == name.lower():
            return opt["id"]
    return "<unset>"


def render_doc(
    *,
    project_title: str,
    project_url: str,
    project_number: str,
    project_id: str,
    owner: str,
    repo: str,
    bootstrap_date: str,
    wip_limit: int,
    status: dict | None,
    priority: dict | None,
    work_stream: dict | None,
) -> str:
    """Render the full project-board.md convention doc from introspected fields.

    Factored out of `main` so tests can exercise conditional rendering
    (Work Stream present vs. absent, Blocked column description, etc.)
    without stubbing `gh` calls.
    """
    has_ws = work_stream is not None
    return TEMPLATE.format(
        project_title=project_title,
        project_url=project_url,
        project_number=project_number,
        project_id=project_id,
        owner=owner,
        repo=repo,
        bootstrap_date=bootstrap_date,
        wip_limit=wip_limit,
        status_columns_table=status_table(status),
        priority_table=priority_table(priority),
        work_stream_section=work_stream_section(work_stream),
        status_field_id=status.get("id", "<unset>") if status else "<unset>",
        priority_field_id=priority.get("id", "<unset>") if priority else "<unset>",
        work_stream_field_id=work_stream.get("id", "<unset>") if work_stream else "<unset>",
        status_options_kv=options_kv_block(status),
        priority_options_kv=options_kv_block(priority),
        work_stream_options_kv=options_kv_block(work_stream),
        status_options_block=options_block(status),
        priority_options_block=options_block(priority),
        work_stream_options_block=options_block(work_stream),
        up_next_option_id=option_id(status, "Up Next"),
        in_progress_rule=in_progress_rule(has_ws),
        triage_checklist=triage_checklist(has_ws, project_number, owner),
        triage_disappears=triage_disappears(has_ws),
    )


# ---------- Main ----------


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--url", required=True, help="GitHub Project v2 URL")
    parser.add_argument(
        "--repo",
        required=True,
        help="Repo slug (owner/repo) this board is paired with",
    )
    parser.add_argument(
        "--output",
        default="docs/project-board.md",
        help="Output path (default: docs/project-board.md)",
    )
    parser.add_argument("--wip-limit", type=int, default=3)
    parser.add_argument(
        "--no-create",
        action="store_true",
        help="Don't offer to create missing fields",
    )
    parser.add_argument("--force", action="store_true", help="Overwrite existing output file")
    parser.add_argument(
        "--non-interactive",
        action="store_true",
        help="Skip prompts (for automation)",
    )
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
    except (RuntimeError, GhInvocationError) as e:
        print(f"bootstrap: {e}", file=sys.stderr)
        return 1

    # Workflow check: without the built-in "Item closed → Done" workflow,
    # paths that close issues outside of `jared close` (raw `gh issue close`,
    # PR-merge auto-close) will leave items stuck in their pre-close Status.
    # `jared close` itself has an explicit-Status fallback so it stays
    # correct either way, but users running on this board with the workflow
    # off will accumulate the drift silently. Warn early.
    workflows = fetch_workflows(owner_type, owner, number)
    item_closed = next(
        (w for w in workflows if w.get("name") == "Item closed"), None
    )
    if item_closed is not None and not item_closed.get("enabled"):
        print(
            "\nWARNING: the 'Item closed' workflow is DISABLED on this project.\n"
            "  Closed issues will NOT auto-move to Done unless closed via `jared close`\n"
            "  (which has an explicit Status=Done fallback). Raw `gh issue close` and\n"
            "  PR-merge auto-close will leave items stuck in their pre-close column.\n"
            f"  Enable at: {args.url}/workflows\n",
            file=sys.stderr,
        )

    project_id = project.get("id")
    if not isinstance(project_id, str):
        print(
            f"bootstrap: project response missing 'id' field: {project}",
            file=sys.stderr,
        )
        return 1
    project_title = project.get("title", f"Project {number}")
    print(f"  Project: {project_title}")
    print(f"  Fields found: {', '.join(f['name'] for f in fields)}")

    # Link the project to the repo so it appears under <repo> → Projects tab.
    # Idempotent on GitHub's side; warn but don't abort on failure (#25).
    ok, link_msg = link_project_to_repo(project_id, args.repo)
    if ok:
        print(f"  Linked project #{number} to {args.repo}")
    else:
        print(
            f"  WARNING: could not link project to {args.repo}: {link_msg}",
            file=sys.stderr,
        )

    # Identify or create standard fields
    status = find_single_select_field(fields, "Status")
    priority = find_single_select_field(fields, "Priority")
    work_stream = find_single_select_field(fields, "Work Stream")

    missing: list[tuple[str, list[str] | None]] = []
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
                except (RuntimeError, GhInvocationError) as e:
                    print(f"    Failed: {e}")
    elif missing:
        print(f"  Note: {[m[0] for m in missing]} missing — skipped creation.")

    # Generate convention doc
    content = render_doc(
        project_title=project_title,
        project_url=args.url,
        project_number=number,
        project_id=project_id,
        owner=owner,
        repo=args.repo,
        bootstrap_date=dt.date.today().isoformat(),
        wip_limit=args.wip_limit,
        status=status,
        priority=priority,
        work_stream=work_stream,
    )

    # Write
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)

    if output.exists() and not args.force:
        existing = output.read_text()
        if existing == content:
            print(f"\n{output}: already up to date.")
            return 0
        # Legacy-shape detection: if the existing doc is missing some of the
        # machine-readable header bullets, propose a minimal patch that
        # inserts just those bullets, preserving the rest of the file. A
        # full-template rewrite (the else branch) would destroy custom
        # prose a project has accumulated.
        missing_bullets = detect_missing_header_bullets(existing)
        if missing_bullets:
            header = render_header_block(
                project_url=args.url,
                project_number=int(number),
                project_id=project_id,
                owner=owner,
                repo=args.repo,
            )
            patched = patch_legacy_doc(existing, header)
            print(
                f"\n{output} is missing the jared header block "
                f"({', '.join(missing_bullets)})."
            )
            print("Proposed patch — insert five machine-readable bullets near the top:\n")
            for line in difflib.unified_diff(
                existing.splitlines(keepends=True),
                patched.splitlines(keepends=True),
                fromfile=f"{output} (existing)",
                tofile=f"{output} (patched)",
            ):
                sys.stdout.write(line)
            new_path = output.with_suffix(output.suffix + ".new")
            new_path.write_text(patched)
            print(f"\nPatched content written to {new_path}")
            print(f"Review, then: mv {new_path} {output}   (or re-run with --force)")
            print(
                "Note: the rest of your doc (prose, custom sections) is preserved verbatim; "
                "only the bullet block is added."
            )
            return 0
        # Full-template diff (existing doc has all bullets but differs from template)
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
    print("  2. Run `scripts/sweep.py` to see any existing drift.")
    print("  3. If this project uses plan/spec artifacts, see references/plan-spec-integration.md.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
