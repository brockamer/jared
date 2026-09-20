"""Unit tests for KanbanFlowProvider (Phase 3, #316). Faked client, no network."""

from __future__ import annotations

from pathlib import Path

import pytest

from skills.jared.scripts.lib.board import FieldNotFound, ItemNotFound, OptionNotFound
from skills.jared.scripts.lib.board_provider import BoardProvider
from skills.jared.scripts.lib.kanbanflow_client import (
    KfChangedProperty,
    KfDetailedEvent,
    KfEvent,
    KfTask,
)
from skills.jared.scripts.lib.kanbanflow_provider import KanbanFlowProvider
from skills.jared.scripts.lib.kf_number_index import KfNumberIndex
from tests.fake_kanbanflow import FakeKanbanFlowClient


def _provider(tmp_path: Path) -> tuple[KanbanFlowProvider, FakeKanbanFlowClient]:
    client = FakeKanbanFlowClient()
    index = KfNumberIndex(tmp_path / "kf-index-B1.json")
    provider = KanbanFlowProvider(
        client=client, board=client.board, field_defs=client.field_defs, index=index
    )
    return provider, client


def test_fake_create_and_get_roundtrip() -> None:
    client = FakeKanbanFlowClient()
    t = client.create_task(name="hi", column_id="col-backlog", number_value=1)
    assert client.get_task(t.id).name == "hi"


def test_fake_get_missing_raises() -> None:
    from skills.jared.scripts.lib.kanbanflow_client import KanbanFlowNotFoundError

    client = FakeKanbanFlowClient()
    with pytest.raises(KanbanFlowNotFoundError):
        client.get_task("nope")


def test_provider_satisfies_protocol(tmp_path: Path) -> None:
    provider, _ = _provider(tmp_path)
    assert isinstance(provider, BoardProvider)


def test_capabilities_is_milestone_assignment_only(tmp_path: Path) -> None:
    """KanbanFlow advertises exactly one capability beyond the core board loop.

    MILESTONE_ASSIGNMENT (#390) — swimlanes give it milestone assignment, but
    nothing richer (state, dates, dependencies, etc).
    """
    from skills.jared.scripts.lib.board_provider import Capability

    provider, _ = _provider(tmp_path)
    assert provider.capabilities() == frozenset({Capability.MILESTONE_ASSIGNMENT})


def test_get_item_maps_task_to_boarditem(tmp_path: Path) -> None:
    provider, client = _provider(tmp_path)
    task = client.create_task(
        name="Do the thing",
        column_id="col-inprog",
        number_value=42,
        swimlane_id="sw-v1",
        description="## Summary\nbody",
    )
    client.set_task_custom_field(task.id, "cf-priority", "High")
    client.add_label(task.id, "session-2")
    client.add_label(task.id, "blocked-by:7")
    provider._index.put(42, task.id)

    item = provider.get_item(42)
    assert item is not None
    assert item.number == 42
    assert item.title == "Do the thing"
    assert item.status == "In Progress"
    assert item.priority == "High"
    assert item.milestone == "v1.0"
    assert item.body == "## Summary\nbody"
    assert item.labels == ["session-2"]  # blocked-by markers stripped
    assert item.blocked_by == [7]
    assert item.provider_ref == task.id


def test_get_item_missing_returns_none(tmp_path: Path) -> None:
    provider, _ = _provider(tmp_path)
    assert provider.get_item(999) is None


def test_list_open_items_excludes_done(tmp_path: Path) -> None:
    provider, client = _provider(tmp_path)
    client.create_task(name="open", column_id="col-upnext", number_value=1)
    client.create_task(name="closed", column_id="col-done", number_value=2)
    items = provider.list_open_items()
    assert sorted(i.title for i in items) == ["open"]


def test_get_body_returns_description(tmp_path: Path) -> None:
    provider, client = _provider(tmp_path)
    t = client.create_task(name="x", column_id="col-backlog", number_value=5, description="hello")
    provider._index.put(5, t.id)
    assert provider.get_body(5) == "hello"


