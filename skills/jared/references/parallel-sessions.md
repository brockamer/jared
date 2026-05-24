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

**Who applies and when.** The *operator* applies `session-N` labels at
parallel-session start (option 1a from the v1.1 multi-session shape spec).
Not Jared, not `/jared-stage`, not `/jared-start`. Auto-application was
considered and deferred — see `docs/superpowers/specs/archived/2026-05/2026-05-23-multi-session-shape.md` § "Workstream 1".

## Pre-parallel-session operator ritual

Before launching two or more Claude sessions against the same repo:

1. Glance at Up Next + In Progress and partition the next pull candidates
   by *surface overlap* — which issues touch the same files, modules, or
   shared helpers.
2. Apply `session-1` to the group session 1 will own, `session-2` to the
   group session 2 will own, etc. Items with no surface overlap stay
   unlabeled and act as floats either session can claim.
3. Start the sessions with `/jared-start <issue> --session N`. The flag
   tells the session-presence resolver which claim it represents.

The discipline is operator vigilance, not mechanism. The mechanism that
*does* land per #235: `jared summary`'s WIP arithmetic collapses items
sharing a `session-N` label into a single workstream count, so two
session-1 issues + one session-2 issue render as "2 workstreams · 3 items"
rather than three independent items pressuring the WIP cap.

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
