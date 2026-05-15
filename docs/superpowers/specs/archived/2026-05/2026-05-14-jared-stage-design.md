---
**Shipped in #128 on 2026-05-15. Final decisions captured in issue body.**
---

# Design — `/jared-stage`: continuous staging discipline

**Date:** 2026-05-14
**Status:** Approved (awaiting user review of this spec before implementation plan)

## Issue

- #128

## Problem

Jared today is deliberately advisory: `/jared-groom` flags drift and proposes, `/jared-start` pulls when asked, but nothing promotes Backlog → Up Next, re-checks whether Blocked items' blockers have closed, or runs on a schedule. The operator ends up manually asking Claude to "stage the next few items" — exactly the pattern Jared was built to absorb.

The 2026-05-14 groom on the jared board demonstrated the gap concretely: `sweep.py::check_in_progress_empty` fired "consider pulling the top of Up Next" while Up Next was *also* empty. The sweep checks Up Next *size* (flagging when > 3) but is silent when Up Next is *empty* — and nothing in jared promotes Backlog items into Up Next under any cadence or trigger.

## Design decisions

### 1. Autonomy: advisory + scheduled

Preserve "Jared mirrors decisions, doesn't make them" (SKILL.md § "The lane"). `/jared-stage` evaluates the Backlog under fixed criteria and *proposes* the next N for promotion; the operator approves per-item or as a batch before any `jared move` runs. `/schedule` integration removes the "remembering to evaluate" burden without ceding decision authority.

Rejected: auto-promote-with-veto and fully-autonomous variants. Both shift Jared from a mirror to a prioritizer of record — a doctrine change with ripples beyond this feature.

### 2. Surface: new `/jared-stage` command

Dedicated slash command, not a fold-in to `/jared-groom`. Three reasons:

- **Mental model fit.** Operators ask "stage the next items" as a focused action, not as part of broader grooming.
- **Cadence separation.** Staging benefits from daily evaluation; the rest of grooming (metadata-completeness, plan/spec drift, legacy-priority labels) needs only weekly or on-demand cadence.
- **Composability.** `/jared-groom` can cross-reference staging without bundling its logic, keeping each command's surface coherent.

### 3. Ranking: Priority > milestone proximity > age in Backlog

Within the population of items that pass two non-negotiable filters (pullable + dependency-ready), the rank order is:

1. **Priority** — High > Medium > Low. Canonical per SKILL.md.
2. **Milestone proximity** — days from now until `milestone.due_on`. Items without a due-dated milestone come last within their tier (sort key = `math.inf`).
3. **Age in Backlog** — older items rank higher within (Priority, milestone). Implements "stale High Backlog should be promoted or downgraded" as a positive promotion signal rather than only as the existing aging-flag.

Non-negotiable filters drop items from consideration before ranking applies. An item that is unpullable or has an open blocker never gets promoted by `/jared-stage` regardless of its Priority.

### 4. Blocked revisit: conservative

