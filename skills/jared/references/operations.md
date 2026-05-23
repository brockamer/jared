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

### Closed-items cache (sweep optimization, #186)

`sweep.py` runs `check_off_board_issues` and `check_closed_not_done`, both of which need closed items in the snapshot — `check_closed_not_done` specifically needs closed-with-Status-not-Done items, so a pure Done-only cache would make them invisible.

To avoid re-pulling the full mature-board history every sweep cycle, sweep maintains a persistent **closed-items cache** at `${JARED_CACHE_DIR}/<project>-closed.json` (24-hour default TTL). On warm-cache reads, sweep pulls open items via `Board.open_items()` (cost scales with open count, not total board size) and merges with the cached closed items. Dedup rule: open-items pull wins on number collision (handles external reopen).

**Invalidation surface.** First-party `jared set <N> Status <value>` invalidates the cache — that catches `jared close` (which delegates to `jared set ... Status Done`), `jared move <N> Done`, and any direct `jared set` of the Status field. Non-Status writes (Priority, Work Stream) leave the cache intact to avoid forcing a needless full-board refetch.

**External-mutation staleness window.** Mutations that bypass the `jared` CLI do **not** invalidate the cache: raw `gh issue close`, raw `gh project item-edit`, the GitHub UI, and the built-in "Item closed → Done" project workflow on PR-merge auto-close. Sweep reports based on the closed-cache may be stale by up to the TTL (24h default). Acceptable trade-off — the alternative is paying full-board GraphQL cost every sweep cycle. Escape valves:

- `JARED_NO_CACHE=1` bypasses every cache layer for one invocation.
- `jared` mutation paths invalidate; if you've just done a UI close and want sweep to see it, run `jared set <N> Status Done` (no-op if already Done; still invalidates).

The 60s `--cache` discipline above is unaffected: it governs `gh` HTTP-response caching, which is keyed by request shape; the 24h closed-cache governs Jared's own on-disk snapshot.

## GitHub API mechanism selection

`gh` exposes four mechanisms for talking to GitHub: subcommands (`gh issue view`, `gh project item-list`, …), raw REST (`gh api repos/…`), raw GraphQL (`gh api graphql`), and — only in the conversational layer — the GitHub MCP plugin (`mcp__plugin_github_github__*`). Each draws from a different rate-limit bucket. Routing matters most when the graphql bucket is pressured (`gh project item-list` on a large board can burn ~5000 graphql points in one call).

**CLI doctrine** (what `lib/board.py` and the batch scripts do):

- **ProjectV2 reads + mutations** — `gh api graphql` only. No alternative; the MCP plugin exposes no ProjectV2 tools at all. The cost levers are caching (`Board.board_items()` 3-layer cache), batched aliased mutations, and the `graphql_budget()` pre-flight.
- **Stable per-issue state checks** — `gh api repos/.../issues/N` with ETag-conditional GET (`_fetch_issue_rest_with_etag`). Steady-state cost is 0 REST core (304 short-circuit). Used by `archive-plan.py` closed-issue scans and `dependency-graph.py` open-state filters.
- **Full issue-body reads in batch scripts** — REST migration target (`gh issue view --json body` is 1 graphql/call; `gh api repos/.../issues/N` is 1 REST core/call). Marginal per call, cumulative in loops over plans and snapshots.
- **Issue CRUD** — `gh issue create / comment / close / edit` already route via REST under the hood. No change.

**Conversational doctrine** (Claude Code sessions, not the CLI):

When the graphql bucket is pressured (`graphql_budget()` reports < 1000 remaining, or operator-observed exhaustion), prefer:

- `mcp__plugin_github_github__issue_read` over `gh issue view --json` — saves ~1 graphql, costs ~2 REST core.
- `mcp__plugin_github_github__add_issue_comment` over `gh issue comment` — no graphql delta (both REST), but bypasses `gh` subprocess overhead.

When graphql is healthy, either path is fine; the choice becomes a UX call (gh's CLI conventions vs MCP's typed-tool ergonomics). ProjectV2 operations stay on graphql via `jared` regardless — there is no MCP alternative.

**Rate-limit recovery — direct REST for comments and edits.** When GraphQL is exhausted (0/5000 remaining), `gh issue comment` itself fails with "GraphQL: API rate limit already exceeded" — `gh` does a GraphQL preflight to resolve the issue → node ID even though the POST is REST. Fallback: post directly via `gh api -X POST /repos/<owner>/<repo>/issues/<N>/comments --input -` with a `{"body": "..."}` payload. The same pattern applies to `gh issue edit --milestone <name>` (broken by the same preflight); use `gh api PATCH /repos/<o>/<r>/issues/<N> -f milestone=<n>` direct. When GraphQL is dry but REST is healthy, the REST endpoint is the escape hatch.

Full investigation, capability matrix, per-call costs, and auth-surface details: [`docs/github-api-tool-selection.md`](../../../docs/github-api-tool-selection.md).

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

