# Dependency Mapping

Dependencies between issues — "A must ship before B can start" — are first-class planning concerns. When they're buried in issue bodies, blocking chains aren't obvious and work gets started on items that are implicitly blocked.

## Primary mechanism: GitHub issue dependencies (when available)

GitHub has added a `Blocked by` / `Blocks` relationship to issues. If the repo has it enabled, use it — it renders natively in the issue timeline and in Projects views.

```bash
# Mark #B blocked by #A (if the feature is enabled on the repo)
gh issue develop <B> --branch "..." # placeholder — the dependency API is evolving
```

If the native dependency feature isn't available on the project, fall back to body conventions.

## Fallback mechanism: body conventions

Every issue with dependencies has two sections in its body:

```markdown
## Depends on
- #42 (the thing this blocks on)
- #47 (another blocker)

## Blocks
- #55 (this issue blocks #55 from starting)
```

Both are `#<number>` references so GitHub auto-links them and creates bidirectional mentions.

Parsing is straightforward — regex `#(\d+)` under a `## Depends on` heading.

## Building a dependency graph

Script at `scripts/dependency-graph.py` (to be authored). Rough procedure:

1. List all open issues on the project with bodies.
2. For each issue, parse `## Depends on` + `## Blocks` sections.
3. Build a directed graph (node = issue, edge = dependency).
4. Compute:
   - **Topological order** — the right order to work in if you had infinite parallelism
   - **Critical path** — longest chain of dependencies (bottleneck)
   - **Cycles** — should be zero; any cycle is a bug in the dependency data

## Surfacing during a sweep

Flag in the sweep output:

- **Circular dependencies** — hard bug. Fix immediately.
- **Priority inversions** — a High-priority issue depending on a Low-priority one. Either the dependency is actually more important than it's labeled, or the dependent doesn't really need it.
- **Blocking chains of length >3** — fragile. Any slip in the chain cascades. Consider parallelizing or cutting scope.
- **Orphaned dependents** — an issue that says `Depends on: #N` where `#N` is closed. Remove the dependency note (or replace with `Was blocked by: #N (resolved)` if you want the history).

## When to add a dependency

Add a dependency when:
- Starting work on the dependent before the dependency ships would waste effort (you'd have to throw away work)
- The dependent's acceptance criteria literally require the dependency's output

Do NOT add a dependency for:
- Nice-to-have ordering preferences (file a comment instead)
- Soft sequencing ("I'd rather do A first" — that's priority ordering, not dependency)

Over-dependency leads to analysis paralysis. Under-dependency leads to wasted work on things that can't ship.

## Rendering for the user

On request ("show me the dependency graph", "what's blocking what"):

1. Run the graph script.
2. Output a text-mode tree or DAG summary:

```
Critical path (3 issues):
  #10 → #12 → #20 → #82

Isolated dependency chains:
  #65 → #85
  #48 → #87

Circular (FIX):
  (none)

Priority inversions (REVIEW):
  #82 (High) depends on #13 (Medium — closed OK)
  #84 (Medium) depends on #78 (Low)
```

For visual rendering, emit DOT syntax that Graphviz can render:

```
digraph deps {
  "#10" -> "#12";
  "#12" -> "#20";
  "#20" -> "#82";
  "#65" -> "#85";
}
```

Write to a file, note the path, and let the user decide whether to render.