def test_fetch_blocked_by_edges_parses_labels(tmp_path: Path) -> None:
    provider, client = _provider(tmp_path)
    a = client.create_task(name="a", column_id="col-upnext", number_value=10)
    client.add_label(a.id, "blocked-by:3")
    client.add_label(a.id, "blocked-by:4")
    client.create_task(name="b", column_id="col-upnext", number_value=11)  # no blockers
    edges = provider.fetch_blocked_by_edges()
    assert sorted((e.dependent, e.blocker) for e in edges) == [(10, 3), (10, 4)]


def _move_event(ev_id: str, ts: str, task_id: str, new_col: str) -> KfEvent:
    return KfEvent(
        id=ev_id,
        timestamp=ts,
        detailed_events=[
            KfDetailedEvent(
                event_type="taskChanged",
                task_id=task_id,
                changed_properties=[
                    KfChangedProperty(
                        property="columnId", old_value="col-inprog", new_value=new_col
                    )
                ],
            )
        ],
    )


def test_recently_closed_maps_columnid_into_done(tmp_path: Path) -> None:
    provider, client = _provider(tmp_path)
    client.tasks["task-A"] = KfTask(
        id="task-A", name="Closed thing", column_id="col-done", number_value=7
    )
    client.board_events = [_move_event("e1", "2026-06-05T13:20:56.216Z", "task-A", "col-done")]
    closed = provider.recently_closed(days=36500)  # wide window: exercise mapping, not cutoff
    assert len(closed) == 1
    assert closed[0].number == 7
    assert closed[0].title == "Closed thing"
    assert closed[0].closed_at == "2026-06-05T13:20:56.216Z"


def test_recently_closed_most_recent_move_wins(tmp_path: Path) -> None:
    provider, client = _provider(tmp_path)
    client.tasks["task-A"] = KfTask(id="task-A", name="T", column_id="col-done", number_value=7)
    client.board_events = [
        _move_event("e2", "2026-06-05T15:00:00.000Z", "task-A", "col-done"),
        _move_event("e1", "2026-06-05T13:00:00.000Z", "task-A", "col-done"),
    ]
    closed = provider.recently_closed(days=36500)
    assert len(closed) == 1
    assert closed[0].closed_at == "2026-06-05T15:00:00.000Z"


def test_recently_closed_skips_moves_into_non_done(tmp_path: Path) -> None:
    provider, client = _provider(tmp_path)
    client.tasks["task-A"] = KfTask(id="task-A", name="T", column_id="col-inprog", number_value=7)
    client.board_events = [_move_event("e1", "2026-06-05T13:00:00.000Z", "task-A", "col-inprog")]
    assert provider.recently_closed(days=36500) == []


def test_recently_closed_skips_unresolvable_task(tmp_path: Path) -> None:
    provider, client = _provider(tmp_path)
    client.board_events = [_move_event("e1", "2026-06-05T13:00:00.000Z", "ghost", "col-done")]
    assert provider.recently_closed(days=36500) == []


def test_recently_closed_excludes_events_before_cutoff(tmp_path: Path) -> None:
    provider, client = _provider(tmp_path)
    client.tasks["task-A"] = KfTask(
        id="task-A", name="Old close", column_id="col-done", number_value=7
    )
    # Event far in the past; a 30-day window must exclude it (deterministic — 2020 is
    # always > 30 days ago). Exercises the provider's own `ev.timestamp < cutoff` gate,
    # which is the only window enforcement in the test path (the fake ignores from_ts).
    client.board_events = [_move_event("e1", "2020-01-01T00:00:00.000Z", "task-A", "col-done")]
    assert provider.recently_closed(days=30) == []


def test_validate_fields_passes_for_valid(tmp_path: Path) -> None:
    provider, _ = _provider(tmp_path)
    provider.validate_fields(priority="High", status="Backlog", fields=[("Work Stream", "alpha")])


