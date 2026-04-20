# Dependency Mapping

Dependencies between issues — "A must ship before B can start" — are first-class planning concerns. When buried in prose, blocking chains aren't obvious and work starts on implicitly-blocked items.

## Primary: native GitHub issue dependencies

GitHub issue dependencies are GA. Prefer them over body conventions. They render natively in issue timelines and Projects views, and a `gh api graphql` call creates them.

### Creating a dependency

```bash
# Get node IDs for both issues
BLOCKER_ID=$(gh issue view <A> --repo <owner>/<repo> --json id --jq '.id')
DEPENDENT_ID=$(gh issue view <B> --repo <owner>/<repo> --json id --jq '.id')

# Mark B blocked by A
gh api graphql -f query='
  mutation($issueId: ID!, $blockingIssueId: ID!) {
    addBlockedBy(input: {issueId: $issueId, blockingIssueId: $blockingIssueId}) {
      issue { number }
    }
  }' -F issueId="$DEPENDENT_ID" -F blockingIssueId="$BLOCKER_ID"
```

### Reading dependencies

```bash
gh api graphql -f query='
  query($owner: String!, $repo: String!, $number: Int!) {
    repository(owner: $owner, name: $repo) {
      issue(number: $number) {
        number
        title
        blockedBy(first: 20) {
          nodes { number title state }
        }
        blocking(first: 20) {
          nodes { number title state }
        }
      }
    }
  }' -F owner=<owner> -F repo=<repo> -F number=<issue-number>
```

### Removing

```bash
gh api graphql -f query='
  mutation($issueId: ID!, $blockingIssueId: ID!) {
    removeBlockedBy(input: {issueId: $issueId, blockingIssueId: $blockingIssueId}) {
      issue { number }
    }
  }' -F issueId=<dependent-id> -F blockingIssueId=<blocker-id>
```

## Fallback: body conventions

Use when native dependencies aren't available or for cross-repo dependencies (which the native feature doesn't handle well).

Two sections in the issue body:

```markdown
## Depends on
- #42 (what this needs)
- #47

## Blocks
- #55 (what this is blocking)
```

Both are `#<number>` references so GitHub auto-links and creates bidirectional mentions. Parsing is regex `#(\d+)` under each heading.

**For cross-repo:** `<owner>/<repo>#N`.

## Building a dependency graph

`scripts/dependency-graph.py` walks both mechanisms (native + body-convention) and builds a directed graph.

```bash
# Full summary
scripts/dependency-graph.py

# Just the issues in a specific milestone
scripts/dependency-graph.py --milestone "v0.2 — Materials Viewer"

# Emit Graphviz DOT for rendering
scripts/dependency-graph.py --format dot > deps.dot
dot -Tpng deps.dot -o deps.png
```

Output surfaces:

- **Topological order** — the right sequence if parallelism were infinite
- **Critical path** — longest chain (bottleneck)
- **Cycles** — should be zero; any cycle is a bug
- **Priority inversions** — High depending on Medium/Low

## Surfacing during a sweep

The dependency section of `references/board-sweep.md` flags:

- **Cycles.** Hard bug. Fix immediately.
- **Priority inversions.** Either the dependency is more important than labeled, or the dependent doesn't really need it.
- **Chains >3 deep.** Fragile — slip cascades. Consider parallelizing or cutting scope.
- **Orphaned dependents** — dependencies pointing at closed issues. Remove the dependency or replace with a historical note.

## When to add a dependency

Add when:

- Starting the dependent before the dependency ships would waste effort (you'd throw work away).
- The dependent's acceptance criteria literally require the dependency's output.

Do NOT add when:

- You'd prefer to do A first (that's priority ordering, not dependency).
- The dependency is "nice to have" ordering.

Over-dependency leads to analysis paralysis. Under-dependency leads to wasted work on things that can't ship.

## Rendering for the user

Default (text-mode):

```
Critical path (3 issues):
  #10 → #12 → #20 → #82

Isolated chains:
  #65 → #85
  #48 → #87

Cycles (FIX):
  (none)

Priority inversions (REVIEW):
  #82 (High) depends on #13 (Medium, closed OK)
  #84 (Medium) depends on #78 (Low, open)
```

For visual, `--format dot` emits Graphviz syntax. Write to a file, note the path, let the user render.
