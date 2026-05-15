"""Unit tests for skills/jared/scripts/stage.py — /jared-stage eval engine."""

from __future__ import annotations

import math
from dataclasses import is_dataclass
from datetime import UTC, date, datetime
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

    def test_unknown_blocker_ref_treated_as_still_blocked(self) -> None:
        stage = import_stage()
        target = {"number": 1, "body": "Summary.\n", "blocked_by_native": [999]}
        # #999 not present in the items list — conservative: treat as still blocked.
        assert stage.has_no_open_blockers(target, self._items(target)) is False


class TestHasRealWorldAnnotation:
    def test_only_issue_refs_no_annotation(self) -> None:
        stage = import_stage()
        item = {"body": "Summary.\n\n## Blocked by\n\n#42, #51\n"}
        assert stage.has_real_world_annotation(item) is False

    def test_substantial_prose_is_annotation(self) -> None:
        stage = import_stage()
        item = {
            "body": (
                "Summary.\n\n"
                "## Blocked by\n\n"
                "Waiting on next non-trivial findajob session — no code change unblocks it.\n"
            )
        }
        assert stage.has_real_world_annotation(item) is True

    def test_short_text_after_stripping_refs_is_not_annotation(self) -> None:
        stage = import_stage()
        item = {"body": "Summary.\n\n## Blocked by\n\nWaiting on #42\n"}
        # "Waiting on " stripped of #42 = "Waiting on " — under 10 non-whitespace chars
        assert stage.has_real_world_annotation(item) is False

    def test_no_blocked_by_section_returns_false(self) -> None:
        stage = import_stage()
        item = {"body": "Summary.\n\n## Decisions\n\n(none)\n"}
        assert stage.has_real_world_annotation(item) is False


class TestRankingHelpers:
    def test_priority_rank_canonical_order(self) -> None:
        stage = import_stage()
        assert stage.priority_rank("High") == 0
        assert stage.priority_rank("Medium") == 1
        assert stage.priority_rank("Low") == 2

    def test_priority_rank_unknown_sorts_last(self) -> None:
        stage = import_stage()
        assert stage.priority_rank(None) == 3
        assert stage.priority_rank("") == 3
        assert stage.priority_rank("Whatever") == 3

    def test_milestone_proximity_days_with_future_due(self) -> None:
        stage = import_stage()
        future = date.today().toordinal() + 30
        future_iso = date.fromordinal(future).isoformat()
        item = {"milestone": {"due_on": f"{future_iso}T00:00:00Z"}}
        assert stage.milestone_proximity_days(item, today=date.today()) == 30

    def test_milestone_proximity_days_no_milestone(self) -> None:
        stage = import_stage()
        assert stage.milestone_proximity_days({}, today=date.today()) == math.inf

    def test_milestone_proximity_days_no_due_on(self) -> None:
        stage = import_stage()
        item = {"milestone": {"title": "Phase 2"}}
        assert stage.milestone_proximity_days(item, today=date.today()) == math.inf

    def test_days_in_backlog_uses_created_at_fallback(self) -> None:
        stage = import_stage()
        # Item created 14 days ago
        created = datetime.now(UTC).timestamp() - 14 * 86400
        item = {"createdAt": datetime.fromtimestamp(created, tz=UTC).isoformat()}
        days = stage.days_in_backlog(item, today=date.today())
        assert 13 <= days <= 15  # allow 1d slack for test timing
