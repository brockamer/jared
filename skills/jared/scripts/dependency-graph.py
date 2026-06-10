#!/usr/bin/env python3
"""
dependency-graph.py — build and analyze the issue dependency graph.

Reads dependencies with native GitHub `blockedBy` as the primary source;
falls back to `## Depends on` body-section parsing only when native returns
nothing for an issue (so narrative prose in that section doesn't override
canonical edges).

Outputs analysis:
  - Topological order (right sequence if parallelism were infinite)
  - Critical path (longest chain)
  - Cycles (should always be zero)
  - Priority inversions (High depending on Medium/Low)
  - Orphaned dependents (referencing closed issues)

Usage:
  dependency-graph.py --repo owner/repo
  dependency-graph.py --repo owner/repo --format dot > deps.dot
  dependency-graph.py --repo owner/repo --milestone "v0.2"
  dependency-graph.py --repo owner/repo --summary      # one-liner for sweep output
"""

from __future__ import annotations

import argparse
import re
import sys
from collections import defaultdict, deque
from pathlib import Path
from typing import Any, cast

# Make sibling lib/ importable regardless of cwd — same pattern as the jared CLI.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from lib.board import (  # type: ignore[import-not-found]  # noqa: E402
    Board,
    BoardConfigError,
    GhInvocationError,
)
from lib.board import (
    check_graphql_budget as board_check_graphql_budget,
)
from lib.board import (
    fetch_blocked_by_edges as board_fetch_blocked_by_edges,
)
from lib.board import (
    fetch_issue_state_rest as board_fetch_issue_state_rest,
)
from lib.board import (
    graphql_budget as board_graphql_budget,
)
from lib.board import (
    run_gh as board_run_gh,
)
from lib.board_provider import (  # type: ignore[import-not-found]  # noqa: E402
    Capability,
)
from lib.capabilities import (  # type: ignore[import-not-found]  # noqa: E402
    degraded_or_none,
)

# ---------- gh helpers ----------


def fetch_open_issues(repo: str, milestone: str | None) -> list[dict[str, Any]]:
    cmd = [
        "issue",
        "list",
        "--repo",
        repo,
        "--state",
        "open",
        "--limit",
        "500",
        "--json",
        "number,title,body,labels,state",
    ]
    if milestone:
        cmd += ["--milestone", milestone]
    return cast(list[dict[Any, Any]], board_run_gh(cmd))


def fetch_issue_state(repo: str, number: int) -> str:
    """Return state for an issue via REST (`core` bucket — #54).

    Delegates to `lib.board.fetch_issue_state_rest`, dropping the per-issue
    GraphQL pressure when this script fans out across unknown dependency edges.
    """
    state, _ = board_fetch_issue_state_rest(repo, number)
    return cast(str, state)


def fetch_field_priorities(repo: str, *, board: Board | None = None) -> dict[int, str]:
    """Map open-issue number -> project-field Priority (e.g. "High").

    Priority is a project **field** under jared doctrine; the `priority:` labels
    this script used to read are stripped as legacy (`sweep.py`
    `check_legacy_priority_labels`), so a label-based read always came back
    empty on a doctrine board and `find_priority_inversions` could never fire
    (#299). This sources Priority the way the rest of the CLI does — through the
    parsed board snapshot.

    Degrades to an empty map — priority check disabled, but the graph / cycle /
    critical-path / orphaned analysis still runs — rather than crashing when:
      - no board config doc is present (`BoardConfigError`),
      - the board doc's repo != `repo` (`Board` reads its repo from the doc, not
        from `--repo`; a join on mismatched issue numbers would manufacture
        phantom inversions), or
      - the open-items GraphQL call fails or overflows its 100-issue cap
        (`GhInvocationError`).
    """
    if board is None:
        try:
            board = Board.from_default()
        except BoardConfigError as e:
            print(
                f"dependency-graph: no board config ({e}); priority check disabled",
                file=sys.stderr,
            )
            return {}
    if board.repo != repo:
        print(
            f"dependency-graph: board doc repo {board.repo!r} != --repo {repo!r}; "
            "priority check disabled",
            file=sys.stderr,
        )
        return {}
    try:
        items = board.open_items()
    except GhInvocationError as e:
        print(
            f"dependency-graph: open_items failed ({e}); priority check disabled",
            file=sys.stderr,
        )
        return {}
    priorities: dict[int, str] = {}
    for item in items:
        number = item.get("content", {}).get("number")
        priority = item.get("priority")
        if isinstance(number, int) and priority:
            priorities[number] = priority
    return priorities


