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

# Make sibling lib/ importable regardless of cwd — same pattern as the jared CLI.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from lib.board import (  # type: ignore[import-not-found]  # noqa: E402
    GhInvocationError,
)
from lib.board import (
    run_gh as board_run_gh,
)

# ---------- gh helpers ----------


def fetch_open_issues(repo: str, milestone: str | None) -> list[dict]:
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
    return board_run_gh(cmd)


def fetch_issue_state(repo: str, number: int) -> str:
    try:
        data = board_run_gh(["issue", "view", str(number), "--repo", repo, "--json", "state"])
        return data.get("state", "UNKNOWN")
    except GhInvocationError:
        return "UNKNOWN"


def fetch_native_dependencies(repo: str, number: int) -> list[int] | None:
    """Fetch native blockedBy edges (what this issue is blocked by).

    Returns a list of OPEN dependency numbers on success, or None if the
    GraphQL call fails (e.g. the repo doesn't have native dependencies
    enabled). Callers should treat None as "no native data — fall back to
    body conventions" and an empty list as "native says no dependencies."
    """
    query = """
    query($owner: String!, $repo: String!, $number: Int!) {
      repository(owner: $owner, name: $repo) {
        issue(number: $number) {
          blockedBy(first: 50) {
            nodes { number state }
          }
        }
      }
    }
    """
    owner, name = repo.split("/", 1)
    try:
        result = board_run_gh(
            [
                "api",
                "graphql",
                "-f",
                f"query={query}",
                "-F",
                f"owner={owner}",
                "-F",
                f"repo={name}",
                "-F",
                f"number={number}",
            ]
        )
    except GhInvocationError:
        return None
    issue = result.get("data", {}).get("repository", {}).get("issue")
    if issue is None:
        return None
    deps = (issue.get("blockedBy") or {}).get("nodes", [])
    return [d["number"] for d in deps if d.get("state") == "OPEN"]


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


def body_dependencies(issue: dict) -> list[int]:
    return parse_section_refs(issue.get("body", "") or "", "Depends on")


def issue_priority(issue: dict) -> str | None:
    for label in issue.get("labels", []):
        name = label.get("name", "").lower()
        if name.startswith("priority:"):
            return name.split(":", 1)[1].strip()
    return None


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
    graph: dict[int, set[int]], repo: str, open_numbers: set[int]
) -> list[tuple[int, int]]:
    """Dependents whose dependencies are closed or missing."""
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
    args = parser.parse_args()

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

    # Build graph: N → set of issues N depends on
    graph: dict[int, set[int]] = defaultdict(set)
    priorities: dict[int, str] = {}

    for issue in issues:
        n = issue["number"]
        # Native edges are canonical when present. Body `## Depends on` sections
        # may contain narrative prose ("#10 — shipped, #12 — critical path"),
        # so treat them as a fallback only when native has nothing for this
        # issue — either the API call failed (None) or returned no edges ([]).
        native = None
        if not args.no_native:
            try:
                native = fetch_native_dependencies(args.repo, n)
            except Exception:
                native = None

        if native:
            for dep in native:
                graph[n].add(dep)
        elif native is None or args.no_native:
            # No native data available — fall back to body-text parsing.
            for dep in body_dependencies(issue):
                graph[n].add(dep)
        # native == [] means "native says this issue has no deps" — don't
        # second-guess it with stale body text.

        # Priority from label
        p = issue_priority(issue)
        if p:
            priorities[n] = p

    if not graph:
        print("No dependencies found.", file=sys.stderr)
        return 0

    titles = {n: issues_by_number[n]["title"] for n in issues_by_number}

    # Analyze
    topo, cycles = topological_sort(dict(graph))
    critical = critical_path(dict(graph))
    inversions = find_priority_inversions(graph, priorities)
    orphaned = find_orphaned(graph, args.repo, open_numbers)

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
