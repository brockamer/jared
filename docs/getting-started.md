# Getting started — your first 15 minutes

This walkthrough takes you from a freshly-bootstrapped board to "I get the
loop" in about 15 minutes. It assumes you've already followed the README's
[Getting started](../README.md#getting-started) section — `gh` is
authenticated with `project` scope, the `jared` plugin is installed in
Claude Code, and you ran `/jared-init` against your board.

If you haven't done those yet, do them first — this walkthrough starts
where that one ends.

> **Out of scope here:** `/jared-stage` (needs an established backlog),
> plans and specs (`docs/superpowers/`), the structural-review skill
> (`/jared-reshape`). See the README's [A typical week](../README.md#a-typical-week)
> section for the bigger picture once you've used the basics for a few days.

---

## What you'll do

In order:

1. File your first issue.
2. Look at the board.
3. Pull the issue into In Progress.
4. Add a Session note.
5. Close it.
6. Wrap the session.

Everything is typed into Claude Code (slash commands) or your shell (the
`jared` CLI). They produce the same results — slash commands are the
discoverable surface, the CLI is what slash commands call under the hood.

---

## 1. File your first issue

In Claude Code:

```
/jared-file
```

Jared will gather the inputs — either by reading what you already
described in your message, or by asking one short question at a time
(title, body, priority). It also runs a duplicate check before filing,
so if you already opened a similar issue, you'll see that match and be
asked whether to proceed.

Once it has what it needs, the slash command calls the underlying CLI.
The output is two lines:

```
OK: filed #<N> → Backlog, Priority=Medium
URL: https://github.com/<you>/<repo>/issues/<N>
```

Claude may render that summary a little differently in the chat — the
load-bearing facts are the issue number, the Status column, and the
Priority. Note the issue number for the next steps — pass it to CLI
commands as digits only (e.g. `42`, not `#42`; in the shell, `#` starts
a comment).

**What just happened:** Jared created the issue, added it to your project
board, and set Status=Backlog and Priority=Medium atomically. None of
those steps can be skipped — the discipline is that every issue on the
board has Status + Priority set the moment it lands.

> **Why this matters:** issues without a Status sort to the bottom of the
> board and effectively disappear. The `jared file` workflow makes that
> failure mode impossible.

---

## 2. Look at the board

```
/jared
```

You'll see something like:

```
Board: https://github.com/users/<you>/projects/<project-#>

In Progress (0):

Up Next (top 3 of 0):
```

Your new issue is in Backlog, which `/jared` deliberately doesn't list —
the point of the snapshot is "what am I working on right now," not "what
might I work on someday." To see the full backlog, open the board URL.
Blocked is also omitted when empty; it appears as its own section as
soon as the column has at least one item.

---

## 3. Pull the issue into In Progress

```
/jared-start <your-issue-#>
```

Jared will:

- Check WIP (default cap: 3 In Progress at once).
- Read the issue body and verify it's "pullable" — has a summary,
  acceptance criteria, no open dependencies.
- Move it to In Progress.
- Load the latest Session note and any linked plan or spec.
- Print a session-plan announcement and wait for your confirmation.

The move happens *before* the announcement — by the time you see the
plan, the board already shows the issue in In Progress. The confirmation
step is about the work approach, not about the status change.

(`/jared-file` populated the acceptance criteria template when you
filed the issue, so a fresh-filed issue passes the pullable check on
the first try. If you ever try to pull an issue with an empty body,
Jared will pause and suggest reshaping it first — that's the
discipline. You can fill it in, or tell Jared to proceed anyway.)

Reply `go` (or amend the plan first) and the work begins.

---

## 4. Add a Session note

Session notes are how Jared keeps continuity across sessions. The simplest
way to add one manually is via the `jared comment` CLI — body is passed
via `--body` (inline) or `--body-file` (from a file):

```
jared comment <your-issue-#> --body "Started on the typo fix; localized to README line 47."
```

You'll see:

```
OK: commented on #<N> (https://github.com/<you>/<repo>/issues/<N>#issuecomment-<id>)
```

In a real session, notes are richer — what you did, what's next, any
gotchas. The `/jared-wrap` slash command (step 6) writes more structured
notes automatically. This step shows you the manual path.

> **Why session notes:** they're the artifact that makes "what was I
> doing here?" answerable the next time you (or another agent) pulls
> this issue. The wrap workflow folds them in automatically.

---

## 5. Close it

When the work is done, close the issue. For a real fix you'd open a PR
that uses GitHub's auto-close keywords (`Closes #<N>`) and let the merge
close it; the equivalent direct call is:

```
jared close <your-issue-#>
```

You'll see two lines:

```
OK: set Status=Done on issue #<N>
OK: closed #<N>, Status=Done
```

The first line is `jared close`'s defense-in-depth — it *always* writes
Status=Done explicitly, regardless of whether GitHub's project workflow
fired the auto-move. (The auto-move has an observed false-positive mode
where a post-close poll claims Status=Done while the field hasn't
actually changed; the explicit write is the source of truth.) The
second line is the final confirmation. Either way, your issue lands in
the Done column rather than sitting closed-but-stuck.

---

## 6. Wrap the session

In Claude Code:

```
/jared-wrap
```

Wrap is what makes Jared more than a kanban board. It walks every issue
you touched this session, appends a structured Session note to each,
reconciles any drift between work-in-flight and what the issues claim,
and proposes plan archivals for anything completed. On the way out it
regenerates the next-session prompt — the handoff you saw at the top of
this session.

Wrap is a slash-command-driven flow, so the exact rendering varies with
the session. Expect a short summary per touched issue (what was
appended), plus any archival proposals Jared wants you to confirm
before they apply. Read what it shows you and approve or amend.

That's the loop: **file → start → comment → close → wrap.** Everything
else in Jared — stage, groom, reshape, dependency graphs, bake tests —
is in service of keeping that loop honest as the board grows past a
handful of issues.

---

## Where to go next

- **`/jared`** as you start each working session — orient on what's in
  flight and what's queued.
- **`/jared-stage`** once your backlog has more than ~5 items — promotes
  Backlog → Up Next based on pullability, priority, and milestone
  proximity.
- **`/jared-groom`** weekly or so — board hygiene sweep (aging items,
  WIP overflow, missing metadata, pullable check).
- **[SKILL.md](../skills/jared/SKILL.md)** for the full discipline that
  underlies these commands. The slash commands are an entry point; the
  skill is the contract.

When you find yourself filing issues, moving them, and closing them
without thinking about the mechanics — that's the indicator that the
loop has stuck. From there, the rest of Jared (stage, groom, reshape,
plans, specs) is incremental.
