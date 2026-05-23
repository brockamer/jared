# Spec: multi-session — stage/start/git hygiene for parallel Claude sessions

**Issue:** #232
**Milestone:** v1.1 — multi-session
**Parent epic:** #233
**Date:** 2026-05-23

## Posture

Parallel Claude sessions against the same project board are already in active ad-hoc use. The pattern works, but it leans on operator vigilance for two distinct hazards: WIP cap arithmetic and shared `.git/HEAD` collisions. Neither hazard is mentioned in the doctrine; both are operator-discoverable, which means new users hit them.

This spec converts "works if you're careful" into "works because it's designed to." The shape composes three workstreams — labeling, selection, git/worktree hygiene — into a single coherent discipline.

Operator-triggered throughout. No auto-partitioning of work in v1.1 (deferred — see Phase-2 hardening).

## The trap this milestone exists to prevent

**Local working-tree damage from shared `.git/HEAD`.** 2026-05-23: session 1 was working on `fix/765-followup-data-unwrap`. Session 2 ran `git checkout main` to capture in-progress work on a different issue. The shared `.git/HEAD` moved silently. Session 1's next `git commit` landed on `main` instead of the intended branch. Recovery required `git branch -f` + `git reset --hard origin/main` + `git cherry-pick` + `git rebase --onto` — a six-step sequence that's easy to fat-finger.

The damage is local, before any push. This is the discriminator that ruled out a push-only-guard cut: a push guard only catches escapes, not the wrong-branch commits themselves.

## Three workstreams

### Workstream 1: Labeling discipline

`session-N` labels (`session-1`, `session-2`, …) on issues are the durable claim about which session owns which work. Options considered:

| Option | Who applies the label, when | Tradeoff |
|---|---|---|
| 1a. Operator manually at parallel-session start | Zero code. Easy to forget; unlabeled item gets pulled by either session |
| 1b. `/jared-stage` auto-partitions Up Next by surface overlap | High-risk: mis-routes sessions into colliding work silently |
| 1c. `/jared-start` auto-applies on pull | Useful as audit trail; doesn't prevent collisions (labels reflect what happened, not what should happen) |
| 1d. Hybrid: stage proposes (advisory), operator confirms, start enforces | Most coverage; most surface area |

**Chosen for v1.1:** **1a** (operator-applied). Simplest; no new failure modes. 1d is the migration target but premature.

### Workstream 2: Selection logic

How `/jared-start` knows which session it is:

| Option | Mechanism | Tradeoff |
|---|---|---|
| 2a. CLI flag (`/jared-start 232 --session 1`) | Argparse change; explicit | Operator forgets the flag → label drift |
| 2b. Env var (`JARED_SESSION=1`) | Read env in CLI | Same forget-failure as 2a; env state invisible, harder to recover |
| 2c. Inferred from worktree path | Path parsing | **Killed: incompatible with workstream-3.** Worktree path encodes the *issue*, not the session |
| 2d. Asked at start time if absent | Interactive prompt | Slows start; failure-safe |

