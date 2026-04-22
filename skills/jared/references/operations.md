# Board Operations — Raw `gh` Escape Hatch

Primary reference is `references/jared-cli.md` — use the `jared` CLI for any
board operation it covers (file, move, set, close, comment, blocked-by,
get-item, summary). This file is the **escape hatch**: commands for things
the CLI doesn't wrap, and a handful of inspection commands useful when
debugging a mismatch between `docs/project-board.md` and reality.

## Placeholder key

All IDs come from `docs/project-board.md`. If that file doesn't exist, run
`${CLAUDE_PLUGIN_ROOT}/skills/jared/scripts/bootstrap-project.py` to generate
it.

- `<owner>` — GitHub account that owns the project (user or org)
- `<repo>` — repo slug (e.g., `brockamer/jared`)
- `<project-number>` — integer project number (e.g., 2)
- `<project-id>` — node ID starting with `PVT_`
- `<field-id>` — field node ID (e.g., Status field → `PVTSSF_…`)
- `<option-id>` — 8-char hex single-select option ID (e.g., `0369b485`)
- `<issue-number>` — integer issue number
- `<item-id>` — project item node ID (different from issue node ID; starts
  with `PVTI_`)

## Raw `gh` fallback — the minimum escape-hatch set

### Inspect the board

```bash
# Full item list — item-ids, field values, content snippets for every row
gh project item-list <project-number> --owner <owner> --limit 500 --format json

# Project metadata (title, id, field counts)
gh project view <project-number> --owner <owner> --format json

# All fields + their options (field-ids, option-ids, types)
gh project field-list <project-number> --owner <owner> --format json
```

### Inspect an issue

```bash
# Body + state + labels + milestone
gh issue view <issue-number> --repo <repo> --json \
  body,state,labels,milestone,closedAt

# Native blocked-by edges (GraphQL — not exposed via `gh issue view`)
gh api graphql -f query='
query($o:String!,$r:String!,$n:Int!) {
  repository(owner:$o, name:$r) {
    issue(number:$n) {
      blockedBy(first:50) { nodes { number state } }
    }
  }
}' -F o=<owner> -F r=<repo-name> -F n=<issue-number>
```

### Introspect the GraphQL schema

```bash
# When "is this field available on this GitHub version?" comes up
gh api graphql -f query='
{ __type(name: "Issue") { fields { name type { name } } } }'
```

## Operations Jared doesn't wrap today

These remain raw-gh territory; none are used often enough to pull into the CLI.

- **Milestones** — `gh milestone create|edit|close|list` (see
  `references/milestones-and-roadmap.md` for when and how).
- **Labels** — `gh label create|delete|list`.
- **Issue search** — `gh search issues` / `gh search prs` for dup-check
  queries (see `/jared-file` flow).
- **Issue delete** — `gh issue delete` (rare; typically close instead).

## MCP equivalents

When the GitHub MCP plugin is loaded, prefer its typed tools over `gh`:

| Operation | gh command | MCP tool (typical) |
|---|---|---|
| Create issue | `gh issue create` | `create_issue` |
| Comment | `gh issue comment` | `add_issue_comment` |
| Close | `gh issue close` | `update_issue` with `state: closed` |
| Edit body | `gh issue edit --body-file` | `update_issue` with `body` |
| Project item add | `gh project item-add` | `add_project_item` |
| Field edit | `gh project item-edit` | `update_project_item_field_value` |

Exact tool names depend on the MCP server version. Use `tool_search` to
discover what's actually loaded rather than assuming.
