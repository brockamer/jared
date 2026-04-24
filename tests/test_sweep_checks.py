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
    assert len(stuck) == 2
    joined = "\n".join(stuck)
    assert "#92" in joined
    assert "#93" in joined
    # Neither the properly-Done nor the open item should appear.
    assert "#42" not in joined
    assert "#100" not in joined


def test_check_closed_not_done_includes_propose_command() -> None:
    """Each stuck item's line must name the remediation command so /jared-groom
    can propose a concrete next action at the conversational layer."""
    mod = import_sweep()
    items = [_item(92, "CLOSED", "Backlog", title="Stuck")]
    [line] = mod.check_closed_not_done(items)
    assert "jared set 92 Status Done" in line
    # Preserves the existing "[<status>]: <title>" shape too.
    assert "[Backlog]" in line
    assert "Stuck" in line


def test_check_closed_not_done_handles_no_status() -> None:
    """An item that's CLOSED but missing the status key entirely (older API
    responses, or pre-workflow boards) still gets flagged — renders as
    'no Status' in the output so the row is still readable."""
    mod = import_sweep()
    items = [
        {"content": {"number": 99, "state": "CLOSED", "title": "No status at all"}}
    ]
    [line] = mod.check_closed_not_done(items)
    assert "#99" in line
    assert "no Status" in line
    assert "jared set 99 Status Done" in line


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
    assert "#5" in stuck[0]
