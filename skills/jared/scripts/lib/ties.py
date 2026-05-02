"""Tied-issues analysis — pure Python, no I/O.

Six deterministic signals tagged by confidence (strong/medium/weak), combined
into a per-related-issue score, filtered by threshold, sorted, capped at 8,
formatted for the /jared-start announce block.

See docs/superpowers/specs/2026-05-02-tied-issues-design.md for the full
design.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

SignalName = Literal[
    "cross_ref",
    "blocked_by",
    "milestone",
    "title_tokens",
    "labels",
    "file_paths",
]
Confidence = Literal["strong", "medium", "weak"]
# Threshold and Confidence model different roles (filter cutoff vs. signal
# strength) but share the same domain — Literal members are unordered, so
# they are the same type. Aliasing makes the relationship explicit.
Threshold = Confidence

# Default stop-words for label-intersection signal. Project-board.md may override.
DEFAULT_LABEL_STOP_WORDS: frozenset[str] = frozenset(
    {"enhancement", "bug", "documentation", "refactor"}
)

# Output cap on number of ties surfaced.
MAX_TIES_DISPLAYED = 8

# Confidence weights for combined_score.
CONFIDENCE_WEIGHT: dict[Confidence, int] = {"strong": 3, "medium": 2, "weak": 1}

# Score cap so a single candidate firing every signal doesn't dominate sorting.
MAX_COMBINED_SCORE = 5


@dataclass(frozen=True)
class SignalHit:
    related_n: int
    name: SignalName
    confidence: Confidence
    evidence: str


@dataclass(frozen=True)
class Tie:
    related_n: int
    related_title: str
    related_status: str
    hits: tuple[SignalHit, ...]
    combined_score: int
    primary_relationship: str
    secondary_relationships: tuple[str, ...]
    suggested_action: str


@dataclass(frozen=True)
class OpenIssueForTies:
    """Single record returned by Board.fetch_open_issues_for_ties().

    body may be empty string in partial mode (low GraphQL budget). All other
    fields are always populated.
    """

    number: int
    title: str
    body: str
    labels: tuple[str, ...]
    milestone: str | None
    status: str
    priority: str | None
    blocked_by: tuple[int, ...]
