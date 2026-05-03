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

## Cache discipline

Almost every `gh` invocation Jared makes is GraphQL-billed against the same
5000-point/hour bucket — `gh project ...`, `gh issue view --json ...`, `gh
issue list --json ...`, and `gh api graphql` all draw from it. Two rules
keep conversational sessions inside that budget:

1. **Pass `--cache 60s` on every read-only `gh api ...` call.** This
   includes `gh api graphql ...` (the cache key covers the POST body, so
   identical queries hit it). Use a longer TTL — `5m`, `1h` — for things
   that genuinely don't change inside a session (e.g., milestone inventory,
   schema introspection). The cache is a transparent HTTP response cache
   keyed by request shape, with no smart invalidation: after mutating
   something, a cached read of that data returns stale until TTL expires.
   Pass `--cache 0` to force a refresh after a mutation when you need the
   updated state. Worked example: `gh api graphql -f query='…' --cache 60s`.

2. **Prefer the `jared` CLI for board-shaped queries.** `jared summary` and
   `jared get-item <N>` share a per-process snapshot of `gh project
   item-list`, so a session that asks "what's on the board?" then "what's
   the state of #51?" pays for one `item-list` fetch, not two. Reach for
   `gh issue view --json …` only when you actually need body / title /
   labels / milestone — the fields the CLI doesn't expose. For Status /
   Priority / item-id / field values, `jared get-item` is cheaper and
   bounded.

The escape-hatch examples below are written with these rules applied.

## Raw `gh` fallback — the minimum escape-hatch set

### Inspect the board

```bash
# Full item list — item-ids, field values, content snippets for every row.
# Prefer `jared summary` / `jared get-item` in conversational flows; those
# share one fetch per process. Use this raw form only for ad-hoc inspection
# of fields the CLI doesn't expose.
gh project item-list <project-number> --owner <owner> --limit 500 --format json

# Project metadata (title, id, field counts)
gh project view <project-number> --owner <owner> --format json

# All fields + their options (field-ids, option-ids, types)
gh project field-list <project-number> --owner <owner> --format json
```

### Inspect an issue

```bash
# Body + state + labels + milestone.
# For state-only checks (Status / Priority / item-id), use `jared get-item
# <N>` instead — it hits the per-process snapshot cache. Use this raw form
# only when you need the body / labels / milestone fields.
gh issue view <issue-number> --repo <repo> --json \
  body,state,labels,milestone,closedAt

# Native blocked-by edges (GraphQL — not exposed via `gh issue view`).
# `--cache 60s` deduplicates repeats inside a single session.
gh api graphql --cache 60s -f query='
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
# When "is this field available on this GitHub version?" comes up.
# Schema doesn't change inside a session — long TTL is safe.
gh api graphql --cache 1h -f query='
{ __type(name: "Issue") { fields { name type { name } } } }'
```

## Cautions

**Canonical vs legacy surfaces.** Some projects carry both a Priority field on the project board and legacy `priority:*` labels on the issue (or similar duplication on other axes). The convention doc (`docs/project-board.md`) defines which surface is canonical — Jared writes only to that one. Legacy duplicates are read-only; reconcile drift by *removing* the legacy label or unsetting the legacy field, never by mirroring writes across both. `sweep.py::check_legacy_priority_labels` flags drift; remediation always strips the legacy surface, never the canonical one.

**ProjectV2 single-select mutations are destructive.** `updateProjectV2ItemFieldValue` overwrites the existing value — there is no "merge," "append," or "add to set." Bucketing tags that need additive semantics belong on issue labels (which *are* additive by nature), not on single-select fields. If you find yourself wanting to express "this issue belongs to multiple work streams," that's a label schema problem, not a field-value problem.

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
