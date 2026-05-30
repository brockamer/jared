# Jared

A Claude Code plugin that turns a GitHub Projects v2 board into the
single source of truth for what's being worked on — with a discipline
that survives across sessions, weeks, and shifts in scope.

> Project boards drift. Scope leaks into `TODO:` comments and
> `tmp/next-session-prompt.md` files. Plans approved three weeks ago no
> longer match the code. By month two the board is decorative and real
> status lives in your head. **Jared makes the board the thing you
> actually look at.**

---

## What it's for

Long-running work on a complex project — features that take more than
one sitting, bugs surfaced mid-refactor, plans that need to outlast the
session that wrote them. Anywhere the work is bigger than your working
memory, Jared keeps the board in lockstep with reality so you (and any
agent picking up the work) can resume from the board instead of from
recollection.

It works just as well on non-software projects. A kanban for renovating
a house uses the same model — `Backlog / Up Next / In Progress /
Blocked / Done` — with work streams like *Demo*, *Rough-in*, *Finish*.
The invariants are identical.

The shape Jared enforces:

- **Five Status columns.** `Backlog / Up Next / In Progress / Blocked /
  Done`. Blocked is a column, never a label.
- **Status + Priority required** the moment an issue lands. `jared
  file` is atomic — issue created, on board, fields set, or fail loudly.
- **Blocked-by is a native GitHub dependency** (`addBlockedBy` /
  `removeBlockedBy` GraphQL), not a comment convention.
- **WIP cap on In Progress** (default 4, counted in workstreams when
  multiple parallel sessions are running).

---

## Getting started

### Prerequisites

