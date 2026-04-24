---
**Shipped in #4, #8, #9, #10, #12, #13, #18, #22, #24, #25 on 2026-04-24. Final decisions captured in issue body.**
---

# Jared Level-Up Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild the `jared` skill as a premium-quality, properly-packaged Claude Code plugin: rename the repo, install via marketplace, extract common GitHub operations into a unified CLI backed by a shared library, rewrite `SKILL.md` around an MCP-first tool-selection discipline, and add unit + opt-in integration tests.

**Architecture:** Three-tier operations model (MCP single-call → `jared` CLI multi-step orchestration → raw `gh` escape hatch). Shared `Board` helper class centralizes `docs/project-board.md` parsing and `gh` invocation. TDD throughout Phase 2. Integration tests run against a dedicated `brockamer/jared-testbed` project.

**Tech Stack:** Python 3.11+, pytest, ruff, mypy (strict), `gh` CLI, GitHub MCP plugin (runtime tool preference), Claude Code plugin system.

**Spec:** `docs/superpowers/specs/2026-04-22-jared-levelup-design.md` — read it first. This plan implements that spec phase-by-phase.

**Convention:** Scripts invoked from skill/command context use `${CLAUDE_PLUGIN_ROOT}/skills/jared/scripts/jared <subcommand>`. Never hardcode `~/.claude/skills/...` paths.

## Issue(s)

- #4 — jared file: GraphQL rate limit during batch filing
- #8 — jared CLI: leaked tracebacks from typed exceptions
- #9 — jared parser: pre-header-block project-board.md rejection
- #10 — jared file: single-shot verification vs. eventual-consistency lag
- #12 — jared CLI: inconsistent error-message prefix
- #13 — jared-init: legacy project-board.md detect + patch
- #18 — Closed issues stuck in pre-close Status column
- #22 — jared close: poll retry + symmetric rate-limit handling
- #24 — jared comment: parses gh plain-text URL response as JSON
- #25 — jared-init: link Projects v2 board to repo

---

## Phase 0 — Housekeeping

### Task 0.1: Push the unpushed commits to origin

**Files:** none (remote sync)

- [ ] **Step 1: Verify state**

```bash
cd ~/Code/claude-skills
git status
git log --oneline origin/main..HEAD
```

Expected: clean working tree; two unpushed commits (`30726d0` and the spec commit `bb04881`).

- [ ] **Step 2: Push**

```bash
git push origin main
```

Expected: both commits uploaded. No errors.

### Task 0.2: Rename GitHub repo

**Files:** none (GitHub state)

- [ ] **Step 1: Rename via gh**

```bash
gh repo rename jared --repo brockamer/claude-skills
```

Expected: "✓ Renamed repository brockamer/claude-skills to brockamer/jared."

- [ ] **Step 2: Verify redirect works**

```bash
gh repo view brockamer/claude-skills --json name,url
```

Expected: JSON reports `"name": "jared"` (auto-redirect resolved the old name).

### Task 0.3: Update local git remote + rename local directory

**Files:** git config only.

- [ ] **Step 1: Update origin URL**

```bash
cd ~/Code/claude-skills
git remote set-url origin git@github.com:brockamer/jared.git
git remote -v
```

Expected: both fetch + push URLs show `:brockamer/jared.git`.

- [ ] **Step 2: Confirm pull still works (exercises new URL)**

```bash
git fetch origin
```

Expected: no errors.

- [ ] **Step 3: Move the local directory**

```bash
cd ~/Code
mv claude-skills jared
cd ~/Code/jared
pwd
```

Expected: `/home/brockamer/Code/jared`.

**Note:** All subsequent commands in this plan assume `cd ~/Code/jared` unless noted.

### Task 0.4: Update `plugin.json` metadata

**Files:**
- Modify: `.claude-plugin/plugin.json`

- [ ] **Step 1: Read current content**

```bash
cat .claude-plugin/plugin.json
```

- [ ] **Step 2: Edit**

Change `homepage` and `repository` to the new URL:

```json
{
  "name": "jared",
  "description": "Jared — steward a GitHub Projects v2 board as the single source of truth. Files, moves, grooms, and structurally reviews issues with discipline. Includes /jared, /jared-file, /jared-groom, /jared-reshape, /jared-start, /jared-wrap, /jared-init.",
  "version": "0.2.0-dev",
  "author": {
    "name": "Daniel Brock"
  },
  "homepage": "https://github.com/brockamer/jared",
  "repository": "https://github.com/brockamer/jared",
  "license": "MIT",
  "keywords": [
    "project-management",
    "github-projects",
    "workflows",
    "pm-discipline"
  ]
}
```

Version bumped to `0.2.0-dev` — finalizes to `0.2.0` in Task 5.4.

### Task 0.5: Audit and update `.gitignore`

**Files:**
- Modify: `.gitignore`

- [ ] **Step 1: Check current state**

```bash
cat .gitignore
git ls-files '*__pycache__*' '*.pyc'
```

Expected: list any tracked Python bytecode files.

- [ ] **Step 2: Append missing entries**

Append to `.gitignore` (check current content first to avoid duplicates):

```
# Python
__pycache__/
*.py[cod]
*.pyo
.pytest_cache/
.mypy_cache/
.ruff_cache/

# Test config
tests/testbed.env
```

- [ ] **Step 3: Untrack any currently tracked bytecode**

```bash
git rm -r --cached skills/jared/scripts/__pycache__ 2>/dev/null || true
git status
```

Expected: `__pycache__` files (if tracked) now staged for deletion.

### Task 0.6: Grep for stale `claude-skills` references

**Files:** whatever contains references.

- [ ] **Step 1: Find all hits**

```bash
grep -rn "claude-skills" . \
  --include='*.md' --include='*.json' --include='*.py' --include='*.sh' \
  --exclude-dir='.git' \
  --exclude-dir='__pycache__'
```

- [ ] **Step 2: Evaluate each hit**

Expected categories:
- `README.md` — multiple hits. Will be fully rewritten in Phase 1 / Task 1.8; note and defer.
- `.claude-plugin/plugin.json` — already fixed in Task 0.4.
- Command stubs or references — fix if they appear; document in this step which files need updates in Phase 5.