def test_validate_fields_raises_on_bad_status(tmp_path: Path) -> None:
    provider, _ = _provider(tmp_path)
    with pytest.raises(FieldNotFound):
        provider.validate_fields(priority="High", status="Nonexistent")


def test_validate_fields_raises_on_bad_priority_option(tmp_path: Path) -> None:
    provider, _ = _provider(tmp_path)
    with pytest.raises(OptionNotFound):
        provider.validate_fields(priority="Critical", status="Backlog")


def test_file_creates_task_with_status_priority_and_indexes(tmp_path: Path) -> None:
    provider, client = _provider(tmp_path)
    item = provider.file(
        title="New work",
        body="## Summary\nx",
        priority="High",
        status="Backlog",
        labels=["session-2"],
        milestone="v1.0",
        fields=[("Work Stream", "alpha")],
    )
    assert item.number == 1  # first allocation
    assert item.status == "Backlog"
    assert item.priority == "High"
    assert item.milestone == "v1.0"
    assert item.fields == {"Work Stream": "alpha"}
    assert "session-2" in item.labels
    assert provider._index.get(1) == item.provider_ref


def test_file_allocates_sequential_numbers(tmp_path: Path) -> None:
    provider, _ = _provider(tmp_path)
    a = provider.file(title="a", body="", priority="Low", status="Backlog")
    b = provider.file(title="b", body="", priority="Low", status="Backlog")
    assert (a.number, b.number) == (1, 2)


def test_file_seeds_next_number_from_existing_tasks(tmp_path: Path) -> None:
    provider, client = _provider(tmp_path)
    client.create_task(name="old", column_id="col-backlog", number_value=50)  # pre-existing
    item = provider.file(title="new", body="", priority="Low", status="Backlog")
    assert item.number == 51  # max existing + 1, via scan-on-seed


def test_file_rolls_back_orphan_on_field_failure(tmp_path: Path) -> None:
    provider, client = _provider(tmp_path)
    client.fail_set_custom_field = True
    with pytest.raises(RuntimeError):
        provider.file(title="doomed", body="", priority="High", status="Backlog")
    assert client.tasks == {}  # orphan deleted
    assert provider._index.get(1) is None  # not recorded


def test_add_to_board_applies_status_priority_fields_labels(tmp_path: Path) -> None:
    provider, client = _provider(tmp_path)
    t = client.create_task(name="bare", column_id="col-backlog", number_value=8)
    provider._index.put(8, t.id)
    provider.add_to_board(
        8,
        priority="Medium",
        status="Up Next",
        labels=["session-2"],
        fields=[("Work Stream", "beta")],
    )
    item = provider.get_item(8)
    assert item is not None
    assert item.status == "Up Next"
    assert item.priority == "Medium"
    assert item.fields == {"Work Stream": "beta"}
    assert "session-2" in item.labels


def _filed(provider: KanbanFlowProvider, **kw: object) -> int:
    item = provider.file(title="t", body="", priority="Low", status="Backlog", **kw)  # type: ignore[arg-type]
    return item.number


def test_set_field_updates_custom_field(tmp_path: Path) -> None:
    provider, _ = _provider(tmp_path)
    n = _filed(provider)
    provider.set_field(n, "Work Stream", "beta")
    assert provider.get_item(n).fields == {"Work Stream": "beta"}  # type: ignore[union-attr]


def test_move_changes_status_column(tmp_path: Path) -> None:
    provider, _ = _provider(tmp_path)
    n = _filed(provider)
    provider.move(n, "In Progress")
    assert provider.get_item(n).status == "In Progress"  # type: ignore[union-attr]


def test_set_body_updates_description(tmp_path: Path) -> None:
    provider, _ = _provider(tmp_path)
    n = _filed(provider)
    provider.set_body(n, "new body")
    assert provider.get_body(n) == "new body"


