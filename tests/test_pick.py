"""The next-item pick for a bare `/jared-start` (#516).

`choose` is pure: it takes the open items in board order, the blocked-by edges,
the issue numbers that hold a session lock, and the session partition. These
tests build `BoardItem`s by hand, so no backend is involved. The CLI wiring on
each backend is pinned in `test_cmd_next_session_prompt.py`.
"""

from __future__ import annotations

from skills.jared.scripts.lib.board_provider import BoardItem, Edge
from skills.jared.scripts.lib.pick import choose, render_pick

PULLABLE = "A real summary.\n\n## Acceptance criteria\n\n- it works\n"
NO_CRITERIA = "A real summary.\n\n## Decisions\n\n(none yet)\n"


def _item(
    number: int,
    status: str,
    *,
    body: str = PULLABLE,
    labels: list[str] | None = None,
) -> BoardItem:
    return BoardItem(
        number=number,
        title=f"item {number}",
        status=status,
        priority="High",
        body=body,
        labels=labels or [],
    )


def test_resumes_an_unlocked_in_progress_item() -> None:
    items = [_item(10, "Up Next"), _item(20, "In Progress")]

    pick = choose(items, edges=[], locked=set())

    assert pick.number == 20
    assert pick.rule == 1
    assert pick.skipped == []


def test_skips_a_locked_in_progress_item_and_names_the_clear_command() -> None:
    items = [_item(20, "In Progress"), _item(10, "Up Next")]

    pick = choose(items, edges=[], locked={20})

    assert pick.number == 10
    assert pick.rule == 2
    assert [s.number for s in pick.skipped] == [20]
    assert "jared session-lock-clear --issue 20" in pick.skipped[0].reason


def test_takes_the_first_up_next_item_in_board_order() -> None:
    items = [_item(30, "Up Next"), _item(10, "Up Next"), _item(5, "Backlog")]

    pick = choose(items, edges=[], locked=set())

    assert pick.number == 30
    assert pick.rule == 2


def test_skips_an_up_next_item_with_an_open_blocker() -> None:
    items = [_item(10, "Up Next"), _item(11, "Up Next"), _item(99, "Backlog")]

    pick = choose(items, edges=[Edge(dependent=10, blocker=99)], locked=set())

    assert pick.number == 11
    assert [(s.number, s.status) for s in pick.skipped] == [(10, "Up Next")]
    assert "#99" in pick.skipped[0].reason


def test_a_blocker_outside_the_open_set_does_not_block() -> None:
    """A done blocker is absent from the open items on both backends."""
    items = [_item(10, "Up Next")]

    pick = choose(items, edges=[Edge(dependent=10, blocker=7)], locked=set())

    assert pick.number == 10
    assert pick.skipped == []


def test_skips_an_in_progress_item_with_an_open_blocker() -> None:
    items = [_item(20, "In Progress"), _item(99, "Backlog"), _item(10, "Up Next")]

    pick = choose(items, edges=[Edge(dependent=20, blocker=99)], locked=set())

    assert pick.number == 10
    assert [s.number for s in pick.skipped] == [20]


def test_skips_a_not_pullable_up_next_item_with_the_pullable_reason() -> None:
    items = [_item(10, "Up Next", body=NO_CRITERIA), _item(11, "Up Next")]

    pick = choose(items, edges=[], locked=set())

    assert pick.number == 11
    assert pick.skipped[0].number == 10
    assert pick.skipped[0].reason.startswith("not pullable")


def test_skips_a_locked_up_next_item() -> None:
    items = [_item(10, "Up Next"), _item(11, "Up Next")]

    pick = choose(items, edges=[], locked={10})

    assert pick.number == 11
    assert "session lock" in pick.skipped[0].reason


def test_session_partition_hides_items_of_other_sessions() -> None:
    items = [
        _item(20, "In Progress", labels=["session-1"]),
        _item(10, "Up Next", labels=["session-1"]),
        _item(11, "Up Next", labels=["session-2"]),
    ]

    pick = choose(items, edges=[], locked=set(), session=2)

    assert pick.number == 11
    assert pick.skipped == []


def test_session_partition_resumes_only_its_own_in_progress_item() -> None:
    items = [
        _item(20, "In Progress", labels=["session-1"]),
        _item(21, "In Progress", labels=["session-2"]),
    ]

    pick = choose(items, edges=[], locked=set(), session=2)

    assert pick.number == 21
    assert pick.rule == 1


def test_no_qualifying_item_returns_no_pick() -> None:
    items = [_item(10, "Up Next", body=""), _item(5, "Backlog")]

    pick = choose(items, edges=[], locked=set())

    assert pick.number is None
    assert pick.rule is None
    assert [s.number for s in pick.skipped] == [10]


def test_body_of_reads_only_the_up_next_items_up_to_the_pick() -> None:
    """GitHub's open-items query has no body, so bodies are read one at a time."""
    items = [
        _item(10, "Up Next", body=""),
        _item(11, "Up Next", body=""),
        _item(12, "Up Next", body=""),
    ]
    bodies = {10: NO_CRITERIA, 11: PULLABLE, 12: PULLABLE}
    read: list[int] = []

    def body_of(item: BoardItem) -> str:
        read.append(item.number)
        return bodies[item.number]

    pick = choose(items, edges=[], locked=set(), body_of=body_of)

    assert pick.number == 11
    assert read == [10, 11]


def test_render_names_the_pick_the_rule_and_each_skip() -> None:
    items = [_item(20, "In Progress"), _item(10, "Up Next", body=""), _item(11, "Up Next")]
    pick = choose(items, edges=[], locked={20})

    lines = render_pick(pick)

    assert lines[0].startswith("Pick: #11 — rule 2:")
    assert lines[1].startswith("Skipped: #20 [In Progress] — ")
    assert lines[2].startswith("Skipped: #10 [Up Next] — not pullable")


def test_render_with_no_pick_points_at_stage() -> None:
    pick = choose([], edges=[], locked=set())

    lines = render_pick(pick)

    assert lines[0].startswith("Pick: none — ")
    assert "/jared-stage" in lines[0]
