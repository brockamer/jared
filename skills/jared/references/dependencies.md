# Dependency Mapping

Dependencies between issues — "A must ship before B can start" — are first-class planning concerns. When buried in prose, blocking chains aren't obvious and work starts on implicitly-blocked items.

## Primary: native GitHub issue dependencies

GitHub issue dependencies are GA. Prefer them over body conventions — they render natively in issue timelines and Projects views, and the `jared` CLI manages them atomically.

### Creating a dependency

```bash
# Mark B blocked by A
${CLAUDE_PLUGIN_ROOT}/skills/jared/scripts/jared blocked-by <B> <A>
```

Under the hood the CLI resolves both issue node-IDs via `gh issue view` and runs the `addBlockedBy` GraphQL mutation. See `references/jared-cli.md` for the full subcommand reference.

### Removing a dependency

```bash
${CLAUDE_PLUGIN_ROOT}/skills/jared/scripts/jared blocked-by <B> <A> --remove
```

### Reading dependencies

For ad-hoc inspection, `gh api graphql` is the escape hatch:

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

For structural analysis across a whole board, use `dependency-graph.py` (below).

## Body context (not parsed)

A `## Depends on` section may appear in an issue body as human-readable prose explaining *why* the dependency matters (context, sequencing rationale, what breaks if violated). It is **not authoritative** and is not parsed by sweeps or scripts. The canonical relationship is always the native `blockedBy` edge.

The `## Blocks` body section is retired. To express the inverse direction, add a `blockedBy` edge on the dependent issue instead.

**For cross-repo dependencies** (native `blockedBy` doesn't cross repos), a prose note in `## Depends on` is acceptable as a human reminder. The relationship will not appear in native dependency views.

## Building a dependency graph

`dependency-graph.py` reads native `blockedBy` and builds a directed graph.

```bash
# Full summary
${CLAUDE_PLUGIN_ROOT}/skills/jared/scripts/dependency-graph.py --repo <owner>/<repo>

# Just the issues in a specific milestone
${CLAUDE_PLUGIN_ROOT}/skills/jared/scripts/dependency-graph.py --repo <owner>/<repo> --milestone "v0.2 — Materials Viewer"

# Emit Graphviz DOT for rendering
${CLAUDE_PLUGIN_ROOT}/skills/jared/scripts/dependency-graph.py --repo <owner>/<repo> --format dot > deps.dot
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
