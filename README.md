# Jared

A Claude Code plugin that stewards a GitHub Projects v2 board as the single
source of truth for what's being worked on.

<p align="center">
  <a href="docs/field-notes-full.png">
    <img src="docs/field-notes-full.png"
         alt="Jared — Field Notes: the board is a mirror of reality, not a plan. Click to expand."
         width="480">
  </a>
  <br>
  <em>Field Notes — why Jared exists. Click to expand.</em>
</p>

Project boards drift. Scope gets captured in `TODO:` comments and
`tmp/next-session-prompt.md` files. Issues land on the board with a null
Status field and sort to the bottom of every view, effectively invisible.
Plans approved three weeks ago no longer match the code. By month two the
board is decorative and planning has quietly moved elsewhere.

Jared makes the board unignorable. Every board operation that would
otherwise be a multi-step `gh` dance is a single atomic call that fails
loudly instead of leaving the board half-updated. `jared file` is one
invocation — create the issue, add it to the project, set Priority and
Status, verify. There is no path to "on the board but invisible".

**Status.** v0.2.0, pre-1.0. The plugin's own development runs on a
Jared-stewarded project board; a dedicated `brockamer/jared-testbed`
repo backs the integration tests. Seven slash commands, eight CLI
subcommands, unit + integration test suite.

---

## What it does

Slash commands cover the full work cycle. Use them directly, or let the
skill fire its own triggers mid-conversation when drift signals show up
("let me refactor X", "I noticed", "I'll file that later").

| Command | What it does |
|---|---|
| `/jared` | Fast read-only status — In Progress, top of Up Next, blocked, aging. |
| `/jared-file` | File a new issue with full metadata, atomically. |
| `/jared-start` | Begin work on an issue — move to In Progress, load body + latest Session note + linked plan, announce the session plan. |
| `/jared-groom` | Routine sweep — metadata, WIP, aging, pullable check, plan/spec drift. Proposes; you approve. |
| `/jared-wrap` | End of session — append Session notes to touched issues, reconcile drift, propose plan archivals. |
| `/jared-reshape` | Structural review — shape, phasing, milestones, dependencies, long-horizon arc. |
| `/jared-init` | Bootstrap Jared on a new project — introspect a board, write `docs/project-board.md`, create missing fields. |

Under the hood, a unified Python CLI (`skills/jared/scripts/jared`) owns
the error-prone multi-step operations: `file`, `move`, `set`, `close`,
`comment`, `blocked-by`, `get-item`, `summary`. When the GitHub MCP
plugin is loaded, the skill prefers its typed tools for single-call ops;
the CLI handles everything multi-step. Raw `gh` is a last resort.

## What it enforces

The board model isn't just documented — the CLI validates it.

- **Five Status columns:** `Backlog` / `Up Next` / `In Progress` /
  `Blocked` / `Done`. Blocked is a column, never a label.
- **Status + Priority required** on every issue the moment it lands on
  the board. `jared file` sets them atomically or fails.
- **Blocked-by is a native GitHub issue dependency** (the
  `addBlockedBy` / `removeBlockedBy` GraphQL mutations), not a comment
  convention.
- **Plans cite issues, issues link back.** Plans archive into
  `archived/YYYY-MM/` when the issue ships. Decisions made during
  implementation are captured on the issue, not stranded in a plan file
  that was frozen at approval time.
- **Session notes replace handoff prompts.** `/jared-wrap` appends a
  structured Progress / Decisions / Next action note to every issue
  touched this session. Next session reads the note from the issue — no
  `tmp/next-session-prompt.md` detour.
- **WIP and aging** are enforced with light-touch flagging. In Progress
  caps at the project's configured limit; items with no activity in 7
  days get flagged; Jared never silently re-prioritizes.

---

## Install

```
/plugin marketplace add brockamer/jared
/plugin install jared
```

Then in any project with a `docs/project-board.md`, use `/jared` for a
fast status or the workflow commands above.

## Bootstrap on a new project

If a project has no `docs/project-board.md` yet, run `/jared-init` to
pair the repo with an existing (or new) GitHub Projects v2 board. The
bootstrap introspects the board's field schema and writes a convention
doc with the project ID, field IDs, and single-select option IDs. The
CLI reads that file on every invocation — it's the contract between
Jared and the board.

Non-software projects work the same way. A kanban board for renovating
a house uses the same model — the work streams are "Demo", "Rough-in",
"Finish", the invariants are identical.

---

<details>
<summary><strong>Pocket reference</strong> — install snippets, triggers, the five board states, the Session-note template, anti-patterns. Click to open.</summary>

<p align="center">
  <a href="docs/pocket-reference-full.png">
    <img src="docs/pocket-reference-full.png"
         alt="Jared — Pocket Reference: install, triggers, board states, session-note template, anti-patterns. Click to expand."
         width="560">
  </a>
  <br>
  <em>Click the image for full-resolution.</em>
</p>

</details>

## Developing

For active development, install from a local checkout:

```
/plugin marketplace remove jared-marketplace
/plugin marketplace add file:///path/to/your/checkout/jared
/plugin install jared
```

After editing files, run `/plugin update jared` to re-sync the plugin
cache, then `/reload-plugins` to reload. Claude Code copies plugins into
`~/.claude/plugins/cache/` at install time — source edits are not picked
up until you re-sync. (See [plugin-marketplaces docs][pm].)

[pm]: https://code.claude.com/docs/en/plugin-marketplaces.md

## Testing

```
pytest                  # unit tests — fast, offline, the default
pytest -m integration   # integration tests against brockamer/jared-testbed
                        # (requires tests/testbed.env)
```

See `tests/testbed-setup.md` for testbed setup.

## Layout

```
.claude-plugin/
  plugin.json           Plugin metadata
  marketplace.json      Self-hosted marketplace manifest
commands/               Slash-command stubs (7)
skills/jared/
  SKILL.md              Skill contract
  references/           Detail docs loaded on demand
  scripts/
    jared               Unified CLI: file, move, set, close, comment,
                        blocked-by, get-item, summary
    lib/board.py        Shared helper: board parsing, gh wrapper,
                        item-id lookup
    sweep.py            Routine grooming sweep
    bootstrap-project.py  Introspect a board; write docs/project-board.md
    dependency-graph.py   Render issue-dependency graph
    capture-context.py    Append Session notes / Decisions to issue body
    archive-plan.py       Archive a completed plan doc
  assets/               Templates: issue body, session note, etc.
tests/                  pytest suite (unit + opt-in integration)
docs/                   Field Notes + Pocket Reference + plugin's own
                        project-board.md + superpowers plans
```

## Versioning

Semantic versioning in `.claude-plugin/plugin.json`. Git tag `v<x.y.z>`
per release.

## License

MIT.
