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

from .ties import OpenIssueForTies, file_paths_in_body


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


def extract_surface(body: str) -> frozenset[str]:
    """Compute the surface fingerprint of an issue body — the set of file
    paths it cites. Single signal for v1.

    Direct alias of `lib.ties.file_paths_in_body`. Lives behind a partition-
    specific name so future signal expansion (title scope, label clusters)
    doesn't churn the partition-side import.
    """
    return file_paths_in_body(body)


def propose_partition(
    candidates: list[OpenIssueForTies],
    K: int,
    existing_session_labels: dict[int, int],
) -> Proposal:
    """Greedy anti-overlap partition.

    Walks `candidates` in their given order (caller is expected to sort by
    priority). For each candidate:

    - If body has no file paths → float (no label proposed, regardless of
      existing label).
    - If an existing session-N label is set and 1 ≤ N ≤ K → keep (honor
      operator's prior decision).
    - Otherwise → pick the session with the largest cumulative surface
      overlap (cohesion-first: overlapping issues co-locate); tie-break
      by load (smaller session wins).

    `move` is reserved for a future re-balance flag and is always empty in
    v1 — existing labels are never overridden.
    """
    session_surfaces: dict[int, set[str]] = {n: set() for n in range(1, K + 1)}
    session_loads: dict[int, int] = {n: 0 for n in range(1, K + 1)}

    keep: list[Assignment] = []
    move: list[Assignment] = []
    add: list[Assignment] = []
    floats: list[Assignment] = []

    for candidate in candidates:
        surface = extract_surface(candidate.body)
        if not surface:
            floats.append(
                Assignment(
                    issue=candidate.number,
                    session=None,
                    reason="no surface signal in body",
                )
            )
            continue

        existing = existing_session_labels.get(candidate.number)
        if existing is not None and 1 <= existing <= K:
            keep.append(
                Assignment(
                    issue=candidate.number,
                    session=existing,
                    reason="existing label honored",
                )
            )
            session_surfaces[existing] |= surface
            session_loads[existing] += 1
            continue

        # Pick session with largest surface overlap (cohesion-first), tie-break
        # by smaller load so unrelated issues spread evenly.
        best = max(
            range(1, K + 1),
            key=lambda n: (len(session_surfaces[n] & surface), -session_loads[n]),
        )
        overlap = session_surfaces[best] & surface
        if overlap:
            reason = f"shares {sorted(overlap)[0]} with session-{best}"
        else:
            reason = f"new cluster in session-{best} (lowest load)"

        add.append(
            Assignment(
                issue=candidate.number,
                session=best,
                reason=reason,
            )
        )
        session_surfaces[best] |= surface
        session_loads[best] += 1

    return Proposal(keep=keep, move=move, add=add, floats=floats)


__all__ = ["Assignment", "Proposal", "extract_surface", "propose_partition"]
