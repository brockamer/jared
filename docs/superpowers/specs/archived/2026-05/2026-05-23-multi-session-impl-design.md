---
**Shipped in #231, #236 on 2026-05-23. Final decisions captured in issue body.**
---

# Spec: multi-session implementation — opt-in worktree + session-presence locking

**Issues:** #231 (worktree-by-default) + #236 (`/jared-start --session` flag), bundled
**Parent spec:** `archived/2026-05/2026-05-23-multi-session-shape.md` (#232, shipped)
**Milestone:** v1.1 — multi-session
**Date:** 2026-05-23

## Posture

The composed-shape spec (#232) deferred three implementation-level decisions to workstream 3: the worktree path shape, whether single-session `/jared-start` ever creates a worktree, and the detection mechanism for the B-leg refusal. This document resolves all three, and resolves the resulting coupling between #231 (worktree creation) and #236 (`--session` flag) by bundling them into one PR.

The discipline this design enforces: **every active jared session is visible to every other active jared session**, via an unconditional session-presence lock. Worktree isolation is opt-in via the `--session N` flag, but session presence is not — solo work also leaves a beacon, so a second session that starts later can see the topology and refuse-with-guidance rather than silently sharing `.git/HEAD`.

This is the v1.1 cut. Phase-2 hardening (push-side guards, branch-name discipline, retroactive worktree migration) is explicitly deferred.

## Decisions

### D1. Worktree path shape: flat sibling (`~/Code/<repo>-<N>/`)

Chosen over nested-under-repo (`~/Code/<repo>/.worktrees/<N>/`) and central-outside-Code (`~/.jared-worktrees/<repo>/<N>/`). Reasoning:

- `ls ~/Code/` reveals session topology at a glance. Discoverability is the practical win.
- IDE/shell prompts derive project name from CWD's basename. `jared-231` reads as "jared, working on issue 231"; nested-under-repo's leaf `231/` is meaningless out of context.
- Nested's "cleanup-on-repo-removal" win matters once a year; discoverability matters every session.

### D2. Worktree creation: opt-in via `--session N` flag

Chosen over pure-C (every `/jared-start` creates a worktree). Reasoning:

- Solo work is the common case. Pure C imposes worktree overhead and CWD shifts on operators who never run a second session, indefinitely.
- The opt-in flag also doubles as the session-identity claim (#236's deliverable), composing #231 and #236 into one switch with two effects.
- The mid-session-safety gap that opt-in reopens (start solo, spawn sibling later, session 1 stranded) is closed by D3's unconditional locking, not by always-on worktrees.

`/jared-start <N>` (solo) leaves CWD unchanged. `/jared-start <N> --session N` creates the worktree and shifts CWD. `/jared-start <N> --no-worktree` is the explicit-risk-acknowledgment escape from B-leg refusal.

### D3. Session presence: unconditional file-lock at every `/jared-start`

This is the load-bearing fix that makes B-leg detection real. Every active jared session writes a lock file at `/jared-start` time, regardless of solo/multi.

**Lock-file shape:** one file per session, PID-keyed. Path is `<repo>/.jared/session-<pid>.lock`. JSON contents:

```json
{
  "pid": 12847,
  "started": "2026-05-23T14:22:00Z",
  "session": null,
  "worktree_path": null,
  "issue": 231
}
```

`session` is `null` for solo work or an integer (`1`, `2`, …) when `--session N` was passed. `worktree_path` is `null` for shared-checkout work or the absolute worktree path. PID-keyed file naming avoids any append-concurrency concern: two sessions starting near-simultaneously each write their own file.

`/jared-wrap` removes `<repo>/.jared/session-<pid>.lock` for its own PID. `.jared/` is added to `.gitignore` repo-wide.

**Detection logic** at `/jared-start` time:

1. `ls <repo>/.jared/session-*.lock` to enumerate existing locks. For each, parse the JSON and run `kill -0 <pid>`.
2. Locks with dead PIDs are stale — warn on stderr, delete the file, treat as no sibling.
3. Locks with live PIDs are siblings — resolve the action based on the new session's flags and the sibling's lock contents:

| New session flags | Sibling state | Action |
|---|---|---|
| solo, no flag | (any) | If solo sibling: refuse (B leg). If multi sibling: refuse (B leg). |
| `--session N` (multi) | solo sibling | Refuse (B leg). Solo sibling on shared HEAD is exactly the trap shape. |
| `--session N` (multi) | multi sibling, different N | Proceed — both sessions in separate worktrees, fully isolated. |
| `--session N` (multi) | multi sibling, **same N** | Refuse — session-N must be unique per repo. |
| `--no-worktree` (ack-risk) | (any) | Proceed with warning — operator explicitly accepted the trap. |

### D4. Detection mechanism: file-lock + `kill -0` liveness check

Picked over `ps` walk and `.git`-write timestamp:

- **`ps` walk** for "claude" processes is fragile across shells, IDE-integrated terminals, tmux, and remote sessions.
- **`.git`-write timestamp** has a race window between two sessions racing the same operation.
- **File-lock with PID-liveness** has one known failure mode (PID reuse), which on Linux is rare enough to defer.

Known limitation, documented but not hardened against in v1.1: a stale lock whose PID has been reused by an unrelated process would read as alive. Mitigation if it bites: add a started-at heuristic — if `kill -0 <pid>` succeeds but the process start time is much later than the lock's recorded `started:`, treat as stale. Defer.

### D5. Worktree path collision UX: distinguish registered worktrees from orphaned dirs

When `git worktree add ~/Code/<repo>-<N>/` fails because the path exists:

- If `git worktree list --porcelain` reports the path as a registered worktree: `cd` into it (resuming an abandoned session). Warn if HEAD is on an unexpected branch (e.g., not `feature/<N>-<slug>`).
- If the path exists but is not a registered worktree: error with remediation (`rm -rf <path>` or `git worktree remove <path>` if it was once registered).

Two cases, two messages. The common shape ("laptop crashed yesterday, I want to resume #231") gets the friendly path.

## Behavior shape — what an operator sees

### Solo work (the common case)

```
$ /jared-start 231
# moves #231 to In Progress, loads context
# writes .jared/session-<pid>.lock with session=null, worktree_path=null
# CWD unchanged
```

### Multi-session, opt-in

```
$ /jared-start 231 --session 1
# moves #231 to In Progress
# git worktree add ~/Code/jared-231/ origin/main -b feature/231-worktree-by-default
# CWD shifts to ~/Code/jared-231/
# writes .jared/session-<pid>.lock with session=1, worktree_path=/home/<u>/Code/jared-231/
```

### B-leg refusal

```
$ /jared-start 235
ERROR: another active jared session detected.
  Sibling session: PID 12847, started 2026-05-23T14:22:00Z, issue #231
  Sibling mode: solo (on shared .git/HEAD — vulnerable to the #231 trap)

Choose one:
  - Wrap sibling session, then start fresh with --session 1
  - /jared-start 235 --session 2  (creates worktree for THIS session,
    but session 1 is still on shared HEAD — risk persists for it)
  - /jared-start 235 --no-worktree  (acknowledge risk, start alongside)

Sibling lock: /home/<u>/Code/jared/.jared/session-12847.lock
```

### Wrap clears the lock

```
$ /jared-wrap
# normal wrap flow, also removes lock entry for this session's PID
```

## Components — where the changes land

| Change | File | Source issue |
|---|---|---|
| `--session N` and `--no-worktree` flag parsing in slash-command stub | `commands/jared-start.md` | #236 / #231 |
| Sibling-detection logic in stub (calls into lib) | `commands/jared-start.md` | #236 |
| `lib/session_lock.py` (new): read/write/clear locks, PID-liveness, `resolve_action()` | `skills/jared/scripts/lib/session_lock.py` | #231 |
| `lib/worktree.py` (new): `create_worktree(repo, issue, branch)`, collision-aware | `skills/jared/scripts/lib/worktree.py` | #231 |
| `/jared-wrap` clears the session lock at end of flow | `commands/jared-wrap.md` | #231 |
| `.gitignore` adds `.jared/` | `.gitignore` | #231 |
| CLAUDE.md surface — discoverability for the discipline | `CLAUDE.md` | #231 |
| Memory cross-references | `feedback_parallel_session_worktree.md`, `feedback_session_label_ownership.md` (user memory) | #231 |
| Tests | see § Testing | #231 |

Two new Python modules. Heavy logic in lib (pure functions where possible); slash-command stubs stay thin. Pattern matches `lib/board.py`.

## Out of scope for this PR

- **`session-N` label auto-application.** Spec workstream-1 chose 1a (operator-applied). `/jared-start --session N` does NOT apply the `session-N` label. The label is the operator's pre-pull ritual; the flag tells the session what it IS.
- **`jared summary` per-session WIP arithmetic.** Owned by #235, still Up Next. This PR ships the flag plumbing #235 will consume; the arithmetic is #235's lift.
- **Retroactive worktree migration (B2 / `/jared-rebase-to-worktree`).** Phase-2 hardening. Refusal-with-guidance is the v1.1 stop.
- **Push-side alien-base guard, branch-name discipline.** Phase-2 per parent spec.

## Testing

Three layers. The first two are machine-verifiable; the third is operator-facing documentation.

### 1. Unit tests — `tests/test_session_lock.py`

Pure-function coverage of `lib/session_lock.py`:

- `write_lock(pid, session_n, worktree_path, issue) → lockfile contents match`
- `read_lock() → parses correctly` (including malformed-lock graceful failure)
- `is_alive(pid) → True/False matching `kill -0` reality`
- `is_stale(pid) → True when PID dead, False when alive`
- `clear_lock(pid) → removes matching entry, leaves siblings`
- `resolve_action(lock_state, flags) → Action` — covers all rows of the D3 table

### 2. Integration test — `tests/test_worktree_isolation.py`

This is the test that maps to the body's acceptance criterion *"trap can no longer fire."* Tmpdir-scoped fixture:

- `git init` a temp repo, commit a file
- Invoke `lib/worktree.create_worktree()` → creates worktree at a sibling tmp path
- Assert `git rev-parse --absolute-git-dir` from main checkout != from worktree
- Assert checking out a branch in the main checkout does not change HEAD in the worktree (and vice versa)
- Assert a commit in the worktree lands on the worktree's branch, not on `main`

This is what proves the structural isolation is real for THIS implementation, not just an OS-level invariant.

### 3. Scenario test — `tests/test_jared_start_b_leg.py`

End-to-end of the B-leg refusal path. Mocks the lock file state; invokes `/jared-start`'s detection + arg-resolution helper via `lib/session_lock.resolve_action()`:

- Lock present, alive PID, no flags → expect refusal
- Lock present, alive PID, `--session 2` → expect proceed
- Lock present, alive PID, `--no-worktree` → expect proceed-with-warning
- Lock present, dead PID → expect stale-warning + proceed
- Lock with same `--session N` → expect refusal (uniqueness)
- Conflicting flags (`--session 1 --no-worktree`) → expect refusal

## Known limitations (documented, not hardened)

- **PID reuse on Linux.** Lock with `pid=X` could read as alive if X has been reused by an unrelated process. Rare in practice; mitigation deferred.
- **Cross-machine coordination.** Single-VM assumption holds; lock files don't coordinate across hosts.
- **N > 2 sessions.** Design supports N sessions; tested only against 2.

## Estimated implementation shape

This is multi-session-of-work — not a finish-this-evening lift. (Note: "sessions" here means working blocks across calendar time, NOT `session-N` labels — those are this feature's domain term.) Realistic decomposition into phases:

1. **Phase 1** — `lib/session_lock.py` + unit tests + scenario test + `.gitignore`.
2. **Phase 2** — `lib/worktree.py` + isolation integration test.
3. **Phase 3** — `/jared-start` stub edits (flag parsing, detection wiring, refusal rendering) + `/jared-wrap` lock-clear + CLAUDE.md surface + memory cross-references + PR.

This document is the spec for the writing-plans skill to consume; the plan will break the above into reviewable phases.

## Open questions

None remaining at spec-time. The three resolved decisions (D1–D5) close the parent spec's open questions; the three advisor catches that surfaced during brainstorming are folded into D3, the testing plan, and D5.
