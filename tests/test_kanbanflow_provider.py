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


@pytest.mark.skip(reason="enable in Task 12 once all BoardProvider methods exist")
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
