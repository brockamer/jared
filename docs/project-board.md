# Project Board — How It Works

<!-- Machine-readable metadata — jared scripts parse this. Do not reorder or
     rename the fields below. The narrative docs after the field blocks are
     for humans; jared ignores them. Re-run bootstrap-project.py after any
     schema change to keep this file in sync. -->

- Project URL: https://github.com/users/brockamer/projects/4
- Project number: 4
- Project ID: PVT_kwHOAgGulc4BVgT5
- Owner: brockamer
- Repo: brockamer/jared

### Status
- Field ID: PVTSSF_lAHOAgGulc4BVgT5zhQ7qm4
- Backlog: 4e0a1177
- Up Next: b44a3a0e
- In Progress: 47fc9ee4
- Blocked: 4d8fe8ca
- Done: 98236657

### Priority
- Field ID: PVTSSF_lAHOAgGulc4BVgT5zhQ7sS8
- High: adef53b9
- Medium: d5a00122
- Low: 7d424cac

### Work Stream
- Field ID: <unset>
- (field not present)

<!-- End machine-readable block — narrative docs follow. -->

The GitHub Projects v2 board at [jared](https://github.com/users/brockamer/projects/4) is the **single source of
truth for what is being worked on and why**. No markdown tracking files, no separate
backlog lists, no TODO.md. If it isn't on the board, it isn't on the roadmap.

This document describes the conventions so anyone (human or Claude session) can triage,
prioritize, and move work consistently.

**Bootstrapped by Jared on 2026-04-23.** If you rename fields or add options,
re-run `scripts/bootstrap-project.py --url https://github.com/users/brockamer/projects/4 --repo brockamer/jared` or edit this
file directly.

## Columns (Status field)

| Column | Meaning |
|---|---|
| **Backlog** | Captured but not yet scheduled. |
| **Up Next** | Scheduled to be picked up next. The on-deck queue. |
| **In Progress** | Actively being worked on right now. |
| **Blocked** | Waiting on a dependency. Pair with a `## Blocked by` section in the issue body, or use `jared blocked-by` to record a native GitHub issue dependency. |
| **Done** | Closed issues. Auto-populated when an issue closes. |

**Rules:**

- In Progress stays small. More than ~3 items means focus is scattered.
- Up Next is ordered — top item is what gets worked next. Priority field breaks ties.
- Nothing in In Progress without Priority set.
- When an issue closes, it moves to Done automatically — but only when the project's built-in "Item closed → Done" workflow is enabled. `jared close` has an explicit Status=Done fallback that works regardless; raw `gh issue close` and PR-merge auto-close rely on the workflow. If the workflow is off, `/jared-groom` flags stuck items and proposes `jared set <N> Status Done` per item.

## Priority field

| Value | Meaning |
|---|---|
| **High** | Directly advances the current strategic goal. Addressed before Medium. |
| **Medium** | Quality, efficiency, or reliability improvement. Important but not urgent. |
| **Low** | Nice-to-have, future-facing, or optional. Safe to defer indefinitely. |

**Rules:**

- Every open issue must have a Priority set.
- High is scarce by design — if everything is High, nothing is.
- Two High items in In Progress at once should be rare and deliberate.

## Work Stream field

_Not used on this project — jared is single-purpose._

## Labels

Labels describe **what kind of issue it is**, not where it lives on the board. Status
and priority come from board fields, not labels.

Suggested defaults (create via `gh label create` as needed):

| Label | Meaning |
|---|---|
| `bug` | Something isn't working |
| `enhancement` | New capability |
| `refactor` | Restructuring without behavior change |
| `documentation` | Docs-only change |
| `epic` | Durably parent-shaped — roadmap, checklist, strategic anchor. Lacks acceptance criteria by design; stays in Backlog as a long-horizon container. `/jared-stage` exempts these from "Deferred (this pass)" noise. |

**Do not** create a `blocked` label. Blocked is a Status column on this board, not a label — see Status above.

Project-specific scope labels (e.g., `infra`, `frontend`, `customer-facing`) belong here
too — add them as needed.

## Project workflows — recommended settings

GitHub Projects v2 ships several auto-status workflows. Most are useful with
Jared's discipline, but **"Pull request linked to issue" must be disabled** on
a Jared-stewarded board.

| Workflow | Recommended | Why |
|---|---|---|
| `Item added to project` | off | `jared file` sets Status explicitly. |
| `Item closed` | on | Auto-moves Done when an item is closed. |
| `Pull request linked to issue` | **off** | Sets Status=`In Progress` whenever a PR is linked — including retroactively when a *later* PR's commit body contains `closes #N` / `fixes #N` in prose. Reverts the Status that `jared close` just set. See #156. |
| `Pull request merged` | on | Sets Status=Done on closing PR merge. |
| `Auto-close issue` | on | Closes the issue when its PR merges. |
| `Auto-add sub-issues to project` | on | Convenience. |

To inspect or toggle workflows: open the project's *Workflows* tab in the GitHub UI, or use the GraphQL `deleteProjectV2Workflow` mutation (irreversible via API; re-create from the UI).

**Discipline reminder:** when describing past PRs in commit bodies, avoid the closing keywords `closes #N` / `fixes #N` / `resolves #N` in narrative prose — GitHub's auto-link parser doesn't distinguish parentheticals from directives. Refer to past PRs by number alone (`PR #152`) or paraphrase (`addressed in #152`). Reserve closing keywords for the current PR's own intent, on a dedicated line.

## Triage checklist — new issue

When a new issue is filed:

1. **Auto-add to board.** `gh issue create` does not auto-add; use
   `gh project item-add 4 --owner brockamer --url <issue-url>`.
2. **Set Priority** — High / Medium / Low.
3. **Leave Status as Backlog** unless explicitly scheduling.
4. **Apply labels** for issue type and scope.

An issue without Priority sorts to the bottom and disappears. Use `jared file` — it enforces project membership + Status + Priority atomically so this can't happen.

## Fields quick reference (for gh project CLI)

```
Project ID:          PVT_kwHOAgGulc4BVgT5

Status field ID:     PVTSSF_lAHOAgGulc4BVgT5zhQ7qm4
  Backlog:              4e0a1177
  Up Next:              b44a3a0e
  In Progress:          47fc9ee4
  Blocked:              4d8fe8ca
  Done:                 98236657

Priority field ID:   PVTSSF_lAHOAgGulc4BVgT5zhQ7sS8
  High:                 adef53b9
  Medium:               d5a00122
  Low:                  7d424cac

Work Stream:         (not used on this project)
```

## Example — move an item to Up Next

```bash
gh project item-edit \
  --project-id PVT_kwHOAgGulc4BVgT5 \
  --id <ITEM_ID> \
  --field-id PVTSSF_lAHOAgGulc4BVgT5zhQ7qm4 \
  --single-select-option-id b44a3a0e
```

## Further conventions

This file is the minimum. See the skill's references for:

- `references/human-readable-board.md` — title/body templates
- `references/board-sweep.md` — grooming checklist
- `references/plan-spec-integration.md` — if this project uses plan/spec artifacts
- `references/session-continuity.md` — Session note format

## Jared config

Project-level knobs that change Jared's behavior on this board. Each bullet is `name: value`. Omit any line to use its default.

- `session-handoff-prompt: ask` — when `/jared-wrap` finishes, ask whether to draft a session handoff prompt for the next session. Values: `ask` (default), `always`, `never`. Used by `/jared-wrap`. The prompt is written to `tmp/next-session-prompt-<TIMESTAMP>.md` and is `.gitignore`d — ephemeral by design.

- `voice: enabled` — controls whether the Jared character voice is rendered in slash-command dialogue (`/jared`, `/jared-start`, `/jared-wrap`, etc.). Values: `enabled` (default), `disabled`. When `disabled`, every slash-command stub renders user-facing output in plain technical prose — same structural content, Jared-isms stripped. Used by every slash-command stub. The voice activation lives entirely in the plugin (no user-local Claude Code settings, no SessionStart hooks, no memory entries required); this bullet is the only way to opt out. See SKILL.md § "Project-level kill switch" (under the voice doctrine) and `references/voice.md` for the full spec.

- `admin-merge: --merge` — sanctions the `blocked_on_review` escape path in `/jared-wrap`. When a PR is `mergeable` but blocked by required review / branch protection (the common solo-author case on a protected `main`), wrap may offer an operator-confirmed `gh pr merge <N> --admin --merge`. `--admin` bypasses branch protection, so this is opt-in per project; the value pins the merge strategy (`--merge` preserves the phase-commit trail per CLAUDE.md — do not set `--squash`). Omit this line to leave admin-merge unsanctioned, in which case wrap only surfaces the block. Used by `/jared-wrap` (`blocked_on_review` step).
