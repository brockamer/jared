"""Unit tests for KanbanFlowProvider (Phase 3, #316). Faked client, no network."""

from __future__ import annotations

from pathlib import Path

import pytest

from skills.jared.scripts.lib.board import FieldNotFound, OptionNotFound
from skills.jared.scripts.lib.board_provider import BoardProvider
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


def test_capabilities_is_empty_frozenset(tmp_path: Path) -> None:
    provider, _ = _provider(tmp_path)
    assert provider.capabilities() == frozenset()


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


def test_recently_closed_is_empty_degraded(tmp_path: Path) -> None:
    provider, client = _provider(tmp_path)
    client.create_task(name="done", column_id="col-done", number_value=1)
    assert provider.recently_closed(days=7) == []


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
