# Human-Readable Board Surface

The board's value is that a human glancing at it understands the state of the world. Detailed content belongs in the issue body's living sections or in collapsed `<details>` blocks; the *surface* (column views, titles, first visible lines) must be scannable without expanding.

## Title templates

**Bug:** `Fix <thing>: <specific symptom>`
- ✅ `Fix sync_sheet.py: hidden fingerprint column drifting to column A`
- ❌ `sync_sheet has a bug`

**Enhancement:** `Add <thing>` or `Improve <thing>: <how>`
- ✅ `Add excluded_employers config + prefilter enforcement`
- ✅ `Improve scorer: tier-1 company boost only when JD is present`
- ❌ `More scorer improvements`

**Refactor:** `Refactor <thing> to <outcome>`
- ✅ `Refactor path resolution to use findajob.paths module`
- ❌ `Clean up paths`

**Documentation:** `Doc: <what>` or `Document <thing>`
- ✅ `Doc: refresh operations/architecture/scripts-reference for Docker deploy`
- ❌ `Update docs`

**Non-software (e.g., renovation):** `<Verb> <area>: <specific>`
- ✅ `Demo kitchen: remove upper cabinets and backsplash`
- ❌ `Kitchen work`

### Constraints

- ≤ 70 characters. GitHub truncates after ~50 in list views; 70 is a hard ceiling.
- Verb-first. No "X needs to happen" or "Feature: X" — those waste scannable chars.
- No issue numbers in titles (`#12 follow-up`) — `#N` is already linked natively.

## Issue body template

The default template lives at `assets/issue-body.md.template`. The skeleton:

```markdown
One-sentence summary.

## Current state
Not started. (Or: living summary of where the implementation stands.)

## Decisions
(none yet)

## Acceptance criteria
<details>
<summary>Expand</summary>

- Criterion 1
- Criterion 2

</details>

## Depends on
(none)

## Blocks
(none)

## Planning
(none)
```

### What goes in each section

- **One-sentence summary (first paragraph).** The entire "why" — readable without expanding.
- **`## Current state`** — living, overwrite as work progresses. What's been done so far, what's next. One paragraph. For Backlog items, "Not started." Jared's `capture-context.py` updates this.
- **`## Decisions`** — append-only. Each entry dated. Captures material choices made during implementation that aren't obvious from the diff. Example:
  ```
  ### 2026-04-19
  Chose Redis over Memcached because we already run Redis for session state; adding a second cache layer wasn't worth the operational cost.
  ```
- **`## Acceptance criteria`** — in a `<details>` block. The testable conditions that mean the issue is done.
- **`## Depends on`** / **`## Blocks`** — `#N` references. Used when native GitHub issue dependencies aren't available, or for cross-repo. See `references/dependencies.md`.
- **`## Planning`** — link to plan/spec files if Superpowers-style planning is in use. See `references/plan-spec-integration.md`.

### Constraints

- First paragraph is a single sentence. Readable in under 5 seconds.
- `<details>` for deep scope, not for the living sections. `## Current state` and `## Decisions` are visible.
- No headings deeper than `##` at body top level. `###` and below inside `<details>` or as `## Decisions` entry dates.
- Dependencies, blocks, and planning references go at the bottom — reference metadata, not summary.

## When to break the template

- **Strategic / roadmap issues** (e.g., "GA roadmap" issue) — often longer bodies, functioning as reference docs. Use `##` headings for navigable sections, `<details>` for truly deep content.
- **Execution checklists** — e.g., deployment tickets. Summary at top, checklist after, don't hide the checklist.

## Comments — what to use them for

- **Session notes.** Format at `assets/session-note.md.template`. One per session per touched issue.
- **Context added mid-work** that doesn't belong in the living body sections.
- **PR linkages.** "Implemented in #<PR>" on close.

Don't use comments for:

- Status updates that should be field changes (Priority, Status).
- Content that belongs in `## Current state` or `## Decisions` — keep those on the body so they're visible without scrolling.

## Labels

Labels describe *kind*, not priority or status:

- `bug` / `enhancement` / `refactor` / `documentation` / `test` — type
- `blocked` — state (must pair with `## Blocked by` section in body)
- `good-first-issue` — contributor signal
- Project-specific scope labels (e.g., `job-search`, `pipeline-quality`, or `demo`, `rough-in`, `finish` for renovation)

Do not use labels for:

- Priority (the Priority field is canonical; legacy `priority:` labels get stripped)
- Status (the Status field handles columns)
- Assignment (the Assignee field)

## Scannability tests

After filing or editing, read the first 100 characters. Can you tell:

1. What is this about?
2. What kind of work is it?
3. What's it part of?

Any No, rewrite.

Read in list view (`jared summary` or `gh issue list`). Fits on one line? If not, trim.
