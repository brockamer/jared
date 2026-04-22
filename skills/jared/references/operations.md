# Board Operations Reference

Command reference for board operations. All examples assume values that live in the project's `docs/project-board.md` — never hardcoded. If MCP tools are available for GitHub issues/projects, prefer them over shelling out; the `gh` commands below are the portable fallback.

**Placeholder key:**

- `<owner>` — GitHub account that owns the project (user or org)
- `<repo>` — repo slug
- `<project-number>` — integer project number (e.g., 1)
- `<project-id>` — node ID starting with `PVT_`
- `<status-field-id>`, `<priority-field-id>` — standard field node IDs
- `<backlog-option-id>`, `<up-next-option-id>`, etc. — single-select option IDs
- `<issue-number>` — integer issue number
- `<item-id>` — project item node ID (different from issue node ID)

All of these come from `docs/project-board.md`. If that file doesn't exist, run `scripts/bootstrap-project.py` to generate it.

## Discovery — finding the IDs in the first place

These are the commands `bootstrap-project.py` wraps, shown here in case you need to inspect a board by hand.

```bash
# Project URL, owner type, description
gh project view <project-number> --owner <owner> --format json

# All fields and their option IDs
gh project field-list <project-number> --owner <owner> --format json

# Items currently on the board (useful to confirm a field is actually being used)
gh project item-list <project-number> --owner <owner> --limit 50 --format json
```

Note: `gh project` commands accept `--owner` for both users and organizations. The URL forms differ (`github.com/users/<name>/projects/<N>` vs `github.com/orgs/<name>/projects/<N>`), but the CLI abstracts this.

## Reading board state

### Fast surface (In Progress + Up Next)

Use `scripts/board-summary.sh` — it reads `docs/project-board.md` and prints a compact summary.

### Full item listing with fields

```bash
gh project item-list <project-number> --owner <owner> --limit 200 --format json
```

### Find an issue's project item ID (needed for field edits)

```bash
gh project item-list <project-number> --owner <owner> --limit 200 --format json \
  | python3 -c "
import sys, json
items = json.load(sys.stdin).get('items', [])
n = int(sys.argv[1])
item = next((i for i in items if (i.get('content') or {}).get('number') == n), None)
print(item['id'] if item else 'NOT FOUND')
" <issue-number>
```

## Filing a new issue — the mandatory two-step

`gh issue create` does not add to the project board. Missing the second step is the single most common way items go invisible.

```bash
# Step 1: create
gh issue create --repo <owner>/<repo> \
  --title "Verb-first title under 70 chars" \
  --label "enhancement,<scope-label>" \
  --body "$(cat <<'EOF'
One-sentence summary.

## Current state
Not started.

## Decisions
(none yet)

## Acceptance criteria
<details>
<summary>Expand</summary>

- Criterion 1
- Criterion 2

</details>

## Planning
(none)
EOF
)"

# Capture the returned issue URL, then:

# Step 2: add to project board
gh project item-add <project-number> --owner <owner> --url <issue-url>
```

**Capture the returned item ID** — you need it immediately for the field-setting calls below.

For issue bodies, use `assets/issue-body.md.template` as the scaffold.

## Setting project fields

```bash
# Priority
gh project item-edit \
  --project-id <project-id> \
  --id <item-id> \
  --field-id <priority-field-id> \
  --single-select-option-id <high|medium|low-option-id>

# Other project-specific single-select fields (e.g., Work Stream, if defined)
gh project item-edit \
  --project-id <project-id> \
  --id <item-id> \
  --field-id <field-id> \
  --single-select-option-id <option-id>

# Status (Backlog → Up Next → In Progress → Done)
gh project item-edit \
  --project-id <project-id> \
  --id <item-id> \
  --field-id <status-field-id> \
  --single-select-option-id <target-status-option-id>
```

## Moving to Blocked status

Use only when an item was pulled to In Progress and then hit an unanticipated stoppage. Always add a `## Blocked by` section to the issue body naming the unblock owner and the specific event being waited on. Remove the section when the item moves back to In Progress or Backlog.

```bash
gh project item-edit \
  --project-id <project-id> \
  --id <item-id> \
  --field-id <status-field-id> \
  --single-select-option-id <blocked-option-id>
```

## Closing an issue + verifying auto-move to Done

```bash
gh issue close <issue-number> --repo <owner>/<repo>

# Verify the board auto-moved
gh project item-list <project-number> --owner <owner> --limit 200 --format json \
  | python3 -c "
import sys, json
items = json.load(sys.stdin).get('items', [])
n = int(sys.argv[1])
item = next((i for i in items if (i.get('content') or {}).get('number') == n), None)
print('status:', (item or {}).get('status', 'NOT FOUND'))
" <issue-number>
```

If not auto-moved (occasional race), set Status manually via the field-edit pattern above with `<done-option-id>`.