def fetch_all_native_dependencies(
    repo: str, *, board: Board | None = None
) -> dict[int, list[int]] | None:
    """Fetch native blockedBy edges for ALL open issues in one paginated call.

    Returns `{issue_number: [open_blocker_numbers]}` (closed-state blockers
    are filtered out — the dep-graph only cares about live edges). Returns
    None if the underlying GraphQL call fails entirely (e.g. the repo
    doesn't have native dependencies enabled). Callers treat None as
    "fall back to body-text parsing" and missing-key as "no native data
    for this issue."

    Phase 6: when ``board`` is provided and NATIVE_DEPENDENCIES is absent,
    emits a degradation note to stderr and returns None so the caller
    falls through to body-text parsing (do not silently switch — the note
    makes the fallback explicit).

    Replaces the old per-issue call (which made one GraphQL request per
    open issue — O(N) instead of O(pages)).
    """
    if board is not None:
        note = degraded_or_none(
            board,
            Capability.NATIVE_DEPENDENCIES,
            "native blocked-by edges",
            "native edges unavailable — falling back to `## Blocked by` body-text parsing",
        )
        if note:
            print(f"  {note}", file=sys.stderr)
            return None
    try:
        edges = board_fetch_blocked_by_edges(repo, cache="60s")
    except (GhInvocationError, RuntimeError):
        return None
    return {
        issue_n: [d["number"] for d in deps if d.get("state") == "OPEN"]
        for issue_n, deps in edges.items()
    }


# ---------- Body parsing ----------


def parse_section_refs(body: str, section: str) -> list[int]:
    """Find #N references under a ## <section> heading."""
    if not body:
        return []
    pattern = rf"^#{{1,3}}\s+{re.escape(section)}\s*$([\s\S]+?)(?=^#{{1,3}}\s|\Z)"
    m = re.search(pattern, body, re.MULTILINE | re.IGNORECASE)
    if not m:
        return []
    return [int(n) for n in re.findall(r"#(\d+)", m.group(1))]


def body_dependencies(issue: dict[str, Any]) -> list[int]:
    return parse_section_refs(issue.get("body", "") or "", "Depends on")


# ---------- Graph operations ----------


def topological_sort(graph: dict[int, set[int]]) -> tuple[list[int], list[list[int]]]:
    """Return (topo_order, cycles). Kahn's algorithm.

    `graph[u] = {v1, v2, ...}` means u depends on v1, v2, ... so each vi must
    ship before u. Topological order emits a node only after all of its
    dependencies. For Kahn, we count each node's outstanding dependencies
    (len(graph[u])) and start with nodes that have zero. Processing a node n
    decrements the count of anything that depends on n.
    """
    nodes = set(graph.keys())
    for deps in graph.values():
        nodes.update(deps)

    # Ensure every referenced node is a key so iteration below sees it.
    for n in nodes:
        graph.setdefault(n, set())

    in_degree = {n: len(graph[n]) for n in nodes}

    # Reverse index: blocker -> set of things that depend on it.
    dependents: dict[int, set[int]] = defaultdict(set)
    for u, deps in graph.items():
        for v in deps:
            dependents[v].add(u)

    queue = deque(sorted(n for n in nodes if in_degree[n] == 0))
    order = []
    while queue:
        n = queue.popleft()
        order.append(n)
        for m in dependents.get(n, ()):
            in_degree[m] -= 1
            if in_degree[m] == 0:
                queue.append(m)

    cycles = []
    if len(order) != len(nodes):
        remaining = nodes - set(order)
        cycles.append(sorted(remaining))
    return order, cycles


def critical_path(graph: dict[int, set[int]]) -> list[int]:
    """Longest dependency chain. Returns node list from root to leaf."""
    memo: dict[int, list[int]] = {}

    def longest_from(node: int, visiting: set[int]) -> list[int]:
        if node in memo:
            return memo[node]
        if node in visiting:
            return [node]
        visiting = visiting | {node}
        best = [node]
        for d in graph.get(node, set()):
            chain = [node] + longest_from(d, visiting)
            if len(chain) > len(best):
                best = chain
        memo[node] = best
        return best

    longest: list[int] = []
    for n in graph:
        chain = longest_from(n, set())
        if len(chain) > len(longest):
            longest = chain
    return longest


