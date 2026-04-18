# Board Sweep — Grooming Checklist

Run this procedure when the user asks "where are we", when In Progress drops to 0, when a week passes without explicit grooming, or any time you notice drift.

## Goals

1. Every open item has complete metadata (Priority + Work Stream + Status + Labels + Milestone when applicable).
2. Active work (In Progress) reflects reality — no abandoned items pretending to be active.
3. Near-future work (Up Next) is ordered by priority and pullable.
4. Far-future work (Backlog) is prioritized so the next grooming knows what's next.
5. The Roadmap view (via milestones) shows a credible sequence of near-term releases.
6. Dependencies are surfaced — blocking chains visible, not buried.

## Checks

Run in order — each flag is a prompt for a directive proposal to the user, not a unilateral fix.

### 1. Metadata completeness

Every open item must have Priority + Work Stream set. Items without these sort to the bottom of the board and become invisible. Flag for fix.

Query:
```bash
gh project item-list <project-number> --owner <owner> --limit 200 --format json \
  | python3 -c "
import sys, json
items = json.load(sys.stdin)['items']
missing = []
for i in items:
    if i.get('content', {}).get('state') == 'CLOSED':
        continue
    n = i.get('content', {}).get('number')
    if not i.get('priority') or not (i.get('work Stream') or i.get('workStream')):
        missing.append(f'#{n}: priority={i.get(\"priority\")}, work_stream={i.get(\"work Stream\") or i.get(\"workStream\")}')
for m in missing:
    print(m)
"
```

### 2. In Progress sanity

- Count > 3? Focus is scattered. Propose: finish one, demote one to Up Next, or pause one.
- Count == 0? Nothing actively being worked. Pull the top of Up Next after priority check.
- Any item in In Progress with no commit / comment activity in the last 7 days? Flag as stale — finish, punt, or close.

### 3. Up Next queue

- More than 3 items in Up Next? The queue is overstocked. Only the top item gets picked next; the rest create the illusion of planning.
- Up Next items should have Priority (High or Medium — Low rarely belongs in Up Next).
- Up Next items without a clear "next action" in the issue body — flag to the user; fuzzy planning means the item isn't really ready.

### 4. High-priority backlog age

Any `priority: High` item sitting in Backlog for >14 days without movement? Propose one of:
- Promote to Up Next (if it's still the right priority)
- Downgrade to Medium (if new information reduced urgency)
- Close as obsolete (if the need went away)

Query (approximation):
```bash
gh issue list --repo <owner>/<repo> --state open --limit 200 --json number,title,createdAt,labels \
  | python3 -c "
import sys, json, datetime as dt
items = json.load(sys.stdin)
cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=14)
for i in items:
    created = dt.datetime.fromisoformat(i['createdAt'].replace('Z', '+00:00'))
    if created < cutoff:
        print(f\"#{i['number']}: created {created.date()} — {i['title'][:60]}\")
"
# Then cross-reference with priority:High via project JSON
```

### 5. Done backlog

Issues closed but still on the board in Done since before the last release tag — fine to leave, but glance for anything that should have been closed differently (e.g., an issue closed as "won't fix" that's still listed as Done without context). Add a label like `wontfix` or `obsolete` if appropriate.

### 6. Label hygiene

Legacy labels phase out over time. Check for:
- Deprecated labels (e.g., `priority: high` when the Priority field is now canonical) — strip them.
- Labels on one issue but not on similar issues — either standardize or remove.
- Issues with no labels at all (other than stage labels) — flag for triage.

### 7. Milestone coverage

For every near-term milestone (next 1–2 releases):
- Does it have a target date?
- Is the open/closed ratio realistic for the date (e.g., 20 open issues with a 2-week deadline is suspicious)?
- Are issues in the milestone correctly Work-Streamed?

### 8. Dependency chain visibility

For each open issue with a `Depends on:` section in its body:
- Are the referenced issues still open? If all closed, remove the dependency note (it's done).
- Are dependency issues themselves prioritized? A high-priority dependent on a low-priority dependency is a contradiction.
- Any circular dependencies? Flag hard.

See `dependencies.md` for the graph-building routine that makes this scalable.

### 9. Drift between convention doc and board

Read `docs/project-board.md` and verify the field IDs, option IDs, and conventions it documents match the actual board. If the board has added a new status column, a new priority option, a new work stream, the doc must reflect it. If the doc is stale, fix the doc in the same grooming session.

## Output of a sweep

Present the user with a proposal, not a unilateral fix:

```
Sweep 2026-04-18:
- 3 issues missing Priority (#47, #52, #61) — propose setting all to Medium unless they're urgent.
- In Progress=2 (healthy).
- #27 in High Backlog since 2026-03-25 (24d) — propose demoting to Medium.
- Milestone "v0.2" has no target date — propose 2026-05-15.
- Label `priority: low` still on #7 alongside Priority field Medium — propose stripping.

Approve? (y / cherry-pick / skip)
```

Wait for user sign-off before applying bulk changes. Board-sweep output is *advisory*, not *executable without consent*.