**Chosen for v1.1:** **2a + 2d**. Flag when known; prompt when not (and only when a sibling session is detected — single-session work doesn't prompt).

### Workstream 3: Git / worktree hygiene

Consume #231's existing design space verbatim. Options A/B/C are defined in #231's body; not re-litigating them here.

| Option (from #231) | Shape | Trap-prevention |
|---|---|---|
| A. Worktree-by-default on detection | Lazy; creates worktree only when sibling detected | Yes, if detection is reliable |
| B. Refusal with guidance | Pre-checkout hook errors | Yes, but high operator friction |
| C. Issue-bound worktree via `/jared-start` | Every `/jared-start <N>` creates `~/Code/<repo>-<N>/` | Yes; trap eliminated structurally |
| D. Push-side guard only | Pre-push rejects alien-base commits | **No** — catches some escapes, not the wrong-branch commit itself |
| E. Branch-name discipline only | `feature/session-N-<issue>` + start-time refusal | **No** — same gap as D |

**Chosen for v1.1:** **#231's hybrid — C as default, B as fallback, A as recovery.** Workstream-3 = #231's hybrid; this spec consumes that decision rather than re-deciding.

D and E move to Phase-2 hardening — useful layered defenses on top of C, not substitutes.

#### Why not E + D as the smallest cut

It was considered. The advisor catch that killed it: the milestone deliverable sentence (#233) is "two sessions pull non-overlapping work and commit *without trampling each other's git state*." The 2026-05-23 incident shape was a local wrong-branch commit; the damage was done before any push. E + D would have caught some escapes from the wrong branch (alien-base detection at push time) but would not have prevented the commit itself. A smallest cut that doesn't deliver the deliverable isn't a smallest cut — it's a partial defense dressed up as one.

## Composed shape

> **v1.1 smallest viable cut:**
>
> - **Labeling:** 1a — operator applies `session-N` manually at parallel-session start
> - **Selection:** 2a + 2d — `--session N` flag on `/jared-start`; prompt only if absent *and* a sibling session is detected
> - **Git hygiene:** #231's hybrid (C default, B fallback, A recovery) — issue-bound worktree
>
> **Phase-2 hardening (post-v1.1, not blocking the milestone deliverable):**
>
> - D. Push-side alien-base guard
> - E. Branch-name discipline (`feature/session-N-<issue>`)
> - 1d. `/jared-stage` advisory partition proposal

The composition is coherent: 1a's labels are read by 2a/2d (selection learns session-N), and the worktree path under C is independent of session-N (worktree encodes issue), so 2c's conflict is avoided.

## Subsumes #217 (WIP-cap doctrine)

With `session-N` labels in place, `jared summary`'s WIP arithmetic collapses same-session items into one workstream count — exactly #217's option 1. #217 closes when this spec lands; the WIP-counting change is a sub-task of the labeling workstream's implementation.

## Memory reconciliation

Two existing memories cover the parallel-sessions discipline today as advisory:

- `feedback_dual_session_coordination` — "In Progress = another session is touching that code; check surface overlap; session-N label is the durable claim."
- `feedback_session_label_ownership` — (if it exists; verify at follow-up filing time)

Under v1.1:

- **1a preserves the operator-vigilance posture** the dual-session memory describes — the memory's claim that "session-N label is the durable claim" remains true; the v1.1 ship adds *enforcement* at start-time (selection refuses to pull a `session-2`-labeled issue when `--session 1` is the running session).
- Both memories need cross-references updated to point at this spec once the implementation lands, transitioning them from advisory to "the mechanism enforces this."

## Smallest viable cut → implementation issues

These are the follow-ups #232 files when this spec lands:

1. **Labeling implementation** — new issue. Define `session-N` label semantics, document operator's pre-parallel-session ritual in SKILL.md, update `jared summary` to do per-session WIP arithmetic (subsumes #217).
2. **Selection implementation** — new issue. Add `--session N` flag to `/jared-start`. Add sibling-session detection and conditional prompt (skip prompt when single-session).
3. **Worktree implementation** — **#231 already covers this.** Narrow #231's body to remove its A/B/C design-space prose and point at this spec as the design source; keep its implementation acceptance criteria.
4. **#217 closure** — closes when the labeling implementation ships per-session WIP arithmetic. Note the supersession in #217's close comment.

## Out of scope for v1.1

- N > 2 sessions. Design for 2 first; verify the shape before generalizing.
- Cross-machine coordination. Assume single VM / dev environment.
- Auto-partitioning at `/jared-stage` (1b/1d). Operator vigilance is the v1.1 mode.
- Push-side guards (D) and branch-name discipline (E). Phase-2 hardening once C is muscle-memory.

## Open questions deferred to implementation

- **Exact worktree path shape under C.** `~/Code/jared-<N>/`? `~/Code/jared/.worktrees/<N>/`? Operator ergonomics call; lives in #231's implementation.
- **Detection reliability for the conditional prompt in 2d.** File-lock, `ps` walk, `.git`-write timestamp — picked at selection-implementation time.
- **Whether single-session `/jared-start` ever creates a worktree.** Pure C says yes (every start creates one); a leaner read says only when a sibling is detected. Reconcile during workstream-3 implementation.

## Rationale notes

- **`/jared-stage` stays advisory.** Auto-partitioning has a real failure mode: misjudging surface overlap silently routes two sessions into colliding work. The cost of that failure exceeds the cost of operator vigilance. Defer until the labeling discipline has a track record.
- **C imposes single-session muscle-memory cost.** Real but acceptable — `/jared-start` does the worktree dance; operator's CWD changes but they don't have to think about it. The alternative (E + D) is structurally unsafe per the advisor catch.
- **Why this is "shape documented, follow-ups filed" and not "implemented".** #232's acceptance criteria explicitly closes on shape + follow-ups; implementation lives in #231 + the two new issues this spec triggers. The decomposition #233 set up at the structural review stands.
