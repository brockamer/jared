"""Tests for the partition module — anti-overlap session-N assignment."""

from skills.jared.scripts.lib.partition import Assignment, Proposal, extract_surface


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
