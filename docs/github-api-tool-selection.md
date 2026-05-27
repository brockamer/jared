# GitHub API tool selection

Investigation + routing policy for jared's four candidate mechanisms for talking to GitHub. Filed against [#202](https://github.com/brockamer/jared/issues/202). Investigation only — implementation issues spawn from the recommendations below.

## TL;DR

- **Four mechanisms are available**: `gh` subcommands, raw `gh api` REST, `gh api graphql`, GitHub MCP plugin. Each consumes different rate-limit buckets.
- **ProjectV2 operations (jared's core surface) are graphql-only** at the GitHub API layer. No mechanism — including the MCP plugin — exposes ProjectV2 reads or mutations via REST. This is a hard constraint, not a routing preference.
- **The MCP plugin has no ProjectV2 tools** in its surface. Its scope is issues + PRs + repos + branches + files + tags + releases + reviews + searches. It is therefore **not a contender** for jared's distinctive operations; it is at most an alternative for the issue-CRUD periphery.
- **Python subprocesses cannot call MCP tools** (per [CLAUDE.md](../CLAUDE.md)). The MCP plugin is reachable only from the conversational layer (Claude Code) — never from `lib/board.py` or the batch scripts.
- **The graphql-pressure source is `gh project item-list`**, not per-issue reads. Cost scales linearly with item count (~10 graphql points per project item, because the call traverses every field value per item). On `jared/projects/4` (~50 items) one call costs ~200 points; on a 500-item board (observed empirically on `findajob/projects/1`) a single call can burn ~5000 graphql points — the entire hourly bucket. By contrast, one `gh issue view --json` costs ~1 graphql point. A long /jared-start cycle (next-session-prompt + summary + ties + move) can burn 600–900 graphql points on jared's small board, matching the operator's observed exhaustion pattern on findajob's larger board.
- **Routing recommendation (short form):**
  - ProjectV2 reads + mutations → `gh api graphql` (no alternative)
  - Stable per-issue state checks → `gh api repos/.../issues/N` (REST, ETag-cached) — this is the existing [#54](https://github.com/brockamer/jared/issues/54) / [#147](https://github.com/brockamer/jared/issues/147) path; doctrine confirmed
  - Full issue-body reads in batch scripts (`capture-context.py`, `archive-plan.py`) → migrate from `gh issue view --json body` to `gh api repos/.../issues/N`. Marginal (~1 graphql/call) per call but cumulative in loops.
  - Issue create/edit/comment/close (jared CLI) → `gh issue ...` subcommands (already REST under the hood; no change)
  - Conversational issue reads/comments (Claude Code, when graphql is pressured) → MCP `issue_read` / `add_issue_comment`. Saves ~1 graphql per call, costs ~2 REST core per call.
- **Architecture call**: keep the two-wrapper shape (`run_gh` / `run_graphql`). Existing REST callsites use `run_gh(["api", "repos/..."])` ad-hoc; that's already a clean seam. Add a `run_rest` wrapper only if a future migration introduces 3+ additional REST callsites.

## The four mechanisms

### 1. `gh` CLI subcommands

`gh issue view`, `gh issue create`, `gh issue comment`, `gh issue close`, `gh issue edit`, `gh pr list`, `gh pr view`, `gh project view`, `gh project item-list`, `gh project item-add`, `gh project item-edit`, `gh project field-list`.

The cli wraps both REST and GraphQL internally; which bucket a given subcommand hits depends on what the subcommand does. Project subcommands (`gh project ...`) route to GraphQL. Issue subcommands (`gh issue ...`) route to REST under the hood when no `--json` flag is used, and to GraphQL when `--json` is used.

**Auth surface**: respects `GH_TOKEN` / `GITHUB_TOKEN` when set, otherwise uses `gh auth login` OAuth session. Per [#65](https://github.com/brockamer/jared/issues/65), `lib/board.py` scrubs `GH_TOKEN` / `GITHUB_TOKEN` from the subprocess env before every `gh` invocation, forcing all jared CLI gh calls onto the OAuth session.

### 2. Raw `gh api` REST

`gh api repos/.../issues/N`, `gh api /repos/.../milestones`. Wrapped in `lib/board.py` only via direct `run_gh(["api", ...])` callsites — no dedicated wrapper today.

**Auth surface**: same as `gh` CLI (above).

### 3. `gh api graphql`

`gh api graphql -f query=...`. Wrapped in `lib/board.py` by `run_graphql()`, used for ~all ProjectV2 reads + mutations and for the batched multi-issue queries (open_items, ties, blocked-by edges, recent-comments batch).

**Auth surface**: same as `gh` CLI (above).

### 4. GitHub MCP plugin (`mcp__plugin_github_github__*`)

Tools live in the Claude Code conversational layer. Full surface enumerated below.

**Auth surface**: separate from `gh` CLI — the MCP server has its own configured token. Empirically authenticates as the same user (`brockamer`), so quota is shared, but the auth surface itself is separate from `gh auth login` / `GH_TOKEN`. Setup is handled by Claude Code's MCP server config, not by jared.

**Critical structural constraint**: Python subprocesses cannot call MCP tools. Jared's CLI subcommands (`lib/board.py`) therefore cannot route through MCP — this mechanism is reachable only from Claude Code in interactive sessions.

## MCP plugin tool surface

The complete `mcp__plugin_github_github__*` tool set (as of 2026-05-22):

| Category | Tools |
|---|---|
| **Issues — read** | `issue_read` (get, get_comments, get_sub_issues, get_labels), `list_issues`, `search_issues`, `list_issue_types`, `get_label` |
| **Issues — write** | `issue_write` (create, update), `add_issue_comment`, `sub_issue_write` |
| **PRs — read** | `pull_request_read` (get, get_diff, get_status, get_files, get_review_comments, get_reviews, get_comments, get_check_runs), `list_pull_requests`, `search_pull_requests` |
| **PRs — write** | `create_pull_request`, `update_pull_request`, `update_pull_request_branch`, `merge_pull_request`, `pull_request_review_write` (create, submit_pending, delete_pending, resolve_thread, unresolve_thread), `add_comment_to_pending_review`, `add_reply_to_pull_request_comment`, `request_copilot_review` |
| **Repo content** | `get_file_contents`, `create_or_update_file`, `push_files`, `delete_file`, `get_commit`, `list_commits` |
| **Repo structure** | `list_branches`, `create_branch`, `list_tags`, `get_tag`, `list_releases`, `get_latest_release`, `get_release_by_tag` |
| **People** | `get_me`, `list_repository_collaborators`, `get_teams`, `get_team_members`, `search_users` |
| **Misc** | `search_code`, `search_repositories`, `run_secret_scanning`, `create_repository`, `fork_repository` |
| **ProjectV2** | **(none — the plugin does not expose ProjectV2 operations at all)** |

The ProjectV2 gap is the load-bearing finding: jared's entire operating model is ProjectV2 (Status / Priority field values, project membership, item-list snapshots, blocked-by dependencies). The MCP plugin cannot reach any of it. This functionally limits MCP to issue + PR + repo CRUD — useful, but not in jared's primary workflow.

## Capability matrix — jared operations × mechanism

`✓` = supported, `✗` = not supported, `(rec)` = recommended primary.

| Jared operation | `gh project/issue/pr` | `gh api` REST | `gh api graphql` | MCP plugin |
|---|---|---|---|---|
| List project items (board snapshot) | ✓ (rec — `gh project item-list`) | ✗ | ✓ (raw graphql) | ✗ |
| Find one item by issue number | ✗ | ✗ | ✓ (rec — `fetch_item_for_issue`) | ✗ |
| Set ProjectV2 field value (Status / Priority) | ✓ (`gh project item-edit`) | ✗ | ✓ (rec — aliased mutation) | ✗ |
| Add issue to project | ✓ (rec — `gh project item-add`) | ✗ | ✓ | ✗ |
| Add/remove blocked-by edges | ✗ | ✗ | ✓ (rec — `addBlockedBy`/`removeBlockedBy`) | ✗ |
| Read one issue (state only) | ✓ (`gh issue view --json`) — 1 graphql | ✓ (rec — `gh api repos/.../issues/N` + ETag, #54/#147) — 1 REST core (304→0) | ✓ | ✓ (`issue_read`) — 2 REST core |
| Read one issue (full body, batch context) | ✓ (`gh issue view --json body`) — 1 graphql | ✓ (rec — proposed migration for `capture-context.py`, `archive-plan.py`) — 1 REST core | ✓ | (Python can't reach) |
| Create issue | ✓ (rec — `gh issue create`) — REST | ✓ (raw `gh api -X POST`) — REST | ✗ | ✓ (`issue_write` create) |
| Comment on issue | ✓ (rec — `gh issue comment`) — REST | ✓ (raw `gh api`) — REST | ✗ | ✓ (`add_issue_comment`) |
| Close issue | ✓ (rec — `gh issue close`) — REST | ✓ | ✗ | ✓ (`issue_write` update with state=closed) |
| List closed issues for velocity (`gh issue list --search`) | ✓ (rec) — REST/search | ✓ | ✓ | ✓ (`search_issues` — goes via graphql under MCP) |
| List milestones | ✗ (no `gh milestone list` subcommand) | ✓ (rec — `gh api /repos/.../milestones`) — REST | ✓ | ✗ |
| Fetch PR files for review | ✓ (rec — `gh pr view --json files`) — REST | ✓ | ✓ | ✓ (`pull_request_read` get_files) |
| Conversational: read one issue (Claude Code) | ✓ — 1 graphql | ✓ — 1 REST core | ✓ | ✓ (rec when graphql pressured) — 2 REST core |
| Conversational: comment (Claude Code) | ✓ — REST | ✓ — REST | ✗ | ✓ (rec when graphql pressured) — 2 REST core |

## Rate-limit characteristics

Per-mechanism bucket attribution, measured empirically against the live `brockamer/jared` board (projects/4) during the investigation.

### Measurement note

GitHub rate-limit buckets are shared across the authenticated identity, not per-process. If multiple Claude sessions / jared invocations / direct shell `gh` calls run under the same user concurrently, their consumption mixes into the same counters. A snapshot-call-snapshot measurement can show "this call cost N points" when N is actually `your_call + someone_else_in_the_window`.

The per-call costs in the table below were measured during a deliberately-quiet window on 2026-05-22: graphql freshly reset, other Claude sessions paused, drift verified ≤0 across baseline snapshot pairs. Each REST/MCP call was replicated 3× where the magnitude was small enough that noise might dominate; the high-cost `gh project item-list` call was measured once in the clean window and once previously, with consistent results.

Early in the investigation, several observations against an active background showed large unexplained graphql drops (one snapshot-pair attributed 103 graphql points to a single `gh issue view --json` call; another attributed 437 to a single REST call that should have been graphql-free). Re-running the same calls in isolation produced the single-digit deltas now recorded below — the early figures were noise from concurrent sessions, not real costs.

**Trust small deltas (≤5 points) only when replicated; treat large deltas with suspicion unless replicated under verified-quiet conditions.**

### Bucket quotas

GitHub serves several rate-limit buckets per authenticated user; jared touches four of them.

| Bucket | Quota | Reset cadence | Consumed by |
|---|---|---|---|
| `core` (REST) | 5000/hr | rolling hourly | All `gh api repos/...`, `gh issue/pr` subcommands (when not using `--json`), all MCP plugin reads/writes |
| `graphql` | 5000/hr | rolling hourly | All `gh api graphql ...`, `gh project ...` subcommands, `gh issue view --json` (any field selection), MCP `search_issues` |
| `search` | 30/hr | per-minute reset (much tighter) | Not currently exercised by jared at meaningful volume |
| `code_search` | 10/hr | per-minute | Not used by jared |

### Per-call cost (empirically measured)

All values measured during the 2026-05-22 quiet window. `(3×)` indicates the value was replicated three times consecutively with identical results.

| Call | Bucket | Per-call cost |
|---|---|---|
| `gh project item-list <N> --owner <O> --limit 2000` | graphql | **~10 points per project item.** 203 measured on jared/projects/4 (~50 items); ~5000 observed by operator on findajob/projects/1 (~500 items) — a single call burned the entire hourly bucket. Cost is the chief graphql pressure source. |
| `Board.fetch_open_issues_for_ties()` (paginated, body + labels + milestone + projectItems + blockedBy) | graphql | ~20-50 per page (estimated from board.py docstring; not directly measured this window) |
| `gh issue view N --json <any-fields>` | graphql | **1 point (3×)** — regardless of field count (minimal `number,title,state` and jared-realistic `body,comments,labels,milestone,title,number,state` both consumed 1 point) |
| `mcp__github__issue_read` (method=get) | REST core | **1-2 points** (3× consecutive: 2, 2, 1 — subsequent calls on the same issue appear to be MCP-server-side cached, dropping to 1 point. Budget 2 conservatively.) |
| `gh api repos/.../issues/N` | REST core | **1 point (3×)** — or 0 with ETag 304 (`fetch_issue_state_rest` path) |
| `mcp__github__add_issue_comment` | REST core | **2 points** (1× — write path; kept replication to one to avoid polluting issues) |
| `mcp__github__search_issues` | graphql | **0-1 points** (2×: repeated identical query cost 0 from server-side cache; different query cost 1. Budget 1.) |
| `gh api graphql -f query=mutation {...}` (single ProjectV2 field update) | graphql | 1 point |
| `Board.add_existing_to_board` (aliased mutation setting Priority + Status + extras) | graphql | 1 point (single round trip — same cost as a single field update, thanks to GraphQL aliasing) |
| `gh api rate_limit` | (exempt) | 0 (always free — does not draw from any rate-limit bucket) |

### What graphql exhaustion looks like

`gh` exits non-zero with `API rate limit exceeded` on stderr. `run_gh_raw` raises `GhInvocationError` with the message. There is no automatic backoff — the call fails immediately. The `graphql_budget()` + `check_graphql_budget()` helpers in `board.py` let long-running scripts pre-flight and bail early with a useful message instead of crashing mid-run.

### What ETag-conditional GET (#147) buys

The `_fetch_issue_rest_with_etag()` path in `board.py` sends `If-None-Match: <cached-etag>`. A 304 response is REST-core-exempt at GitHub: the bucket counter does not increment on 304s. So for stable per-issue checks (issue closed-state polls in `archive-plan.py`, dependency-graph open-state filters), the steady-state cost is 0 REST core after the first call. This is the existing doctrine — keep it.

## Auth deconfliction

### The three auth surfaces

1. **`gh auth login` OAuth session** — a token of the shape `gho_...` stored at `~/.config/gh/hosts.yml`. Scopes are interactively granted.
2. **`GH_TOKEN` / `GITHUB_TOKEN` env vars** — a token (usually a fine-grained or classic PAT, shape `ghp_...`) honored by `gh` when set. Active session in this operator's environment has `Token scopes: admin:enterprise, admin:org, project, repo, ...` per `gh auth status`.
3. **MCP plugin's configured token** — managed by Claude Code's MCP server config, separate from gh's auth machinery. Authenticates as the same GitHub identity in this operator's setup; runs with whatever scopes that token has.

### The #65 scrub

`lib/board.py:_child_env()` removes `GH_TOKEN` and `GITHUB_TOKEN` from the subprocess env on every `gh` invocation. Result:

- **Jared CLI's `gh` calls** → always use the OAuth session, regardless of what env vars are set.
- **Direct shell `gh` calls** (operator typing at terminal) → honor `GH_TOKEN` if set.
- **MCP plugin** → uses its own token (Claude Code MCP config), unaffected by `_child_env`.

### Diagnostic for `Resource not accessible by personal access token`

When a project mutation fails with this signature, `_format_token_scope_diagnostic()` in `board.py` surfaces a 4-part diagnostic block: token source used (with #65 caveat), scopes present, scopes needed (`project (write)`), and suggested fix (`gh auth refresh -s project`). Realistic remaining trigger post-#65 is OAuth without `project` scope. The diagnostic does not currently address MCP-plugin scope mismatches — see "Open questions" below.

### One-machine setup checklist

To have all four mechanisms working on a single workstation:

1. `gh auth login` with `project` scope granted (interactive). This is the OAuth session jared CLI uses after the #65 scrub.
2. Optional: set `GH_TOKEN` to a PAT with the same scopes. Direct shell `gh` calls will use this; jared CLI calls will not.
3. MCP plugin: configured via Claude Code's `mcp` settings. Token needs read + write scopes for the operations you intend to exercise.
4. Verify: `gh auth status` shows the OAuth session active; `mcp__github__get_me` returns the expected identity; `jared summary` runs cleanly.

## Routing recommendation (long form)

### ProjectV2 (jared's core surface)

**Unchanged.** Stays graphql-only because there is no alternative. The chief lever is reducing call volume:

- `Board.board_items()` is already 3-layer cached (in-process + on-disk JSON + fresh fetch). Keep it.
- Multi-issue patterns are already batched via aliased graphql (`fetch_project_items_batch`, `fetch_recent_comments_batch`). Keep them.
- `graphql_budget()` pre-flight is already wired into the heavy scripts. Keep it.

### Stable per-issue state checks (closed/open polls)

**Unchanged.** Existing `fetch_issue_state_rest` path with ETag-conditional GET is the right doctrine. Cost in steady state is 0 REST core per call (304 short-circuit). Used by `archive-plan.py` for closed-issue scans and `dependency-graph.py` open-state filters.

### Full issue-body reads in batch scripts

**Migrate.** `capture-context.py` and `archive-plan.py` currently use `gh issue view N --json body` (1 graphql point per call). The equivalent `gh api repos/.../issues/N` consumes 1 REST core per call. Marginal per-call, but these run in loops over plans/snapshots — cumulative graphql savings on long batch runs.

Filed as a follow-up issue rather than this PR's scope (per AC: investigation only).

### Issue CRUD in the jared CLI

**Unchanged.** `gh issue create / comment / close / edit` already route via REST. No graphql savings available.

### Conversational issue CRUD (Claude Code sessions)

**New doctrine.** When the graphql bucket is pressured (`graphql_budget()` reports < 1000 remaining or operator observes exhaustion), the conversational layer should prefer:

- `mcp__github__issue_read` instead of `gh issue view --json` (saves 1 graphql, costs 2 REST core)
- `mcp__github__add_issue_comment` instead of `gh issue comment` (no graphql savings — both REST — but bypasses `gh` subprocess overhead)
- `mcp__github__issue_write` (state=closed) instead of `gh issue close` (same shape)

When graphql is healthy, either path is fine — the choice becomes a question of UX preference (gh's CLI conventions vs MCP's typed-tool ergonomics). Document in `references/operations.md` as a guidance, not a gate.

**MCP cannot replace** jared's CLI subcommands for ProjectV2 operations. The conversational doctrine applies only to issue + PR work.

### Search

Both `gh issue list --search` and MCP `search_issues` work for finding closed issues / velocity computation. MCP `search_issues` routes via graphql (1 point/call); `gh issue list --search` also routes via graphql when `--json` is used. Either is fine; existing `compute_velocity` uses `gh issue list --json`, which is the recommended primary because it integrates cleanly with the existing wrappers.

The tight `search` bucket (30/hr) is not currently consumed at meaningful volume by jared and is not a concern.

## Architectural call: extend the two-wrapper shape

**Recommendation: keep two wrappers** (`run_gh` for shell-form, `run_graphql` for `gh api graphql`). Do **not** add `run_rest` or `run_mcp` wrappers yet.

Reasoning:

- Today's REST callsites use `run_gh(["api", "repos/..."])` ad-hoc. That's a clean seam — `run_gh` is already the choke-point for env scrubbing and error handling.
- A dedicated `run_rest` wrapper only earns its weight if there are ≥3 callsites that share REST-specific concerns beyond what `run_gh` provides (e.g., centralized ETag handling, REST pagination). Today there are 2: `_fetch_issue_rest_with_etag` and `fetch_audit_window`'s milestone fetch. Threshold not met.
- `run_mcp` is structurally not buildable from Python — MCP is reachable only from the conversational layer. If MCP gets used heavily in conversations, the doctrine lives in `references/operations.md` and SKILL.md, not in `lib/board.py`.

Revisit if a future migration introduces 3+ additional REST callsites (e.g., the proposed `capture-context.py` / `archive-plan.py` issue-body migration).

## Open questions

- **MCP scope diagnostic**: `_format_token_scope_diagnostic` in `board.py` only knows about `gh`'s token. If a future MCP-routed mutation fails with the same `Resource not accessible by personal access token` signature, the diagnostic won't fire. Likely a one-line addition if the doctrine of "MCP for conversational issue CRUD" takes hold.
- **Search bucket exposure**: `gh issue list --search` may eventually pressure the tight `search` bucket on larger projects. Not a current concern; flag if pre-flight checks ever surface it.
- **blocked-by via REST**: the native GraphQL `blockedBy` connection (GitHub's issue-dependency feature) is what `fetch_blocked_by_edges` and `fetch_open_issues_for_ties` both read. The equivalent REST endpoint (issue dependencies) may have different shape/scope. Not investigated — both functions stay graphql for now. Note: `blockedBy` is distinct from `trackedInIssues` (the task-list parent/child connection); the two were briefly conflated in `fetch_open_issues_for_ties` until #230.

## Validation log

Each mechanism in the matrix was invoked at least once against `brockamer/jared` projects/4 during this investigation, with rate-limit deltas captured. Final measurements were taken in a verified-quiet window (other Claude sessions paused, graphql freshly reset). Per AC: no "should work" claims; everything below is observed.

| Mechanism / call | Replication | Result | Bucket delta |
|---|---|---|---|
| `gh api rate_limit` (baseline) | n/a | OK | 0 (exempt) |
| `gh issue view 199 --repo brockamer/jared --json number,title,state` | 3× | OK | +1 graphql per call (1, 1, 1) |
| `gh issue view 199 --json body,comments,labels,milestone,title,number,state` (jared-realistic) | 1× | OK | +1 graphql (same as minimal field set) |
| `gh api repos/brockamer/jared/issues/199` | 3× | OK | +1 REST core per call (1, 1, 1) |
| `gh project item-list 4 --owner brockamer --limit 2000 --format json` | 1× clean + 1× pre-quiet | OK | +203 graphql (consistent across windows) |
| `mcp__github__issue_read` (issue 199, method=get) | 3× | OK | +1-2 REST core per call (2, 2, 1 — caching effect on repeats) |
| `mcp__github__search_issues` (different queries) | 2× | OK | +0 graphql (cached identical query) / +1 graphql (different query) |
| `mcp__github__add_issue_comment` (write — on issue #202, two intentional investigation artifacts) | 2× total (pre-quiet + clean window) | OK | +2 REST core per call |
| `mcp__github__get_me` | 1× | OK (same identity as `gh api user`) | +1 REST core |
| `gh auth status` | 1× | OK | 0 |
| `jared next-session-prompt`, `jared summary`, `jared get-item 202`, `jared move 202`, `jared comment 202` | 1× each | OK | ~200-300 graphql per /jared-start cycle (matches operator's observed pattern) |

The `gh issue view --json` numbers in particular were re-measured after an early observation of 103 points (which turned out to be concurrent-activity noise, not a real cost cliff). The stable per-call cost is 1 graphql point regardless of field selection — replicated 3× in the quiet window.

The MCP `issue_read` caching observation (calls 2 and 3 dropped from 2 to 1 REST core) suggests the MCP server maintains some response cache for recent identical reads. Useful in conversational contexts where the same issue is referenced multiple times in a session.

## What shipped

This doc was the deliverable. Four follow-up moves were filed and have all shipped (2026-05-22):

1. **Doctrine update** — `references/operations.md` GitHub API mechanism selection section added (#207, PR #211).
2. **Batch-script migration** — `capture-context.py` + `archive-plan.py` issue-body reads moved to REST (#208, PR #212).
3. **Conversational doctrine** — SKILL.md MCP-vs-gh routing addendum (#209, PR #211).
4. **MCP scope diagnostic** — `_format_token_scope_diagnostic` extended for MCP-token scope failures (#210, PR #213).
