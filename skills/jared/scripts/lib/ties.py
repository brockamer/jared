"""Tied-issues analysis — pure Python, no I/O.

Six deterministic signals tagged by confidence (strong/medium/weak), combined
into a per-related-issue score, filtered by threshold, sorted, capped at 8,
formatted for the /jared-start announce block.

See docs/superpowers/specs/2026-05-02-tied-issues-design.md for the full
design.
"""

from __future__ import annotations

import re
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


def analyze_blocked_by(
    target: OpenIssueForTies, open_issues: list[OpenIssueForTies]
) -> list[SignalHit]:
    """Strong signal: native GitHub addBlockedBy edge in either direction."""
    hits: list[SignalHit] = []
    for related in open_issues:
        if related.number == target.number:
            continue
        # Both directions can fire (rare mutual-blocker case); combine() dedupes per related_n.
        if related.number in target.blocked_by:
            hits.append(
                SignalHit(
                    related_n=related.number,
                    name="blocked_by",
                    confidence="strong",
                    evidence=f"target #{target.number} is blocked by #{related.number}",
                )
            )
        if target.number in related.blocked_by:
            hits.append(
                SignalHit(
                    related_n=related.number,
                    name="blocked_by",
                    confidence="strong",
                    evidence=f"#{related.number} is blocked by target #{target.number}",
                )
            )
    return hits


def analyze_milestone_overlap(
    target: OpenIssueForTies, open_issues: list[OpenIssueForTies]
) -> list[SignalHit]:
    """Strong signal: same milestone as target. None ≠ None — un-milestoned
    issues aren't tied to each other on this signal."""
    if target.milestone is None:
        return []
    hits: list[SignalHit] = []
    for related in open_issues:
        if related.number == target.number:
            continue
        if related.milestone == target.milestone:
            hits.append(
                SignalHit(
                    related_n=related.number,
                    name="milestone",
                    confidence="strong",
                    evidence=f"shares milestone {target.milestone!r}",
                )
            )
    return hits


# Match #N with word boundary, where N is a positive integer.
# Not preceded by an alphanumeric (so item123#42 doesn't match) and N is
# captured. Trailing word boundary handles ", " or end-of-line cleanly.
_ISSUE_REF_RE = re.compile(r"(?<![A-Za-z0-9])#(\d+)\b")


def _strip_fenced_code(text: str) -> str:
    """Remove triple-fenced code blocks so #N inside code doesn't count."""
    return re.sub(r"```.*?```", "", text, flags=re.DOTALL)


def _refs_in_body(body: str) -> set[int]:
    """Return the set of #N references in body, excluding fenced code blocks."""
    if not body:
        return set()
    cleaned = _strip_fenced_code(body)
    return {int(m.group(1)) for m in _ISSUE_REF_RE.finditer(cleaned)}


def analyze_cross_references(
    target: OpenIssueForTies,
    open_issues: list[OpenIssueForTies],
    *,
    direction: Literal["forward", "both"] = "both",
) -> list[SignalHit]:
    """Strong signal: target body mentions #N (forward) or #N body mentions
    target (reverse). Reverse direction skipped when direction='forward'
    (used in low-budget partial mode where other-issue bodies aren't fetched).

    `#N` inside fenced code blocks is ignored. Word-boundary required so
    `v1.0` is not `#0`. Multiple mentions of the same issue produce one hit.
    """
    target_refs = _refs_in_body(target.body)
    hits: list[SignalHit] = []
    seen: set[int] = set()

    for related in open_issues:
        if related.number == target.number or related.number in seen:
            continue
        # Forward: target body → related?
        if related.number in target_refs:
            hits.append(
                SignalHit(
                    related_n=related.number,
                    name="cross_ref",
                    confidence="strong",
                    evidence=f"target #{target.number} body mentions #{related.number}",
                )
            )
            seen.add(related.number)
            continue
        # Reverse: related body → target?
        if direction == "both":
            related_refs = _refs_in_body(related.body)
            if target.number in related_refs:
                hits.append(
                    SignalHit(
                        related_n=related.number,
                        name="cross_ref",
                        confidence="strong",
                        evidence=f"#{related.number} body mentions target #{target.number}",
                    )
                )
                seen.add(related.number)

    return hits
