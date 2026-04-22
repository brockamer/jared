# `jared` CLI — subcommand reference

Unified CLI for common GitHub Projects v2 board operations. Every subcommand
reads `docs/project-board.md` (configurable via `--board`) to resolve the
project number, field IDs, and single-select option IDs before calling `gh`.
This is Tier 2 in the skill's tool-selection model (see `SKILL.md`).

Invoke in production via the plugin root:

```
${CLAUDE_PLUGIN_ROOT}/skills/jared/scripts/jared <subcommand> [...]
```

Global option:

- `--board PATH` — override the convention-doc path (default `docs/project-board.md`).

## Exit codes

| Code | Meaning |
|---|---|
| 0 | Success. |
| 1 | Config or lookup error (missing board file, unknown field/option, issue not on project). Fix the convention doc or argument and retry. |
| 2 | `gh` itself failed (auth, network, GitHub API error) or post-create verification detected a drift. Stderr carries the underlying message. |

---

## `jared summary`

**Purpose.** One-screen board status. Read-only.

```
jared summary
```

Output: In Progress items with priorities, top 3 Up Next, and any Blocked
items (Blocked is rendered without priority — the state matters more than
ranking for blocked work). Does not flag aging or propose changes — for
that use `/jared-groom`.

**Example.**

```
$ jared summary
Board: https://github.com/users/brockamer/projects/2

In Progress (2):
  #1 [High] Generate candidate trajectories in 20Hz loop
  #2 [High] Replace ad-hoc PID with cascaded loop

Up Next (top 3 of 4):
  #3 [High] Waypoint acceptance geometry
  ...

Blocked (1):
  #6 Contract renewal with Vendor Y
```

---

## `jared get-item <issue_number>`

**Purpose.** Print a JSON blob with the item-id, Status, Priority, and all
field values for one issue. Useful as a scripting helper — pipe to `jq`
when composing shell flows.

```
jared get-item <issue_number>
```

**Example.**

```
$ jared get-item 7 | jq '.status, .priority'
"Backlog"
"Medium"
```

---

## `jared set <issue_number> <field_name> <value>`

**Purpose.** Set any single-select field on an issue. Looks up the item-id
from the issue number, then looks up the field-id + option-id from
`docs/project-board.md`, then calls `gh project item-edit`.

```
jared set <issue_number> "Priority"    "High"
jared set <issue_number> "Work Stream" "Planning"
jared set <issue_number> "Status"      "Up Next"
```

For Status specifically, `jared move` is the one-arg shortcut.

---

## `jared move <issue_number> <status>`

**Purpose.** Convenience shortcut: `jared move N "In Progress"` is exactly
`jared set N "Status" "In Progress"`.

```
jared move <issue_number> "In Progress"
jared move <issue_number> "Done"
```

**Note.** `Blocked` is a Status column here, not a label. The five
conventional columns are Backlog / Up Next / In Progress / Blocked / Done.

---

## `jared close <issue_number>`

**Purpose.** Close an issue and verify the board auto-moves it to Done.
GitHub's project-v2 auto-move is eventually consistent; this subcommand
polls for up to ~3 attempts, and if the auto-move hasn't fired, forces
`Status=Done` explicitly. Either way you get a definitive Done state
before the command returns.

```
jared close <issue_number>
```

**Example.**

```
$ jared close 12
OK: closed #12, board auto-moved to Done
```

---

## `jared comment <issue_number> --body-file PATH`

**Purpose.** Add a comment to an issue. `--body-file -` reads from stdin,
which is the typical pattern for session notes or anything multi-line.

```
jared comment <issue_number> --body-file session-note.md
cat session-note.md | jared comment <issue_number> --body-file -
```

---

## `jared file --title ... --body-file ... --priority ...`

**Purpose.** Atomic create-issue + add-to-board + set-Priority + set-Status
+ post-create verification. Kills the `gh issue create` / `gh project
item-add` footgun where issues land on the board with `Status=None` and
disappear.

```
jared file \
  --title "Add waypoint acceptance geometry" \
  --body-file issue-body.md \
  --priority High \
  --status "Up Next" \
  --label enhancement \
  --field "Work Stream=Planning"
```

**Arguments:**

| Flag | Required | Notes |
|---|---|---|
| `--title` | yes | Issue title; keep ≤ 70 chars, verb-first. |
| `--body-file` | yes | Path to the markdown body (see `assets/issue-body.md.template`). |
| `--priority {High,Medium,Low}` | yes | Enforced to avoid filing with null Priority. |
| `--status` | no | Any Status column. Default: `Backlog`. |
| `--label` | no | Repeatable. |
| `--field` | no | Repeatable `NAME=VALUE` for additional single-select fields (e.g. `Work Stream=Planning`). |

**Invariant.** On success, stdout reports `OK: filed #N → <status>,
Priority=<prio>` and the URL. Any step failing — board add fails, verification
finds the item with null Status — exits non-zero with a diagnostic and
leaves the issue in place for a human to reconcile.

---

## `jared blocked-by <dependent> <blocker> [--remove]`

**Purpose.** Add or remove a native GitHub `blockedBy` edge between two
issues. This uses the `addBlockedBy` / `removeBlockedBy` GraphQL mutations;
the edges show up in the GitHub issue UI's "Blocked by" panel and are what
`dependency-graph.py` and `sweep.py` consume.

```
# #4 is blocked by #1
jared blocked-by 4 1

# later, once #1 ships:
jared blocked-by 4 1 --remove
```

**Note.** The `## Blocked by` body-section convention is still used for
narrative context (who owns the blocker, what "unblocked" looks like). The
native edge is the canonical record; the body section is the human gloss.

---

## Common pitfalls

- **Issue not on the project.** `jared` looks up the item-id via
  `gh project item-list`. If the issue was created without
  `gh project item-add`, the lookup returns `ItemNotFound`. Fix by adding
  it: re-file with `jared file`, or fall through to raw gh
  (see `references/operations.md`).
- **Field/option not in `docs/project-board.md`.** The CLI validates every
  field and option name against the convention doc. If you renamed a
  field or added an option via the GitHub UI, re-run
  `bootstrap-project.py` to refresh the machine-readable header.
- **`--body-file -` with a heredoc.** Shells pass a heredoc as stdin, so
  `--body-file -` works with:
  ```
  jared comment 42 --body-file - <<'EOF'
  ## Session 2026-04-22
  ...
  EOF
  ```