def test_comment_adds_and_returns_id(tmp_path: Path) -> None:
    provider, client = _provider(tmp_path)
    n = _filed(provider)
    cid = provider.comment(n, "a note")
    assert cid
    task_id = provider._index.get(n)
    assert client.list_comments(task_id)[-1].text == "a note"  # type: ignore[arg-type]


def test_close_comments_then_moves_to_done(tmp_path: Path) -> None:
    provider, client = _provider(tmp_path)
    n = _filed(provider)
    provider.close(n, comment="closing")
    assert provider.get_item(n).status == "Done"  # type: ignore[union-attr]
    task_id = provider._index.get(n)
    assert client.list_comments(task_id)[-1].text == "closing"  # type: ignore[arg-type]


def test_add_remove_label(tmp_path: Path) -> None:
    provider, _ = _provider(tmp_path)
    n = _filed(provider)
    provider.add_label(n, "session-2")
    assert "session-2" in provider.get_item(n).labels  # type: ignore[union-attr]
    provider.remove_label(n, "session-2")
    assert "session-2" not in provider.get_item(n).labels  # type: ignore[union-attr]


def test_add_remove_blocked_by_uses_label_marker(tmp_path: Path) -> None:
    provider, client = _provider(tmp_path)
    n = _filed(provider)
    provider.add_blocked_by(n, 99)
    task_id = provider._index.get(n)
    assert any(label.name == "blocked-by:99" for label in client.list_labels(task_id))  # type: ignore[arg-type]
    assert provider.get_item(n).blocked_by == [99]  # type: ignore[union-attr]
    provider.remove_blocked_by(n, 99)
    assert provider.get_item(n).blocked_by == []  # type: ignore[union-attr]


def test_set_milestone_moves_swimlane(tmp_path: Path) -> None:
    provider, _ = _provider(tmp_path)
    n = _filed(provider)
    provider.set_milestone(n, "v1.0")
    assert provider.get_item(n).milestone == "v1.0"  # type: ignore[union-attr]


def test_set_milestone_bad_name_raises(tmp_path: Path) -> None:
    provider, _ = _provider(tmp_path)
    n = _filed(provider)
    with pytest.raises(FieldNotFound):
        provider.set_milestone(n, "nonexistent")


def test_clear_milestone_refuses_rather_than_silently_no_opping(tmp_path: Path) -> None:
    """A KanbanFlow task always occupies a swimlane, so there is no clear (#427).

    The failure this guards against is specific: `update_task` builds its body
    with `if <kwarg> is not None`, so a pass-through implementation would POST
    an empty body and report success. Asserting the task's swimlane is
    unchanged afterwards is what separates "refused" from "silently no-opped" —
    a bare `pytest.raises` would pass for either.
    """
    provider, _ = _provider(tmp_path)
    n = _filed(provider)
    provider.set_milestone(n, "v1.0")

    with pytest.raises(FieldNotFound) as exc:
        provider.clear_milestone(n)

    assert "swimlane" in str(exc.value)
    assert provider.get_item(n).milestone == "v1.0"  # type: ignore[union-attr]


def test_list_milestones_from_swimlanes_dateless(tmp_path: Path) -> None:
    provider, _ = _provider(tmp_path)
    names = {m.name: m for m in provider.list_milestones()}
    assert "v1.0" in names
    assert names["v1.0"].state is None and names["v1.0"].due is None
    assert names["v1.0"].description == "First release"


def test_set_field_status_routes_to_move(tmp_path: Path) -> None:
    # Regression: the CLI drives Status changes through set_field("Status")
    # (jared move -> _cmd_set -> set_field, and `jared set N Status`). On
    # KanbanFlow, Status is a structural column, not a custom field, so
    # set_field must route it to a move instead of raising FieldNotFound.
    provider, _ = _provider(tmp_path)
    n = _filed(provider)
    provider.set_field(n, "Status", "In Progress")
    assert provider.get_item(n).status == "In Progress"  # type: ignore[union-attr]


