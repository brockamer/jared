#!/usr/bin/env python3
"""
dependency-graph.py — build and analyze the issue dependency graph.

Reads dependencies from two sources:
  1. Native GitHub issue dependencies (via GraphQL)
  2. Body conventions: ## Depends on / ## Blocks sections with #N references

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
import json
import re
import subprocess
import sys
from collections import defaultdict, deque


# ---------- gh helpers ----------


def run_gh(args: list[str]) -> dict | list:
    result = subprocess.run(args, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(f"{' '.join(args[:6])}... failed: {result.stderr.strip()}")
    return json.loads(result.stdout) if result.stdout.strip() else {}


def fetch_open_issues(repo: str, milestone: str | None) -> list[dict]:
    cmd = [
        "gh", "issue", "list", "--repo", repo, "--state", "open",
        "--limit", "500", "--json", "number,title,body,labels,state",
    ]
    if milestone:
        cmd += ["--milestone", milestone]
    return run_gh(cmd)


def fetch_issue_state(repo: str, number: int) -> str:
    try:
        data = run_gh(
            ["gh", "issue", "view", str(number), "--repo", repo, "--json", "state"]
        )
        return data.get("state", "UNKNOWN")
    except Exception:
        return "UNKNOWN"


def fetch_native_dependencies(repo: str, number: int) -> list[int]:
    """Fetch native issueDependencies (what this issue is blocked by)."""
    query = """
    query($owner: String!, $repo: String!, $number: Int!) {
      repository(owner: $owner, name: $repo) {
        issue(number: $number) {
          issueDependencies(first: 50) {
            nodes { number state }
          }
        }
      }
    }
    """
    owner, name = repo.split("/", 1)
    try:
        result = run_gh([
            "gh", "api", "graphql",
            "-f", f"query={query}",
            "-F", f"owner={owner}",
            "-F", f"repo={name}",
            "-F", f"number={number}",
        ])
    except RuntimeError:
        return []
    deps = (
        result.get("data", {})
        .get("repository", {})
        .get("issue", {})
        .get("issueDependencies", {})
        .get("nodes", [])
    )
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
    """Return (topo_order, cycles). Kahn's algorithm."""
    in_degree = defaultdict(int)
    nodes = set(graph.keys())
    for deps in graph.values():
        nodes.update(deps)
    for deps in graph.values():
        for d in deps:
            in_degree[d] += 1

    # Handle nodes not in graph keys but referenced
    for n in nodes:
        if n not in in_degree:
            in_degree[n] = 0
        if n not in graph:
            graph[n] = set()

    queue = deque(n for n in nodes if in_degree[n] == 0)
    order = []
    while queue:
        n = queue.popleft()
        order.append(n)
        # Reverse edge: if N depends on D, D must come first. So when D is processed,
        # subtract from every N that depends on D.
        for parent, deps in graph.items():
            if n in deps:
                in_degree[parent] -= 1
                if in_degree[parent] == 0:
                    queue.append(parent)

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
    lines = ["digraph deps {", '  rankdir=LR;', '  node [shape=box];']
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
    parser.add_argument("--no-native", action="store_true", help="Skip native issue dependency lookups")
    args = parser.parse_args()

    print(f"Fetching open issues from {args.repo}" +
          (f" (milestone {args.milestone!r})..." if args.milestone else "..."),
          file=sys.stderr)

    try:
        issues = fetch_open_issues(args.repo, args.milestone)
    except RuntimeError as e:
        print(f"dependency-graph: {e}", file=sys.stderr)
        return 1

    issues_by_number = {i["number"]: i for i in issues}
    open_numbers = set(issues_by_number.keys())

    # Build graph: N → set of issues N depends on
    graph: dict[int, set[int]] = defaultdict(set)
    priorities: dict[int, str] = {}

    for issue in issues:
        n = issue["number"]
        # Body-convention deps
        for dep in body_dependencies(issue):
            graph[n].add(dep)
        # Native deps
        if not args.no_native:
            try:
                for dep in fetch_native_dependencies(args.repo, n):
                    graph[n].add(dep)
            except Exception:
                pass
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
