"""Anti-overlap partition: propose session-N label assignments for parallel
Claude sessions sharing one repo.

Single signal (v1): file paths cited in the issue body. Two candidates whose
bodies cite overlapping file paths are presumed to touch overlapping code.

The partition is operator-approved per item. Existing session-N labels are
honored (manual overrides win). A candidate with no surface signal is a
float — no label proposed.

See docs/superpowers/specs/2026-05-28-multi-session-back-end-design.md for
the full design and the cuts that distinguish v1 from a more elaborate
multi-signal version.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from .ties import file_paths_in_body

if TYPE_CHECKING:
    pass  # OpenIssueForTies imported in Task 3.3 when propose_partition is added


@dataclass(frozen=True)
class Assignment:
    """Proposed session-N assignment for one issue.

    `session=None` means float — no label proposed for this issue. `reason`
    is a short rationale shown in the proposal output.
    """

    issue: int
    session: int | None
    reason: str


@dataclass(frozen=True)
class Proposal:
    """Full stage proposal across a candidate set.

    `keep` — issue's existing session-N label is honored.
    `move` — existing label, proposing a different session (reserved for a
             future re-balance flag; v1 never populates this list).
    `add`  — no existing label, proposing one.
    `floats` — no surface signal; no label proposed.
    """

    keep: list[Assignment]
    move: list[Assignment]
    add: list[Assignment]
    floats: list[Assignment]


__all__ = ["Assignment", "Proposal", "file_paths_in_body"]
