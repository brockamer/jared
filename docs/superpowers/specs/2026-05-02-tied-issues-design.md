# Tied-issues pre-pull analysis — Design

**Issue:** [#77 — feat(jared-start): tied-issues pre-pull analysis](https://github.com/brockamer/jared/issues/77)
**Status:** Approved 2026-05-02
**Author:** brainstorm session, 2026-05-02

## Summary

Add a `jared ties <N>` CLI subcommand that analyzes the open board for issues with material ties to a target, and wire `/jared-start` to call it always-on so ties surface at pull time. Six deterministic signals; precision-biased default threshold; rate-limit-aware degraded modes; advisory output (never gates the start).

## Why

External feedback from a downstream project: `/jared-start` correctly drift-checks the target but doesn't catch *board-level* ties — open issues that should change the order of operations (superseded predecessors, feeder bugs, same-file polish, adjacent-scope bundling). The submitter's own session caught five such ties only by manually asking; without that prompt, work would have started against degraded inputs and shipped an under-bundled PR.

This extends jared's existing pullable-is-a-discipline rule from the issue level to the board level.

## Scope decisions

### Layer (Q1 → C, hybrid)

Cheap deterministic Python helper now; LLM-based semantic-tie overlay deferred to a follow-up issue. The cheap helper is the always-on path; the LLM pass is added later as an opt-in overlay over the cheap helper's structured output.

### Surface (Q2 → C, both)

Canonical CLI: `jared ties <N>`. Two entry points:

- `/jared-start <N>` calls it always-on after the drift check, before the announce. Output is injected as a "Ties to consider" block at the top of the announce.
- Operators can also invoke `jared ties <N>` standalone for ad-hoc deep dives, scripting, or already-In-Progress issues.

Same code path either way.

`/jared-reshape` does *not* call this — reshape is a structural review (10,000-foot pass), runs much less often than `/jared-start`, and the leverage is at pull time.

### Signals (Q3)

Six analyzers with confidence tags:

| Signal | Confidence | Rule |
|---|---|---|
| **a. cross_ref** | strong | Target body mentions `#N` (or `#N` body mentions target). Ignore `#N` inside fenced code blocks; require word-boundary. |
| **b. blocked_by** | strong | Native GitHub `addBlockedBy` edge in either direction. |
| **c. milestone** | strong | Same milestone as target. None ≠ None. |
| **f. file_paths** | medium | Both bodies mention same path-like token (`lib/board.py`, `tests/test_*.py`). Generic substrings (`README`, `CHANGELOG`) excluded. |
| **d. title_tokens** | weak | Title token Jaccard overlap above threshold; stop-words stripped; case-insensitive. |
| **e. labels** | weak | Non-stop-word label intersection. Stop-words = `{enhancement, bug, documentation, refactor}` by default; configurable per project. |

Deferred to LLM follow-up:

- **g. possibly_already_done** — open issue references symptoms in code that has since changed. Too judgment-y for cheap heuristics.

Dropped:

- **h. same-author-same-day** — useless on single-stakeholder projects (every issue is same author).

### Scope bounding (Q4 → A, no bound)

No candidate cap on the analysis universe. The expensive part is the GraphQL fetch, which is one batched call regardless of board size. Analyzers run over in-memory data; CPU-only and trivial unless N is huge. Output cap (separate concern) at 8 ties.

### Output shape (Q5 → C, compact + suggested action)

Compact one-liner per tie, sorted by combined_score desc, tie-broken by issue_number asc, capped at 8:

```
Ties to consider:
  #212 [strong, superseded]   close as superseded after target ships
  #345 [strong, feeder]       sequence #345 first, then target
  #215 [medium, same-file]    fold into target's PR
  #372 [medium, adjacent]     bundling vs fast-follow — your call (also same-file)
  ...
  (Suggestions are heuristic — operator decides.)
```

Multi-relationship handling: strongest signal as primary tag; secondary relationships as `(also <rel>, <rel>)` parenthetical. Single-relationship ties have no parenthetical.

### Threshold policy (Q6 → D, default medium with override)

Combined score: `strong=3, medium=2, weak=1`, capped at 5 per candidate.

| Threshold | Rule |
|---|---|
| `weak` | combined ≥ 1 |
| `medium` (default) | combined ≥ 3 (one strong, OR two medium, OR three weak, etc.) |
| `strong` | combined ≥ 3 AND at least one strong-signal hit |

Default is `medium` for the always-on `/jared-start` path. `--threshold weak` available for ad-hoc deep dives.

Pruning rules (always applied regardless of threshold):

- Self-suppression — never include the target itself.
- Closed-target dedup — if target is already closed, exit 0 with empty output.
- Stop-word labels — common labels (`enhancement`, `bug`, `documentation`, `refactor`) excluded from signal **e**.
- Non-pullable filtering — Done items excluded from candidate set; Blocked items included only when fired by signal **b** (native blocker) since blocked-by relationships are exactly what makes a Blocked item relevant.

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│ /jared-start (skill markdown)                                   │
│   1. drift check                                                │
│   2. WIP check                                                  │
│   3. read target body + Session note                            │
│   4. ▶ jared ties <N>                                           │
│        (capture stdout, inject as block in announce)            │
│   5. announce + confirm                                         │
└─────────────────────────────────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────────────┐
│ jared CLI: _cmd_ties                                            │
│   1. parse args (--threshold, --format)                         │
│   2. budget pre-flight via Board.graphql_budget()               │
│      ≥200 → full | 50–199 → partial | <50 → skip                │
│   3. fetch (Board) → analyze (lib/ties) → format → emit         │
└─────────────────────────────────────────────────────────────────┘
                       │
              ┌────────┴────────┐
              ▼                 ▼
┌───────────────────┐  ┌──────────────────────────────────────┐
│ lib/board.py      │  │ lib/ties.py (NEW, pure Python)       │
│   .fetch_open_    │  │   analyze_cross_references           │
│    issues_for_    │  │   analyze_blocked_by                 │
│    ties()         │  │   analyze_milestone_overlap          │
│      ↓            │  │   analyze_title_tokens               │
│   gh api graphql  │  │   analyze_labels                     │
│   --cache 5m      │  │   analyze_file_paths                 │
│                   │  │   combine(hits, threshold) → [Tie]   │
│                   │  │   format_ties_block(ties) → str      │
└───────────────────┘  └──────────────────────────────────────┘
```

The boundary: `Board` owns GitHub I/O; `lib/ties.py` is pure Python with zero I/O; `_cmd_ties` is orchestration glue. Each piece tests in isolation.

## Components & data structures

### `lib/ties.py` (new)

Dataclasses:

```python
@dataclass(frozen=True)
class SignalHit:
    related_n: int
    name: Literal["cross_ref", "blocked_by", "milestone",
                  "title_tokens", "labels", "file_paths"]
    confidence: Literal["strong", "medium", "weak"]
    evidence: str   # human-readable: "target body mentions #345"

@dataclass(frozen=True)
class Tie:
    related_n: int
    related_title: str
    related_status: str
    hits: tuple[SignalHit, ...]
    combined_score: int                      # strong=3, medium=2, weak=1, capped at 5
    primary_relationship: str
    secondary_relationships: tuple[str, ...]
    suggested_action: str
```

Public functions:

- `analyze_cross_references(target, open_issues, *, direction: Literal["forward", "both"] = "both") -> list[SignalHit]`
- `analyze_blocked_by(target, open_issues) -> list[SignalHit]` (reads `blocked_by` edges off the issue records)
- `analyze_milestone_overlap(target, open_issues) -> list[SignalHit]`
- `analyze_title_tokens(target, open_issues) -> list[SignalHit]`
- `analyze_labels(target, open_issues, *, stop_words: set[str]) -> list[SignalHit]`
- `analyze_file_paths(target, open_issues) -> list[SignalHit]` (requires bodies on both sides; not called in partial mode)
- `combine(hits: list[SignalHit], threshold: Literal["weak", "medium", "strong"], target) -> list[Tie]`
- `format_ties_block(ties: list[Tie], *, degraded: bool, diagnostic: str | None) -> str`

Stop-word source: `Board.tie_stop_words() -> set[str]` (reads `### Tie Analysis` section in `docs/project-board.md` if present, falls back to built-in defaults — see Stop-word configuration section below).

### `Board.fetch_open_issues_for_ties()` (extends `lib/board.py`)

Signature: `fetch_open_issues_for_ties(*, include_bodies: bool = True) -> list[OpenIssueForTies]`.

Single GraphQL query returning all open issues' titles, labels, milestones, status, priority, and `addBlockedBy` edges. When `include_bodies=True`, also returns body text. Cached via `cache="5m"`. Two cache keys (one per body inclusion) so partial-mode and full-mode runs can both cache independently. Excludes Done; includes Blocked.

`include_bodies=False` is used in partial (low-budget) mode — saves response size and (sometimes) GraphQL cost, more importantly avoids fetching what the partial-mode analyzers won't use.

### Analyzers and partial mode

`analyze_cross_references` takes a `direction: Literal["forward", "both"] = "both"` parameter. `forward` only checks the target body for `#N` references (target body is always available — `/jared-start` loads it before calling `jared ties`). `both` additionally checks every other open issue's body for references back to the target.

`analyze_file_paths` requires bodies on both sides; in partial mode (no other-issue bodies) it is skipped entirely.

The other four analyzers (`blocked_by`, `milestone_overlap`, `title_tokens`, `labels`) use only fields available in both modes.

### `_cmd_ties` (in `skills/jared/scripts/jared`)

Argparse subcommand. Skeleton:

```python
def _cmd_ties(args: argparse.Namespace) -> int:
    board = Board.from_path(Path(args.board))
    target = board.get_issue(args.issue_number)
    if target is None or target.state == "CLOSED":
        return 1   # target unresolvable

    remaining, _, _ = board.graphql_budget()
    if remaining < 50:
        print("(GraphQL budget exhausted — ties analysis skipped)")
        return 0

    full_mode = remaining >= 200
    open_issues = board.fetch_open_issues_for_ties(include_bodies=full_mode)
    diagnostic = None if full_mode else (
        "(low GraphQL budget — body-aware signals deferred, "
        "run jared ties <N> later for full pass)"
    )

    analyzers: list[tuple[str, Callable]] = [
        ("cross_ref", lambda t, o: analyze_cross_references(
            t, o, direction="both" if full_mode else "forward")),
        ("blocked_by", analyze_blocked_by),
        ("milestone", analyze_milestone_overlap),
        ("title_tokens", analyze_title_tokens),
        ("labels", lambda t, o: analyze_labels(t, o, stop_words=board.tie_stop_words())),
    ]
    if full_mode:
        analyzers.append(("file_paths", analyze_file_paths))

    hits: list[SignalHit] = []
    for name, analyze in analyzers:
        try:
            hits.extend(analyze(target, open_issues))
        except Exception as e:
            diagnostic = (diagnostic + " " if diagnostic else "") + \
                f"(analyzer {name} failed: {e})"

    ties = combine(hits, args.threshold, target)
    if args.format == "human":
        output = format_ties_block(ties, degraded=not full_mode, diagnostic=diagnostic)
    else:
        output = json.dumps([asdict(t) for t in ties], indent=2)
    if output:
        print(output)
    return 0
```

### Skill change: `commands/jared-start.md`

Insert a new step between drift check and announce. Pseudo:

```markdown
4. **Run tied-issues analysis** (advisory, never gates the start). Run
   `${CLAUDE_PLUGIN_ROOT}/skills/jared/scripts/jared ties <N>`. Capture
   stdout. If non-empty, prepend it to the announce as a block before
   the per-issue summary. Non-zero exit or empty stdout: skip the block.
```

## Data flow

1. Operator: `/jared-start <N>`
2. Skill: drift check, WIP check, read target body + Session note (existing).
3. Skill: `jared ties <N>` (default `--threshold medium --format human`).
4. `_cmd_ties`: budget pre-flight → fetch → analyze → combine → format → stdout.
5. Skill: capture stdout; non-empty → inject as first block of announce.
6. Operator: confirms; work begins.

## Error handling

Principle: ties analysis is **advisory** — its failure must never break `/jared-start`.

| Failure mode | exit code | stdout | `/jared-start` action |
|---|---|---|---|
| Target #N not found / closed | 1 | (none) | Drift check should catch first. If race: skill suppresses block, proceeds. |
| Budget exhausted (<50 pts) | 0 | `(GraphQL budget exhausted — ties analysis skipped)` | Render diagnostic line, proceed. |
| Budget low (50–199 pts) | 0 | Partial-mode block + low-budget note | Render block as-is. |
| GraphQL fetch fails | 0 | `(ties analysis unavailable: <one-line>)` | Render diagnostic, proceed. |
| `BoardConfigError` / parse failure | 1 | error to stderr | Skill notices non-zero, suppresses block. |
| Empty open set OR no ties cross threshold | 0 | (empty) | Skill suppresses block. |
| Analyzer crash | 0 | `(ties analyzer error: <exception>)` | Render diagnostic, proceed. |

Stderr policy: developer-friendly fragments to stderr; skill captures but doesn't include in announce.

Typed exceptions used directly (no rewrap): `BoardConfigError`, `FieldNotFound`, `ItemNotFound`, `GhInvocationError`. Top-level `_cmd_ties` catches them and converts to one-line stderr + appropriate exit code.

## Testing

| Test file | Coverage | Approx test count |
|---|---|---|
| `tests/test_ties_analyzers.py` | Per-analyzer positive, negative, edge cases | ~12 |
| `tests/test_ties_combine.py` | Threshold logic, sort order, cap, multi-relationship, action mapping | ~8 |
| `tests/test_ties_format.py` | Golden output for all output shapes | ~6 |
| `tests/test_board_fetch_for_ties.py` | One-call assertion, cache flag, response parsing | ~3 |
| `tests/test_cmd_ties.py` | CLI smoke, budget branches, exit codes, JSON format | ~6 |
| `tests/test_ties_integration.py` (`@pytest.mark.integration`) | E2E against `jared-testbed` | 1 |

Net: ~36 new tests; suite goes from 131 to ~167.

Test machinery: existing `tests/conftest.py` helpers — `patch_gh`, `patch_gh_by_arg`, `import_cli`. Respect the dual-import-path gotcha (CLAUDE.md) — pure functions in `lib/ties.py` aren't affected, but `Board` patches must work for both import paths.

`/jared-start` skill behavior is verified by reading the spec + a manual smoke run after merge. The skill itself isn't unit-testable.

## Stop-word configuration

Reads from `docs/project-board.md` if a `### Tie Analysis` section with `- Label stop-words: <list>` exists; falls back to built-in `{"enhancement", "bug", "documentation", "refactor"}`. No required schema change to existing project-board.md docs — fully backward-compatible.

## Out of scope (filed as follow-ups)

1. **LLM-pass overlay (signal g, semantic ties).** Build on the structured output of the cheap helper. Filed as a separate issue.
2. **`--fresh` flag** to bypass the 5-min GraphQL cache. Defer until requested. (`gh api --no-cache` semantics; ~3 LOC change.)
3. **Cross-board ties.** Ties limited to the current project. A future "tied-issues across coordinated boards" feature is interesting but out of v1.

## Acceptance

A `/jared-start <N>` session that pulls a target with strong ties to other open issues *also* surfaces a "Ties to consider" block listing the top candidates with relationship type, confidence tag, and suggested action. The block is suppressed when nothing crosses confidence threshold. Operator can act, defer, or ignore. Standalone `jared ties <N>` works the same way at the terminal.

Concrete acceptance tests:

- A board where issue A's body contains `#B` → `jared ties A` surfaces B with `[strong, cross-ref]`.
- A board where A and B share only a milestone (single strong, combined = 3) → surfaces at all three thresholds (medium and strong both require ≥ 3, and milestone is a strong-signal hit).
- A board where A and B share only same-file body mentions and a non-stop-word label (medium + weak, combined = 3) → surfaces at `weak` and `medium`; does NOT surface at `strong` (no strong-signal hit).
- A board where A and B share only a non-stop-word label and overlapping title tokens (weak + weak, combined = 2) → surfaces at `weak`; does NOT surface at `medium` or `strong`.
- A board where the only relationship between A and B is the `enhancement` label (stop-word) → does NOT surface at any threshold.
- Budget pre-flight: mocked `graphql_budget()` returning 100 remaining → output contains the partial-mode diagnostic line; signals f and reverse-direction cross_ref are skipped.
- Budget pre-flight: mocked `graphql_budget()` returning 25 remaining → output is exactly the budget-exhausted skip line; exit code 0.
- `pytest && ruff check . && mypy --strict` all clean.
