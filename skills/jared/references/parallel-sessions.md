# Parallel sessions — coordination, label semantics, worktree pattern

When two Claude Code sessions work concurrently in the same Jared-stewarded
repo, the board is the coordination surface and the worktree is the
isolation surface. Both are required — neither alone is sufficient.

## The `session-N` label is a durable claim

When the board shows an issue In Progress with a `session-N` label (N = 1,
2, …), that label means session N is actively touching that code right now.
The label outlives the conversation; it's the durable claim that survives
the next session-start.

**Exact format.** `session-<positive-integer>` — `session-1`, `session-2`,
…. The parser is a strict regex (`^session-(\d+)$`); `session-a`,
`Session-1`, `sess-1` don't count. Peer labels (`enhancement`, `bug`, …)
sit alongside without interfering — the per-session arithmetic only
considers labels matching the strict shape.

**Who applies and when.** The *operator* approves every `session-N` label
change. `/jared-stage --sessions N` proposes assignments based on file-paths
overlap and applies them only on operator approval. `/jared-start` and
`/jared-file` never touch labels. The proposal-with-approval shape replaces
the original manual-only model (option 1a from the v1.1 multi-session shape
spec); the constraint that survives is operator approval — see
`docs/superpowers/specs/2026-05-28-multi-session-back-end-design.md` for
the new flow.

## Pre-parallel-session ritual

Before launching two or more Claude sessions against the same repo:

1. Run `/jared-stage --sessions N` (e.g., `--sessions 2` for two sessions). Jared reads current `session-N` labels and the Up Next candidates, then proposes a partition based on file-paths overlap in issue bodies. Operator approves or edits per-item.

2. Start the sessions with `/jared-start <issue> --session N`, or `/jared-start --session N` (no issue) to pull the top of the session-N filtered queue.

The partition is operator-approved per item; Jared never applies a `session-N` label without the operator saying so. To re-balance later, re-run `/jared-stage --sessions N` — existing labels are honored unless the operator removes them manually first.

The WIP arithmetic lands per #235: `jared summary` collapses items sharing a `session-N` label into a single workstream count, so two session-1 issues + one session-2 issue render as "2 workstreams · 3 items" rather than three independent items pressuring the WIP cap.

## How per-session WIP arithmetic renders

`jared summary` and `jared next-session-prompt` show the collapse when it
applies:

- **No `session-N` labels in play** (common case): `In Progress (N):` —
  unchanged, no parenthetical, no per-item suffix.
- **`session-N` labels present**: `In Progress (M workstreams · N items):`
  with each item suffixed by its session tag, e.g.
  `#235 [High] Per-session WIP (session-1)`.

The leading number is the workstream count — that's what `/jared-start`'s
WIP-cap check compares against the project's configured cap. Two
session-1 items + one session-2 item read as 2 workstreams, not 3 items.

An item carrying both `session-1` and `session-2` is malformed (the
discipline exists to prevent exactly that collision) but the set-union
arithmetic handles it without special-casing: both labels contribute to
the workstream set, the item contributes zero to the unlabeled count.

**Before pulling a new issue:**

1. Scan In Progress for items labeled `session-M` where M ≠ your session
   number.
2. For each, check whether its surface (the files / functions / dependencies
   it modifies) overlaps your candidate's surface.
3. **Soft conflict** (same file, different functions, well-separated): note
   it, proceed if safe, plan to rebase if the other lands first.
4. **Hard conflict** (same function, same imports, shared helpers): stop,
   surface options to the operator, defer the decision.

Labels run both ways. Your own work should carry your `session-N` label so
the other session sees you. Unlabeled In Progress work is invisible to the
coordination discipline — flag the gap rather than silently grabbing
adjacent items.

## The worktree pattern — never checkout-b in a shared repo

`git checkout -b <new-branch>` in a shared checkout moves the shared
`.git/HEAD`. The other session's next `git status` will report the wrong
branch, and a commit from either side risks stealing the other's WIP.

**Correct pattern:**

```bash
git fetch origin
git worktree add ~/Code/<repo>-<issue> -b feature/<issue>-<slug> origin/main
cd ~/Code/<repo>-<issue>
```

