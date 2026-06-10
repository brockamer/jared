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

`sweep.py` runs `check_off_board_issues`, a pure number-intersection between open repo issues and board items. It needs the closed board items in the snapshot too, so a closed-but-on-board issue isn't false-flagged as off-board — hence the cache holds the closed subset alongside the open pull.

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

## `jared migrate`

Copies a project's open items from the current backend (GitHub Projects v2 or KanbanFlow) to the other, surfacing every named, accepted loss before the first write.

```
jared migrate --to <github|kanbanflow> --target-doc PATH [--apply] [--include-closed] [--out FILE] [--yes]
```

**Dry-run is the default.** Without `--apply`, the command reads the source board, validates the target, computes the full loss report and (for KanbanFlow targets) a write-call estimate, prints the report, and stops. No writes are performed.

**`--apply` performs writes** after an interactive confirmation prompt ("Type 'y' to proceed"). Pass `--yes` to skip the prompt for non-interactive use.

**`--target-doc PATH`** is the path to the target project's `docs/project-board.md` — the convention doc produced by running `jared init` against the target backend. It identifies the target board and the Status column map. The target backend must differ from the source; `jared migrate` refuses with exit 2 if `--to` equals the current backend.

**Target-structure validation** runs before any write for any target: every distinct Status + Priority pair across source items is probed via `validate_fields()`; every distinct source milestone name is checked against the target's swimlane list (KanbanFlow) or milestone list (GitHub). All missing elements are printed together; the command exits 1 if any are absent. KanbanFlow cannot create missing columns, dropdown options, or swimlanes via the API, so every miss must be resolved manually before `--apply`. GitHub targets must pre-create any missing Priority/Status single-select option on the target Project before `--apply`.

**`--out FILE`** names the run artifact (default: `tmp/migrate-<src>-to-<dst>-<timestamp>.json`). The artifact is an old→new number map that doubles as a resume ledger. It is written atomically after each created item and after each second-pass port (body/comment rewrite, edge translation). Re-running `--apply --out <same-file>` against an existing artifact resumes from the last completed state without duplicating items, comments, or blocked-by edges — comment() and add_blocked_by() are not idempotent on either live backend, so the ledger guards both passes.

**`--include-closed`** is accepted but currently inoperative — no provider exposes a closed-items reader beyond `recently_closed` (which KanbanFlow degrades to `[]`). The command warns and migrates only open items. Closed-history migration is a named follow-up.

**On-success backend-selector flip.** After a fully-successful `--apply`, `jared migrate` overwrites the source project's `docs/project-board.md` with the target's convention doc (an atomic copy). All subsequent `jared` invocations against that project then route to the new backend. The flip is the last statement in the apply path; an abort, a confirmation refusal, or any mid-run exception bypasses it so a partial run never flips.

**KanbanFlow write-call quota guidance.** KanbanFlow's free tier allows approximately 1,000 API requests per hour. The dry-run report prints a write-call estimate: `1 create + 1 Priority POST + 1 extra-field POST` per item, plus 1 label POST per blocked-by edge. Comment portage is not counted in this estimate (`comment_count=0`), so boards with many comments will exceed it. For a board with many items, check this estimate before running `--apply`; a KF-rate-limited run is safe to resume via `--out` after the quota resets.

**Loss axes.** The dry-run report itemizes every named loss for the direction:

- GH→KF: `native_dependencies` (edges become `blocked-by:<N>` label markers), `milestone_state` (due dates and open/close state dropped), `velocity_timestamps`, `markdown_body` (rendering only — text round-trips), `closed_state` (Done column only), `sub_issues`, `mcp_tier`. GH→KF **preserves `#N`** exactly.
- KF→GH: `renumber` only — GitHub auto-assigns issue numbers; every `#N` is reassigned and cross-references in bodies and comments are rewritten through the old→new number map. KF→GitHub is otherwise structurally lossless.
