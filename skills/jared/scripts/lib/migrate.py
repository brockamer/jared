"""Pure translation core for `jared migrate` (Phase 5, #318).

No I/O, no provider calls. Functions take neutral dataclasses (BoardItem, Edge,
Comment, Milestone) and the two backends' capability sets, and return
dataclasses/strings the CLI orchestrator (`_cmd_migrate`) applies. The lossiness
model is anchored to Appendix A of the Phase-1 board-provider spec.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from .board_provider import Capability, Edge

Direction = str  # "github->kanbanflow" | "kanbanflow->github"

# Capability -> (loss key, human description) when the target LACKS it.
_CAPABILITY_LOSS = {
    Capability.NATIVE_DEPENDENCIES: (
        "native_dependencies",
        "native blocked-by edges become 'blocked-by:<N>' label markers + the Blocked column",
    ),
    Capability.MILESTONE_STATE: (
        "milestone_state",
        "milestone open/close state and due dates are dropped"
        " (swimlanes carry name + description only)",
    ),
    Capability.VELOCITY_TIMESTAMPS: (
        "velocity_timestamps",
        "created/closed/transition timestamps are not portable",
    ),
    Capability.MARKDOWN_BODY: (
        "markdown_body",
        "markdown rendering is lost (text round-trips; only rendering, not data)",
    ),
    Capability.CLOSED_STATE: (
        "closed_state",
        "no real closed state on the target (Done column only)",
    ),
    Capability.SUB_ISSUES: ("sub_issues", "sub-issue hierarchy is not portable"),
    Capability.MCP_TIER: ("mcp_tier", "MCP-tier operations are unavailable on the target"),
}


@dataclass
class LossAxis:
    key: str
    description: str
    count: int = 0  # dataset-specific magnitude (e.g. # of edges affected); 0 = N/A


def compute_loss_axes(
    *, source_caps: frozenset[Capability], target_caps: frozenset[Capability], direction: Direction
) -> list[LossAxis]:
    """Itemize every named loss for this direction.

    A capability the SOURCE has but the TARGET lacks is a loss. KF->GitHub
    additionally renumbers (#N is auto-assigned on GitHub), which is a loss axis
    even though it is not a capability difference.
    """
    axes: list[LossAxis] = []
    for cap in Capability:
        if cap in source_caps and cap not in target_caps and cap in _CAPABILITY_LOSS:
            key, desc = _CAPABILITY_LOSS[cap]
            axes.append(LossAxis(key=key, description=desc))
    if direction == "kanbanflow->github":
        axes.append(
            LossAxis(
                key="renumber",
                description=(
                    "every #N is reassigned by GitHub;"
                    " cross-references are rewritten via the number map"
                ),
            )
        )
    return axes


@dataclass
class NumberMap:
    """old #N -> new #N. Identity on GH->KF; load-bearing on KF->GitHub."""

    mapping: dict[int, int] = field(default_factory=dict)

    @classmethod
    def identity(cls, numbers: list[int]) -> NumberMap:
        return cls({n: n for n in numbers})

    def put(self, old: int, new: int) -> None:
        self.mapping[old] = new

    def to_new(self, old: int) -> int | None:
        return self.mapping.get(old)

    def keys(self) -> set[int]:
        return set(self.mapping)


_ISSUE_REF_RE = re.compile(r"#(\d+)\b")


def rewrite_cross_refs(text: str, number_map: NumberMap) -> str:
    """Rewrite '#<old>' -> '#<new>' for every old number that is a key in the map.

    Numbers absent from the map are left untouched — the false-positive guard
    for '#N' tokens that are not migrated issue refs (Q2).
    """

    def _sub(m: re.Match[str]) -> str:
        old = int(m.group(1))
        new = number_map.to_new(old)
        return f"#{new}" if new is not None else m.group(0)

    return _ISSUE_REF_RE.sub(_sub, text)


def translate_edges(edges: list[Edge], number_map: NumberMap) -> list[Edge]:
    """Re-key edges through the number map. Drop any edge whose endpoint is
    unmapped (an item that was not migrated)."""
    out: list[Edge] = []
    for e in edges:
        dep = number_map.to_new(e.dependent)
        blk = number_map.to_new(e.blocker)
        if dep is not None and blk is not None:
            out.append(Edge(dependent=dep, blocker=blk))
    return out


def estimate_kf_calls(
    *, item_count: int, extra_fields_per_item: int, edge_count: int, comment_count: int
) -> int:
    """Upper-bound KanbanFlow write calls for a GH->KF apply run.

    Per item: 1 create + 1 Priority custom-field POST + N extra custom-field
    POSTs. Plus 1 label POST per edge (blocked-by:<N>) and 1 POST per comment.
    Printed in the dry-run so the operator knows whether the run fits KF's
    1,000 req/hr window.
    """
    per_item = 1 + 1 + extra_fields_per_item
    return item_count * per_item + edge_count + comment_count


def render_report(
    *, direction: Direction, item_count: int, axes: list[LossAxis], kf_call_estimate: int
) -> str:
    lines = [
        f"Migration plan: {direction}",
        f"  {item_count} items to copy",
    ]
    if kf_call_estimate:
        lines.append(f"  ~{kf_call_estimate} KanbanFlow write calls (1,000/hr budget)")
    lines.append("  Named losses (Appendix A):")
    if not axes:
        lines.append("    (none — lossless in this direction)")
    for a in axes:
        suffix = f" [{a.count}]" if a.count else ""
        lines.append(f"    - {a.key}: {a.description}{suffix}")
    return "\n".join(lines)


@dataclass
class MigrationLedger:
    """Durable resume ledger + run artifact.

    Tracks two distinct kinds of progress so a resume re-run is duplication-free:

    - `completed` maps old#->new# — the first-pass record that an item was
      *created* on the target. `number_map()` is built from the full set, so the
      second pass can re-key cross-refs/edges against items created in earlier
      runs too.
    - `ported` / `edges_applied` record *second-pass* progress (body+comment
      portage per item, and blocked-by edges by source endpoint pair). The second
      pass is NOT idempotent on a live backend — comment() duplicates on every
      replay — so these guards are what make a resume (or a re-run against a
      finished artifact) a no-op rather than a comment-duplicator. They are
      separate from `completed` because an item can be created in one run and have
      its body/comments ported in a later one.
    """

    direction: Direction
    completed: dict[int, int] = field(default_factory=dict)
    losses: list[str] = field(default_factory=list)
    # Second-pass progress. `ported` holds source numbers whose body + comments
    # are done; `edges_applied` holds source (dependent, blocker) pairs already
    # replayed. Keyed on SOURCE numbers/pairs (stable across runs, independent of
    # the number map).
    ported: set[int] = field(default_factory=set)
    edges_applied: set[tuple[int, int]] = field(default_factory=set)

    def mark(self, *, old: int, new: int) -> None:
        self.completed[old] = new

    def is_done(self, old: int) -> bool:
        return old in self.completed

    def number_map(self) -> NumberMap:
        return NumberMap(dict(self.completed))

    def mark_ported(self, old: int) -> None:
        self.ported.add(old)

    def is_ported(self, old: int) -> bool:
        return old in self.ported

    def mark_edge(self, *, dependent: int, blocker: int) -> None:
        self.edges_applied.add((dependent, blocker))

    def is_edge_applied(self, *, dependent: int, blocker: int) -> bool:
        return (dependent, blocker) in self.edges_applied

    def to_json(self) -> str:
        return json.dumps(
            {
                "direction": self.direction,
                "completed": {str(k): v for k, v in self.completed.items()},
                "losses": self.losses,
                "ported": sorted(self.ported),
                "edges_applied": [[d, b] for d, b in sorted(self.edges_applied)],
            },
            indent=2,
        )

    @classmethod
    def from_json(cls, blob: str) -> MigrationLedger:
        data = json.loads(blob)
        return cls(
            direction=str(data["direction"]),
            completed={int(k): int(v) for k, v in (data.get("completed") or {}).items()},
            losses=[str(x) for x in (data.get("losses") or [])],
            ported={int(x) for x in (data.get("ported") or [])},
            edges_applied={(int(d), int(b)) for d, b in (data.get("edges_applied") or [])},
        )
