# Jared

Claude Code plugin: a GitHub Projects v2 board steward. Treats the board
as the single source of truth for what's being worked on. Files, moves,
grooms, and structurally reviews issues with discipline.

## Install

```
/plugin marketplace add brockamer/jared
/plugin install jared
```

Then in any project with a `docs/project-board.md`, use `/jared` for a fast
status, or one of the workflow commands: `/jared-file`, `/jared-start`,
`/jared-groom`, `/jared-wrap`, `/jared-reshape`, `/jared-init`.

If the project has no `docs/project-board.md` yet, run `/jared-init` to
bootstrap it against an existing (or new) GitHub Projects v2 board.

## Developing

This plugin lives at `~/Code/jared/`. For active development, install from
the local checkout:

```
/plugin marketplace remove jared-marketplace
/plugin marketplace add file:///home/brockamer/Code/jared
/plugin install jared
```

After editing files under `~/Code/jared/`, run `/plugin update jared` to
re-sync the plugin cache, then `/reload-plugins` to reload. Claude Code
copies plugins into `~/.claude/plugins/cache/` at install time — edits to
the source are not picked up until you re-sync. (See
[plugin-marketplaces docs][pm].)

[pm]: https://code.claude.com/docs/en/plugin-marketplaces.md

## Testing

```
pytest                  # unit tests (fast, offline)
pytest -m integration   # integration tests (runs against the testbed
                        # in brockamer/jared-testbed; requires
                        # tests/testbed.env configured)
```

See `tests/testbed-setup.md` for testbed setup.

## Layout

```
.claude-plugin/
  plugin.json           Plugin metadata
  marketplace.json      Self-hosted marketplace manifest
commands/               Slash-command stubs (7 of them)
skills/jared/
  SKILL.md              Skill contract
  references/           Detail docs loaded on demand
  scripts/              jared CLI + batch tools
    jared               Unified CLI: file, move, set, close, comment,
                        blocked-by, get-item, summary
    lib/board.py        Shared helper: board parsing, gh wrapper,
                        item-id lookup
    sweep.py            Routine grooming sweep
    bootstrap-project.py  Introspect a board; write docs/project-board.md
    dependency-graph.py  Render issue-dependency graph
    capture-context.py   Append Session notes / Decisions to issue body
    archive-plan.py      Archive a completed plan doc
  assets/               Templates (issue body, session note, etc.)
tests/                  pytest suite
docs/superpowers/       Specs and plans for this plugin's own work
```

## Versioning

Semantic versioning in `plugin.json`. Git tag `v<x.y.z>` per release.

## License

MIT.
