# claude-skills

User-level Claude Code skills, version-controlled.

Each subdirectory is one skill, installed automatically by Claude Code when this
directory is mapped to `~/.claude/skills/`. Skills activate based on their
`description` field in SKILL.md's frontmatter — Claude sees the description in
every session's available-skills list and invokes the skill when its triggers
match the conversation.

## Layout

```
~/.claude/skills/
├── README.md                    ← this file
├── .gitignore                   ← ignores eval workspaces + pycache
└── <skill-name>/
    ├── SKILL.md                 ← required: frontmatter (name, description) + body
    ├── references/              ← optional: detailed how-tos, loaded on demand
    └── scripts/                 ← optional: executables the skill can invoke
```

## Skills

- **manage-project-board** — steward GitHub Projects v2 boards with PM discipline. Fires on session start, starting/completing work, scope changes, and any `where are we / what's next` moment.

## Authoring new skills

Use the `skill-creator` skill (from the claude-code-setup plugin) to scaffold
and iterate. Core loop: draft → test cases → user review → iterate.

## Machine-level vs cross-device use

This repo is cloned into `~/.claude/skills/` on each machine. Claude Code
auto-discovers whatever's there. Multi-device setup:

```bash
git clone git@github.com:brockamer/claude-skills.git ~/.claude/skills
```

Skill-level evaluation workspaces (`*-workspace/`) are gitignored — they hold
large binary eval artifacts and are per-machine.

## Modifying a skill

Edit in place and commit. Skills load fresh per session, so the next session
picks up the new version automatically. For non-trivial changes, run eval
iterations via skill-creator to verify the change didn't regress triggering or
output quality.
