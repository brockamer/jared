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

## `jared get-item <issue_number> [--body]`

**Purpose.** Print a JSON blob with the item-id, Status, Priority, and all
field values for one issue. Useful as a scripting helper — pipe to `jq`
when composing shell flows.

```
jared get-item <issue_number> [--body]
```

**Flags.**

- `--body` — also return the issue's full Markdown body under a `body` key.
  This is the supported route to an issue body on **either** backend (#410),
  and the one `/jared-start` step 5 cites: `gh issue view --json body` has no
  equivalent where there is no GitHub repo. Opt-in, because the body costs an
  extra read and most callers want only the field values. Without the flag the
  output shape is unchanged and no body read is issued.

**Example.**

```
$ jared get-item 7 | jq '.status, .priority'
"Backlog"
"Medium"

$ jared get-item 7 --body | jq -r '.body' | head -1
One-sentence summary of what this issue is about and why it matters.
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

## `jared set-milestone <issue_number> (<title> | --none)`

**Backend gate.** Assignment works on both backends — milestones map to
swimlanes on KanbanFlow (MILESTONE_ASSIGNMENT present, #390). `--none` (clear)
is different: a KanbanFlow task always occupies a swimlane, so there is no
"no milestone" state to clear into. `jared set-milestone <N> --none` on
KanbanFlow exits nonzero with a message explaining that, rather than silently
no-oping.

**Purpose.** Assign a milestone to an issue **already on the board**, or clear
one. `jared file --milestone` covers the creation case; this covers everything
after. Without it the only route was `gh issue edit`, which does not exist on a
non-GitHub backend.

```
jared set-milestone <issue_number> "Marketplace readiness"
jared set-milestone <issue_number> --none
```

**Why it matters more than it looks.** `stage.py` ranks Priority ties by
milestone proximity. An item with no dated milestone is *deferred* with
`no milestone with due date` rather than ranked, so it never promotes on its
own. Assigning a milestone is what makes a Backlog item competitive — it is a
staging operation, not cosmetic metadata.

**Validation.** The title must match an open milestone, checked before any
write. An unknown or closed title exits 2 and lists the open milestones rather
than creating one silently — `jared file --milestone`'s posture, deliberately.
The validation lives in the CLI rather than the provider so both backends
refuse with one error shape.

**`--none` is the only clear.** There is no `--milestone ""`; an empty value
must never reach the clear path. Passing neither a title nor `--none` is a
refusal, not a silent clear, and passing both is a refusal rather than a
precedence rule.

**Design note — why the seam has two methods.** `clear_milestone(ref)` is paired
with `set_milestone(ref, name)` instead of widening `name` to `str | None`.
`gh issue edit` models the clear as its own `--remove-milestone` flag, the
provider interface already pairs `add_label`/`remove_label` and
`add_blocked_by`/`remove_blocked_by`, and — decisively — KanbanFlow's
`update_task` uses `None` to mean *leave unchanged*, so a nullable argument
there would POST an empty body and report success having changed nothing.
Verified against the fake client: the pass-through implementation did not raise
and the swimlane survived. See #427.

---

## `jared close <issue_number> [--body TEXT | --body-file PATH]`

**Backend gate (CLOSED_STATE absent — KanbanFlow).** The Done column is the sole closed signal, so no native closed state is set. The OK line gains `(column-move only — no native closed state on this backend)`. `_cmd_close` computes its own note through `degraded_or_none`; read `lib/capabilities.py` for the one note phrasing rather than trusting a literal quoted here.

**Purpose.** Close an issue and leave it in a definitive Done state.
The subcommand runs `gh issue close`, then **always** sets `Status=Done`
explicitly. This is defense-in-depth (#137), not a poll: GitHub's
project-v2 auto-move is eventually consistent, so the explicit set is a
cheap no-op when the auto-move already fired and a genuine save when it
did not. There is no retry loop and no conditional fallback.

Optionally post a Session note in the same atom — `--body` / `--body-file`
mirror `jared comment` and `jared file`. When supplied, the comment is
posted *before* the close, so a close failure leaves the issue open with
a stray comment; re-run `jared close <N>` without `--body*` to retry just
the close. Closing first then failing to comment would leave a closed
issue without a Session note, which is the discipline this flag exists
to enforce.

```
jared close <issue_number> --body "Done — shipped in v0.21."
jared close <issue_number> --body-file close-note.md
cat close-note.md | jared close <issue_number> --body-file -
```

**Example.**

```
$ jared close 12
OK: closed #12, board auto-moved to Done

$ jared close 12 --body-file close-note.md
OK: commented on #12 (https://github.com/owner/repo/issues/12#issuecomment-…)
OK: closed #12, Status=Done
```

PII pre-flight (#102) runs on the comment body, same as `jared comment`
and `jared file`. A redaction-dirty body short-circuits before any gh call —
neither the comment nor the close runs.

---

## `jared comment <issue_number> (--body TEXT | --body-file PATH)`

**Purpose.** Add a comment to an issue. Three input forms, mutually exclusive:
`--body "<text>"` for inline content, `--body-file <path>` for a markdown file,
`--body-file -` to read from stdin (the typical pattern for session notes or
anything multi-line).

```
jared comment <issue_number> --body "Quick one-liner update."
jared comment <issue_number> --body-file session-note.md
cat session-note.md | jared comment <issue_number> --body-file -
```

---

## `jared file --title ... (--body ... | --body-file ...) --priority ... (--milestone NAME | --no-milestone)`

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
  --field "Work Stream=Planning" \
  --milestone "v1.0 — public install"

# Or inline body + explicit no-milestone for big-idea/wishlist filings:
jared file --title "Quick fix" --body "One-line summary of the bug." \
  --priority Low --no-milestone
```

**Arguments:**

| Flag | Required | Notes |
|---|---|---|
| `--title` | yes | Issue title; keep ≤ 70 chars, verb-first. |
| `--body` / `--body-file` | yes (exactly one) | `--body "<text>"` for inline content; `--body-file <path>` for a markdown file; `--body-file -` reads stdin. Mutually exclusive. |
| `--priority {High,Medium,Low}` | yes | Enforced to avoid filing with null Priority. |
| `--milestone NAME` / `--no-milestone` | yes (exactly one) | Either assign a milestone by title (validated against the repo's open milestones) or opt out explicitly. Filing without either flag is refused with a listing of open milestones — closes the orphan-issue stream that eight consecutive findajob structural reviews had to bulk-absorb. Mutually exclusive. |
| `--status` | no | Any Status column. Default: `Backlog`. |
| `--label` | no | Repeatable. |
| `--field` | no | Repeatable `NAME=VALUE` for additional single-select fields (e.g. `Work Stream=Planning`). |

**Milestone resolution.** `--milestone NAME` is matched by exact title
against `gh api repos/<owner>/<repo>/milestones?state=open`. An unmatched
name produces a clear error listing the open milestones — no silent
fallback, no auto-create. Use `--no-milestone` for filings where assignment
doesn't make sense yet (wishlist, big-idea items).

**Invariant.** On success, stdout reports `OK: filed #N → <status>,
Priority=<prio>` and the URL. Any step failing — board add fails, verification
finds the item with null Status — exits non-zero with a diagnostic and
leaves the issue in place for a human to reconcile.

---

## `jared add-to-board <issue_number> --priority ... [--status ...] [--label ...] [--field ...]`

**Purpose.** Add an *existing* issue to the board and set its required fields —
Priority + Status (+ any extra single-select fields). Idempotent, so it is safe
to re-run. Two uses: the **recovery path** when `jared file` fails *after* the
issue is created (the issue exists but never made it onto the board), and a
**standalone** add for issues created outside `jared file` (e.g. `gh issue
create`, or an issue opened in the GitHub UI).

```
# Recovery / standalone add with the required Priority:
jared add-to-board 42 --priority High

# Land it directly in a column, with labels and an extra field:
jared add-to-board 42 --priority Medium --status "Up Next" \
  --label enhancement --field "Work Stream=Planning"
```

**Arguments:**

| Flag | Required | Notes |
|---|---|---|
| `issue_number` | yes | Positional. The existing issue to add to the board. |
| `--priority {High,Medium,Low}` | yes | Enforced — an issue added without Priority sorts to the bottom with null Status and effectively disappears. |
| `--status` | no | Any Status column. Default: `Backlog`. |
| `--label` | no | Repeatable issue label. |
| `--field` | no | Repeatable `NAME=VALUE` for additional single-select fields (e.g. `Work Stream=Planning`). |

**Why it exists.** `jared file` is create + add + set-fields as one atom; if it
fails *after* the GitHub issue is created, the issue is stranded off the board.
`add-to-board` is the idempotent re-entry point that finishes the job — which is
why `sweep.py` and `references/board-sweep.md` hand it to the operator as
paste-able recovery copy. It takes no `--milestone` flag; milestone assignment
lives on `jared file` (or raw `gh issue edit --milestone`).

---

## `jared blocked-by <dependent> <blocker> [--remove]`

**Backend gate (NATIVE_DEPENDENCIES absent — KanbanFlow).** GraphQL mutations are unavailable; label-marker emulation is used instead. The command still works — edges are recorded as `blocked-by:<N>` label markers — and the OK line gains `(label emulation — NATIVE_DEPENDENCIES not supported on this backend)`. `_cmd_blocked_by` computes its own note through `degraded_or_none`; read `lib/capabilities.py` for the one note phrasing rather than trusting a literal quoted here. Note that `dependency-graph.py` does not consume these label markers — see `references/dependencies.md`.

**Purpose.** Add or remove a native GitHub `blockedBy` edge between two
issues. This uses the `addBlockedBy` / `removeBlockedBy` GraphQL mutations;
the edges show up in the GitHub issue UI's "Blocked by" panel and are what
`dependency-graph.py` and `sweep.py` consume. *(GraphQL mutations are GitHub-specific — see backend gate above.)*

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
