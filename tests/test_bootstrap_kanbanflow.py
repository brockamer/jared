"""Unit tests for the KanbanFlow bootstrap path (Phase 4, #317)."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest
from _pytest.monkeypatch import MonkeyPatch

from skills.jared.scripts.lib.kanbanflow_client import KfBoard, KfColumn, KfCustomFieldDef


def _load_bootstrap() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "bootstrap_project", Path("skills/jared/scripts/bootstrap-project.py")
    )
    assert spec is not None
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def _gtd_board() -> KfBoard:
    return KfBoard(
        id="p9vK6cR",
        name="Jared Test",
        columns=[
            KfColumn(unique_id="c1", name="Maybe Never?"),
            KfColumn(unique_id="c2", name="Planned One Day"),
            KfColumn(unique_id="c3", name="Planned This Week"),
            KfColumn(unique_id="c4", name="Will Do Today"),
            KfColumn(unique_id="c5", name="Doing Now"),
            KfColumn(unique_id="c6", name="Blocked"),
            KfColumn(unique_id="c7", name="Done"),
        ],
    )


def test_map_status_columns_auto_and_interview(monkeypatch: MonkeyPatch) -> None:
    b = _load_bootstrap()
    answers = iter(["Planned One Day", "Planned This Week", "Doing Now"])
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(answers))
    mapping, unmapped = b.map_status_columns(_gtd_board())
    assert mapping == {
        "Backlog": "Planned One Day",
        "Up Next": "Planned This Week",
        "In Progress": "Doing Now",
        "Blocked": "Blocked",
        "Done": "Done",
    }
    assert set(unmapped) == {"Maybe Never?", "Will Do Today"}


def test_validate_priority_field_missing_hard_stops() -> None:
    b = _load_bootstrap()
    with pytest.raises(SystemExit):
        b.validate_priority_field([])


def test_validate_priority_field_present_ok() -> None:
    b = _load_bootstrap()
    defs = [
        KfCustomFieldDef(
            id="x",
            name="Priority",
            field_type="dropdown",
            dropdown_options=["High", "Medium", "Low"],
        )
    ]
    b.validate_priority_field(defs)  # no raise


def test_render_kanbanflow_doc_shape() -> None:
    b = _load_bootstrap()
    doc = b.render_kanbanflow_doc(
        board=_gtd_board(),
        repo="brockamer/jared",
        status_map={
            "Backlog": "Planned One Day",
            "Up Next": "Planned This Week",
            "In Progress": "Doing Now",
            "Blocked": "Blocked",
            "Done": "Done",
        },
    )
    assert "- backend: kanbanflow" in doc
    assert "### Status column map" in doc
    assert "- In Progress: Doing Now" in doc
    assert "- Board ID: p9vK6cR" in doc
    # Secrets stay in env: the doc documents the env-var NAME as guidance, and
    # render_kanbanflow_doc never receives the token value, so it cannot leak it.
    assert "KANBANFLOW_API_TOKEN" in doc


def test_map_status_columns_out_of_range_number_hard_stops(monkeypatch: MonkeyPatch) -> None:
    b = _load_bootstrap()
    # First interview prompt is Backlog; the GTD board offers 5 unmapped choices,
    # so "9" is out of range and must hard-stop rather than IndexError.
    monkeypatch.setattr("builtins.input", lambda _prompt="": "9")
    with pytest.raises(SystemExit):
        b.map_status_columns(_gtd_board())


def test_map_status_columns_zero_number_hard_stops(monkeypatch: MonkeyPatch) -> None:
    b = _load_bootstrap()
    # "0" must hard-stop, NOT silently select choices[-1] (the old bug).
    monkeypatch.setattr("builtins.input", lambda _prompt="": "0")
    with pytest.raises(SystemExit):
        b.map_status_columns(_gtd_board())


def test_map_status_columns_non_interactive_unmapped_hard_stops() -> None:
    b = _load_bootstrap()
    # GTD board: only Blocked/Done auto-map; Backlog/Up Next/In Progress need the
    # interview, so a non-interactive (--yes) run must fail cleanly, not EOFError.
    with pytest.raises(SystemExit):
        b.map_status_columns(_gtd_board(), assume_yes=True)


def test_map_status_columns_non_interactive_canonical_ok() -> None:
    from tests.fake_kanbanflow import FakeKanbanFlowClient

    b = _load_bootstrap()
    # A board whose columns ARE the canonical names auto-maps fully -> no interview
    # needed -> assume_yes succeeds.
    mapping, unmapped = b.map_status_columns(FakeKanbanFlowClient().board, assume_yes=True)
    assert mapping == {s: s for s in ("Backlog", "Up Next", "In Progress", "Blocked", "Done")}
    assert unmapped == []


def test_map_status_columns_free_text_collision_hard_stops(monkeypatch: MonkeyPatch) -> None:
    b = _load_bootstrap()
    # Backlog -> "Doing Now", then Up Next -> "Doing Now" again (already used) must hard-stop.
    answers = iter(["Doing Now", "Doing Now"])
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(answers))
    with pytest.raises(SystemExit):
        b.map_status_columns(_gtd_board())
