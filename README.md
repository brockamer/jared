# claude-skills

A Claude Code plugin that bundles a skill and its matching slash commands.

Currently ships one skill — **jared** — a GitHub Projects v2 steward that
treats the board as the single source of truth for what's being worked on,
with a disciplined set of slash commands for filing, grooming, starting,
wrapping, and structurally reviewing work.

## Layout

```
claude-skills/
├── .claude-plugin/
│   └── plugin.json            ← plugin metadata
├── commands/                  ← slash command stubs
│   ├── jared.md               ← /jared        — fast read-only status
│   ├── jared-file.md          ← /jared-file   — file a new issue with full metadata
│   ├── jared-groom.md         ← /jared-groom  — routine board sweep
│   ├── jared-init.md          ← /jared-init   — bootstrap Jared on a project
│   ├── jared-reshape.md       ← /jared-reshape — structural review
│   ├── jared-start.md         ← /jared-start  — begin work on an issue
│   └── jared-wrap.md          ← /jared-wrap   — end-of-session handoff
├── skills/
│   └── jared/
│       ├── SKILL.md           ← skill contract + frontmatter
│       ├── references/        ← detailed references loaded on demand
│       ├── scripts/           ← executable helpers (sweep.py, bootstrap, etc.)
│       └── assets/            ← templates (issue body, plan conventions, etc.)
├── .gitignore
└── README.md
```

## Installing

### Machine-local (via symlinks)

The simplest setup — links the plugin's `skills/` and `commands/` into
Claude Code's user-level directories:

```bash
git clone git@github.com:brockamer/claude-skills.git ~/Code/claude-skills
mkdir -p ~/.claude/skills ~/.claude/commands
ln -s ~/Code/claude-skills/skills/jared ~/.claude/skills/jared
for f in ~/Code/claude-skills/commands/*.md; do
  ln -s "$f" ~/.claude/commands/"$(basename "$f")"
done
```

### As a Claude Code plugin

If/when this repo is published to a plugin marketplace, `/plugin install
jared` will be the preferred path. Until then, the symlink install above
is equivalent.

## Authoring new skills

Use the `skill-creator` skill (from the claude-code-setup plugin) to
scaffold and iterate. Core loop: draft → test cases → user review →
iterate. When a skill has matching slash commands, colocate them in
`commands/` — the plugin layout pairs them.

## Modifying an existing skill

Edit in place and commit. Claude Code loads skills fresh per session,
so the next session picks up the new version automatically. For
non-trivial changes, run eval iterations via skill-creator to verify
the change didn't regress triggering or output quality.
