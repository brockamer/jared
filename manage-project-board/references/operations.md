# Board Operations Reference

All commands assume `gh` is authenticated and `jq` / `python3` are available. Replace `<owner>` and `<project-number>` with project-specific values from `docs/project-board.md`.

## Reading board state

### Summary of In Progress + Up Next (quick orientation)

```bash
gh project item-list <project-number> --owner <owner> --limit 100 --format json \
  | python3 -c "
import sys, json
items = json.load(sys.stdin)['items']
by_status = {}
for i in items:
    s = i.get('status', 'No status')
    num = i.get('content', {}).get('number', '?')
    title = i.get('title', '')[:60]
    prio = i.get('priority', '-')
    ws = i.get('work Stream') or i.get('workStream') or '-'
    by_status.setdefault(s, []).append(f'#{num} [{prio}/{ws}] {title}')
for s in ['In Progress', 'Up Next']:
    print(f'== {s} ==')
    for line in sorted(by_status.get(s, []), reverse=True):
        print(f'  {line}')
"
```

### Find an issue's item ID (for field edits)

```bash
gh project item-list <project-number> --owner <owner> --limit 100 --format json \
  | python3 -c "import sys, json; items = json.load(sys.stdin)['items']; n = int(sys.argv[1]); item = next((i for i in items if i.get('content', {}).get('number') == n), None); print(item['id'] if item else 'NOT FOUND')" <issue-number>
```

## Filing a new issue — two-step

```bash
# Step 1: create the issue
gh issue create --repo <owner>/<repo> \
  --title "Verb-first title under 70 chars" \
  --label "enhancement,<work-stream-label>" \
  --body "$(cat <<'EOF'
One-sentence summary.

<details>
<summary>Details</summary>

Longer scope, acceptance criteria, implementation notes.

</details>

## Related
- Depends on: #N
- Spec: [link if applicable]
EOF
)"

# Step 2: add to project board — gh issue create does NOT auto-add
gh project item-add <project-number> --owner <owner> --url <issue-url>
```

**Capture the returned item ID** — you'll need it immediately for field-setting.

## Setting project fields

Field IDs and option IDs live in the project's `docs/project-board.md`. For findajob as of 2026-04-18:

```
Project ID:          PVT_kwHOAgGulc4BUtxZ
Status field ID:     PVTSSF_lAHOAgGulc4BUtxZzhCOoMM
  Backlog:           ee143341
  Up Next:           52541ab6
  In Progress:       2c2c07d2
  Done:              a2d5723e
Priority field ID:   PVTSSF_lAHOAgGulc4BUtxZzhCWZ08
  High:              f0a4404c
  Medium:            4e8ef0ac
  Low:               79925e2f
Work Stream ID:      PVTSSF_lAHOAgGulc4BUtxZzhCWa0Y
  Job Search:        36c0909b
  Generalization:    506d8256
  Infrastructure:    b1dd326d
```

### Set Priority

```bash
gh project item-edit \
  --project-id <project-id> \
  --id <item-id> \
  --field-id <priority-field-id> \
  --single-select-option-id <high|medium|low-option-id>
```

### Set Work Stream

```bash
gh project item-edit \
  --project-id <project-id> \
  --id <item-id> \
  --field-id <work-stream-field-id> \
  --single-select-option-id <work-stream-option-id>
```

### Move Status (Backlog → Up Next → In Progress)

```bash
gh project item-edit \
  --project-id <project-id> \
  --id <item-id> \
  --field-id <status-field-id> \
  --single-select-option-id <target-status-option-id>
```

## Closing an issue + verifying auto-move to Done

```bash
gh issue close <number> --repo <owner>/<repo>

# Verify board auto-moved to Done
gh project item-list <project-number> --owner <owner> --limit 100 --format json \
  | python3 -c "import sys, json; items = json.load(sys.stdin)['items']; n = int(sys.argv[1]); item = next((i for i in items if i.get('content', {}).get('number') == n), None); print('status:', item.get('status') if item else 'NOT FOUND')" <issue-number>
```

If not auto-moved, set Status manually via field-edit (Status field ID, Done option ID).

## Commenting on an issue

```bash
gh issue comment <number> --repo <owner>/<repo> --body "$(cat <<'EOF'
Comment body with markdown.
EOF
)"
```

## Editing issue body in place (e.g., checklist updates)

Pull body → modify → put back:

```bash
# Pull
gh issue view <number> --repo <owner>/<repo> --json body --jq '.body' > /tmp/body.md

# Modify /tmp/body.md (checklist checkboxes, etc.)

# Put back
gh issue edit <number> --repo <owner>/<repo> --body-file /tmp/body.md
```

## Editing an issue comment

```bash
# Find comment ID via the issue's comment listing
gh api repos/<owner>/<repo>/issues/<number>/comments --jq '.[] | {id: .id, first_line: (.body | split("\n")[0])}'

# Patch the body
gh api --method PATCH repos/<owner>/<repo>/issues/comments/<comment-id> -f body="new body"
```

## Milestones

### Create a milestone

```bash
gh api --method POST repos/<owner>/<repo>/milestones \
  -f title="v0.2 — Materials Viewer" \
  -f description="What ships in this cut" \
  -f state="open" \
  -f due_on="2026-05-15T00:00:00Z"
```

### Assign an issue to a milestone

```bash
gh issue edit <number> --repo <owner>/<repo> --milestone "v0.2 — Materials Viewer"
```

### List milestones with progress

```bash
gh api repos/<owner>/<repo>/milestones --jq '.[] | {title, state, open_issues, closed_issues, due_on}'
```

## Labels

### Create a new label

```bash
gh label create "<name>" --color "<hex-no-#>" --description "..." --repo <owner>/<repo>
```

### Apply labels to an issue

```bash
gh issue edit <number> --repo <owner>/<repo> --add-label "bug,pipeline-quality"
```

### Remove labels

```bash
gh issue edit <number> --repo <owner>/<repo> --remove-label "priority: high"
```

## Deleting an issue (rare — destructive)

Only when you need to wipe edit history (e.g., PII leak). Prefer editing for normal scrubbing. Requires repo admin.

```bash
gh issue delete <number> --repo <owner>/<repo> --yes
```

Note: issue numbers are not reused. Plan to refile under a new number.

## Searching issues

```bash
# All issues mentioning a string in title/body
gh search issues --repo <owner>/<repo> --match body --match title "<query>" --json number,title,state

# Open issues with a specific label
gh issue list --repo <owner>/<repo> --label "bug" --state open

# Issues in a milestone
gh issue list --repo <owner>/<repo> --milestone "v0.2 — Materials Viewer" --state all
```