**Pre-flight redaction.** Every `jared file` and `jared comment` runs a pre-flight scan against gitignored claude-shaped local files (`CLAUDE.local.md`, `.claude/local/*.md`). On a hit, the call is refused with a structured diff and exit 2; nothing is posted. Full reference: `references/pii-pre-flight.md`.

## Model & execution guidance — section + kill switch

Every issue body filed through `/jared-file` carries a `## Model & execution guidance` H2 between `## Acceptance criteria` and `## Planning`. Three tier subsections + Execution sketch + a leading caveat:

```markdown
## Model & execution guidance

*Tiers below classify the work — they do not prescribe dispatch. Use judgment at
session-time; the wrap audit will ask you to evaluate that judgment honestly.*

**Cheap-tier work:**
- <bullet>

**Standard-tier work:**
- <bullet>

**Smart-tier moments (USE `advisor()`):**
- <bullet>

**Execution sketch:**
1. <step — name a subagent inline if the dispatch is genuinely load-bearing (e.g., `Explore` for a surface-map task that exceeds the parent session's read budget)>
```

Headers classify work, they do not prescribe dispatch — Cheap/Standard tier headers carry no `USE` directive because work size is unknown at file-time and operators correctly resize at session-time (per #162 audit: task-tier dispatch prescriptions held 23–43% worked-rate). Only the `advisor()` directive in Smart-tier is prescribed, because decision-point prescriptions hold regardless of work size (95% worked-rate). Use abstract tier labels (Cheap / Standard / Smart) — model names age faster than the cost structure. Full doctrine and rendered example in SKILL.md § "Model & execution guidance".

**Two enforcement points:**

| When | Where | What |
|---|---|---|
| File-time | `/jared-file` body composition | Section is part of every new issue body. |
| Start-time | `/jared-start` step 6 | If the body has no `## Model & execution guidance` H2, generate evaluation, surface in announce, post as Session-note-shaped comment on user approval. |

**Project-level kill switch.** Add this bullet to `## Jared config` in `docs/project-board.md`:

```markdown
## Jared config

- model-guidance: disabled
```

The kill switch is doctrinal: `/jared-file` reads this bullet from `docs/project-board.md` and skips composition when it says `disabled`; `/jared-start` does the same for the backstop. Default is enabled. Only the literal value `disabled` flips it off — typos and other values fail safe toward the discipline being on.

**Where the start-time evaluation lands.** Posted as a comment on the issue with header `## Session <YYYY-MM-DD> — Model & execution guidance (start-time backstop)`, using `jared comment <N> --body-file <path>`. The body is not retroactively amended — comments are append-only and durable, body edits are not. Subject to the standard pre-flight redaction.

## `/jared-audit`

Skeptical per-item accuracy audit. Fetches a working set (oldest-first issues, optionally milestones) with each item's open-dependents and a velocity block (recent closure rate + median age-at-close + median PR duration). The conversation runs a seven-question checklist per item, optionally invokes `advisor()` to pressure-test non-trivial batches before the operator sees them, and applies approved mutations via the existing atoms (`jared close`, `jared comment`, `jared set`) plus `gh api` for body / title / milestone changes. See `commands/jared-audit.md` for the full doctrine. The CLI side is just `jared audit fetch [--count N | --age-days N | --issues N,M,…] [--type issues|milestones|both]` — verdicts and mutation orchestration live in the conversational layer.

## Operations Jared doesn't wrap today

These remain raw-gh territory; none are used often enough to pull into the CLI.

- **Milestones** — `gh milestone create|edit|close|list` (see
  `references/milestones-and-roadmap.md` for when and how).
- **Labels** — `gh label create|delete|list`.
- **Issue search** — `gh search issues` / `gh search prs` for dup-check
  queries (see `/jared-file` flow).
- **Issue delete** — `gh issue delete` (rare; typically close instead).

## MCP equivalents

For issue + PR work, the GitHub MCP plugin's typed tools are a viable alternative to `gh` — see "GitHub API mechanism selection" above for when to prefer one over the other. The actual tool surface (as enumerated in `docs/github-api-tool-selection.md` § "MCP plugin tool surface"):

| Operation | gh command | MCP tool |
|---|---|---|
| Create issue | `gh issue create` | `issue_write` (method=`create`) |
| Read issue | `gh issue view --json` | `issue_read` (method=`get`) |
| Comment | `gh issue comment` | `add_issue_comment` |
| Close | `gh issue close` | `issue_write` (method=`update`, state=closed) |
| Edit body | `gh issue edit --body-file` | `issue_write` (method=`update`, body=…) |
| Read PR | `gh pr view` | `pull_request_read` (method=`get`) |
| **ProjectV2 ops** (`item-add`, `item-edit`, field reads, blocked-by edges, …) | `gh project …` / `gh api graphql` | **Not available — the MCP plugin exposes no ProjectV2 tools.** Use `jared` (which wraps the graphql calls) or raw `gh api graphql`. |

Tool names can shift across MCP server versions. Use `tool_search` to confirm what's actually loaded rather than assuming.