Do NOT fix README.md now (it's getting a full rewrite). Fix any other stray hits in this step.

- [ ] **Step 3: Record findings**

Write a note in the commit message for Task 0.7 listing what was updated and what was deferred (README).

### Task 0.7: Commit Phase 0

**Files:** whatever's staged.

- [ ] **Step 1: Verify staged**

```bash
git status
git diff --cached
```

- [ ] **Step 2: Commit**

```bash
git add .claude-plugin/plugin.json .gitignore
# Plus any other files touched in 0.6 step 2
git commit -m "$(cat <<'EOF'
chore(jared): rename repo to jared, bump to 0.2.0-dev, gitignore audit

Phase 0 of the level-up (spec: 2026-04-22-jared-levelup-design.md):
- repo renamed brockamer/claude-skills → brockamer/jared
- local dir renamed ~/Code/claude-skills → ~/Code/jared
- plugin.json homepage/repository updated
- .gitignore: add pycache, pytest/mypy/ruff cache, tests/testbed.env

README rewrite deferred to Phase 1.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
git push
```

---

## Phase 0.5 — Test-board setup

### Task 0.5.1: Create the testbed repo

**Files:** none (GitHub state).

- [ ] **Step 1: Create**

```bash
gh repo create brockamer/jared-testbed \
  --private \
  --description "Fixture repo for jared integration tests — seed data is fictional."
```

Expected: repo URL printed.

- [ ] **Step 2: Clone to a scratch location** (so we can seed issues)

```bash
cd /tmp && gh repo clone brockamer/jared-testbed
```

### Task 0.5.2: Create paired Project v2 + fields

**Files:** none (GitHub state).

- [ ] **Step 1: Create project**

```bash
gh project create --owner brockamer --title "Jared Testbed — Sparrow Robotics"
```

Expected: project URL + number printed. Record the number.

- [ ] **Step 2: Link the project to the testbed repo**

```bash
PROJECT_NUM=<from previous step>
gh project link $PROJECT_NUM --owner brockamer --repo brockamer/jared-testbed
```

- [ ] **Step 3: Customize the default Status field**

GitHub adds a `Status` field by default with options `Todo / In Progress / Done`. Jared's convention is `Backlog / Up Next / In Progress / Blocked / Done` (five columns — **Blocked is a Status column, not a label**; dependencies between issues are modeled separately via native issue-dependency edges in Task 0.5.3).

`gh` has no `field-edit` subcommand, so use GraphQL. First grab the Status field's node ID:

```bash
STATUS_FIELD_ID=$(gh project field-list $PROJECT_NUM --owner brockamer --format json \
  | python3 -c "import json,sys; print([f['id'] for f in json.load(sys.stdin)['fields'] if f['name']=='Status'][0])")
```

Then replace options:

```bash
gh api graphql -f query='
mutation($fieldId: ID!) {
  updateProjectV2Field(input: {
    fieldId: $fieldId
    name: "Status"
    singleSelectOptions: [
      {name: "Backlog", color: GRAY, description: ""},
      {name: "Up Next", color: BLUE, description: ""},
      {name: "In Progress", color: YELLOW, description: ""},
      {name: "Blocked", color: RED, description: ""},
      {name: "Done", color: GREEN, description: ""}
    ]
  }) { projectV2Field { ... on ProjectV2SingleSelectField { options { id name } } } }
}' -f fieldId="$STATUS_FIELD_ID"
```

Capture the five option IDs from the response — `item-edit` needs them in Task 0.5.3.

- [ ] **Step 4: Add Priority field**

```bash
gh project field-create $PROJECT_NUM --owner brockamer \
  --name "Priority" --data-type SINGLE_SELECT \
  --single-select-options "High,Medium,Low"
```

- [ ] **Step 5: Add Work Stream field** (three fictional options)

```bash
gh project field-create $PROJECT_NUM --owner brockamer \
  --name "Work Stream" --data-type SINGLE_SELECT \
  --single-select-options "Perception,Planning,Fleet Ops"
```

### Task 0.5.3: Seed fictional issues

**Files:** none (GitHub state).

- [ ] **Step 1: Draft the seed set**

15 fictional issues about a robotics tooling roadmap. Titles:

1. "Add stereo-calibration watchdog to perception test harness" (High / Perception / In Progress)
2. "Refactor path planner's obstacle inflation" (High / Planning / In Progress) — blocked-by #11
3. "Fleet dashboard: add battery-health column" (Medium / Fleet Ops / Up Next)
4. "Instrument SLAM drift budget alerts" (Medium / Perception / Up Next) — blocked-by #1
5. "Migrate waypoint serializer to protobuf v3" (Medium / Planning / Up Next)
6. "Fix intermittent timeout in fleet heartbeat" (High / Fleet Ops / Blocked)
7. "Document sensor-extrinsics bootstrap for new hires" (Low / Perception / Backlog)
8. "Prune deprecated trajectory types" (Low / Planning / Backlog)
9. "Add fleet-ops on-call rotation doc" (Low / Fleet Ops / Backlog)
10. "Rebuild occupancy grid viewer in React" (Medium / Perception / Backlog) — blocked-by #11
11. "Replace ad-hoc costmap format with standard grid" (Medium / Planning / Backlog)
12. "Wire up cost alarms for S3 log egress" (High / Fleet Ops / Backlog)
13. "Retire v1 telemetry schema" (Low / Fleet Ops / Done, closed)
14. "Add dark-mode support to fleet dashboard" (Low / Fleet Ops / Done, closed)
15. "Publish perception benchmark baseline" (Medium / Perception / Done, closed)

**Coverage:** All 5 Status columns, all 3 Priorities, all 3 Work Streams. Issue #6 exercises the pure Blocked-column case (no dep edges — work started, stuck externally). The three blocked-by edges exercise dep graph scenarios: in-progress→backlog (#2→#11), cross-stream fan-out (#10→#11 alongside #2→#11), and up-next→in-progress (#4→#1).

- [ ] **Step 2: File them**

Use `gh issue create` + `gh project item-add` + `gh project item-edit` per issue (we're eliminating this multi-step flow in Phase 2, but need it here before Phase 2 exists). Script it — doing 15 by hand is error-prone. Example Python skeleton:

```python
# For each seed row:
#   1. gh issue create --repo brockamer/jared-testbed --title <t> --body <seed-body>
#   2. gh project item-add $PROJECT_NUM --owner brockamer --url <url> --format json  -> item_id
#   3. gh project item-edit --id <item_id> --project-id $PROJECT_ID \
#        --field-id $STATUS_FIELD_ID --single-select-option-id <status-opt-id>
#      ... repeat for Priority and Work Stream
#   4. Verify: re-read the ProjectV2Item via GraphQL; halt if not on project or Status is null.
#   5. If closed=true, gh issue close <n>
```

**Critical invariant (flagged in level-up feedback as a prior-Jared regression):** each iteration must verify, before moving on, that the new item is (a) on the project and (b) has Status set. A null Status or missing project membership is a hard failure — halt and inspect. Do not batch creates and hope.

Scratch script goes in `/tmp` — not committed. Phase 2 replaces it with `tests/testbed-reset.py`, which reads `tests/seed-issues.yaml`.

**Issue #6 (Blocked):** set `Status="Blocked"` on the Status field. Do NOT use a label. Blocked is a dedicated Status column in the Jared convention (see `references/new-board.md` after Phase 4 update).

**Issues 13/14/15 (closed):** `gh issue close <n>` after filing + status-setting.

- [ ] **Step 3: Wire up dependency edges**

Three blocked-by edges per the table above. `gh` has no built-in command; use the `addBlockedBy` GraphQL mutation:

```bash
gh api graphql -f query='
mutation($blockee: ID!, $blocker: ID!) {
  addBlockedBy(input: { issueId: $blockee, blockingIssueId: $blocker }) {
    issue { number }
  }
}' -f blockee="<blockee-node-id>" -f blocker="<blocker-node-id>"
```

Issue node IDs come from `gh api repos/brockamer/jared-testbed/issues/<n>` (`.node_id`). Verify each edge by re-reading `repository.issue(number: N).blockedBy` for the blockee.

### Task 0.5.4: Write testbed setup doc

**Files:**
- Create: `tests/testbed-setup.md`

- [ ] **Step 1: Write the file**

```bash
mkdir -p tests
```

```markdown
# Testbed Setup

Integration tests run against a real GitHub project. This doc reproduces the
testbed from scratch.

## Preconditions

- `gh` authenticated (`gh auth status` green).
- Write access to `brockamer/jared-testbed` (or equivalent — adjust names below).

## One-time setup

1. Create repo:

   gh repo create brockamer/jared-testbed --private \
     --description "Fixture repo for jared integration tests — seed data is fictional."

2. Create project:

   gh project create --owner brockamer --title "Jared Testbed — Sparrow Robotics"
   # record the project number printed

3. Link project to repo:

   gh project link <project-number> --owner brockamer --repo brockamer/jared-testbed

4. Create Priority + Work Stream fields (Status exists by default):

   gh project field-create <project-number> --owner brockamer \
     --name "Priority" --data-type SINGLE_SELECT \
     --single-select-options "High,Medium,Low"

   gh project field-create <project-number> --owner brockamer \
     --name "Work Stream" --data-type SINGLE_SELECT \
     --single-select-options "Perception,Planning,Fleet Ops"

5. Seed fictional issues (see `tests/seed-issues.yaml` for the 15 seed items).

   Each entry lists: title, priority, work stream, status, and (for closed) whether to close.

6. Copy `tests/testbed.env.example` to `tests/testbed.env` and fill in:

   - REPO: brockamer/jared-testbed
   - PROJECT_NUMBER: <number from step 2>

7. Verify:

   pytest -m integration -k test_get_item -v

## Reset / re-seed

If the testbed gets polluted, run `tests/testbed-reset.py` (additive tool —
created later in Phase 2). It closes and deletes anything not in the seed set.

## Costs

- Private repo; does not count toward free-tier limits for private repos in
  personal accounts.
- Project boards: free. No ongoing cost.
```

- [ ] **Step 2: Write the seed file**

Create `tests/seed-issues.yaml` — the machine-readable source of truth for the 15 seed entries. Schema per entry:

```yaml
- title: <string>
  priority: High | Medium | Low
  work_stream: Perception | Planning | "Fleet Ops"
  status: Backlog | "Up Next" | "In Progress" | Blocked | Done
  closed: true | false
  blocked_by: [<1-based seed index>, ...]   # optional; dependency edges
```

`blocked_by` entries are 1-based indexes into this file's ordered list — the Phase 2 `tests/testbed-reset.py` resolves them against the order in the file.

The definitive seed list (as committed in this phase) is in `tests/seed-issues.yaml`. Coverage: all 5 Status columns, all 3 Priorities, all 3 Work Streams, a pure Blocked-column case (#6), and 3 dependency edges (#2→#11, #10→#11, #4→#1).

### Task 0.5.5: Write testbed env example

**Files:**
- Create: `tests/testbed.env.example`

- [ ] **Step 1: Write**

```bash
# Copy to tests/testbed.env (gitignored) and fill in real values.
# Used by pytest integration tests to locate the testbed project.

TESTBED_REPO=brockamer/jared-testbed
TESTBED_OWNER=brockamer
TESTBED_PROJECT_NUMBER=<fill-in>
```

### Task 0.5.6: Commit Phase 0.5

**Files:** staged.

- [ ] **Step 1: Commit**

```bash
git add tests/testbed-setup.md tests/testbed.env.example tests/seed-issues.yaml
git commit -m "$(cat <<'EOF'
feat(jared): scaffold integration testbed

Phase 0.5 of the level-up:
- tests/testbed-setup.md — reproducible testbed creation doc
- tests/seed-issues.yaml — 15 fictional seed issues for a robotics tooling
  roadmap, spanning all priorities / statuses / work streams
- tests/testbed.env.example — integration test config template

Actual testbed repo + project created on GitHub (brockamer/jared-testbed).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
git push
```

---

## Phase 1 — Marketplace packaging

### Task 1.1: Research marketplace schema

**Files:** none (reading only).

- [ ] **Step 1: Read the official marketplace.json for schema shape**

```bash
cat ~/.claude/plugins/marketplaces/claude-plugins-official/.claude-plugin/marketplace.json | python3 -c "import json,sys; d=json.load(sys.stdin); print(json.dumps({k:v for k,v in d.items() if k!='plugins'}, indent=2)); print('---first plugin---'); print(json.dumps(d['plugins'][0], indent=2))"
```

Expected: top-level keys (`$schema`, `name`, `description`, `owner`); per-plugin keys (`name`, `description`, `source`, `homepage`, `category`).

- [ ] **Step 2: Note the `source` shape for a root-colocated plugin**

The source can be a string path (`"source": "."`) for a plugin at the marketplace repo root, or an object (`{source: "url", url: "..."}`) for external. For jared: use `"source": "."`.

### Task 1.2: Write marketplace.json

**Files:**
- Create: `.claude-plugin/marketplace.json`

- [ ] **Step 1: Write**

```json
{
  "$schema": "https://anthropic.com/claude-code/marketplace.schema.json",
  "name": "jared-marketplace",
  "description": "Single-plugin marketplace for jared — GitHub Projects v2 board steward.",
  "owner": {
    "name": "Daniel Brock",
    "email": "brockamer@gmail.com"
  },
  "plugins": [
    {
      "name": "jared",
      "description": "Steward a GitHub Projects v2 board as the single source of truth. Files, moves, grooms, and structurally reviews issues with discipline.",
      "source": ".",
      "category": "development",
      "homepage": "https://github.com/brockamer/jared"
    }
  ]
}
```

### Task 1.3: Install via local file:// marketplace

**Files:** none (Claude Code plugin state).

- [ ] **Step 1: Add local marketplace**

From within a Claude Code session:

```
/plugin marketplace add file:///home/brockamer/Code/jared
```

Expected: "Added marketplace jared-marketplace".

- [ ] **Step 2: Install plugin**

```
/plugin install jared
```

Expected: install succeeds. A new directory appears under `~/.claude/plugins/cache/jared-marketplace/jared/`.

- [ ] **Step 3: Reload plugins**

```
/reload-plugins
```

Expected: plugin count increments; SessionStart reports jared skills/commands loaded from the new cache path.

- [ ] **Step 4: Verify the skill loads from cache, not symlink**

```bash
ls -la ~/.claude/plugins/cache/jared-marketplace/jared/
readlink ~/.claude/skills/jared
```

Confirm the cache contains plugin.json + skills/ + commands/. The old symlink in `~/.claude/skills/jared` still exists — that's fine for now.

### Task 1.4: Verify file:// dev-loop behavior

**Files:** none.

- [ ] **Step 1: Make a trivial edit to the source**

```bash
cd ~/Code/jared
echo "# dev-loop test $(date +%s)" >> skills/jared/SKILL.md
```

- [ ] **Step 2: Check whether the cache sees it immediately**

```bash
grep "dev-loop test" ~/.claude/plugins/cache/jared-marketplace/jared/skills/jared/SKILL.md
```

If present → file:// marketplace **symlinks** the source; edits are live. (Document as: `"Edit in ~/Code/jared, run /reload-plugins to pick up SKILL.md / command changes"`.)

If absent → file:// marketplace **copies**; needs explicit sync. Try:

```
/plugin update jared
```

Then re-check.

- [ ] **Step 3: Record finding**

Note the result (symlinks or copies + requires /plugin update). This goes into the README in Task 1.8.

- [ ] **Step 4: Revert the test edit**

```bash
cd ~/Code/jared
git checkout -- skills/jared/SKILL.md
```

If the cache was symlinked, the revert is live. If copied, run `/plugin update jared` again.

### Task 1.5: Kill the old symlinks

**Files:** symlinks under `~/.claude/`.

- [ ] **Step 1: Verify plugin install is working** (redundant but explicit)

```
/jared
```

Expected: fast status output of the current directory's project board. If this works with the symlinks *still present*, the plugin might be shadowing them or vice versa — either way, next step disambiguates.

- [ ] **Step 2: Remove symlinks**

```bash
rm ~/.claude/skills/jared
rm ~/.claude/commands/jared*.md
ls ~/.claude/skills/
ls ~/.claude/commands/
```

Expected: empty (or non-jared) directories.

- [ ] **Step 3: Reload + re-verify**

```
/reload-plugins
/jared
```

Expected: `/jared` still works, now exclusively from the plugin cache.

### Task 1.6: Push marketplace config to GitHub, test remote install

**Files:** none (git state + plugin state).

- [ ] **Step 1: Commit + push marketplace.json**

```bash
cd ~/Code/jared
git add .claude-plugin/marketplace.json
git commit -m "feat(jared): add marketplace.json for self-hosted install"
git push
```

- [ ] **Step 2: Test remote install from scratch**

In a temporary throwaway Claude Code session (or carefully, same session — see notes):

```
/plugin marketplace remove jared-marketplace   # remove the file:// one first
/plugin marketplace add brockamer/jared
/plugin install jared
/reload-plugins
/jared
```

Expected: works over the network.

- [ ] **Step 3: Decide which marketplace config to keep on this machine**

For active development, the file:// marketplace is preferable (fast iteration). Re-add it:

```
/plugin marketplace remove jared-marketplace
/plugin marketplace add file:///home/brockamer/Code/jared
/plugin install jared
```

### Task 1.7: Rewrite README

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Replace content**

Write the new README (preserve license / keywords sections if you care about them). Shape:

```markdown
# Jared

Claude Code plugin: a GitHub Projects v2 board steward. Treats the board
as the single source of truth for what's being worked on. Files, moves,
grooms, and structurally reviews issues with discipline.

## Install

    /plugin marketplace add brockamer/jared
    /plugin install jared

Then in any project with a `docs/project-board.md`, use `/jared` for a fast
status, `/jared-file`, `/jared-start`, `/jared-groom`, `/jared-wrap`,
`/jared-reshape`, or `/jared-init`.

If the project has no `docs/project-board.md` yet, run `/jared-init` to
bootstrap it against an existing (or new) GitHub Projects v2 board.

## Developing

This plugin lives at `~/Code/jared/`. For active development, install from
the local checkout:

    /plugin marketplace remove jared-marketplace
    /plugin marketplace add file:///home/brockamer/Code/jared
    /plugin install jared

<!-- Fill in based on Task 1.4 result: -->
<!-- If file:// symlinks the source: -->
Edits to files under `~/Code/jared/` are live. Run `/reload-plugins` to
pick up changes to `SKILL.md` or command stubs.

<!-- If file:// copies: -->
After editing files under `~/Code/jared/`, run `/plugin update jared`
to re-sync the plugin cache, then `/reload-plugins`.

## Testing

    pytest                  # unit tests (fast, offline)
    pytest -m integration   # integration tests (runs against the testbed
                            # in brockamer/jared-testbed; requires
                            # tests/testbed.env configured)

See `tests/testbed-setup.md` for testbed setup.

## Layout

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

## Versioning

Semantic versioning in `plugin.json`. Git tag `v<x.y.z>` per release.

## License

MIT.
```

- [ ] **Step 2: Apply the file:// result**

Pick the right dev-loop text from Task 1.4's finding; delete the unused alternative.

### Task 1.8: Commit Phase 1

**Files:** staged.

- [ ] **Step 1: Stage + commit**

```bash
git add README.md
git commit -m "$(cat <<'EOF'
docs(jared): rewrite README for marketplace install + dev loop

Phase 1 of the level-up:
- Install is now /plugin marketplace add + /plugin install.
- Dev loop documented based on verified file:// marketplace behavior.
- Symlink install removed from this machine; cache install is authoritative.
- Layout overview + testing notes.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
git push
```

---

## Phase 2 — Core library + CLI (TDD)

Pre-work before subcommands: project config, helper module, entry point.

### Task 2.0: Set up pyproject.toml for dev tooling

**Files:**
- Create: `pyproject.toml` (at repo root)

- [ ] **Step 1: Write**

```toml
[project]
name = "jared"
version = "0.2.0-dev"
description = "Jared — GitHub Projects v2 board steward (Claude Code plugin)"
requires-python = ">=3.11"
dependencies = [
    "pyyaml>=6.0",  # tests/seed-issues.yaml loader
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "ruff>=0.4",
    "mypy>=1.10",
]

[tool.ruff]
line-length = 100
target-version = "py311"

[tool.ruff.lint]
select = ["E", "F", "W", "I", "UP", "B", "SIM"]

[tool.mypy]
strict = true
python_version = "3.11"
files = ["skills/jared/scripts", "tests"]
exclude = ["skills/jared/scripts/__pycache__"]

[tool.pytest.ini_options]
markers = [
    "integration: requires TESTBED_* env + network; opt-in via -m integration",
]
testpaths = ["tests"]
addopts = "-m 'not integration'"  # default: skip integration
```

- [ ] **Step 2: Install dev deps**

```bash
cd ~/Code/jared
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

Expected: installs pyyaml + pytest + ruff + mypy.

- [ ] **Step 3: Verify tooling**

```bash
ruff --version
mypy --version
pytest --version
```

- [ ] **Step 4: Add .venv to .gitignore** (if not already)

```bash
grep -q "^\\.venv" .gitignore || echo -e "\n# Local venv\n.venv/" >> .gitignore
```

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml .gitignore
git commit -m "chore(jared): set up pyproject.toml with pytest/ruff/mypy"
```

### Task 2.1: Write `Board` class — project-board.md parsing (TEST FIRST)

**Files:**
- Create: `tests/test_board.py`
- Create: `skills/jared/scripts/lib/__init__.py` (empty)
- Create: `skills/jared/scripts/lib/board.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_board.py`:

```python
from pathlib import Path
from textwrap import dedent

import pytest


def test_parse_project_board_md(tmp_path: Path) -> None:
    from skills.jared.scripts.lib.board import Board, BoardConfigError

    board_md = tmp_path / "docs" / "project-board.md"
    board_md.parent.mkdir(parents=True)
    board_md.write_text(dedent("""\
        # Project board

        - Project URL: https://github.com/users/brockamer/projects/7
        - Project number: 7
        - Project ID: PVT_kwHO_xyz
        - Owner: brockamer
        - Repo: brockamer/findajob

        ## Fields

        - Status (field ID: PVTSSF_status): Backlog, Up Next, In Progress, Done, Blocked
        - Priority (field ID: PVTSSF_prio): High, Medium, Low
        """))

    board = Board.from_path(board_md)

    assert board.project_number == 7
    assert board.project_id == "PVT_kwHO_xyz"
    assert board.owner == "brockamer"
    assert board.repo == "brockamer/findajob"


def test_missing_file_raises_board_config_error(tmp_path: Path) -> None:
    from skills.jared.scripts.lib.board import Board, BoardConfigError

    with pytest.raises(BoardConfigError) as exc:
        Board.from_path(tmp_path / "missing.md")

    assert "project-board.md" in str(exc.value)
```

- [ ] **Step 2: Run the test, verify fail**

```bash
cd ~/Code/jared
mkdir -p skills/jared/scripts/lib
touch skills/jared/scripts/lib/__init__.py
pytest tests/test_board.py -v
```

Expected: fail with ImportError or ModuleNotFoundError for `Board`.

- [ ] **Step 3: Implement minimal `Board` with `from_path` and parser**

Create `skills/jared/scripts/lib/board.py`:

```python
"""Shared helper for jared scripts: parse docs/project-board.md, wrap gh calls."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


class BoardConfigError(Exception):
    """Raised when docs/project-board.md is missing or malformed."""


@dataclass
class Board:
    project_number: int
    project_id: str
    owner: str
    repo: str
    project_url: str
    _field_ids: dict[str, str]  # human name → PVTSSF_* id
    _field_options: dict[str, dict[str, str]]  # field name → {option name → option id}

    @classmethod
    def from_path(cls, path: Path) -> Board:
        if not path.exists():
            raise BoardConfigError(
                f"Missing {path}. Run /jared-init to bootstrap the project."
            )
        text = path.read_text()
        return cls._parse(text, source=str(path))

    @classmethod
    def _parse(cls, text: str, *, source: str) -> Board:
        def find(pattern: str) -> str:
            m = re.search(pattern, text, re.MULTILINE)
            if not m:
                raise BoardConfigError(
                    f"Could not find required field matching r'{pattern}' in {source}"
                )
            return m.group(1).strip()

        project_url = find(r"Project URL:\s*(\S+)")
        project_number = int(find(r"Project number:\s*(\d+)"))
        project_id = find(r"Project ID:\s*(\S+)")
        owner = find(r"Owner:\s*(\S+)")
        repo = find(r"Repo:\s*(\S+)")

        # Field IDs and options come next; parser is deliberately lenient.
        # Stub for this task; expanded in 2.2.
        return cls(
            project_number=project_number,
            project_id=project_id,
            owner=owner,
            repo=repo,
            project_url=project_url,
            _field_ids={},
            _field_options={},
        )
```

- [ ] **Step 4: Run test, verify pass**

```bash
pytest tests/test_board.py -v
```

Expected: both tests pass.

- [ ] **Step 5: Commit**

```bash
git add skills/jared/scripts/lib/__init__.py skills/jared/scripts/lib/board.py tests/test_board.py
git commit -m "feat(jared): scaffold Board helper — project-board.md parsing"
```

### Task 2.2: Extend `Board` with field + option lookup (TEST FIRST)

**Files:**
- Modify: `tests/test_board.py`
- Modify: `skills/jared/scripts/lib/board.py`

- [ ] **Step 1: Add failing tests**

Append to `tests/test_board.py`:

```python
def test_field_and_option_lookup(tmp_path: Path) -> None:
    from skills.jared.scripts.lib.board import Board

    board_md = tmp_path / "docs" / "project-board.md"
    board_md.parent.mkdir(parents=True)
    board_md.write_text(dedent("""\
        - Project URL: https://github.com/users/brockamer/projects/7
        - Project number: 7
        - Project ID: PVT_kwHO_xyz
        - Owner: brockamer
        - Repo: brockamer/findajob

        ## Fields

        ### Status
        - Field ID: PVTSSF_status
        - Backlog: OPTION_backlog
        - Up Next: OPTION_up_next
        - In Progress: OPTION_in_progress
        - Done: OPTION_done
        - Blocked: OPTION_blocked

        ### Priority
        - Field ID: PVTSSF_prio
        - High: OPTION_high
        - Medium: OPTION_med
        - Low: OPTION_low
        """))

    board = Board.from_path(board_md)

    assert board.field_id("Status") == "PVTSSF_status"
    assert board.field_id("Priority") == "PVTSSF_prio"
    assert board.option_id("Status", "In Progress") == "OPTION_in_progress"
    assert board.option_id("Priority", "High") == "OPTION_high"


def test_unknown_field_raises(tmp_path: Path) -> None:
    from skills.jared.scripts.lib.board import Board, FieldNotFound

    board_md = tmp_path / "docs" / "project-board.md"
    board_md.parent.mkdir(parents=True)
    board_md.write_text(dedent("""\
        - Project URL: https://github.com/users/brockamer/projects/7
        - Project number: 7
        - Project ID: PVT_kwHO_xyz
        - Owner: brockamer
        - Repo: brockamer/findajob
        """))

    board = Board.from_path(board_md)
    with pytest.raises(FieldNotFound):
        board.field_id("Nonexistent")
```

- [ ] **Step 2: Run, verify fail**

```bash
pytest tests/test_board.py -v
```

Expected: two new failures (FieldNotFound missing; methods not implemented).

- [ ] **Step 3: Extend `board.py`**

Update `skills/jared/scripts/lib/board.py`. Add the new exceptions + methods, and extend `_parse` to read the field sections:

```python
class FieldNotFound(Exception):
    """Raised when a field name is not present in docs/project-board.md."""


class OptionNotFound(Exception):
    """Raised when a field's option name is not present in docs/project-board.md."""


# In Board class, add:

    def field_id(self, name: str) -> str:
        if name not in self._field_ids:
            available = ", ".join(sorted(self._field_ids)) or "(none)"
            raise FieldNotFound(
                f"Field '{name}' not found in project-board.md. Available: {available}"
            )
        return self._field_ids[name]

    def option_id(self, field: str, option: str) -> str:
        options = self._field_options.get(field, {})
        if option not in options:
            available = ", ".join(sorted(options)) or "(none)"
            raise OptionNotFound(
                f"Option '{option}' not found for field '{field}'. Available: {available}"
            )
        return options[option]
```

Extend `_parse` to recognize the `### <FieldName>` + `- Field ID: ...` + `- <Option>: OPTION_...` pattern:

```python
    @classmethod
    def _parse(cls, text: str, *, source: str) -> Board:
        # ... existing header extraction ...

        field_ids: dict[str, str] = {}
        field_options: dict[str, dict[str, str]] = {}

        field_blocks = re.split(r"^### ", text, flags=re.MULTILINE)[1:]
        for block in field_blocks:
            lines = block.splitlines()
            field_name = lines[0].strip()
            options: dict[str, str] = {}
            field_id: str | None = None
            for line in lines[1:]:
                m = re.match(r"^\s*-\s*Field ID:\s*(\S+)\s*$", line)
                if m:
                    field_id = m.group(1)
                    continue
                m = re.match(r"^\s*-\s*(.+?):\s*(OPTION_\S+)\s*$", line)
                if m:
                    options[m.group(1).strip()] = m.group(2).strip()
            if field_id is None:
                continue  # skip sections without a field ID
            field_ids[field_name] = field_id
            field_options[field_name] = options

        return cls(
            # ... other fields ...
            _field_ids=field_ids,
            _field_options=field_options,
        )
```

- [ ] **Step 4: Run, verify pass**

```bash
pytest tests/test_board.py -v
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add skills/jared/scripts/lib/board.py tests/test_board.py
git commit -m "feat(jared): Board field + option lookup with typed errors"
```

### Task 2.3: Add `run_gh` + `find_item_id` (TEST FIRST with subprocess mock)

**Files:**
- Modify: `tests/test_board.py`
- Modify: `skills/jared/scripts/lib/board.py`

- [ ] **Step 1: Add failing test using monkeypatched subprocess**

Append:

```python
def test_run_gh_parses_json(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from skills.jared.scripts.lib import board as board_mod
    from skills.jared.scripts.lib.board import Board

    # Build a minimal Board
    board_md = tmp_path / "docs" / "project-board.md"
    board_md.parent.mkdir(parents=True)
    board_md.write_text(dedent("""\
        - Project URL: https://github.com/users/brockamer/projects/7
        - Project number: 7
        - Project ID: PVT_kwHO_xyz
        - Owner: brockamer
        - Repo: brockamer/findajob
    """))
    b = Board.from_path(board_md)

    class FakeResult:
        returncode = 0
        stdout = '{"hello": "world"}'
        stderr = ""

    called_args: list[list[str]] = []

    def fake_run(args, capture_output, text, check):
        called_args.append(args)
        return FakeResult()

    monkeypatch.setattr(board_mod.subprocess, "run", fake_run)

    result = b.run_gh(["api", "user"])
    assert result == {"hello": "world"}
    assert called_args == [["gh", "api", "user"]]


def test_find_item_id_finds_match(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from skills.jared.scripts.lib import board as board_mod
    from skills.jared.scripts.lib.board import Board

    board_md = tmp_path / "docs" / "project-board.md"
    board_md.parent.mkdir(parents=True)
    board_md.write_text(dedent("""\
        - Project URL: https://github.com/users/brockamer/projects/7
        - Project number: 7
        - Project ID: PVT_kwHO_xyz
        - Owner: brockamer
        - Repo: brockamer/findajob
    """))
    b = Board.from_path(board_md)

    class FakeResult:
        returncode = 0
        stdout = '{"items": [{"id": "PVTI_aaa", "content": {"number": 42}}, {"id": "PVTI_bbb", "content": {"number": 99}}]}'
        stderr = ""

    monkeypatch.setattr(board_mod.subprocess, "run", lambda *a, **kw: FakeResult())

    assert b.find_item_id(42) == "PVTI_aaa"

    # miss path
    from skills.jared.scripts.lib.board import ItemNotFound
    with pytest.raises(ItemNotFound):
        b.find_item_id(123456)
```

- [ ] **Step 2: Run, verify fail**

```bash
pytest tests/test_board.py -v
```

Expected: new tests fail (`run_gh`, `find_item_id`, `ItemNotFound` missing).

- [ ] **Step 3: Implement**

Add to `board.py`:

```python
import json
import subprocess


class GhInvocationError(Exception):
    """Raised when `gh` exits non-zero."""


class ItemNotFound(Exception):
    """Raised when no project item corresponds to the given issue number."""


# On Board:

    def run_gh(self, args: list[str]) -> dict:
        result = subprocess.run(
            ["gh", *args],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            raise GhInvocationError(
                f"gh {' '.join(args)} exited {result.returncode}: {result.stderr.strip()}"
            )
        stdout = result.stdout.strip()
        if not stdout:
            return {}
        try:
            return json.loads(stdout)
        except json.JSONDecodeError as e:
            raise GhInvocationError(f"gh returned non-JSON output: {stdout[:200]}") from e

    def find_item_id(self, issue_number: int) -> str:
        data = self.run_gh([
            "project", "item-list",
            str(self.project_number),
            "--owner", self.owner,
            "--limit", "500",
            "--format", "json",
        ])
        for item in data.get("items", []):
            content = item.get("content") or {}
            if content.get("number") == issue_number:
                return item["id"]
        raise ItemNotFound(
            f"No project item for issue #{issue_number} in project {self.project_number}. "
            f"Is the issue added to the board?"
        )
```

- [ ] **Step 4: Run, verify pass**

```bash
pytest tests/test_board.py -v
```

- [ ] **Step 5: Commit**

```bash
git add skills/jared/scripts/lib/board.py tests/test_board.py
git commit -m "feat(jared): Board.run_gh + find_item_id with typed errors"
```

### Task 2.4: Add `run_graphql` (TEST FIRST)

**Files:**
- Modify: `tests/test_board.py`
- Modify: `skills/jared/scripts/lib/board.py`

- [ ] **Step 1: Failing test**

```python
def test_run_graphql(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from skills.jared.scripts.lib import board as board_mod
    from skills.jared.scripts.lib.board import Board

    board_md = tmp_path / "docs" / "project-board.md"
    board_md.parent.mkdir(parents=True)
    board_md.write_text(dedent("""\
        - Project URL: https://github.com/users/brockamer/projects/7
        - Project number: 7
        - Project ID: PVT_kwHO_xyz
        - Owner: brockamer
        - Repo: brockamer/findajob
    """))
    b = Board.from_path(board_md)

    captured: dict = {}

    class FakeResult:
        returncode = 0
        stdout = '{"data": {"ok": true}}'
        stderr = ""

    def fake_run(args, capture_output, text, check):
        captured["args"] = args
        return FakeResult()

    monkeypatch.setattr(board_mod.subprocess, "run", fake_run)

    result = b.run_graphql("query { ok }", owner="brockamer")
    assert result == {"data": {"ok": True}}
    assert captured["args"][:4] == ["gh", "api", "graphql", "-f"]
    assert any("owner=brockamer" in a for a in captured["args"])
```

- [ ] **Step 2: Run, verify fail**

```bash
pytest tests/test_board.py::test_run_graphql -v
```

- [ ] **Step 3: Implement**

```python
    def run_graphql(self, query: str, **variables: str | int) -> dict:
        args = ["api", "graphql", "-f", f"query={query}"]
        for k, v in variables.items():
            # -F casts to appropriate type (int/bool); -f is string
            if isinstance(v, bool) or isinstance(v, int):
                args.extend(["-F", f"{k}={v}"])
            else:
                args.extend(["-f", f"{k}={v}"])
        return self.run_gh(args)
```

- [ ] **Step 4: Pass**

```bash
pytest tests/test_board.py -v
```

- [ ] **Step 5: Commit**

```bash
git add skills/jared/scripts/lib/board.py tests/test_board.py
git commit -m "feat(jared): Board.run_graphql"
```

### Task 2.5: Create `scripts/jared` entry point with argparse skeleton (TEST FIRST)

**Files:**
- Create: `tests/test_cli.py`
- Create: `skills/jared/scripts/jared` (executable)

- [ ] **Step 1: Failing test**

```python
# tests/test_cli.py
import subprocess
import sys
from pathlib import Path

CLI = Path(__file__).parents[1] / "skills" / "jared" / "scripts" / "jared"


def test_cli_help_lists_subcommands() -> None:
    result = subprocess.run(
        [sys.executable, str(CLI), "--help"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    for cmd in ["file", "move", "set", "close", "comment", "blocked-by", "get-item", "summary"]:
        assert cmd in result.stdout


def test_cli_unknown_subcommand_exits_nonzero() -> None:
    result = subprocess.run(
        [sys.executable, str(CLI), "bogus"],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
```

- [ ] **Step 2: Run, verify fail**

```bash
pytest tests/test_cli.py -v
```

- [ ] **Step 3: Implement skeleton**

```python
#!/usr/bin/env python3
"""jared — unified CLI for common Jared (GitHub Projects v2) operations."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Make sibling lib/ importable regardless of cwd
sys.path.insert(0, str(Path(__file__).resolve().parent))

# Subcommand imports go here as they are implemented in later tasks
# from lib.board import Board


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="jared",
        description="jared — GitHub Projects v2 board operations.",
    )
    parser.add_argument(
        "--board",
        default="docs/project-board.md",
        help="Path to project-board.md (default: docs/project-board.md)",
    )
    sub = parser.add_subparsers(dest="cmd", required=True, metavar="{file,move,set,close,comment,blocked-by,get-item,summary}")

    # Subcommand registration stubs — real impls in later tasks
    for name in ["file", "move", "set", "close", "comment", "blocked-by", "get-item", "summary"]:
        p = sub.add_parser(name, help=f"(stub) {name}")
        p.set_defaults(func=lambda args, n=name: _stub(n))

    return parser


def _stub(name: str) -> int:
    print(f"{name}: not implemented yet", file=sys.stderr)
    return 2


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
```

Make executable:

```bash
chmod +x skills/jared/scripts/jared
```

- [ ] **Step 4: Pass**

```bash
pytest tests/test_cli.py -v
```

- [ ] **Step 5: Commit**

```bash
git add skills/jared/scripts/jared tests/test_cli.py
git commit -m "feat(jared): scaffold unified jared CLI with argparse"
```

### Task 2.6: Implement `jared get-item` (TEST FIRST, unit + integration)

**Files:**
- Modify: `tests/test_cli.py`
- Create: `tests/test_integration.py`
- Modify: `skills/jared/scripts/jared`

- [ ] **Step 1: Failing unit test**

Append to `tests/test_cli.py`:

```python
def test_get_item_invokes_find_item_id(monkeypatch, tmp_path, capsys) -> None:
    # Build a fake board file
    board_md = tmp_path / "docs" / "project-board.md"
    board_md.parent.mkdir(parents=True)
    board_md.write_text(...)  # reuse minimal content from test_board.py

    # Build fake gh response
    class FakeResult:
        returncode = 0
        stdout = '{"items": [{"id": "PVTI_aaa", "content": {"number": 42}, "priority": "High"}]}'
        stderr = ""

    import subprocess as sp
    monkeypatch.setattr(sp, "run", lambda *a, **kw: FakeResult())

    # Import main from the jared CLI file via runpy
    import runpy
    runpy.run_path(str(CLI), run_name="not_main")  # loads module without executing main

    # Easier: just invoke the CLI directly and capture
    result = sp.run(
        [sys.executable, str(CLI), "--board", str(board_md), "get-item", "42"],
        capture_output=True, text=True,
    )
    # Because we monkeypatched in this process but subprocess spawns a new process,
    # the monkeypatch doesn't apply. Refactor this test to either:
    #   a) import main() and call it with argv
    #   b) skip — rely on integration test
    # Choose (a) — see below.
```

**Refined approach**: unit tests for `jared` subcommands import and call `main()` directly in-process (so monkeypatch applies). The subprocess-based test (`test_cli_help_lists_subcommands`) stays for the argparse skeleton only.

Revise: unit tests for subcommand logic go in separate files (`tests/test_cmd_get_item.py` etc.). For now:

```python
# tests/test_cmd_get_item.py
import sys
from pathlib import Path
from textwrap import dedent

import pytest


SKILL_SCRIPTS = Path(__file__).parents[1] / "skills" / "jared" / "scripts"
sys.path.insert(0, str(SKILL_SCRIPTS))


def test_get_item_prints_json(monkeypatch, tmp_path, capsys) -> None:
    from skills.jared.scripts.lib import board as board_mod
    board_md = tmp_path / "docs" / "project-board.md"
    board_md.parent.mkdir(parents=True)
    board_md.write_text(dedent("""\
        - Project URL: https://github.com/users/brockamer/projects/7
        - Project number: 7
        - Project ID: PVT_kwHO_xyz
        - Owner: brockamer
        - Repo: brockamer/findajob
    """))

    class FakeResult:
        returncode = 0
        stdout = '{"items": [{"id": "PVTI_aaa", "content": {"number": 42}, "status": "In Progress"}]}'
        stderr = ""

    monkeypatch.setattr(board_mod.subprocess, "run", lambda *a, **kw: FakeResult())

    # Load the CLI module as a module so we can import `main`
    import importlib.util
    spec = importlib.util.spec_from_file_location("jared_cli", SKILL_SCRIPTS / "jared")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    rc = mod.main(["--board", str(board_md), "get-item", "42"])
    captured = capsys.readouterr()

    assert rc == 0
    # Assert JSON output contains the item id and issue number
    import json
    out = json.loads(captured.out)
    assert out["issue_number"] == 42
    assert out["item_id"] == "PVTI_aaa"
```

- [ ] **Step 2: Run, verify fail**

```bash
pytest tests/test_cmd_get_item.py -v
```

Expected: fail — `get-item` is currently a stub.

- [ ] **Step 3: Implement `get-item` in `skills/jared/scripts/jared`**

Add (replacing the stub registration for `get-item`):

```python
import json

from lib.board import Board


def _cmd_get_item(args: argparse.Namespace) -> int:
    board = Board.from_path(Path(args.board))
    item_id = board.find_item_id(args.issue_number)
    # Fetch full field values for this item
    data = board.run_gh([
        "project", "item-list",
        str(board.project_number),
        "--owner", board.owner,
        "--limit", "500",
        "--format", "json",
    ])
    match = next(
        (
            i for i in data.get("items", [])
            if (i.get("content") or {}).get("number") == args.issue_number
        ),
        {},
    )
    output = {
        "issue_number": args.issue_number,
        "item_id": item_id,
        "status": match.get("status"),
        "priority": match.get("priority"),
        "fields": {k: v for k, v in match.items() if k not in {"id", "content", "status", "priority"}},
    }
    print(json.dumps(output, indent=2))
    return 0


# In build_parser, replace the stub:
    get_item = sub.add_parser("get-item", help="Return JSON: issue number, item-id, field values.")
    get_item.add_argument("issue_number", type=int)
    get_item.set_defaults(func=_cmd_get_item)
```

Remove `get-item` from the stub-registration loop.

- [ ] **Step 4: Pass**

```bash
pytest tests/test_cmd_get_item.py -v
```

- [ ] **Step 5: Integration test**

Create `tests/test_integration.py`:

```python
"""Integration tests — run against brockamer/jared-testbed."""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration

REPO_ROOT = Path(__file__).parents[1]
CLI = REPO_ROOT / "skills" / "jared" / "scripts" / "jared"


def _load_env() -> dict[str, str]:
    env_file = REPO_ROOT / "tests" / "testbed.env"
    if not env_file.exists():
        pytest.skip("tests/testbed.env not configured; see tests/testbed-setup.md")
    env = {}
    for line in env_file.read_text().splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()
    return env


@pytest.fixture(scope="session")
def testbed():
    return _load_env()


def test_get_item_on_seed_issue(testbed) -> None:
    # Find any open seed issue
    repo = testbed["TESTBED_REPO"]
    out = subprocess.check_output(
        ["gh", "issue", "list", "--repo", repo, "--state", "open", "--limit", "1", "--json", "number"],
        text=True,
    )
    issues = json.loads(out)
    assert issues, "testbed has no open issues"
    issue_number = issues[0]["number"]

    # Write a minimal docs/project-board.md in a temp dir
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        (Path(d) / "docs").mkdir()
        # NOTE: bootstrap-project.py will eventually generate this;
        # for now, integration test users place a valid one manually
        # or skip this test until bootstrap is ported.
        pytest.skip("testbed docs/project-board.md generation pending in Task 3.2")
```

Note: integration test for `get-item` is deferred until after Task 3.2 when `bootstrap-project.py` can auto-generate the testbed's `docs/project-board.md`. Skip for now; the unit test covers logic.

- [ ] **Step 6: Commit**

```bash
git add skills/jared/scripts/jared tests/test_cmd_get_item.py tests/test_integration.py
git commit -m "feat(jared): implement 'jared get-item' with unit tests"
```

### Task 2.7: Implement `jared summary` (TEST FIRST)

**Files:**
- Create: `tests/test_cmd_summary.py`
- Modify: `skills/jared/scripts/jared`

- [ ] **Step 1: Failing test**

```python
# tests/test_cmd_summary.py
import importlib.util
import sys
from pathlib import Path
from textwrap import dedent

SKILL_SCRIPTS = Path(__file__).parents[1] / "skills" / "jared" / "scripts"
sys.path.insert(0, str(SKILL_SCRIPTS))


def _import_cli():
    spec = importlib.util.spec_from_file_location("jared_cli", SKILL_SCRIPTS / "jared")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_summary_groups_by_status(monkeypatch, tmp_path, capsys) -> None:
    from skills.jared.scripts.lib import board as board_mod

    board_md = tmp_path / "docs" / "project-board.md"
    board_md.parent.mkdir(parents=True)
    board_md.write_text(dedent("""\
        - Project URL: https://github.com/users/brockamer/projects/7
        - Project number: 7
        - Project ID: PVT_kwHO_xyz
        - Owner: brockamer
        - Repo: brockamer/findajob
    """))

    class FakeResult:
        returncode = 0
        stdout = '''{"items": [
            {"id": "a", "content": {"number": 1, "title": "Issue one"}, "status": "In Progress", "priority": "High"},
            {"id": "b", "content": {"number": 2, "title": "Issue two"}, "status": "Up Next", "priority": "Medium"},
            {"id": "c", "content": {"number": 3, "title": "Issue three"}, "status": "Backlog", "priority": "Low"}
        ]}'''
        stderr = ""

    monkeypatch.setattr(board_mod.subprocess, "run", lambda *a, **kw: FakeResult())

    mod = _import_cli()
    rc = mod.main(["--board", str(board_md), "summary"])
    out = capsys.readouterr().out

    assert rc == 0
    assert "In Progress" in out
    assert "Up Next" in out
    assert "Issue one" in out
    assert "Issue two" in out
    # Backlog items should NOT show in the fast summary (only In Progress + Up Next)
    assert "Issue three" not in out
```

- [ ] **Step 2: Run, verify fail**

```bash
pytest tests/test_cmd_summary.py -v
```

- [ ] **Step 3: Implement `summary`**

Add to the CLI:

```python
def _cmd_summary(args: argparse.Namespace) -> int:
    board = Board.from_path(Path(args.board))
    data = board.run_gh([
        "project", "item-list",
        str(board.project_number),
        "--owner", board.owner,
        "--limit", "500",
        "--format", "json",
    ])
    items = data.get("items", [])

    def by_status(s: str) -> list[dict]:
        return [i for i in items if i.get("status") == s]

    in_progress = by_status("In Progress")
    up_next = by_status("Up Next")[:3]
    blocked = by_status("Blocked")

    print(f"Board: {board.project_url}")
    print()
    print(f"In Progress ({len(in_progress)}):")
    for it in in_progress:
        num = (it.get("content") or {}).get("number")
        title = (it.get("content") or {}).get("title", "")
        pri = it.get("priority") or ""
        print(f"  #{num} [{pri}] {title}")
    print()
    print(f"Up Next (top 3 of {len([i for i in items if i.get('status') == 'Up Next'])}):")
    for it in up_next:
        num = (it.get("content") or {}).get("number")
        title = (it.get("content") or {}).get("title", "")
        pri = it.get("priority") or ""
        print(f"  #{num} [{pri}] {title}")
    if blocked:
        print()
        print(f"Blocked ({len(blocked)}):")
        for it in blocked:
            num = (it.get("content") or {}).get("number")
            title = (it.get("content") or {}).get("title", "")
            print(f"  #{num} {title}")
    return 0


# In build_parser:
    summary = sub.add_parser("summary", help="One-screen board status summary.")
    summary.set_defaults(func=_cmd_summary)
```

- [ ] **Step 4: Pass**

```bash
pytest tests/test_cmd_summary.py -v
```

- [ ] **Step 5: Commit**

```bash
git add skills/jared/scripts/jared tests/test_cmd_summary.py
git commit -m "feat(jared): implement 'jared summary'"
```

### Task 2.8: Implement `jared set` (generic field setter)

**Files:**
- Create: `tests/test_cmd_set.py`
- Modify: `skills/jared/scripts/jared`

- [ ] **Step 1: Failing test**

```python
# tests/test_cmd_set.py — closely mirrors test_cmd_get_item.py scaffolding
# Test that `jared set 42 Priority High` resolves IDs and invokes the correct
# gh project item-edit command with the expected args.

def test_set_invokes_item_edit(monkeypatch, tmp_path, capsys) -> None:
    from skills.jared.scripts.lib import board as board_mod

    board_md = tmp_path / "docs" / "project-board.md"
    board_md.parent.mkdir(parents=True)
    board_md.write_text(dedent("""\
        - Project URL: https://github.com/users/brockamer/projects/7
        - Project number: 7
        - Project ID: PVT_kwHO_xyz
        - Owner: brockamer
        - Repo: brockamer/findajob

        ### Priority
        - Field ID: PVTSSF_prio
        - High: OPTION_high
        - Medium: OPTION_med
        - Low: OPTION_low
    """))

    calls: list[list[str]] = []

    def fake_run(args, capture_output, text, check):
        calls.append(args)
        # Pretend item-list returns one item matching #42
        class R:
            returncode = 0
            stdout = '{"items": [{"id": "PVTI_aaa", "content": {"number": 42}}]}'
            stderr = ""
        class R2:
            returncode = 0
            stdout = '{}'
            stderr = ""
        # First call: item-list. Second call: item-edit.
        return R() if "item-list" in args else R2()

    monkeypatch.setattr(board_mod.subprocess, "run", fake_run)

    mod = _import_cli()  # reuse helper
    rc = mod.main(["--board", str(board_md), "set", "42", "Priority", "High"])

    assert rc == 0
    assert any("item-edit" in c for c in calls), "expected item-edit invocation"
    edit_call = next(c for c in calls if "item-edit" in c)
    assert "PVT_kwHO_xyz" in " ".join(edit_call)  # project-id
    assert "PVTI_aaa" in " ".join(edit_call)      # item-id
    assert "PVTSSF_prio" in " ".join(edit_call)   # field-id
    assert "OPTION_high" in " ".join(edit_call)   # option-id
```

Add the `_import_cli()` helper to a shared `conftest.py`:

```python
# tests/conftest.py
import importlib.util
import sys
from pathlib import Path

SKILL_SCRIPTS = Path(__file__).parents[1] / "skills" / "jared" / "scripts"
sys.path.insert(0, str(SKILL_SCRIPTS))


def _import_cli():
    spec = importlib.util.spec_from_file_location("jared_cli", SKILL_SCRIPTS / "jared")
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(mod)
    return mod
```

And import in each test module:

```python
from conftest import _import_cli
```

- [ ] **Step 2: Run, verify fail**

```bash
pytest tests/test_cmd_set.py -v
```

- [ ] **Step 3: Implement `set`**

```python
def _cmd_set(args: argparse.Namespace) -> int:
    board = Board.from_path(Path(args.board))
    item_id = board.find_item_id(args.issue_number)
    field_id = board.field_id(args.field_name)
    option_id = board.option_id(args.field_name, args.value)
    board.run_gh([
        "project", "item-edit",
        "--project-id", board.project_id,
        "--id", item_id,
        "--field-id", field_id,
        "--single-select-option-id", option_id,
    ])
    print(f"OK: set {args.field_name}={args.value} on issue #{args.issue_number}")
    return 0


# In build_parser:
    set_p = sub.add_parser("set", help="Set a single-select field on an issue.")
    set_p.add_argument("issue_number", type=int)
    set_p.add_argument("field_name", help='e.g. "Priority" or "Status"')
    set_p.add_argument("value", help='e.g. "High" or "In Progress"')
    set_p.set_defaults(func=_cmd_set)
```

- [ ] **Step 4: Pass**

```bash
pytest tests/test_cmd_set.py -v
```

- [ ] **Step 5: Commit**

```bash
git add skills/jared/scripts/jared tests/test_cmd_set.py tests/conftest.py
git commit -m "feat(jared): implement 'jared set' for single-select fields"
```

### Task 2.9: Implement `jared move` (wrapper on `set`)

**Files:**
- Create: `tests/test_cmd_move.py`
- Modify: `skills/jared/scripts/jared`

- [ ] **Step 1: Failing test**

```python
# tests/test_cmd_move.py
import sys
from pathlib import Path
from textwrap import dedent

sys.path.insert(0, str(Path(__file__).parents[1] / "skills" / "jared" / "scripts"))
from conftest import _import_cli


def test_move_sets_status(monkeypatch, tmp_path, capsys) -> None:
    from skills.jared.scripts.lib import board as board_mod

    board_md = tmp_path / "docs" / "project-board.md"
    board_md.parent.mkdir(parents=True)
    board_md.write_text(dedent("""\
        - Project URL: https://github.com/users/brockamer/projects/7
        - Project number: 7
        - Project ID: PVT_kwHO_xyz
        - Owner: brockamer
        - Repo: brockamer/findajob

        ### Status
        - Field ID: PVTSSF_status
        - Backlog: OPTION_backlog
        - In Progress: OPTION_in_progress
        - Done: OPTION_done
    """))

    calls: list[list[str]] = []
    def fake_run(args, capture_output, text, check):
        calls.append(args)
        class R:
            returncode = 0
            stdout = '{"items": [{"id": "PVTI_aaa", "content": {"number": 42}}]}' if "item-list" in args else "{}"
            stderr = ""
        return R()
    monkeypatch.setattr(board_mod.subprocess, "run", fake_run)

    mod = _import_cli()
    rc = mod.main(["--board", str(board_md), "move", "42", "In Progress"])
    assert rc == 0
    edit = next(c for c in calls if "item-edit" in c)
    assert "PVTSSF_status" in " ".join(edit)
    assert "OPTION_in_progress" in " ".join(edit)
```

- [ ] **Step 2: Run, verify fail**

- [ ] **Step 3: Implement**

```python
def _cmd_move(args: argparse.Namespace) -> int:
    # Delegate to _cmd_set with field="Status"
    args.field_name = "Status"
    args.value = args.status
    return _cmd_set(args)


# In build_parser:
    move = sub.add_parser("move", help="Move an issue to a new Status (Backlog/Up Next/In Progress/Blocked/Done).")
    move.add_argument("issue_number", type=int)
    move.add_argument("status", help='e.g. "In Progress"')
    move.set_defaults(func=_cmd_move)
```

- [ ] **Step 4: Pass + commit**

```bash
pytest tests/test_cmd_move.py -v
git add skills/jared/scripts/jared tests/test_cmd_move.py
git commit -m "feat(jared): implement 'jared move' as Status shortcut"
```

### Task 2.10: Implement `jared close` (close + verify auto-move)

**Files:**
- Create: `tests/test_cmd_close.py`
- Modify: `skills/jared/scripts/jared`

- [ ] **Step 1: Failing test**

```python
# tests/test_cmd_close.py  — uses same scaffolding as test_cmd_move.py.
# Test: `jared close 42` calls `gh issue close`, re-queries item-list,
# and if status becomes "Done" prints OK and returns 0.
# Monkeypatch subprocess.run to sequence responses:
#   call 1 (issue close): returns "" stdout
#   call 2 (item-list): returns items with Status "Done"
# Assert rc=0 and "issue close" appeared in the call args.
```

Model this after test_cmd_move.py; use a stateful fake_run that returns different outputs based on call order or arg inspection.

- [ ] **Step 2: Fail verify**

- [ ] **Step 3: Implement**

```python
import time


def _cmd_close(args: argparse.Namespace) -> int:
    board = Board.from_path(Path(args.board))
    # Close the issue
    board.run_gh([
        "issue", "close",
        str(args.issue_number),
        "--repo", board.repo,
    ])
    # Verify auto-move (small retry)
    for _ in range(3):
        data = board.run_gh([
            "project", "item-list",
            str(board.project_number),
            "--owner", board.owner,
            "--limit", "500",
            "--format", "json",
        ])
        match = next(
            (i for i in data.get("items", []) if (i.get("content") or {}).get("number") == args.issue_number),
            None,
        )
        if match and match.get("status") == "Done":
            print(f"OK: closed #{args.issue_number}, board auto-moved to Done")
            return 0
        time.sleep(1.0)
    # Fallback: set Status=Done explicitly
    args.field_name = "Status"
    args.value = "Done"
    _cmd_set(args)
    print(f"OK: closed #{args.issue_number} (manual move to Done)")
    return 0


# In build_parser:
    close_p = sub.add_parser("close", help="Close issue + verify auto-move to Done.")
    close_p.add_argument("issue_number", type=int)
    close_p.set_defaults(func=_cmd_close)
```

- [ ] **Step 4: Pass + commit**

### Task 2.11: Implement `jared comment`

**Files:**
- Create: `tests/test_cmd_comment.py`
- Modify: `skills/jared/scripts/jared`

- [ ] **Step 1: Failing test**

```python
# tests/test_cmd_comment.py — test that `jared comment 42 --body-file <path>`
# reads the file and invokes gh issue comment with --body-file.
# Write a body file to tmp_path, monkeypatch board_mod.subprocess.run to capture,
# assert the call contains "issue comment" and "--body-file" with a path pointing
# to a file whose content matches the body.
```

- [ ] **Step 2: Fail verify**

- [ ] **Step 3: Implement**

```python
def _cmd_comment(args: argparse.Namespace) -> int:
    board = Board.from_path(Path(args.board))
    if args.body_file == "-":
        body = sys.stdin.read()
    else:
        body = Path(args.body_file).read_text()
    import tempfile
    with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
        f.write(body)
        path = f.name
    try:
        board.run_gh([
            "issue", "comment",
            str(args.issue_number),
            "--repo", board.repo,
            "--body-file", path,
        ])
    finally:
        Path(path).unlink(missing_ok=True)
    print(f"OK: commented on #{args.issue_number}")
    return 0


# In build_parser:
    comment = sub.add_parser("comment", help="Add a comment to an issue.")
    comment.add_argument("issue_number", type=int)
    comment.add_argument("--body-file", required=True, help='Path to markdown file, or "-" for stdin.')
    comment.set_defaults(func=_cmd_comment)
```

- [ ] **Step 4: Pass + commit**

### Task 2.12: Implement `jared file` (the atomic create)

**Files:**
- Create: `tests/test_cmd_file.py`
- Modify: `skills/jared/scripts/jared`

- [ ] **Step 1: Failing test**

```python
# tests/test_cmd_file.py — test that the atomic file op sequences:
#   1. gh issue create → returns https URL on stdout
#   2. gh project item-add → returns {"id": "PVTI_xxx"}
#   3. gh project item-edit (Priority)
#   4. gh project item-edit (Status)
# Monkeypatch subprocess.run with a stateful callable that returns different
# FakeResult based on args, and assert all four calls occurred in order.
# Use a body file in tmp_path.
```

- [ ] **Step 2: Fail verify**

- [ ] **Step 3: Implement**

```python
def _cmd_file(args: argparse.Namespace) -> int:
    board = Board.from_path(Path(args.board))
    # 1. Create the issue
    create_args = [
        "issue", "create",
        "--repo", board.repo,
        "--title", args.title,
        "--body-file", args.body_file,
    ]
    for label in args.label or []:
        create_args.extend(["--label", label])
    # gh issue create returns URL on stdout (not JSON in --format json's normal form)
    import subprocess as sp
    result = sp.run(["gh", *create_args], capture_output=True, text=True, check=False)
    if result.returncode != 0:
        print(f"error: gh issue create failed: {result.stderr.strip()}", file=sys.stderr)
        return 2
    issue_url = result.stdout.strip()
    if not issue_url.startswith("http"):
        print(f"error: unexpected gh output: {result.stdout[:200]}", file=sys.stderr)
        return 2
    # Extract issue number for follow-up logging
    issue_number = int(issue_url.rsplit("/", 1)[-1])

    # 2. Add to project board
    add_data = board.run_gh([
        "project", "item-add",
        str(board.project_number),
        "--owner", board.owner,
        "--url", issue_url,
        "--format", "json",
    ])
    item_id = add_data["id"]

    # 3. Set Priority
    board.run_gh([
        "project", "item-edit",
        "--project-id", board.project_id,
        "--id", item_id,
        "--field-id", board.field_id("Priority"),
        "--single-select-option-id", board.option_id("Priority", args.priority),
    ])

    # 4. Set Status (default: Backlog)
    status = args.status or "Backlog"
    board.run_gh([
        "project", "item-edit",
        "--project-id", board.project_id,
        "--id", item_id,
        "--field-id", board.field_id("Status"),
        "--single-select-option-id", board.option_id("Status", status),
    ])

    # 5. Any extra --field Name=Value args
    for spec in args.field or []:
        if "=" not in spec:
            print(f"error: --field expects NAME=VALUE, got {spec!r}", file=sys.stderr)
            return 1
        name, value = spec.split("=", 1)
        board.run_gh([
            "project", "item-edit",
            "--project-id", board.project_id,
            "--id", item_id,
            "--field-id", board.field_id(name),
            "--single-select-option-id", board.option_id(name, value),
        ])

    print(f"OK: filed #{issue_number} → {status}, Priority={args.priority}")
    print(f"URL: {issue_url}")
    return 0


# In build_parser:
    file_p = sub.add_parser("file", help="File a new issue + add to board + set fields atomically.")
    file_p.add_argument("--title", required=True)
    file_p.add_argument("--body-file", required=True)
    file_p.add_argument("--priority", required=True, choices=["High", "Medium", "Low"])
    file_p.add_argument("--status", help="Default: Backlog")
    file_p.add_argument("--label", action="append")
    file_p.add_argument("--field", action="append", help='NAME=VALUE for additional fields (e.g. "Work Stream=Planning")')
    file_p.set_defaults(func=_cmd_file)
```

- [ ] **Step 4: Pass + commit**

### Task 2.13: Implement `jared blocked-by`

**Files:**
- Create: `tests/test_cmd_blocked_by.py`
- Modify: `skills/jared/scripts/jared`

- [ ] **Step 1: Failing test**

```python
# tests/test_cmd_blocked_by.py — test that `jared blocked-by 99 42` makes
# two `gh issue view --json id` calls (one per issue) then a `gh api graphql`
# call whose query contains "addBlockedBy". With --remove, the query contains
# "removeBlockedBy". Monkeypatch subprocess.run with a stateful callable
# returning {"id": "I_xxx"} for issue-view and {"data": {...}} for graphql.
```

- [ ] **Step 2: Fail verify**

- [ ] **Step 3: Implement**

```python
def _resolve_issue_node_id(board: "Board", issue_number: int) -> str:
    data = board.run_gh([
        "issue", "view",
        str(issue_number),
        "--repo", board.repo,
        "--json", "id",
    ])
    return data["id"]


def _cmd_blocked_by(args: argparse.Namespace) -> int:
    board = Board.from_path(Path(args.board))
    dep_id = _resolve_issue_node_id(board, args.dependent)
    blocker_id = _resolve_issue_node_id(board, args.blocker)
    mutation_name = "removeBlockedBy" if args.remove else "addBlockedBy"
    # Schema-name variants: also try addIssueDependency if the canonical fails
    query = f'''
        mutation($issueId: ID!, $blockingIssueId: ID!) {{
          {mutation_name}(input: {{issueId: $issueId, blockingIssueId: $blockingIssueId}}) {{
            issue {{ number }}
          }}
        }}
    '''
    try:
        board.run_graphql(query, issueId=dep_id, blockingIssueId=blocker_id)
    except GhInvocationError as e:
        # Fallback: older schema name
        alt = "removeIssueDependency" if args.remove else "addIssueDependency"
        fallback = query.replace(mutation_name, alt)
        try:
            board.run_graphql(fallback, issueId=dep_id, blockingIssueId=blocker_id)
        except GhInvocationError as e2:
            print(f"error: both {mutation_name} and {alt} failed: {e2}", file=sys.stderr)
            return 2
    action = "removed" if args.remove else "added"
    print(f"OK: {action} blocked-by edge #{args.dependent} ← #{args.blocker}")
    return 0


# In build_parser:
    dep = sub.add_parser("blocked-by", help="Mark (or --remove) a blocked-by dependency edge.")
    dep.add_argument("dependent", type=int, help="Issue number that is blocked")
    dep.add_argument("blocker", type=int, help="Issue number doing the blocking")
    dep.add_argument("--remove", action="store_true", help="Remove the edge instead of adding it.")
    dep.set_defaults(func=_cmd_blocked_by)
```

Add to imports: `from lib.board import GhInvocationError`.

- [ ] **Step 4: Pass + commit**

### Task 2.14: Run ruff + mypy over all new code

**Files:** lint-only.

- [ ] **Step 1: Ruff**

```bash
ruff check skills/jared/scripts/ tests/
ruff format --check skills/jared/scripts/ tests/
```

Fix any errors with `ruff check --fix` and `ruff format`.

- [ ] **Step 2: Mypy strict**

```bash
mypy
```

Fix any type errors. Add type hints where missing. Type-ignore legitimately dynamic constructs only.

- [ ] **Step 3: Commit**

```bash
git add -A
git commit -m "style(jared): ruff + mypy strict clean for Phase 2 code"
```

---

## Phase 3 — Batch script migration

Pattern for each: read current file, identify `gh` invocations / ID-lookup code, replace with `Board` helper calls, run against testbed, commit. CLI surface preserved.

### Task 3.1: Migrate `sweep.py`

**Files:**
- Modify: `skills/jared/scripts/sweep.py`

- [ ] **Step 1: Read current state**

```bash
wc -l skills/jared/scripts/sweep.py
```

Expected: ~600-700 lines.

- [ ] **Step 2: Identify patterns to replace**

Grep for:
- `subprocess.run(["gh", ...` — replace with `board.run_gh([...])`
- Inline parsing of `docs/project-board.md` — replace with `Board.from_path()`
- Inline item-id lookup — replace with `board.find_item_id(n)`

- [ ] **Step 3: Refactor** (in-place edits)

Replace the project-board.md parser block with a single `Board.from_path(Path(args.board_md))` call. Replace each `gh` shell-out with `board.run_gh([...])`. Remove dead code (the old helpers this replaces).

- [ ] **Step 4: Capture pre-refactor baseline BEFORE step 3's edits**

Before you edit sweep.py, capture the current output:

```bash
cd ~/Code/findajob
python3 ~/Code/jared/skills/jared/scripts/sweep.py > /tmp/sweep-old.txt 2>&1 || true
```

This should have been done before step 3; if you already edited, use `git show HEAD:skills/jared/scripts/sweep.py > /tmp/sweep_old.py` and run that copy instead.

- [ ] **Step 4b: Run refactored sweep, diff**

```bash
cd ~/Code/findajob
python3 ~/Code/jared/skills/jared/scripts/sweep.py > /tmp/sweep-new.txt 2>&1 || true
diff /tmp/sweep-old.txt /tmp/sweep-new.txt
```

Expected: no meaningful output differences (modulo whitespace / ordering). If differences exist, investigate before committing.

- [ ] **Step 5: Commit**

```bash
git add skills/jared/scripts/sweep.py
git commit -m "refactor(jared): migrate sweep.py onto Board helper"
```

### Task 3.2: Migrate `bootstrap-project.py`

**Files:**
- Modify: `skills/jared/scripts/bootstrap-project.py`

- [ ] **Steps**: same pattern as 3.1. Extract any parsing / gh code to use `Board` / the lib module. Note that `bootstrap-project.py` *writes* the project-board.md that `Board.from_path` reads — it's the one script that has to invert the parser. Make sure the write format matches what `Board._parse` expects.

- [ ] **Verification**: run against the testbed — should produce a valid `docs/project-board.md` that `Board.from_path` can read back.

- [ ] **Commit**

### Task 3.3: Migrate `dependency-graph.py`

- [ ] Same pattern. Test against findajob or testbed.

### Task 3.4: Migrate `capture-context.py`

- [ ] Same pattern. Add a pure-logic unit test for the body-section parse/replace if one doesn't exist (`tests/test_capture_context.py`).

### Task 3.5: Migrate `archive-plan.py`

- [ ] Same pattern. Test by running against a mock plan file.

### Task 3.6: Final regression verify — run full sweep against findajob

- [ ] Run old + new sweep output against findajob, confirm identical. If not identical, investigate; do not proceed to Phase 4 until sweep is a no-op regression.

---

## Phase 4 — SKILL.md + references rewrite

### Task 4.1: Rewrite SKILL.md "Tool selection" section

**Files:**
- Modify: `skills/jared/SKILL.md`

- [ ] **Step 1: Replace the section starting "## Tool selection — MCP first, `gh` as fallback"**

New content:

```markdown
## Tool selection — the three tiers

For any board operation, pick the right tier:

**Tier 1 — single-call conversational ops.** Comment on an issue, close an issue, read an issue body, set one field. Prefer the GitHub MCP plugin's typed tools (`add_issue_comment`, `update_issue`, `issue_read`, `update_project_item_field_value`, etc.) when loaded. If MCP is absent, fall back to `jared <cmd>` below. Raw `gh` is a last resort.

**Tier 2 — multi-step orchestrations.** Any operation that would take more than one underlying call: filing an issue (create + add-to-board + set fields), moving an issue (lookup item-id + set Status), closing with verification (close + confirm auto-move), dependency edges (resolve both node-IDs + graphql mutation). Always use the `jared` CLI:

```
${CLAUDE_PLUGIN_ROOT}/skills/jared/scripts/jared file --title "..." --body-file - --priority High
${CLAUDE_PLUGIN_ROOT}/skills/jared/scripts/jared move <N> "In Progress"
${CLAUDE_PLUGIN_ROOT}/skills/jared/scripts/jared set <N> <FieldName> <OptionName>
${CLAUDE_PLUGIN_ROOT}/skills/jared/scripts/jared close <N>
${CLAUDE_PLUGIN_ROOT}/skills/jared/scripts/jared comment <N> --body-file -
${CLAUDE_PLUGIN_ROOT}/skills/jared/scripts/jared blocked-by <dependent> <blocker> [--remove]
${CLAUDE_PLUGIN_ROOT}/skills/jared/scripts/jared get-item <N>     # JSON lookup helper
${CLAUDE_PLUGIN_ROOT}/skills/jared/scripts/jared summary          # fast one-screen status
```

See `references/jared-cli.md` for the full subcommand reference.

**Tier 3 — batch / advisory / setup.** Named batch scripts under `${CLAUDE_PLUGIN_ROOT}/skills/jared/scripts/`: `sweep.py`, `bootstrap-project.py`, `dependency-graph.py`, `capture-context.py`, `archive-plan.py`. Each has its own slash command; invoke by name via those commands, not directly in conversation.

**Escape hatch.** Raw `gh issue`, `gh project`, `gh api graphql` only for cases none of the above cover. See `references/operations.md` for the reference card.

Jared never reconstructs a multi-step `gh` flow in conversation when a `jared` subcommand exists for it. Reaching for raw `gh` when `jared file` is the right tool is a drift signal.
```

- [ ] **Step 2: Grep for other references to gh multi-step flows in SKILL.md**

Update each to cite `jared <cmd>` instead.

- [ ] **Step 3: Commit**

```bash
git add skills/jared/SKILL.md
git commit -m "docs(jared): rewrite SKILL.md tool-selection around jared CLI"
```

### Task 4.2: Trim `references/operations.md`

**Files:**
- Modify: `skills/jared/references/operations.md`

- [ ] **Step 1: Replace with reference-card form**

Strip the long bash-block examples. Keep:
- The "placeholder key" section (still useful for raw-gh fallback).
- A pointer to `references/jared-cli.md` for the primary subcommand reference.
- A terse "Raw gh fallback" section covering: item-list, issue view JSON, graphql introspection. These are the escape-hatch commands.

- [ ] **Step 2: Commit**

### Task 4.3: Write `references/jared-cli.md`

**Files:**
- Create: `skills/jared/references/jared-cli.md`

- [ ] **Step 1: Content**

Subcommand-by-subcommand reference. Each section: `## jared <subcommand>`, then purpose, then signature + arguments (copied from `argparse --help`), then 1-2 concrete examples, then exit codes. Generate the initial draft from `jared <cmd> --help` output, then editorial-pass for clarity.

- [ ] **Step 2: Commit**

### Task 4.4: Light touch-ups to other references

**Files:**
- Modify: several under `skills/jared/references/`

- [ ] **Step 1: Grep**

```bash
grep -rn "gh issue\|gh project\|gh api" skills/jared/references/
```

Each hit: evaluate whether it should cite `jared <cmd>` now. Update.

- [ ] **Step 2: Commit**

```bash
git commit -m "docs(jared): update references to cite jared CLI over raw gh"
```

---

## Phase 5 — Command stubs + cleanup

### Task 5.1: Rewrite the seven command stubs

**Files:**
- Modify: `commands/jared.md`, `commands/jared-file.md`, `commands/jared-start.md`, `commands/jared-wrap.md`, `commands/jared-groom.md`, `commands/jared-reshape.md`, `commands/jared-init.md`

- [ ] **Step 1: Replace hardcoded paths**

For each stub, replace any `~/.claude/skills/jared/scripts/...` or bare `scripts/...` references with `${CLAUDE_PLUGIN_ROOT}/skills/jared/scripts/<name>`.

For commands that used to describe multi-step gh flows (e.g., `/jared-file`), rewrite the stub to invoke `${CLAUDE_PLUGIN_ROOT}/skills/jared/scripts/jared file ...` as a single call.

- [ ] **Step 2: Commit**

```bash
git add commands/
git commit -m "docs(jared): command stubs use \${CLAUDE_PLUGIN_ROOT}; revert 30726d0 hardcoded paths"
```

### Task 5.2: Delete superseded files

**Files:**
- Delete: `skills/jared/scripts/board-summary.sh`
- Delete: any stray `skills/jared/scripts/__pycache__/` tracked content

- [ ] **Step 1: Remove**

```bash
git rm skills/jared/scripts/board-summary.sh
```

- [ ] **Step 2: Commit**

```bash
git commit -m "chore(jared): delete board-summary.sh (replaced by 'jared summary')"
```

### Task 5.3: Final stale-reference grep

**Files:** any with stale hits.

- [ ] **Step 1: Grep**

```bash
grep -rn "claude-skills\|~/.claude/skills/jared" . \
  --include='*.md' --include='*.json' --include='*.py' --include='*.sh' \
  --exclude-dir='.git' --exclude-dir='.venv' --exclude-dir='__pycache__'
```

- [ ] **Step 2: Fix remaining hits**

Any findings: patch + commit. Exception: the spec doc itself and commit messages are allowed to mention the old name for historical context.

### Task 5.4: Bump version + tag release

**Files:**
- Modify: `.claude-plugin/plugin.json`

- [ ] **Step 1: Bump**

In `plugin.json`, change `"version": "0.2.0-dev"` → `"version": "0.2.0"`.

- [ ] **Step 2: Commit + tag**

```bash
git add .claude-plugin/plugin.json
git commit -m "release(jared): v0.2.0 — CLI, marketplace install, shared lib, tests"
git tag -a v0.2.0 -m "Level-up release — spec: 2026-04-22-jared-levelup-design.md"
git push origin main
git push origin v0.2.0
```

### Task 5.5: Final verification pass

- [ ] **Step 1: All tests pass**

```bash
pytest                 # fast, default
pytest -m integration  # against testbed
```

- [ ] **Step 2: Lint + type clean**

```bash
ruff check .
ruff format --check .
mypy
```

- [ ] **Step 3: Plugin loads and commands work**

In Claude Code:

```
/plugin update jared
/reload-plugins
/jared
```

Expected: status output for current dir (any dir with a `docs/project-board.md`).

- [ ] **Step 4: End-of-plan review**

Re-read the spec's "Success criteria" section; confirm each is met. If not, open a new task.

---

## Self-review checklist (done before handoff)

- Spec coverage: Phase 0 / 0.5 / 1 / 2 / 3 / 4 / 5 correspond to spec Phase 0 / 0.5 / 1 / 2 / 3 / 4 / 5. All eight CLI subcommands implemented (file, move, set, close, comment, blocked-by, get-item, summary). Integration test track scaffolded. `${CLAUDE_PLUGIN_ROOT}` convention enforced in Phase 5.
- Placeholder scan: no TBDs, no "implement later," every code step shows code.
- Type consistency: `Board` method names match across tasks. `_cmd_*` convention throughout the CLI. `find_item_id(issue_number: int)` signature stable.
- Known risk: `file://` marketplace behavior is verified during execution (Task 1.4), not pre-declared. The plan accommodates both outcomes in README (Task 1.7).

---

## Execution notes

- **Plan doc will be read task-by-task by a subagent** (recommended) or inline (fallback). Either mode expects each task to be self-contained and to leave the repo in a committable state.
- **Findings during execution** (schema drifts, unexpected behaviors, bugs in old scripts discovered during migration) become new tasks *appended* to the plan, not mid-task detours.
- **If a regression appears in a migrated batch script**, stop and fix before advancing phases. The invariant is that every `*.py` script behaves identically post-migration (same inputs → same outputs) before Phase 4 begins.