## Commenting on an issue

Use for Session notes, mid-work updates that don't belong in the body's living sections, or decision-log pointers.

```bash
gh issue comment <issue-number> --repo <owner>/<repo> --body "$(cat <<'EOF'
Markdown body here.
EOF
)"
```

## Editing an issue body in place

Pull → modify → put back. Used by `scripts/capture-context.py` to update `## Current state` and append to `## Decisions`.

```bash
gh issue view <issue-number> --repo <owner>/<repo> --json body --jq '.body' > /tmp/body.md
# ...modify /tmp/body.md...
gh issue edit <issue-number> --repo <owner>/<repo> --body-file /tmp/body.md
```

## Milestones

### Create

```bash
gh api --method POST repos/<owner>/<repo>/milestones \
  -f title="v0.2 — Materials Viewer" \
  -f description="What ships in this cut" \
  -f state="open" \
  -f due_on="2026-05-15T00:00:00Z"
```

### Assign an issue

```bash
gh issue edit <issue-number> --repo <owner>/<repo> --milestone "v0.2 — Materials Viewer"
```

### List with progress

```bash
gh api repos/<owner>/<repo>/milestones --jq '.[] | {title, state, open_issues, closed_issues, due_on}'
```

### Update target date

```bash
gh api --method PATCH repos/<owner>/<repo>/milestones/<milestone-number> \
  -f due_on="2026-05-15T00:00:00Z"
```

### Close

```bash
gh api --method PATCH repos/<owner>/<repo>/milestones/<milestone-number> -f state="closed"
```

## Labels

### Create

```bash
gh label create "<name>" --color "<hex-no-#>" --description "..." --repo <owner>/<repo>
```

### Apply / remove

```bash
gh issue edit <issue-number> --repo <owner>/<repo> --add-label "bug,pipeline-quality"
gh issue edit <issue-number> --repo <owner>/<repo> --remove-label "priority: high"
```

## Native dependency mutations

`addBlockedBy` / `removeBlockedBy` are the canonical mutations. Verify names via introspection if uncertain — some schema versions use `addIssueDependency` / `issueDependencies` instead.

```bash
# Verify actual mutation names
gh api graphql -f query='{ __type(name: "Mutation") { fields { name } } }' \
  | python3 -c "import sys,json; print('\n'.join(f['name'] for f in json.load(sys.stdin)['data']['__type']['fields'] if 'block' in f['name'].lower() or 'depend' in f['name'].lower()))"

# Mark issue B blocked by issue A
BLOCKER_ID=$(gh issue view <A> --repo <owner>/<repo> --json id --jq '.id')
DEPENDENT_ID=$(gh issue view <B> --repo <owner>/<repo> --json id --jq '.id')
gh api graphql -f query='
  mutation($issueId: ID!, $blockingIssueId: ID!) {
    addBlockedBy(input: {issueId: $issueId, blockingIssueId: $blockingIssueId}) {
      issue { number }
    }
  }' -F issueId="$DEPENDENT_ID" -F blockingIssueId="$BLOCKER_ID"

# Remove an edge
gh api graphql -f query='
  mutation($issueId: ID!, $blockingIssueId: ID!) {
    removeBlockedBy(input: {issueId: $issueId, blockingIssueId: $blockingIssueId}) {
      issue { number }
    }
  }' -F issueId="$DEPENDENT_ID" -F blockingIssueId="$BLOCKER_ID"
```

A `blockedBy` edge does NOT automatically move an item to the Blocked column. Items move to Blocked only when actively stuck during In Progress. See `references/dependencies.md` for the conceptual model.

## Searching issues

```bash
# All issues mentioning a string
gh search issues --repo <owner>/<repo> --match body --match title "<query>" --json number,title,state

# Open issues with a specific label
gh issue list --repo <owner>/<repo> --label "blocked" --state open

# Issues in a milestone
gh issue list --repo <owner>/<repo> --milestone "v0.2 — Materials Viewer" --state all
```

## Deleting an issue (rare)

Only when you need to wipe edit history (e.g., PII leak). Prefer editing for normal scrubbing. Requires repo admin. Issue numbers are not reused.

```bash
gh issue delete <issue-number> --repo <owner>/<repo> --yes
```

## MCP equivalents

If the GitHub MCP server is connected, the typical mapping is:

| Operation | gh command | MCP tool (typical) |
|---|---|---|
| Create issue | `gh issue create` | `create_issue` |
| Comment | `gh issue comment` | `add_issue_comment` |
| Close | `gh issue close` | `update_issue` with `state: closed` |
| Edit body | `gh issue edit --body-file` | `update_issue` with `body` |
| Project item add | `gh project item-add` | `add_project_item` |
| Field edit | `gh project item-edit` | `update_project_item_field_value` |

Exact tool names depend on the MCP server version. Use `tool_search` to discover what's actually loaded rather than assuming.
