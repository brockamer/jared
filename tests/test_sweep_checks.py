"""Tests for sweep.py check functions.

Narrow-scope tests for the drift detectors in the batch sweep script. Kept
separate from the full sweep flow (which shells out to gh and reads live
board state) — these only exercise the pure list-processing logic.
"""

from typing import Any

from tests.conftest import import_sweep


def _item(number: int, state: str, status: str, title: str = "") -> dict[str, Any]:
    """Shape matches what `gh project item-list --format json` returns."""
    return {
        "content": {"number": number, "state": state, "title": title or f"Issue {number}"},
        "status": status,
    }


def test_check_closed_not_done_returns_empty_when_all_closed_on_done() -> None:
    mod = import_sweep()
    items = [
        _item(1, "CLOSED", "Done"),
        _item(2, "CLOSED", "Done"),
        _item(3, "OPEN", "In Progress"),
    ]
    assert mod.check_closed_not_done(items) == []


def test_check_closed_not_done_flags_stuck_items() -> None:
    mod = import_sweep()
    items = [
        _item(42, "CLOSED", "Done", title="Done properly"),
        _item(92, "CLOSED", "Backlog", title="Stuck in Backlog"),
        _item(93, "CLOSED", "In Progress", title="Stuck in In Progress"),
        _item(100, "OPEN", "Backlog", title="Open — not stuck"),
    ]
    stuck = mod.check_closed_not_done(items)
    numbers = [entry["number"] for entry in stuck]
    assert numbers == [92, 93]
    assert stuck[0]["current_status"] == "Backlog"
    assert stuck[1]["current_status"] == "In Progress"


def test_check_closed_not_done_handles_no_status() -> None:
    """An item that's CLOSED but missing the status key entirely (older API
    responses, or pre-workflow boards) still gets flagged — its
    current_status renders as 'no Status' so the downstream format is
    still readable."""
    mod = import_sweep()
    items = [{"content": {"number": 99, "state": "CLOSED", "title": "No status at all"}}]
    [entry] = mod.check_closed_not_done(items)
    assert entry["number"] == 99
    assert entry["current_status"] == "no Status"


def test_check_closed_not_done_ignores_missing_content() -> None:
    """Items without a `content` payload (e.g. draft items) must not crash."""
    mod = import_sweep()
    items = [
        {"status": "Backlog"},  # no content at all
        _item(5, "CLOSED", "Backlog"),
    ]
    stuck = mod.check_closed_not_done(items)
    # Only the well-formed closed item is flagged.
    assert len(stuck) == 1
    assert stuck[0]["number"] == 5


def test_format_closed_not_done_line_includes_propose_command() -> None:
    """The render-site formatter names the remediation command so the groom
    flow has a concrete next action to propose with per-item approval.

    Format lives here, not in check_closed_not_done — so next sweep-check
    that needs a Propose-style suffix can follow the same
    detector-returns-data / renderer-formats-line split.
    """
    mod = import_sweep()
    entry = {"number": 92, "current_status": "Backlog", "title": "Stuck"}
    line = mod.format_closed_not_done_line(entry)
    assert "jared set 92 Status Done" in line
    assert "[Backlog]" in line
    assert "Stuck" in line
