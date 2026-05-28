"""Tests for the partition module — anti-overlap session-N assignment."""

from skills.jared.scripts.lib.partition import (
    Assignment,
    Proposal,
    extract_surface,
    propose_partition,
)
from skills.jared.scripts.lib.ties import OpenIssueForTies


def test_assignment_dataclass_shape() -> None:
    a = Assignment(issue=42, session=1, reason="existing label honored")
    assert a.issue == 42
    assert a.session == 1
    assert a.reason == "existing label honored"


def test_assignment_session_none_for_float() -> None:
    a = Assignment(issue=42, session=None, reason="no surface signal in body")
    assert a.session is None


def test_proposal_dataclass_shape() -> None:
    p = Proposal(keep=[], move=[], add=[], floats=[])
    assert p.keep == []
    assert p.move == []
    assert p.add == []
    assert p.floats == []


def test_extract_surface_returns_file_paths_from_body() -> None:
    body = "Fix bug in `lib/board.py` and update `commands/jared-stage.md`."
    surface = extract_surface(body)
    assert "lib/board.py" in surface
    assert "commands/jared-stage.md" in surface


def test_extract_surface_excludes_generic_files() -> None:
    body = "Touches README.md and lib/board.py."
    surface = extract_surface(body)
    assert "README.md" not in surface
    assert "lib/board.py" in surface


def test_extract_surface_empty_body_returns_empty() -> None:
    assert extract_surface("") == frozenset()


def test_extract_surface_no_paths_returns_empty() -> None:
    assert extract_surface("Prose with no paths anywhere.") == frozenset()


def _candidate(
    number: int,
    *,
    title: str = "",
    body: str = "",
    labels: tuple[str, ...] = (),
) -> OpenIssueForTies:
    return OpenIssueForTies(
        number=number,
        title=title,
        body=body,
        labels=labels,
        milestone=None,
        status="Up Next",
        priority="Medium",
        blocked_by=(),
    )


def test_propose_partition_disjoint_clusters_split_cleanly() -> None:
    """Two candidate groups citing entirely different file paths land in
    different sessions."""
    candidates = [
        _candidate(1, body="Update `lib/board.py`."),
        _candidate(2, body="Refactor `lib/board.py`."),
        _candidate(3, body="Edit `commands/jared-stage.md`."),
        _candidate(4, body="Edit `commands/jared-wrap.md`."),
    ]
    proposal = propose_partition(candidates, K=2, existing_session_labels={})

    # All four are `add` (no existing labels)
    assert len(proposal.add) == 4
    assert len(proposal.keep) == 0
    assert len(proposal.move) == 0
    assert len(proposal.floats) == 0

    # Issues 1 and 2 share lib/board.py — should be in the same session
    by_issue = {a.issue: a.session for a in proposal.add}
    assert by_issue[1] == by_issue[2]
    # Issues 3 and 4 share commands/ — should be in the same session
    assert by_issue[3] == by_issue[4]
    # The two groups should be in different sessions
    assert by_issue[1] != by_issue[3]