Each session gets its own working directory with its own HEAD while sharing
`.git`. After the PR merges:

```bash
git worktree remove ~/Code/<repo>-<issue>
git branch -d feature/<issue>-<slug>
```

Each worktree needs its own `.venv` — `uv sync` or `uv pip install -e .`
inside the new worktree before running tests.

## The wrap back-end

`/jared-wrap` runs the full commit → integrate `main` → push → PR create → mergeable check → confirm merge → cleanup sequence after Session notes are posted. The operator confirms only the merge (the irreversible step against protected `main`).

Idempotency: each step inspects current state via `jared wrap-state`. Re-running `/jared-wrap` after a failure or interruption picks up at the current state — no in-flight lock, no manual recovery sequencing. The state IS the lock.

Concurrent merge safety: two sessions reaching the merge step around the same time both re-check `mergeable` immediately before calling `gh pr merge`. GitHub's PR-merge API is atomic; the second call rejects with a not-mergeable error if the first's merge created a conflict. No Jared-side serialization is needed.

The back-end flow does not auto-commit. If the working tree is dirty at wrap time, wrap pauses and asks for a commit message — your commit discipline (phase-numbered prefixes, "why not what" bodies) is preserved.

## Integrate `main` before the PR

Parallel sessions branch from the same `origin/main` and then diverge. By
the time the second session wraps, `main` has usually moved — the first
session's work landed. The wrap back-end therefore folds `main` into the
branch (`git fetch && git merge --no-edit origin/main`) *before* pushing or
opening the PR, not after GitHub reports the PR unmergeable.

Two distinct conflict classes motivate this, and integrating early addresses
both:

- **Spurious (formatting/whitespace).** A whole-file `ruff format` run
  reformats lines *outside* your diff — a comprehension collapsed to one
  line, an import reordered. If the other branch reformatted the same line
  in a different surrounding context, the two diverge and git flags a
  conflict on code neither session logically touched. Integrating `main`
  *before* you format means you format on top of `main`'s canonical form and
  produce the identical output — the divergence never arises. This is the
  common, two-minute-to-resolve class, and integrating early eliminates it
  rather than just relocating it.
- **Genuine (same logic).** Two sessions edited the same function, the same
  argparse block, the shared import list, or the same `lib/board.py` helper.
  Git genuinely can't reconcile them. Integrating early doesn't *prevent*
  this, but it surfaces it in the session that still holds the context to
  resolve it well — far better than a terse "unmergeable" discovered at
  merge time, after the PR exists and the reasoning has gone cold.

**Merge, not rebase.** The branch may already be pushed (wrap is
idempotent and re-runnable), so a rebase would force a force-push and risk
the other session's view of a shared branch. A merge commit is safe and
consistent with the concurrent-merge-safety model above.

### Reducing the genuine class is a structural problem, not a wrap problem

Integrating early surfaces genuine conflicts earlier; it can't stop two
sessions from colliding in a hot file. The dominant driver is the
`skills/jared/scripts/jared` CLI monolith (and, secondarily, `lib/board.py`):
nearly every feature edits it, so two unrelated issues routinely both touch
it. The remedy is **opportunistic extraction**, not a refactor project: when
a session substantially edits one region (a subcommand's `_cmd_*` handler and
its argparse block), lift *that* region into a focused module as part of that
issue's work. The monolith shrinks where it's hottest, with no dedicated
big-bang split — which would itself be the kind of sprawl this project avoids.

## Triggers for the worktree default

- Operator explicitly says "the other session is working #X, you start #Y."
- The board shows a `session-N` label that's not yours on an In Progress
  item.
- You spot a `feature/<issue>-...` branch you didn't create on the current
  checkout (likely the other session's WIP).

## Don't

- `git checkout -b` in the shared checkout when another session is active.
- Stash, commit, or `git checkout --` over a dirty working tree another
  session is driving.
- Pull from another session's `session-N` queue silently — the label is the
  durable claim.

## When in doubt

Surface the conflict to the operator. The cost of pausing to ask is low;
the cost of clobbering the other session's branch is high. Cross-session
coordination is the one place where defaulting to *more communication* is
the right move — see `references/voice.md` for the surfacing style.