def test_list_open_items_skips_unnumbered_tasks(tmp_path: Path) -> None:
    provider, client = _provider(tmp_path)
    client.create_task(name="numbered", column_id="col-upnext", number_value=1)
    ui_made = client.create_task(name="ui-made", column_id="col-upnext", number_value=2)
    ui_made.number_value = None  # a task created in the KF UI without a jared number
    items = provider.list_open_items()
    assert [i.title for i in items] == ["numbered"]
    assert all(i.number != 0 for i in items)


def test_get_item_reseeds_index_on_cold_miss(tmp_path: Path) -> None:
    # Task exists on the board but the index is cold (never seeded). get_item
    # must reseed via a scan, find it, and leave the index populated.
    provider, client = _provider(tmp_path)
    client.create_task(name="preexisting", column_id="col-upnext", number_value=7)
    assert provider._index.get(7) is None
    item = provider.get_item(7)
    assert item is not None and item.number == 7
    assert provider._index.get(7) is not None


def _gtd_client() -> FakeKanbanFlowClient:
    """A board whose columns are NOT jared's canonical names."""
    from skills.jared.scripts.lib.kanbanflow_client import KfBoard, KfColumn, KfCustomFieldDef

    board = KfBoard(
        id="B1",
        name="GTD",
        columns=[
            KfColumn(unique_id="c-someday", name="Someday"),
            KfColumn(unique_id="c-soon", name="Planned Soon"),
            KfColumn(unique_id="c-now", name="Doing Now"),
            KfColumn(unique_id="c-blk", name="Blocked"),
            KfColumn(unique_id="c-complete", name="Complete"),  # Done renamed
        ],
    )
    fields = [
        KfCustomFieldDef(
            id="cf-priority",
            name="Priority",
            field_type="dropdown",
            dropdown_options=["High", "Medium", "Low"],
        ),
    ]
    return FakeKanbanFlowClient(board=board, field_defs=fields)


_GTD_MAP = {
    "Backlog": "Someday",
    "Up Next": "Planned Soon",
    "In Progress": "Doing Now",
    "Blocked": "Blocked",
    "Done": "Complete",
}


def test_status_map_move_writes_mapped_column(tmp_path: Path) -> None:
    client = _gtd_client()
    index = KfNumberIndex(tmp_path / "kf-index-B1.json")
    provider = KanbanFlowProvider(
        client=client,
        board=client.board,
        field_defs=client.field_defs,
        index=index,
        status_column_map=_GTD_MAP,
    )
    task = client.create_task(name="x", column_id="c-someday", number_value=5)
    provider._index.put(5, task.id)
    provider.move(5, "In Progress")
    assert client.get_task(task.id).column_id == "c-now"


def test_status_map_get_item_reports_canonical_status(tmp_path: Path) -> None:
    client = _gtd_client()
    index = KfNumberIndex(tmp_path / "kf-index-B1.json")
    provider = KanbanFlowProvider(
        client=client,
        board=client.board,
        field_defs=client.field_defs,
        index=index,
        status_column_map=_GTD_MAP,
    )
    task = client.create_task(name="x", column_id="c-now", number_value=6)
    provider._index.put(6, task.id)
    assert provider.get_item(6).status == "In Progress"  # type: ignore[union-attr]


def test_status_map_list_open_excludes_mapped_done(tmp_path: Path) -> None:
    # The regression guard: Done is mapped from "Complete". A task there must
    # be excluded from open items. An identity Done->Done fake would pass even
    # with the map unwired — this renamed-Done case is what proves the wiring.
    client = _gtd_client()
    index = KfNumberIndex(tmp_path / "kf-index-B1.json")
    provider = KanbanFlowProvider(
        client=client,
        board=client.board,
        field_defs=client.field_defs,
        index=index,
        status_column_map=_GTD_MAP,
    )
    client.create_task(name="done", column_id="c-complete", number_value=7)
    client.create_task(name="open", column_id="c-now", number_value=8)
    nums = {it.number for it in provider.list_open_items()}
    assert 8 in nums
    assert 7 not in nums


