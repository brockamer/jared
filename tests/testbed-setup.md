# Testbed Setup

Integration tests run against a real GitHub project. This doc reproduces the
testbed from scratch.

## Preconditions

- `gh` authenticated (`gh auth status` green) with `project` scope.
- Write access to `brockamer/jared-testbed` (or equivalent — adjust names below).

> **`GH_TOKEN` gotcha.** When `GH_TOKEN` (or `GITHUB_TOKEN`) is exported, `gh`
> uses it for every API call regardless of `gh auth login`'s OAuth session, and
> `gh auth status` still reports the OAuth scopes ✓ — misleading, since it's
> reporting scopes from a source `gh` won't actually use. If a fine-grained PAT
> without `project` scope is in `GH_TOKEN`, project mutations fail with
> `Resource not accessible by personal access token`. Jared's `lib/board.py`
> wrapper scrubs both vars from the child env before invoking `gh`, so the
> OAuth session is what takes effect — but `gh` invoked directly from the
> shell still picks up the env. If you hit a token-scope error from a raw
> `gh` command in this doc, run `unset GH_TOKEN GITHUB_TOKEN` first.

## One-time setup

1. Create repo:

   ```bash
   gh repo create brockamer/jared-testbed --private \
     --description "Fixture repo for jared integration tests — seed data is fictional."
   ```

2. Create project:

   ```bash
   gh project create --owner brockamer --title "Jared Testbed — Sparrow Robotics"
   # record the project number printed
   ```

3. Link project to repo:

   ```bash
   gh project link <project-number> --owner brockamer --repo brockamer/jared-testbed
   ```

4. Customize the default Status field. GitHub's default is `Todo / In Progress /
   Done`; Jared's convention is `Backlog / Up Next / In Progress / Blocked / Done`.
   `gh` has no `field-edit` subcommand, so use GraphQL:

   ```bash
   # Get the Status field's node ID
   gh project field-list <project-number> --owner brockamer --format json \
     | python3 -c "import json,sys; print([f['id'] for f in json.load(sys.stdin)['fields'] if f['name']=='Status'][0])"

   # Replace options
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
     }) { projectV2Field { ... on ProjectV2SingleSelectField { options { name } } } }
   }' -f fieldId="<status-field-id>"
   ```

   Note: `Blocked` is a **Status column**, not a label. Dependencies between
   issues are modeled separately via native GitHub issue dependencies
   (`blocked-by` edges).

5. Create Priority + Work Stream fields:

   ```bash
   gh project field-create <project-number> --owner brockamer \
     --name "Priority" --data-type SINGLE_SELECT \
     --single-select-options "High,Medium,Low"

   gh project field-create <project-number> --owner brockamer \
     --name "Work Stream" --data-type SINGLE_SELECT \
     --single-select-options "Perception,Planning,Fleet Ops"
   ```

6. Seed the 15 fictional issues from `tests/seed-issues.yaml`.

   For each entry: `gh issue create` → `gh project item-add` →
   `gh project item-edit` (Status, Priority, Work Stream) → verify the item is
   on the project with non-null Status before moving to the next. Close any
   entries where `closed: true`. Apply `blocked_by` edges via the
   `addBlockedBy` GraphQL mutation:

   ```bash
   gh api graphql -f query='
   mutation($blockee: ID!, $blocker: ID!) {
     addBlockedBy(input: { issueId: $blockee, blockingIssueId: $blocker }) {
       issue { number }
     }
   }' -f blockee="<node-id-of-blocked-issue>" -f blocker="<node-id-of-blocker>"
   ```

   Phase 2 produces `tests/testbed-reset.py` which automates all of this from
   the YAML; until then, seed via the one-time script committed at
   `/tmp/seed-testbed.py` during the Phase 0.5 setup.

7. Copy `tests/testbed.env.example` to `tests/testbed.env` and fill in:

   - `TESTBED_REPO`: brockamer/jared-testbed
   - `TESTBED_OWNER`: brockamer
   - `TESTBED_PROJECT_NUMBER`: <number from step 2>

8. Verify:

   ```bash
   pytest -m integration -k test_get_item -v
   ```

## Seed coverage

The 15 seed items exercise:

- All 5 Status columns (Backlog×6, Up Next×3, In Progress×2, Blocked×1, Done×3).
- All 3 Priority levels.
- All 3 Work Stream buckets.
- A pure external-blocker case (#6 — `Status: Blocked`, no dependency edges).
- Dependency edges (`blocked-by`):
  - #2 → #11 (in-progress refactor waiting on backlog standardization work)
  - #10 → #11 (backlog item waiting on same #11; exercises fan-out)
  - #4 → #1 (up-next waiting on in-progress work)
- Closed issues in Done (#13, #14, #15).

## Reset / re-seed

If the testbed gets polluted, run `tests/testbed-reset.py` (additive tool —
created later in Phase 2). It closes and deletes anything not in the seed set
and re-applies expected field values + dependency edges.

## Costs

- Private repo; does not count toward free-tier limits for private repos in
  personal accounts.
- Project boards: free. No ongoing cost.
