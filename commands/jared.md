---
description: Fast read-only status of the project board — In Progress, top of Up Next, blocked, aging.
---

Invoke the Jared skill and produce a fast status report of the project board in the current repo.

Specifically:

1. Read `docs/project-board.md` (or the equivalent convention file) to identify the project URL and owner.
2. Show In Progress items with their most recent Session note's Next action.
3. Show the top 3 items in Up Next.
4. Show any items in Blocked state.
5. Flag aging: In Progress items with no activity in 7+ days, and High-priority Backlog items older than 14 days.
6. Report total open items and count by Priority.

This is read-only — do not propose changes, do not run a full sweep. For grooming, use `/jared-groom`. For structural review, use `/jared-reshape`.

Output format (one screen):

```
Where we are (YYYY-MM-DD):

In Progress (N/cap):
  #<N> [<Priority>] <title>
    Last session: "<one-line Next action from latest Session note>"

Up Next (top 3):
  #<N> [<Priority>] <title> — <pullable? yes/no — reason if no>

Blocked:
  #<N> — <reason from ## Blocked by>

Aging:
  #<N> (<In Progress: no activity Nd> | <High Backlog: Nd old>)

Totals: <open> open (<H>H / <M>M / <L>L)
```

If anything looks urgent — a Blocked item whose blocker is now closed, an aging High that's been ignored — mention it in one line after the summary but don't propose a fix in `/jared`. That's what `/jared-groom` is for.
