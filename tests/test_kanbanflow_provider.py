"""Unit tests for KanbanFlowProvider (Phase 3, #316). Faked client, no network."""

from __future__ import annotations

from pathlib import Path

import pytest

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
