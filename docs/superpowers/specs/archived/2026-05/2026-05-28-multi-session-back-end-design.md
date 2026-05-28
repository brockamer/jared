---
**Shipped in #233 on 2026-05-28. Final decisions captured in issue body.**
---

# Multi-session back-end: stage proposal, start filter, wrap merge

**Issue:** #233
**Date:** 2026-05-28
**Status:** Shipped via PR #271 (closes #270) and PR #273 (closes #253, #272). Parent epic #233 closed 2026-05-28.
**Related issues:** #270, #253, #272 (all closed). #233 v0.22 multi-session readiness umbrella (closed).
**Related references:** `skills/jared/references/parallel-sessions.md`, `docs/superpowers/specs/archived/2026-05/2026-05-23-multi-session-impl-design.md`.

## Problem

The plugin supports parallel Claude Code sessions (one operator, one repo, one machine) at the mechanism layer — issue-keyed session locks (`lib/session_lock.py`, post-#259), worktree creation on `/jared-start --session N`, per-session WIP arithmetic in `jared summary`, and a session-presence lock that refuses risky B-leg starts. The `session-N` GitHub labels (`session-1`, `session-2`) exist as a partition convention.

What does **not** work is the operator workflow. Demonstrated gaps:

1. **Stage doesn't honor or propose the partition.** Operators apply `session-N` labels manually via `gh issue edit`. There is no Jared surface that suggests assignments, and no surface that surfaces drift as the board changes.
2. **Start's menu ignores the partition.** `/jared-start --session 1` (without an issue argument) shows the global top-3 of Up Next — not the session-1-labeled subset. The operator must mentally cross-reference labels before choosing.
3. **Wrap stops short of the merge.** Step 5 removes a worktree only *if* the branch already merged — wrap never pushes, creates a PR, checks mergeability, or merges. The operator runs `git push`, `gh pr create`, `gh pr merge --merge --delete-branch` by hand for each session.

The result: the mechanism is correct but the experience is high-ceremony. Two sessions can run safely, but the operator carries the partition + merge ritual entirely by hand.

## Goals

- **Stage proposes session-N assignments** based on a single signal (file-paths overlap), respecting existing labels (manual overrides win).
- **Stage maintains the partition** — re-running `/jared-stage` considers the current labels plus new Up Next candidates and proposes deltas.
- **Start's recommendation respects the partition** — `/jared-start --session N` filters its menu to `session-N`-labeled Up Next items.
- **Wrap runs the commit → push → PR → merge → cleanup back-end automatically up to the irreversible step**, with the operator confirming the merge.
- **Idempotent re-run** — wrap can be re-invoked at any failure point and picks up from the current state.

## Non-goals

These were considered and explicitly cut as overengineering for the two-session-one-operator-one-machine use case:

- **Multi-signal weighted partition scoring.** File paths in body is the only signal. Title-scope, label-cluster, and plan-doc signals are marginal value for batches of ~10 candidates that the operator can eyeball.
- **Surface-fingerprint cache or `--annotate` issue comments.** ~10 body reads per stage run is not a measured bottleneck. ETag caching at the fetch layer (#216, on the roadmap) addresses the real cost when it manifests. Profile first; cache later.
- **Polling wait-for-checks.** Wrap checks PR status once and exits if not green. Re-run wrap to pick up. No 30-second poll loop, no 10-minute timeout — idempotent re-run is the loop.
- **Integration merge smoke test.** Unit-test the state-detection logic. The merge step is `gh pr merge --merge --delete-branch` — a one-line shell-out that GitHub validates atomically. Failure surfaces as a clear gh error.
- **Hard merge-serialization lock.** GitHub's PR-merge API is atomic; concurrent `gh pr merge` calls cannot corrupt main. The second one rejects with "not mergeable" if there's an overlap. A Jared-side lock would solve a problem GitHub already solves.
- **Active groom integration in v1.** `/jared-groom` does not surface stale session-N labels. "Up to date" is operator-driven: re-running `/jared-stage` is the rebalance trigger.
- **Auto-application of session-N labels by `/jared-start` or `/jared-file`.** Operator approval gates every label change (in stage proposal output).

## Architecture

Three phases across the three existing slash commands. No new top-level command.

```
PHASE         COMMAND                     OWNS
─────────────────────────────────────────────────────────────────────
1. Partition  /jared-stage --sessions N   Propose label deltas across
                                          existing labels + Up Next
2. Pull       /jared-start --session N    Filter recommendation by
                                          session-N label
3. Land       /jared-wrap                 Commit → push → PR create →
                                          mergeable check → confirm
                                          merge → cleanup
```

The `session-N` GitHub label is the durable identity carried between phases. Each phase queries it; nothing else needs to coordinate.

## Phase 1 — Stage proposal

### Signal

A single signal: **file paths mentioned in the issue body**. Two candidates whose bodies cite overlapping file paths are presumed to touch overlapping code. Extraction reuses `lib/ties.py`'s existing `_file_paths_in_body` regex (path-like tokens with slash or code/doc extension; excludes generic files like `README.md`, `CHANGELOG.md`).

### Reuse from `lib/ties.py` (option 2 refactor)

Promote four symbols from private (leading `_`) to public:

| Currently | After |
|---|---|
| `_file_paths_in_body(body)` | `file_paths_in_body(body)` |
| `_GENERIC_FILES` | `GENERIC_FILES` |
| `_tokenize_title(title)` | `tokenize_title(title)` |
| `_FILE_PATH_RE` | `FILE_PATH_RE` |

The rename is mechanical — four underscores. Docstrings updated to reflect public status. Existing callers in `ties.py` updated to use the public names. No behavior change.

The new `lib/partition.py` imports these from `ties` directly. `SignalHit` and `OpenIssueForTies` dataclasses are reused as-is.

### `lib/partition.py` — new module (~100 lines)

```python
@dataclass(frozen=True)
class Assignment:
    """Proposed session-N assignment for one issue."""
    issue: int
    session: int | None  # None == float (no label)
    reason: str  # short rationale: "respects existing label", "lowest-overlap", "float"


@dataclass(frozen=True)
class Proposal:
    """Full stage proposal across a candidate set."""
    keep: list[Assignment]   # existing label honored
    move: list[Assignment]   # existing label, proposing different session
    add: list[Assignment]    # no existing label, proposing one
    floats: list[Assignment] # no overlap signal, no label proposed


def extract_surface(body: str) -> frozenset[str]:
    """Surface = file paths cited in the body. Single signal."""
    return file_paths_in_body(body)  # imported from ties


def propose_partition(
    candidates: list[OpenIssueForTies],
    K: int,
    existing_session_labels: dict[int, int],
) -> Proposal:
    """Greedy partition: walk candidates in priority order, assign each to the
    session with the largest cumulative surface-overlap so far (cohesion-first:
    co-locate work that shares files, so conflict-prone items land in one
    session rather than across sessions). Tie-break by load-balance (smaller
    session wins). Existing labels are honored unless the operator opts into a
    full re-balance (a future flag — not in v1).

    A candidate with no surface signal is a float: no proposal.
    """
```

### Algorithm

For each candidate in priority order:

1. If it has an existing `session-N` label and N ≤ K, propose `keep` (honor the operator's prior decision).
2. If it has no surface signal (no file paths in body), propose `float` (no label).
3. Otherwise, compute its overlap (set-intersection of surface) against each session's current cumulative surface. Pick the session with the **largest** intersection (cohesion-first — co-locate items that share files). Tie-break by smaller per-session load.

Output as a `Proposal` — `keep`/`move`/`add`/`floats` lists.

### `/jared-stage --sessions N` surface

Reads current board state (Up Next + Backlog top candidates + currently-labeled session-N items In Progress). Runs `propose_partition`. Renders an operator review block:

```
Looking at 11 candidates across sessions 1 and 2.

session-1 (currently 4 items, proposing 5):
  keep #223, #216, #190, #178 — already labeled
  add  #233 — body mentions lib/board.py (shared surface with #216)

session-2 (currently 4 items, proposing 4):
  keep #229, #192, #191, #140 — already labeled

floats (no surface signal):
  #253 — no file paths in body

Approve? (y / edit #N session=N / skip)
```

On approve, apply labels via `gh issue edit ... --add-label session-N` for each proposed `add` and `move`. Label application is per-item via `Board` (no new gh wrapper needed).

### CLI

New subcommand:

```
jared propose-partition --sessions N [--format human|json]
```

The slash command shells out to this and renders the human-format output. Programmatic consumers (tests, future automation) use `--format json`.

## Phase 2 — Start filter

### Extend `jared next-session-prompt`

Add `--session N` flag. When present, filter the `## Top of Up Next` section to issues whose label set includes `session-N`. `## In flight` and `## Recently closed` are unfiltered (they reflect actual board state, not a candidate pool).

```
jared next-session-prompt --session 1 [--include-session-checks] [--fresh]
```

Filter is applied after fetch + sort, before the top-3 cap. Behavior with no matching items: print `(none labeled session-1)` under the heading; do not fall through to unlabeled items (silent fallthrough would defeat the partition).

### `/jared-start --session N` integration

The slash command (`commands/jared-start.md` step 1) currently runs:

```bash
jared next-session-prompt --include-session-checks
```

Update to pass `--session $SESSION_FLAG` when the operator's `--session N` argument is present:

```bash
jared next-session-prompt --include-session-checks ${SESSION_FLAG:+--session $SESSION_FLAG}
```

When `$ARGUMENTS` is empty, the menu shown for "which issue would you like to pull?" is now the session-N-filtered Top of Up Next.

## Phase 3 — Wrap back-end

### State-detection idempotency

Wrap does not need a "wrap-in-progress" lock. Each step inspects state and decides whether to act:

| Pre-state | Action |
|---|---|
| Working tree dirty | Pause; prompt for commit message; commit (single confirm) |
| Local branch ahead of remote | `git push -u origin <branch>` |
| No PR for branch | `gh pr create` with auto-generated title + body |
| PR exists, checks pending | Surface PR # + check status; exit clean |
| PR exists, checks failed | Surface failed check names; exit clean |
| PR exists, checks green, `mergeable: false` | Surface conflict; exit clean |
| PR exists, checks green, `mergeable: true` | Show confirm-merge block; on yes, merge |
| PR merged, branch still local | Worktree-remove + branch-d (existing step) |
| Session lock present | Clear lock (existing step) |

Re-running wrap re-evaluates state and picks up at the appropriate step. The state IS the lock.

### Commit prompt

If the working tree is dirty:

```
Working tree has uncommitted changes:
  M skills/jared/scripts/lib/partition.py
  A tests/test_partition.py

Commit message? (or "skip" to leave uncommitted and exit)
> _
```

Operator types a message; wrap runs `git add -A && git commit -m "$msg"`. No automatic message generation — the operator's commit-message discipline (phase-numbered, "why not what") is preserved.

### PR body template

When wrap creates a PR:

```
Closes #<N>.

<first paragraph of issue body, verbatim>

## Commits
<one line per commit on the branch since origin/main, just subject>

🤖 Generated with [Claude Code](https://claude.com/claude-code)
```

PR title: the issue title verbatim (which is already conventional-commit-shaped by convention).

Operator can `[e]dit` the title/body at the confirm-merge block — wrap prompts inline for the new values, pushes the changes via `gh pr edit`, then re-shows the block.

### Confirm-merge block

```
PR #<N>: <title>
  branch:     feature/<N>-worktree
  mergeable:  yes
  checks:     all green (3/3)
  sibling:    session-2 has PR #<M> open on feature/<M>-worktree (independent surface)

Merge? (y / edit / no)
```

On `y`: `gh pr merge <N> --merge --delete-branch`. After successful merge, the existing worktree-remove + branch-d + lock-clear steps run.

On `edit`: prompt for new title/body inline, push via `gh pr edit`, re-show the block with the updated values.

On `no` / Ctrl+C: exit clean. Re-running wrap re-enters the state machine.

### Failure handling

Each step's failure is surfaced to the operator with the underlying `gh` or `git` error and the wrap step exits clean. Re-running wrap evaluates the new state. No automatic retry, no destructive recovery.

Example: `gh pr create` fails due to a missing token scope. Wrap prints the gh error and exits. Operator fixes the scope (or auths), re-runs wrap. Wrap detects the branch is pushed but no PR exists, attempts `gh pr create` again.

### Concurrent-merge safety

Two sessions reaching the merge step at the same time: each wrap re-checks `mergeable` immediately before calling `gh pr merge`. GitHub's PR merge API is atomic — the first call serializes ahead of the second. The second's pre-merge check returns `mergeable: true` (if no surface overlap) or `mergeable: false` (if the first's merge created a conflict). On `mergeable: false`, the second wrap surfaces the conflict and exits clean; the operator rebases in the worktree and re-runs wrap.

No Jared-side serialization is needed. GitHub atomicity is the safety net.

## Tracked work

Two PRs, doctrine piggybacks.

### PR 1 — Start-side filter (ship first, standalone)

Tiny diff. Stands alone — useful even if PR 2 never lands.

- Add `--session N` flag to `jared next-session-prompt`
- Update `commands/jared-start.md` step 1 to pass through the flag
- Unit tests for the filter

**Lands as:** new issue, e.g., `feat(start): --session N filter on next-session-prompt`.

### PR 2 — Stage proposal + wrap back-end

Larger diff covering both the partition system and the wrap back-end.

- Promote `_file_paths_in_body`, `_GENERIC_FILES`, `_tokenize_title`, `_FILE_PATH_RE` to public in `lib/ties.py`
- New `lib/partition.py` with `Assignment`, `Proposal`, `extract_surface`, `propose_partition`
- New `jared propose-partition --sessions N` CLI subcommand
- Update `commands/jared-stage.md` to drive the proposal flow
- Update `commands/jared-wrap.md` with the back-end flow steps (commit prompt → push → PR create → mergeable check → confirm merge → existing cleanup)
- Update `references/parallel-sessions.md` to describe the new flow
- Unit tests: partition algorithm, ties.py promotion (existing tests should pass unchanged), wrap state-detection logic
- No integration merge smoke; manual verification in a real two-session workflow before merge

**Lands as:** #253 (extend scope from "propose alongside promotions" to "propose + maintain") + new issue for wrap back-end. Both PRs reference both issues if work is bundled, or split across two PRs if cleaner.

### Doctrine

Updates to `references/parallel-sessions.md`:

- New section: "How partition is proposed" — single-signal file-paths overlap, operator approval gates label changes.
- Update existing "Pre-parallel-session operator ritual" section to point at `/jared-stage --sessions N` instead of manual labeling.
- New section: "The wrap back-end" — what wrap automates, what it confirms, what state means for re-run idempotency.

Doctrine lands with whichever PR ships second to keep doctrine + code in sync.

## Testing

### Unit tests

- **`tests/test_partition.py`** — partition algorithm. Deterministic input → deterministic output. Cases:
  - All candidates have existing labels → all `keep`, no `move`/`add`
  - No existing labels, two disjoint surface clusters → clean 2-way split
  - No existing labels, one cluster dominates → load-balance kicks in
  - Float candidate (no surface signal) → no label proposed
  - Existing label + zero overlap with same-session items → `keep` (no spurious `move`)
- **`tests/test_ties.py`** — existing tests should pass unchanged after the underscore-removal refactor. Add one test confirming the public symbols are importable.
- **`tests/test_cmd_next_session_prompt.py`** — `--session N` filter. Cases:
  - Items labeled session-1 surface; items labeled session-2 hidden
  - No matching items → `(none labeled session-N)` rendered
  - No `--session` flag → unfiltered output (no regression)
- **`tests/test_cmd_wrap_state.py`** — state-detection table. Pure function: `(git_state, pr_state) → next_step`. Each row in the state table is one test.

### What's not tested

- The merge step itself (`gh pr merge --merge --delete-branch`) — single-line shell-out, GitHub validates atomically, failure surfaces clearly.
- Cross-session integration — exercised manually in real two-session use before each PR merges.
- `/jared-stage` end-to-end with real label application — manual verification against `jared-testbed`.

## Out-of-scope, deferred

- **Surface cache.** Profile first. If `/jared-stage` becomes slow on real boards, add `<repo>/.jared/cache/surface-<issue>.json` with body-hash invalidation. Reuses the existing `lib/cache.py` infrastructure pattern.
- **`--annotate` flag** to write surface findings as GitHub issue comments. Cross-machine / cross-operator concern. Not relevant for the one-machine use case.
- **Multi-signal weighted partition scoring.** When a real surface overlap goes undetected by file-paths-only and creates a merge conflict, that's the trigger to add title-scope or label-cluster signals.
- **`/jared-groom` integration to surface stale labels.** Operator-driven rebalance (re-running stage) is sufficient for v1.
- **Polling wait-for-checks.** Adds value if the operator wants wrap to block until checks finish. Not present in v1 — operator re-runs wrap when ready.
- **Auto-application of session-N labels by `/jared-file` or `/jared-start`.** Every label change goes through operator approval in stage.

## Open questions

None at design time. Implementation may surface details — file these as plan-level adjustments rather than re-opening the spec.
