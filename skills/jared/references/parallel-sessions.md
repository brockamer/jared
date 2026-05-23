# Parallel sessions — coordination, label semantics, worktree pattern

When two Claude Code sessions work concurrently in the same Jared-stewarded
repo, the board is the coordination surface and the worktree is the
isolation surface. Both are required — neither alone is sufficient.

## The `session-N` label is a durable claim

When the board shows an issue In Progress with a `session-N` label (N = 1,
2, …), that label means session N is actively touching that code right now.
The label outlives the conversation; it's the durable claim that survives
the next session-start.

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
