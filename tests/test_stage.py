"""Unit tests for skills/jared/scripts/stage.py — /jared-stage eval engine."""

from __future__ import annotations

from dataclasses import is_dataclass
from typing import Any

from tests.conftest import import_stage


def test_stage_module_imports() -> None:
    stage = import_stage()
    assert stage is not None


def test_stage_proposals_dataclass_shape() -> None:
    stage = import_stage()
    assert is_dataclass(stage.StageProposals)
    assert is_dataclass(stage.DeferredItem)

    fields = {f.name for f in stage.StageProposals.__dataclass_fields__.values()}
    assert fields == {
        "promotions",
        "deferred",
        "unblocked",
        "real_world_still_blocked",
        "almost_ready",
    }


class TestIsPullable:
    def test_well_shaped_item_is_pullable(self) -> None:
        stage = import_stage()
        item = {
            "body": (
                "Real summary paragraph describing the work.\n\n"
                "## Acceptance criteria\n\n"
                "<details>\n<summary>Expand</summary>\n\n"
                "- Real criterion 1\n"
                "- Real criterion 2\n\n"
                "</details>"
            )
        }
        assert stage.is_pullable(item) is True

    def test_empty_body_is_not_pullable(self) -> None:
        stage = import_stage()
        assert stage.is_pullable({"body": ""}) is False

    def test_template_placeholder_first_para_is_not_pullable(self) -> None:
        stage = import_stage()
        item = {
            "body": (
                "One-sentence summary of what this issue is about and why it matters.\n\n"
                "## Acceptance criteria\n\n"
                "<details>\n<summary>Expand</summary>\n\n"
                "- Real criterion\n\n"
                "</details>"
            )
        }
        assert stage.is_pullable(item) is False

    def test_no_acceptance_criteria_section_is_not_pullable(self) -> None:
        stage = import_stage()
        item = {"body": "Real summary.\n\n## Decisions\n\n(none)\n"}
        assert stage.is_pullable(item) is False

    def test_placeholder_criteria_only_is_not_pullable(self) -> None:
        stage = import_stage()
        item = {
            "body": (
                "Real summary.\n\n"
                "## Acceptance criteria\n\n"
                "<details>\n<summary>Expand</summary>\n\n"
                "- Criterion 1\n"
                "- Criterion 2\n"
                "- Criterion 3\n\n"
                "</details>"
            )
        }
        assert stage.is_pullable(item) is False


class TestHasNoOpenBlockers:
    def _items(self, *defs: dict[str, Any]) -> list[dict[str, Any]]:
        return list(defs)

    def test_no_blockers_at_all(self) -> None:
        stage = import_stage()
        item = {"number": 1, "body": "Summary.\n", "blocked_by_native": []}
        assert stage.has_no_open_blockers(item, self._items(item)) is True

    def test_native_blocker_closed(self) -> None:
        stage = import_stage()
        target = {"number": 1, "body": "Summary.\n", "blocked_by_native": [2]}
        blocker = {"number": 2, "state": "CLOSED"}
        assert stage.has_no_open_blockers(target, self._items(target, blocker)) is True

    def test_native_blocker_open(self) -> None:
        stage = import_stage()
        target = {"number": 1, "body": "Summary.\n", "blocked_by_native": [2]}
        blocker = {"number": 2, "state": "OPEN"}
        assert stage.has_no_open_blockers(target, self._items(target, blocker)) is False

    def test_body_ref_blocker_open(self) -> None:
        stage = import_stage()
        target = {
            "number": 1,
            "body": "Summary.\n\n## Blocked by\n\nWaiting on #2.\n",
            "blocked_by_native": [],
        }
        blocker = {"number": 2, "state": "OPEN"}
        assert stage.has_no_open_blockers(target, self._items(target, blocker)) is False

    def test_body_ref_blocker_closed(self) -> None:
        stage = import_stage()
        target = {
            "number": 1,
            "body": "Summary.\n\n## Blocked by\n\nWaiting on #2.\n",
            "blocked_by_native": [],
        }
        blocker = {"number": 2, "state": "CLOSED"}
        assert stage.has_no_open_blockers(target, self._items(target, blocker)) is True

    def test_mixed_native_and_body_one_open(self) -> None:
        stage = import_stage()
        target = {
            "number": 1,
            "body": "Summary.\n\n## Blocked by\n\nWaiting on #3.\n",
            "blocked_by_native": [2],
        }
        b2 = {"number": 2, "state": "CLOSED"}
        b3 = {"number": 3, "state": "OPEN"}
        assert stage.has_no_open_blockers(target, self._items(target, b2, b3)) is False
