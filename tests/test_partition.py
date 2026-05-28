"""Tests for the partition module — anti-overlap session-N assignment."""

from skills.jared.scripts.lib.partition import Assignment, Proposal


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