def find_priority_inversions(
    graph: dict[int, set[int]], priorities: dict[int, str]
) -> list[tuple[int, int]]:
    """Dependent is higher priority than its dependency."""
    rank = {"high": 3, "medium": 2, "med": 2, "low": 1}
    inversions = []
    for dependent, deps in graph.items():
        dp = rank.get((priorities.get(dependent) or "").lower(), 0)
        for dep in deps:
            dq = rank.get((priorities.get(dep) or "").lower(), 0)
            if dp > dq and dq > 0:
                inversions.append((dependent, dep))
    return inversions


def find_orphaned(
    graph: dict[int, set[int]],
    repo: str,
    open_numbers: set[int],
    *,
    board: Board | None = None,
) -> list[tuple[int, int]]:
    """Dependents whose dependencies are closed or missing.

    Phase 6: when ``board`` is provided and CLOSED_STATE is absent, the
    closed-state lookup is meaningless (there is no real "closed" state,
    only the Done column). Returns [] with a note on stderr.
    """
    if board is not None:
        orphan_note = degraded_or_none(
            board,
            Capability.CLOSED_STATE,
            "orphaned-dependency check",
            "no closed-state lookup on this backend",
        )
        if orphan_note:
            print(f"  {orphan_note}", file=sys.stderr)
            return []
    orphaned = []
    # Check referenced issues that aren't in the open set
    referenced = set()
    for deps in graph.values():
        referenced.update(deps)
    unknown = referenced - open_numbers
    states = {n: fetch_issue_state(repo, n) for n in unknown}
    for dependent, deps in graph.items():
        for dep in deps:
            if states.get(dep) == "CLOSED":
                orphaned.append((dependent, dep))
    return orphaned


# ---------- Output formats ----------


def format_summary(
    graph: dict[int, set[int]],
    titles: dict[int, str],
    cycles: list[list[int]],
    critical: list[int],
    inversions: list[tuple[int, int]],
    orphaned: list[tuple[int, int]],
) -> str:
    lines = []
    edge_count = sum(len(v) for v in graph.values())
    lines.append(f"Dependency graph: {len(graph)} issues, {edge_count} dependencies.")
    if cycles:
        lines.append(f"  CYCLES (fix immediately): {cycles}")
    else:
        lines.append("  Cycles: none")
    if critical and len(critical) > 1:
        chain = " → ".join(f"#{n}" for n in critical)
        lines.append(f"  Critical path ({len(critical)}): {chain}")
    else:
        lines.append("  Critical path: trivial (no chains >1)")
    if inversions:
        lines.append(f"  Priority inversions: {len(inversions)}")
        for dep, blk in inversions:
            lines.append(f"    #{dep} depends on #{blk}")
    else:
        lines.append("  Priority inversions: none")
    if orphaned:
        lines.append(f"  Orphaned (depends on closed): {len(orphaned)}")
        for dep, blk in orphaned:
            lines.append(f"    #{dep} → #{blk} (closed)")
    else:
        lines.append("  Orphaned: none")
    return "\n".join(lines)


def format_dot(graph: dict[int, set[int]], titles: dict[int, str]) -> str:
    lines = ["digraph deps {", "  rankdir=LR;", "  node [shape=box];"]
    for n in graph:
        title = titles.get(n, "?").replace('"', "'")[:40]
        lines.append(f'  "#{n}" [label="#{n}\\n{title}"];')
    for dependent, deps in graph.items():
        for dep in deps:
            lines.append(f'  "#{dependent}" -> "#{dep}";')
    lines.append("}")
    return "\n".join(lines)