- **Claude Code.** Jared's commands are typed into the Claude Code
  chat, not into your shell.
  ([Install Claude Code](https://code.claude.com/docs/en/quickstart))
- **`gh` CLI, authenticated.** Every Jared operation calls GitHub on
  your behalf. Run `gh auth login`; confirm with `gh auth status`.
- **GitHub token with `project` scope.** Default `gh auth login`
  scopes cover `repo` but not `project`. Add it:

    ```
    gh auth refresh -s project
    ```

    Without `project` scope, board mutations fail silently or with
    confusing 404s.
- **A GitHub Projects v2 board.** Either an existing one, or a fresh
  empty project at `https://github.com/users/<you>/projects`. Jared
  introspects the field schema during bootstrap, so any board works.

### Install

In Claude Code:

```
/plugin marketplace add brockamer/jared
/plugin install jared
```

This makes the 9 slash commands available: `/jared`, `/jared-file`,
`/jared-start`, `/jared-stage`, `/jared-groom`, `/jared-audit`,
`/jared-reshape`, `/jared-wrap`, `/jared-init`.

### Bootstrap your project

Open the project where you want Jared to steward the board, then run:

```
/jared-init
```

The bootstrap asks for your project's URL (e.g.
`https://github.com/users/you/projects/4`), introspects the board's
Status and Priority field schema, and writes a convention doc to
`docs/project-board.md`. **Commit and push it** — the CLI re-reads it
on every invocation, so it has to live in the repo.

### First command

```
/jared
```

Shows your project URL, the In Progress count, and the top of Up Next /
Blocked. On a fresh board this is mostly empty — that's expected. As
you file and move issues, the posture fills out.

> If `/jared` errors with "no docs/project-board.md found," the
> bootstrap step was skipped or the file lives elsewhere. The CLI
> autodiscovers across `docs/project-board.md`,
> `docs/maintainers/project-board.md`, `PROJECT_BOARD.md`, and
> `.github/project-board.md` — pass `--board <path>` if yours is
> somewhere else.

### Next: the loop

The install above gets you to a working CLI. The
[first 15 minutes walkthrough](docs/getting-started.md) takes you the
rest of the way — file an issue, pull it into In Progress, add a
Session note, close it, wrap the session. Do it once and the rest of
the discipline (stage, groom, plans) becomes incremental.

---

## Working in Claude Code, with vs. without Jared

| | Without Jared | With Jared |
|---|---|---|
| **Starting a session** | "What were we doing?" Skim recent commits, re-read CLAUDE.md, scroll the issue list trying to remember which ones are actually live right now. | `/jared` shows In Progress, top of Up Next, what's blocked, what's aging — in two seconds. `/jared-start <N>` loads issue body + latest Session note + linked plan. |
| **Mid-session scope discovery** | "We should also fix X" — either filed as an issue you'll forget about, or done inline and lost in the diff. | The skill triggers on phrases like *"let me refactor X"*, *"I noticed"*, *"I'll file that later"*. `jared file` opens an issue with Priority + Status set atomically before the change happens. |
| **Plans** | Plans accumulate as markdown files. Claude reads everything in the plans directory each time, so old, shipped, or superseded plans dilute the context that's actually relevant. | Each plan cites its issue. When the issue ships, `/jared-wrap` proposes archiving the plan into `archived/YYYY-MM/`. The active set stays small enough to be load-bearing. |
| **Ending a session** | Rely on you remembering to commit cleanly, push, and update the right tracking artifact every time, even when the session ran long. The discipline is correct; it's also exactly the discipline that erodes first when you're tired. | `/jared-wrap` checkpoints the session: appends a structured `## Session YYYY-MM-DD` note (Progress / Decisions / Next action / Gotchas / State) to every issue touched, files any discovered scope, and proposes plan archivals. Next session reads from the issue, not your recollection. |
| **Two months in** | Board half-decorative, items with `Status=null` floating off the kanban, `## Blocked by` written as a label that nobody's filtering for. | Daily `/jared-groom` flags drift before it accumulates: missing metadata, WIP-cap violations, aging items, stale plans, native-dependency hygiene. Nothing silent. |
| **Cross-session continuity** | Lives in your head. | Lives on the board, in Session notes on issues, in the Status column. Any agent — Sonnet, Opus, you next Tuesday — picks up the same context. |
| **Multiple Claude sessions in one repo** | Both sessions share one `.git/HEAD`. A `git checkout -b` from either silently steals the other's branch state; the next commit may clobber WIP. | `/jared-start <N> --session N` writes a presence lock, creates an isolated git worktree, and the operator applies a `session-N` label so each session can see who's touching what. WIP arithmetic counts workstreams, not items. |

---

## A typical week

| When | Command | Why |
|---|---|---|
| Once a week (Mon morning) | `/jared-reshape` | Structural review — shape, phasing, milestones, dependencies, long-horizon arc. Catches drift the daily groom can't see. |
| Every day | `/jared-groom` | Routine sweep — metadata, WIP cap, aging items, pullable check, plan/spec drift, label hygiene. Advisory; you approve each proposed change. |
| Every day or so | `/jared-stage` | Propose promotions from Backlog → Up Next and revisit anything in Blocked. With `--sessions N`, also proposes cohesion-first `session-N` label assignments so parallel sessions work on file surfaces that overlap with their own, not each other's. Advisory; you approve each move. |
| When the backlog gets long | `/jared-audit` | Skeptical walk through the oldest items — verdict per issue (close / reshape / leave-alone), operator approves any mutation. |
| Per work session — start | `/jared` then `/jared-start <N>` | `/jared` orients in 2 seconds. `/jared-start` moves the issue to In Progress and loads everything you need to resume. |
| Per work session — end | `/jared-wrap` | Captures Progress / Decisions / Next action on every touched issue. Files any discovered scope. Proposes plan archivals. |
| As scope arrives | `/jared-file` | One atomic operation: create issue, add to board, set Priority + Status + milestone, verify. Milestone is required — pass `--milestone NAME` or `--no-milestone` explicitly. No "filed but invisible" state. |

### What the cycle looks like

<details>
<summary><strong>Excerpt — <code>/jared</code> at session start</strong></summary>

```
Where we are (2026-05-24):

In Progress (1/4):
  #89 [Low] feat(archive-plan): support recycled-issue plans
    Last session: "Add ## Shipped section parser to lib/board.py; tests next"

Up Next (top 3):
  #76 [Medium] Jared roadmap — open strategic questions — pullable: yes
  #80 [Medium] feat(ties): LLM-pass overlay for semantic ties — pullable: yes
  #67 [Low] verify: #22 rate-limit fix smoke results on findajob — pullable: yes

Blocked:
  #60 — waiting on findajob measurement run for post-#51/#55 GraphQL delta

Aging: none
Totals: 6 open (0 H / 3 M / 3 L)
```

</details>

<details>
<summary><strong>Excerpt — <code>/jared-start 89</code></strong></summary>

```
Started #89 — feat(archive-plan): support recycled-issue plans via ## Shipped section
  Status: Backlog → In Progress
  Priority: Low
  Linked plan: docs/superpowers/plans/2026-05-03-89-shipped-section.md
  Latest Session note (2026-05-02):
    Progress: Designed ## Shipped section convention; reviewed bug repros.
    Next action: Add parse_shipped_section to lib/board.py with same
                 line-start rules as parse_referenced_issues.
    Gotchas: PR/Issue label needs to be gated behind a list marker or
             we re-open the #87 false-positive class.
  Branch: feature/89-shipped-section-archival
```

Session plan announced. Picking up from the documented Next action.

</details>

<details>
<summary><strong>Excerpt — <code>/jared-file</code> mid-session, scope discovered</strong></summary>

```
You: "Hmm, the regex relaxation here re-opens the #87 prose-match bug
      if I don't gate the label behind a list marker. Let me file that as
      a sub-concern so we don't lose it."

  → jared file --title "bug: PR/Issue label gating in plan-line ref regex"
                --body-file /tmp/issue.md --priority Medium

OK: filed #94 → Backlog, Priority=Medium
URL: https://github.com/brockamer/jared/issues/94
```

The conversation continues. The scope is on the board, not in your head.

</details>

<details>
<summary><strong>Excerpt — <code>/jared-groom</code></strong></summary>

```
Sweep for https://github.com/users/brockamer/projects/4
Run at: 2026-05-24T13:42:00+00:00

Open items on board: 6

== Metadata completeness ==
  All open items have required metadata

== WIP (In Progress cap = 4) ==
  Healthy

== Stale High-priority Backlog (>14d) ==
  None

== Stalled In Progress (>7d no activity) ==
  None

== Blocked-status hygiene (>7d) ==
  #60: in Blocked status with no activity for 9 days

== Plan/spec drift ==
  docs/superpowers/plans/2026-05-03-89-shipped-section.md:
    all referenced issues closed ([89]) — propose archiving

Sweep complete. Advisory only — review and propose before applying.
```

You approve each proposed change individually. The groom never silently mutates state.

</details>

<details>
<summary><strong>Excerpt — <code>/jared-wrap</code> at session end</strong></summary>

```
Touched this session: #89

Proposed Session note for #89:

  ## Session 2026-05-24

  **Progress:** Implemented ## Shipped section archival path. Added
  parse_shipped_section to lib/board.py via shared _parse_plan_section
  helper. Tightened _PLAN_LINE_REF_RE to gate the PR/Issue label behind
  a list marker. PR #93 merged.

  **Decisions:** Shipped takes priority over ## Issue when both are
  present — explicit shipping evidence beats potentially-recycled refs.

  **Next action:** None — issue shipped.

  **Gotchas:** Advisor caught the label-gating regression before push;
  test_parse_referenced_issues_ignores_prose_line_starting_with_issue_label
  locks it in.

  **State:** Branch deleted; main tagged v0.9.0.

Apply? [Y/n] y
  Appended Session note to #89.

Discovered scope filed this session: none.

Plans ready to archive:
  docs/superpowers/plans/2026-05-03-89-shipped-section.md → archived/2026-05/
Archive? [Y/n] y
  Archived. Updated #89 ## Planning section.
```

</details>

---

## A note on voice

Jared's conversational surfaces — `/jared` status reports, `/jared-start`
announces, drift-reconcile prompts, error-mode chatter — speak as Jared
Dunn from *Silicon Valley*: deferential, formally polite, quietly fierce
about operational integrity. Board writes (issue bodies, Session notes,
PR descriptions, commit messages) stay plain technical prose, so the
permanent record remains greppable and scannable. If the voice isn't to
your taste, add `- voice: disabled` under `## Jared config` in
`docs/project-board.md` and the slash commands fall back to plain prose
with the same structural content.

---

## Multi-session work

When two Claude sessions work the same repo at once, they share one
`.git/HEAD` — a `git checkout -b` from either silently steals the
other's branch state. Jared layers four defenses:

- **Presence locks.** Every `/jared-start` writes
  `<repo>/.jared/session-<pid>.lock`. A second session sees the lock
  and refuses to start in the shared checkout unless you opt in.
- **Worktree isolation.** `/jared-start <N> --session N` creates
  `~/Code/<repo>-<N>/` via `git worktree add`, checks out a fresh
  feature branch from `origin/main`, and shifts CWD into the worktree.
  Separate working dir, separate HEAD, one shared `.git`.
- **`session-N` labels.** The operator applies `session-1` / `session-2`
  labels to In Progress items so each session can see who's touching
  what. `jared summary` collapses same-labeled items into a single
  workstream count against the WIP cap.
- **Cohesion-first partition.** `/jared-stage --sessions N` (and the
  `jared propose-partition --sessions N` CLI surface) proposes
  `session-N` label assignments by maximizing file-surface overlap
  within each session — so conflict-prone items co-locate instead of
  spreading. Operator approves the assignment before it lands.

`/jared-wrap` clears its own session's lock at session end. Solo
sessions still write a lock (with no session number) so a later
sibling can detect them.

Full discipline, label semantics, and conflict-triage decision tree:
[`skills/jared/references/parallel-sessions.md`](skills/jared/references/parallel-sessions.md).

---

## Under the hood

Slash commands sit on top of a unified Python CLI
(`skills/jared/scripts/jared`) that owns the multi-step operations.
Each subcommand is atomic — `file` guarantees "issue exists AND on
board AND Status set" or fails with a non-zero exit; `close` verifies
auto-move to Done and falls back to explicit Status=Done; the session
subcommands gate worktree creation behind lock-resolution.

When the GitHub MCP plugin is loaded, the skill prefers its typed
tools for single-call operations. The CLI handles everything
multi-step. Raw `gh` is the last resort.

Every issue body and comment passes through a PII pre-flight before
any `gh` call — it scans for content sourced from gitignored
claude-shaped local files (`CLAUDE.local.md`, `.claude/local/*.md`)
and refuses to post on a hit, so private context Jared *reads* never
leaks into the public board it *writes*.

For development setup, testing, and the layout of the plugin's
internals, see [`CLAUDE.md`](CLAUDE.md).

---

## License

MIT.