For each item in the Blocked column, check both native blocker edges (`addBlockedBy` GraphQL edges, fetched via `lib/board.py`'s `fetch_blocked_by_edges`) AND issue references parsed from the `## Blocked by` body section (regex `#\d+`).

When all blockers are closed:

- If `## Blocked by` contains text beyond `#\d+` references (real-world annotation, e.g., #60's "waiting on next non-trivial findajob session"): surface the item as "still Blocked, check manually" — never auto-revisit.
- Otherwise: propose moving to Backlog. The next stage pass treats it as a regular candidate and promotes if it ranks.

Return destination is Backlog, not Up Next directly. Conservative; preserves the ranking discipline (a low-priority unblocked item doesn't jump to Up Next).

### 5. Scheduling: external via `/schedule`; `--report-only` flag

`/schedule` owns the cron mechanics. The operator configures their preferred cadence:

```
/schedule jared-stage daily at 9am
```

`/schedule` invokes `/jared-stage --report-only` at the configured times. The flag suppresses the "Approve?" prompt; output goes to `/schedule`'s default delivery surface (notification, log thread). The operator re-runs `/jared-stage` interactively in a session to apply.

Two modes, one slash command, one underlying script:

| Trigger | Mode | Output | Apply path |
|---|---|---|---|
| Interactive | normal | conversation | inline approval (`y` / `<numbers>` / `skip`) |
| Scheduled fire | `--report-only` | `/schedule` default | informational only |

### 6. Kill switch: none

Opt-in is implicit. If the operator never invokes `/jared-stage` and never schedules it, no staging activity occurs on their board. No `staging: disabled` bullet under `## Jared config` — different shape from `model-guidance: disabled`, which exists because guidance is *emitted into every new issue* and operators on suppressing projects need a way to refuse the emission. Staging has no file-time emission; the kill switch is unneeded.

## Architecture

### New files

- **`skills/jared/scripts/stage.py`** — batch script.
  - Fetches Backlog + Blocked items via `lib/board.py`'s `run_gh*` wrappers (with `--cache 60s` per cache discipline).
  - Evaluates filters + ranks + revisits Blocked items.
  - Emits the proposal block to stdout in the documented format.
  - Pure functions (`is_pullable`, `has_no_open_blockers`, `has_real_world_annotation`, `priority_rank`, `milestone_proximity_days`, ranking comparator) are independently testable.
  - Passes `ruff` + `mypy --strict` alongside the rest of the tree.

- **`commands/jared-stage.md`** — slash command.
  - Invokes `stage.py`, displays output, walks operator through approve / cherry-pick / skip.
  - Applies approved promotions via `jared move <N> "Up Next"`.
  - Applies approved unblocks via `jared move <N> "Backlog"`.
  - Documents the `--report-only` flag and the recommended `/schedule` setup.

- **`tests/test_stage.py`** — unit tests for pure functions; integration test optional per the existing `pytest -m integration` pattern against `brockamer/jared-testbed`.

### Touched files (light)

- **`skills/jared/SKILL.md`** — add a brief subsection under § "Periodically — groom" naming staging as the forward-looking complement to grooming's backward-looking sweep. One paragraph.
- **`skills/jared/references/board-sweep.md`** — cross-reference staging from grooming.
- **`commands/jared-wrap.md`** — optional "see also" line for discoverability.

### Integration points

- **`lib/board.py`**: uses existing `fetch_items`, `fetch_blocked_by_edges`, field-ID lookups. No new helpers unless DRY-at-2 becomes obvious during implementation.
- **`jared` CLI**: uses existing `jared move` for applies. No new subcommand for staging itself.
- **`/schedule` skill**: external; operator configures the cron. Jared has no scheduling infra.
- **`dependency-graph.py`**: independent. `stage.py` reads blocker edges directly via `lib/board.py`, matching the existing batch-script-independence pattern.

## Algorithm

```python
def stage_proposals(board: Board, up_next_cap: int = 3) -> StageProposals:
    items = board.fetch_items()   # one fetch, shared across both passes

    slots_available = max(0, up_next_cap - count_status(items, "Up Next"))
    backlog = [i for i in items if i.status == "Backlog"]
    deferred: list[DeferredItem] = []   # everything not promoted, with one-line reason

    # === Filter: pullable (shape) ===
    pullable, not_pullable = partition(backlog, is_pullable)
    for item in not_pullable:
        deferred.append(DeferredItem(item, "not pullable — no acceptance criteria"))

    # === Filter: dependency-ready ===
    dep_ready, dep_blocked = partition(pullable, lambda i: has_no_open_blockers(i, items))
    # dep_blocked items are surfaced via `almost_ready`, not `deferred`

    # === Rank dep_ready and split into promote / defer ===
    rank_key = lambda i: (
        priority_rank(i.priority),       # 0=High, 1=Medium, 2=Low
        milestone_proximity_days(i),     # days to due_on; no milestone or no due_on = math.inf
        -days_in_backlog(i),             # older wins (negate so ascending = older first)
    )
    ranked = sorted(dep_ready, key=rank_key)
    promotions = ranked[:slots_available]
    for item in ranked[slots_available:]:
        deferred.append(DeferredItem(item, deferred_reason(item)))

    # === Blocked revisit ===
    unblocked, real_world_still_blocked = [], []
    for item in [i for i in items if i.status == "Blocked"]:
        if (any_open_blocker_native(item, items)
            or any_open_blocker_body_ref(item, items)):
            continue
        if has_real_world_annotation(item):
            real_world_still_blocked.append(item)
        else:
            unblocked.append(item)

    # === Almost ready (top 3 dep_blocked items by the same rank order) ===
    almost_ready = sorted(dep_blocked, key=rank_key)[:3]

    return StageProposals(
        promotions=promotions,
        deferred=deferred,
        unblocked=unblocked,
        real_world_still_blocked=real_world_still_blocked,
        almost_ready=almost_ready,
    )
```

`StageProposals` is a frozen dataclass with five fields: `promotions`, `deferred`, `unblocked`, `real_world_still_blocked`, `almost_ready`. The rendering layer (in `stage.py`'s `main()` or a sibling `render()` function) consumes the dataclass and produces the stdout block documented under [Output shape](#output-shape).

`deferred_reason(item)` is a heuristic that returns a one-liner naming the dominant reason this item didn't make the slot cut: `"Low tier"`, `"no milestone with due date"`, `"older items promoted first"`, or `"ranked below slot cap"`. Implementation picks the most-specific applicable reason; the spec doesn't pin the precise tie-breaking logic since the output is advisory text, not a contract.

### Filter semantics

| Function | Definition |
|---|---|
| `is_pullable(item)` | First paragraph of body is non-empty and not the template placeholder `One-sentence summary of what this issue is about and why it matters.` `## Acceptance criteria` section exists AND its `<details>` block has ≥1 non-placeholder bullet (not `Criterion 1`, `Criterion 2`, etc.). |
| `has_no_open_blockers(item, items)` | All `addBlockedBy` edges point to closed issues AND all `#\d+` references parsed from the `## Blocked by` section body point to closed issues. |
| `has_real_world_annotation(item)` | After stripping `#\d+` matches from the `## Blocked by` section body, ≥10 non-whitespace characters remain. Heuristic — surfaces #60's "waiting on next non-trivial findajob session" pattern. |
| `milestone_proximity_days(item)` | `(item.milestone.due_on - today()).days` if milestone has `due_on`; else `math.inf`. |
| `days_in_backlog(item)` | Days since the item's most recent transition into Status=Backlog. If transition history isn't accessible via the GitHub API at reasonable cost, fall back to `(today() - item.created_at).days` — acceptable approximation since most items don't migrate columns repeatedly. |

## Output shape

```
/jared-stage — proposals YYYY-MM-DD HH:MM

== Backlog → Up Next ==
Up Next: <current>/<cap> (<slots> slots available)

Promote:
  #<N> [<Priority>] <title>
        <milestone> (<due-state>) · <Nd> in Backlog
  ...

Deferred (this pass):
  #<N> [<Priority>] <title> — <reason>
  ...

== Blocked revisit ==

Unblocked (propose moving to Backlog):
  #<N> <title>      (or "(none — ...)" if empty)

Still Blocked, real-world annotation — check manually:
  #<N> <title>
       Real-world dep: "<annotation excerpt>"

== Almost ready (advisory) ==

Pullable but blocked by open issue(s):
  #<N> [<Priority>] <title> — blocked by #<M> (open)
  ...

──────────────────────────────────────────────────
Approve? (y / <issue numbers> / skip)
  y               apply all proposed promotions + unblocks
  <numbers>       apply only those (e.g., "y #111 #54")
  skip            apply nothing; output is record only
```

Every section prints every run, including empty ones — keeps the structure greppable across runs. The "Deferred" sub-list names a one-line reason per item ("Low tier", "no milestone", "blocked by #N", "not pullable — no acceptance criteria") so the operator can see exactly which lever to pull to change a deferral.

## Approval flow

| Operator input | `stage.py`-driven outcome |
|---|---|
| `y` | For each promotion: `jared move <N> "Up Next"`. For each unblock: `jared move <N> "Backlog"`. Print one confirmation line per `jared move`. |
| `y <numbers>` or `<numbers>` | Same as above but only for the named issues. Validate that each number appears in the current proposal; reject unknown numbers with a stderr line, don't apply anything. |
| `skip` | No `jared move` calls. Stage.py exits 0. Output remains in the session record. |

Errors during apply (e.g., `jared move` fails for a specific item) surface inline: print the error, continue with remaining items, exit with the count of successes vs. failures. Never roll back partial successes — `jared move` is idempotent and the operator can retry manually.

## Verification

- **Unit tests** (`tests/test_stage.py`): one test per pure function. Edge cases for ranking: ties on Priority, ties on milestone proximity, no-milestone items, empty Backlog. Edge cases for blocker detection: native-only blocker, body-ref-only blocker, mixed, real-world annotation.
- **Manual smoke**: invoke `/jared-stage` against the live `brockamer/jared` board after implementation; confirm the proposal matches what the operator would have chosen manually.
- **Integration test** (optional): `tests/test_stage_integration.py` against the `brockamer/jared-testbed` project (opt-in via `pytest -m integration` per existing pattern). Useful if there's value in exercising the full `gh` integration; skip if pure-function coverage suffices.

## Out of scope

- **Live event-driven Blocked revisit.** A GitHub webhook listening for `closed` events on issues that block any Jared-tracked issue is meaningfully larger work (infrastructure, auth, delivery semantics). The daily-scheduled + on-demand combination handles 95% of cases.
- **Auto-promotion without operator approval.** Different feature; would require amending SKILL.md § "The lane". Flag for a future version, do not bundle here.
- **Cross-project staging.** Single board at a time. Multi-project pipelines are a separate concern.

## Open questions

None — all six tensions resolved through brainstorming. Implementation plan can proceed.

## References

**Memories that shaped this design:**

- `feedback_design_tension_pause` — why #128 was filed in design-question shape rather than implementation shape.
- `feedback_jared_doctrine_first` — informed the Python-vs-prose split: doctrine prose for *rules*, Python for *computation* (this is computation).
- `feedback_model_selection` — implementation goes on Sonnet, review/advisory on Opus; informed how subagent dispatches will be sequenced during implementation.

**Prior art consulted during brainstorming (#126 session):**

- Reflexion 2023 / LangChain reflection pattern — informed Phase 2 audit shape for #126; not directly load-bearing for #128 but reinforced the "ephemeral output for advisory passes, durable for actionable" split that appears here as scheduled-fire vs. manual-fire.
- Augment Code routing guide / wshobson/agents — confirmed that per-task tier hints in issue templates is domain-novel; no surfaced prior art for jared's continuous-staging shape either, so this design is informed by kanban / WIP-limit doctrine rather than direct precedent.

**Related work shipped this session:**

- #126 / v0.14.0 — established the imperative `## Model & execution guidance` shape; #128's body is the first issue filed using it.
- The 2026-05-14 groom — surfaced the empty-Up-Next gap that motivated this work.