# ---------- Main ----------


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--repo", required=True, help="Repo slug (owner/repo)")
    parser.add_argument("--milestone", help="Limit to issues in this milestone")
    parser.add_argument("--format", choices=["text", "dot"], default="text")
    parser.add_argument("--summary", action="store_true", help="One-block summary")
    parser.add_argument(
        "--no-native",
        action="store_true",
        help="Skip native issue dependency lookups",
    )
    parser.add_argument(
        "--min-budget",
        type=int,
        default=200,
        help="Skip if remaining GraphQL budget is below this (default: 200)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Run even if GraphQL budget is below --min-budget",
    )
    args = parser.parse_args()

    # Pre-flight GraphQL budget gate. Building the dep-graph fans out
    # GraphQL calls; bail out early when budget can't cover the work.
    try:
        budget = board_graphql_budget()
    except (RuntimeError, GhInvocationError) as e:
        print(f"dependency-graph: budget probe failed ({e}); proceeding anyway", file=sys.stderr)
    else:
        warning = board_check_graphql_budget(budget, min_required=args.min_budget, force=args.force)
        if warning:
            print(f"dependency-graph: {warning}", file=sys.stderr)
            return 0

    print(
        f"Fetching open issues from {args.repo}"
        + (f" (milestone {args.milestone!r})..." if args.milestone else "..."),
        file=sys.stderr,
    )

    try:
        issues = fetch_open_issues(args.repo, args.milestone)
    except GhInvocationError as e:
        print(f"dependency-graph: {e}", file=sys.stderr)
        return 1

    issues_by_number = {i["number"]: i for i in issues}
    open_numbers = set(issues_by_number.keys())

    # Resolve capabilities offline (no live API calls — never touch board.provider).
    # If the board doc can't be found/parsed, capability_board stays None and all
    # gates are skipped, preserving pre-Phase-6 behaviour.
    capability_board: Board | None = None
    try:  # noqa: SIM105
        capability_board = Board.from_default()
    except Exception:  # noqa: BLE001 — offline doc parse; never fail the graph build
        pass

    # Pre-fetch ALL native dependency edges for the repo in one paginated
    # GraphQL call instead of one per issue. None means the GraphQL call
    # failed entirely; any per-issue lookup miss means no native data for
    # that issue (treat as fall-back-to-body, same as before).
    all_native: dict[int, list[int]] | None = None
    if not args.no_native:
        all_native = fetch_all_native_dependencies(args.repo, board=capability_board)

    # Build graph: N → set of issues N depends on
    graph: dict[int, set[int]] = defaultdict(set)

    for issue in issues:
        n = issue["number"]
        # Native edges are canonical when present. Body `## Depends on` sections
        # may contain narrative prose ("#10 — shipped, #12 — critical path"),
        # so treat them as a fallback only when native has nothing for this
        # issue — either the API call failed (None) or returned no edges ([]).
        # Missing key in all_native means no native data for this issue
        # (e.g. milestone-filtered out, or issue isn't in the open-issues
        # state set). Treat as None — body-text fallback may still find edges.
        native: list[int] | None = (
            None if args.no_native or all_native is None else all_native.get(n)
        )

        if native:
            for dep in native:
                graph[n].add(dep)
        elif native is None or args.no_native:
            # No native data available — fall back to body-text parsing.
            for dep in body_dependencies(issue):
                graph[n].add(dep)
        # native == [] means "native says this issue has no deps" — don't
        # second-guess it with stale body text.

    if not graph:
        print("No dependencies found.", file=sys.stderr)
        return 0

    titles = {n: issues_by_number[n]["title"] for n in issues_by_number}

    # Priority from the project field, not `priority:` labels (doctrine strips
    # those, so the old label read was always empty — #299). Degrades to {} if
    # the board can't be read; the rest of the analysis still runs.
    priorities = fetch_field_priorities(args.repo)

    # Analyze
    topo, cycles = topological_sort(dict(graph))
    critical = critical_path(dict(graph))
    inversions = find_priority_inversions(graph, priorities)
    orphaned = find_orphaned(graph, args.repo, open_numbers, board=capability_board)

    # Output
    if args.format == "dot":
        print(format_dot(graph, titles))
        return 0

    if args.summary:
        print(format_summary(graph, titles, cycles, critical, inversions, orphaned))
        return 0

    # Full text output
    print(format_summary(graph, titles, cycles, critical, inversions, orphaned))
    print()
    print("All dependencies:")
    for dependent in sorted(graph):
        for dep in sorted(graph[dependent]):
            title = titles.get(dep, "?")[:40]
            print(f"  #{dependent} → #{dep} ({title})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
