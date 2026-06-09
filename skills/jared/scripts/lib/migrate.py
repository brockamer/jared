"""Pure translation core for `jared migrate` (Phase 5, #318).

No I/O, no provider calls. Functions take neutral dataclasses (BoardItem, Edge,
Comment, Milestone) and the two backends' capability sets, and return
dataclasses/strings the CLI orchestrator (`_cmd_migrate`) applies. The lossiness
model is anchored to Appendix A of the Phase-1 board-provider spec.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .board_provider import Capability

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