def test_expected_board_id_mismatch_warns(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    client = FakeKanbanFlowClient()
    index = KfNumberIndex(tmp_path / "kf-index-B1.json")
    KanbanFlowProvider(
        client=client,
        board=client.board,
        field_defs=client.field_defs,
        index=index,
        expected_board_id="some-other-board",
    )
    assert "some-other-board" in capsys.readouterr().err


def test_status_map_missing_mapped_column_raises_on_move(tmp_path: Path) -> None:
    client = _gtd_client()
    index = KfNumberIndex(tmp_path / "kf-index-B1.json")
    bad_map = dict(_GTD_MAP, Done="No Such Column")
    provider = KanbanFlowProvider(
        client=client,
        board=client.board,
        field_defs=client.field_defs,
        index=index,
        status_column_map=bad_map,
    )
    task = client.create_task(name="x", column_id="c-now", number_value=9)
    provider._index.put(9, task.id)
    with pytest.raises(FieldNotFound):
        provider.move(9, "Done")


# --- F3 (#371): reseed must detect collisions; allocation must read live state ---


class TestReseedCollisionDetection:
    """`kf_number_index.py`'s docstring promises that when two tasks end up
    sharing a jared #N, "a reseed scan + manual renumber repairs it". As
    implemented the reseed was a plain dict comprehension keyed by number, so
    one `_id` was silently and permanently dropped — nothing ever told the
    operator there was a collision to renumber.
    """

    def test_duplicate_numbers_are_reported_on_stderr(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        provider, client = _provider(tmp_path)
        client.create_task(name="first", column_id="col-backlog", number_value=7)
        client.create_task(name="second", column_id="col-backlog", number_value=7)

        provider._reseed_index()

        err = capsys.readouterr().err
        assert "7" in err
        assert "task-1" in err and "task-2" in err, err
        assert "renumber" in err.lower(), "the operator needs the remedy named"

    def test_a_clean_board_reports_nothing(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        provider, client = _provider(tmp_path)
        client.create_task(name="a", column_id="col-backlog", number_value=1)
        client.create_task(name="b", column_id="col-backlog", number_value=2)

        provider._reseed_index()

        assert capsys.readouterr().err == ""

    def test_the_winner_is_deterministic_not_iteration_order(self, tmp_path: Path) -> None:
        """Whichever task wins, it must be the same one on every reseed —
        otherwise #7 resolves to a different task run to run."""
        provider, client = _provider(tmp_path)
        client.create_task(name="first", column_id="col-backlog", number_value=7)
        client.create_task(name="second", column_id="col-backlog", number_value=7)

        provider._reseed_index()
        first_pass = provider._index.get(7)

        # Re-insert in the opposite order to change what iter_all_tasks yields first.
        client.tasks = dict(reversed(list(client.tasks.items())))
        provider._reseed_index()

        assert provider._index.get(7) == first_pass
        assert first_pass == "task-1", "lowest task id wins, by documented tie-break"

    def test_no_task_is_lost_from_the_report(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Three-way collision: every colliding id must be named, not just the
        winner and the last writer."""
        provider, client = _provider(tmp_path)
        for name in ("a", "b", "c"):
            client.create_task(name=name, column_id="col-backlog", number_value=4)

        provider._reseed_index()

        err = capsys.readouterr().err
        for task_id in ("task-1", "task-2", "task-3"):
            assert task_id in err, err


class TestNextNumberReadsLiveState:
    def test_allocation_sees_a_task_added_after_the_index_was_seeded(self, tmp_path: Path) -> None:
        """`_ensure_seeded` only reseeded when the index was *empty*, so a
        non-empty-but-stale index handed out a number already in use on the
        live board — the exact collision the docstring calls "last-writer-wins".
        """
        provider, client = _provider(tmp_path)
        first = provider.file(title="a", body="", priority="Low", status="Backlog")
        assert first.number == 1  # index is now non-empty

        # A task jared did not allocate appears on the board (another session,
        # a manual KanbanFlow edit, a concurrent `jared file`).
        client.create_task(name="external", column_id="col-backlog", number_value=99)

        second = provider.file(title="b", body="", priority="Low", status="Backlog")
        assert second.number == 100, "allocation must read the live board, not a stale index"

    def test_allocation_still_starts_at_one_on_an_empty_board(self, tmp_path: Path) -> None:
        provider, _ = _provider(tmp_path)
        assert provider.file(title="a", body="", priority="Low", status="Backlog").number == 1

    def test_reseed_does_not_drop_entries_for_live_tasks(self, tmp_path: Path) -> None:
        """`replace()` overwrites the map wholesale, so the reseed scan must be
        a complete superset of the board — otherwise fixing the stale-max bug
        would trade it for a dropped-entry bug."""
        provider, _ = _provider(tmp_path)
        a = provider.file(title="a", body="", priority="Low", status="Backlog")
        b = provider.file(title="b", body="", priority="Low", status="Backlog")

        provider._reseed_index()

        assert provider._index.get(a.number) is not None
        assert provider._index.get(b.number) is not None


class TestStaleIndexHit:
    """A stale index *hit* — distinct from the stale-max path `_next_number`
    now covers by reseeding unconditionally.

    `get_item` / `_resolve_id` reseed only on a index *miss*. If the index
    holds an entry whose task has since been renumbered in the KanbanFlow UI,
    `get(ref)` returns an id and no reseed happens, so jared reports one
    task's data under another task's number.
    """

    def test_get_item_does_not_report_a_renumbered_task_under_the_old_number(
        self, tmp_path: Path
    ) -> None:
        provider, client = _provider(tmp_path)
        item = provider.file(title="a", body="", priority="Low", status="Backlog")
        assert item.number == 1
        task_id = client.tasks[item.provider_ref or ""].id

        # Someone renumbers the task in the KanbanFlow UI. The on-disk index
        # still says 1 -> this task.
        client.tasks[task_id].number_value = 9
        assert provider._index.get(1) == task_id

        result = provider.get_item(1)

        assert result is None or result.number == 1, (
            f"get_item(1) returned #{result.number if result else None} — a stale index "
            f"hit reported another task's data under #1"
        )

    def test_get_item_finds_the_task_under_its_new_number(self, tmp_path: Path) -> None:
        provider, client = _provider(tmp_path)
        item = provider.file(title="a", body="", priority="Low", status="Backlog")
        task_id = client.tasks[item.provider_ref or ""].id
        client.tasks[task_id].number_value = 9

        found = provider.get_item(9)

        assert found is not None
        assert found.number == 9

    def test_a_fresh_index_hit_is_not_re_fetched_needlessly(self, tmp_path: Path) -> None:
        """The validation must not turn every read into a board scan — it uses
        the task `get_item` already fetched."""
        provider, _ = _provider(tmp_path)
        provider.file(title="a", body="", priority="Low", status="Backlog")

        item = provider.get_item(1)

        assert item is not None
        assert item.number == 1


class TestStaleIndexHitOnAWrite:
    """The write-path half of the same defect (#385, ledger F70).

    `TestStaleIndexHit` above covers the read path, which #371 could fix for
    free: `get_item` already fetched the task, so comparing `number_value` to
    the ref cost nothing. `_resolve_id` hands back an id *without* fetching, so
    every caller that goes through it inherits the stale-hit bug — the index
    says #1 -> task-1, the board says task-1 is now #9, and the write lands on
    task-1 regardless.

    These pin the corrected contract: a stale hit reseeds once, and a ref that
    still does not resolve raises `ItemNotFound` rather than writing.
    """

    def _numbered_task(
        self, tmp_path: Path
    ) -> tuple[KanbanFlowProvider, FakeKanbanFlowClient, str]:
        provider, client = _provider(tmp_path)
        item = provider.file(title="a", body="body-of-1", priority="Low", status="Backlog")
        assert item.number == 1
        task_id = client.tasks[item.provider_ref or ""].id
        return provider, client, task_id

    def test_a_write_does_not_land_on_a_renumbered_task(self, tmp_path: Path) -> None:
        provider, client, task_id = self._numbered_task(tmp_path)

        # Someone renumbers the task in the KanbanFlow UI. The on-disk index
        # still says 1 -> this task, and nothing on the board is #1 any more.
        client.tasks[task_id].number_value = 9
        assert provider._index.get(1) == task_id

        with pytest.raises(ItemNotFound):
            provider.move(1, "In Progress")

        assert client.tasks[task_id].column_id == "col-backlog", (
            "move(1) wrote to the task that is now #9 — a stale index hit routed "
            "the mutation to the wrong task"
        )

    def test_a_read_through_resolve_id_does_not_serve_a_renumbered_task(
        self, tmp_path: Path
    ) -> None:
        """`get_body` resolves through `_resolve_id` too, so it has the same hole.

        The issue body named six mutations; `_resolve_id` in fact has 13 call
        sites, two of which are reads that `get_item`'s own validation never
        covered.
        """
        provider, client, task_id = self._numbered_task(tmp_path)
        client.tasks[task_id].number_value = 9

        with pytest.raises(ItemNotFound):
            provider.get_body(1)

    def test_a_write_against_a_deleted_task_raises_item_not_found(self, tmp_path: Path) -> None:
        """The dangling shape must surface as the neutral exception.

        Before the fix the raw `KanbanFlowNotFoundError` escaped from the client
        through the provider, which the CLI's error handling does not catch —
        the two classes are unrelated (`KanbanFlowError` vs `Exception`).
        """
        provider, client, task_id = self._numbered_task(tmp_path)
        client.delete_task(task_id)
        assert provider._index.get(1) == task_id

        with pytest.raises(ItemNotFound):
            provider.move(1, "In Progress")

    def test_a_write_follows_a_renumbered_task_to_its_new_number(self, tmp_path: Path) -> None:
        """The reseed-and-retry success path: #9 resolves after one reseed."""
        provider, client, task_id = self._numbered_task(tmp_path)
        client.tasks[task_id].number_value = 9

        provider.move(9, "In Progress")

        assert client.tasks[task_id].column_id == "col-inprog"

    def test_a_write_costs_exactly_one_fetch(self, tmp_path: Path) -> None:
        """The price of the guard, pinned (#385 Option 1).

        `FakeKanbanFlowClient.get_task_calls` counts public fetches only — the
        fake's own writes go through `_require` — so this is the extra GET the
        validation adds, not the fake's bookkeeping. Verified against the
        unguarded code, where it read 0.
        """
        provider, client, _ = self._numbered_task(tmp_path)
        client.get_task_calls = 0

        provider.move(1, "In Progress")

        assert client.get_task_calls == 1

    def test_a_read_that_already_fetched_pays_nothing_extra(self, tmp_path: Path) -> None:
        """`get_body` and `get_item` reuse the validated task, so they stay flat.

        Validating inside `_resolve_id` alone would have made these two fetches
        each: one to validate, one to read. The resolution seam returns the task
        so the caller can reuse it.
        """
        provider, client, _ = self._numbered_task(tmp_path)

        client.get_task_calls = 0
        assert provider.get_body(1) == "body-of-1"
        assert client.get_task_calls == 1

        client.get_task_calls = 0
        item = provider.get_item(1)
        assert item is not None and item.number == 1
        assert client.get_task_calls == 1
