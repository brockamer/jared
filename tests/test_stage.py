"""Unit tests for skills/jared/scripts/stage.py — /jared-stage eval engine."""

from __future__ import annotations

import json
import math
from dataclasses import is_dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pytest

from tests.conftest import import_stage, patch_gh, patch_gh_by_arg, write_minimal_board


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

    def test_no_summary_details_shape_is_pullable(self) -> None:
        """`<details>` with no `<summary>` line at all. Real-world shape
        surfaced by findajob#679 and findajob#680 (2026-05-15) — #134."""
        stage = import_stage()
        item = {
            "body": (
                "Real summary paragraph describing the work.\n\n"
                "## Acceptance criteria\n\n"
                "<details>\n\n"
                "- Real criterion 1\n"
                "- Real criterion 2\n\n"
                "</details>"
            )
        }
        assert stage.is_pullable(item) is True

    def test_arbitrary_summary_text_is_pullable(self) -> None:
        """`<summary>` text other than the canonical `Expand` — e.g.
        `<summary>Acceptance criteria</summary>`. Real-world shape — #134."""
        stage = import_stage()
        item = {
            "body": (
                "Real summary paragraph describing the work.\n\n"
                "## Acceptance criteria\n\n"
                "<details>\n<summary>Acceptance criteria</summary>\n\n"
                "- Real criterion 1\n"
                "- Real criterion 2\n\n"
                "</details>"
            )
        }
        assert stage.is_pullable(item) is True

    def test_legacy_expand_summary_still_pullable(self) -> None:
        """Regression: the canonical `<summary>Expand</summary>` shape that
        `jared file` produces must continue to pass after the regex relaxation
        for #134."""
        stage = import_stage()
        item = {
            "body": (
                "Real summary paragraph describing the work.\n\n"
                "## Acceptance criteria\n\n"
                "<details>\n<summary>Expand</summary>\n\n"
                "- Real criterion 1\n\n"
                "</details>"
            )
        }
        assert stage.is_pullable(item) is True

    def test_unwrapped_canonical_ac_is_pullable(self) -> None:
        """#307: canonical `## Acceptance criteria` heading with substantive
        `-` bullets but NO `<details>` wrapper is pullable. This is the shape
        the 2026-06-01 audit filed (#299–#305) — readiness is the bullets,
        not the display fold."""
        stage = import_stage()
        item = {
            "body": (
                "Real summary paragraph describing the work.\n\n"
                "## Acceptance criteria\n"
                "- Real criterion 1\n"
                "- Real criterion 2\n\n"
                "## Effort / Confidence\nS · High\n"
            )
        }
        assert stage.is_pullable(item) is True

    def test_unwrapped_checkbox_ac_is_pullable(self) -> None:
        """#307: `- [ ]` checkbox bullets (start with `-`) count as real
        criteria, wrapper or not — the exact bullet style #299–#305 used."""
        stage = import_stage()
        item = {
            "body": (
                "Real summary.\n\n"
                "## Acceptance criteria\n"
                "- [ ] `find_priority_inversions` reads the project field.\n"
                "- [ ] `ruff` + `mypy --strict` clean.\n"
            )
        }
        assert stage.is_pullable(item) is True

    def test_unwrapped_placeholder_criteria_is_not_pullable(self) -> None:
        """#307: dropping the wrapper requirement must NOT let a fresh,
        unwrapped template body through — `- Criterion N` placeholders still
        fail."""
        stage = import_stage()
        item = {"body": ("Real summary.\n\n## Acceptance criteria\n- Criterion 1\n- Criterion 2\n")}
        assert stage.is_pullable(item) is False

    def test_unwrapped_prose_only_is_not_pullable(self) -> None:
        """#307: canonical heading + prose, no bullets, no wrapper → not
        pullable. Readiness still requires at least one real bullet."""
        stage = import_stage()
        item = {
            "body": (
                "Real summary.\n\n"
                "## Acceptance criteria\n"
                "Criteria will be concretized once dependencies land.\n"
            )
        }
        assert stage.is_pullable(item) is False

    def test_half_filled_real_template_is_not_pullable(self) -> None:
        """#307 regression guard: a body built from the real issue-body
        template with a written summary but UNTOUCHED placeholder AC must stay
        not-pullable. The wrapper-agnostic capture now extends past
        `</details>` to the next `## ` heading, swallowing the template's
        trailing HTML comment — whose closing `-->` line starts with `-`. If
        the bullet matcher counted it, a half-filled template would sneak onto
        Up Next. Built from the template verbatim so it tracks the real shape."""
        stage = import_stage()
        template = Path("skills/jared/assets/issue-body.md.template").read_text()
        # Write a real summary; leave the `- Criterion N` placeholders intact.
        body = template.replace(
            "One-sentence summary of what this issue is about and why it matters.",
            "Real summary describing genuine work to be done.",
        )
        assert stage.is_pullable({"body": body}) is False

    def test_unclosed_details_with_real_bullet_is_pullable(self) -> None:
        """#307: an unclosed `<details>` followed by a real criterion is now
        pullable — the AC section is bounded by the next `## ` heading / EOF,
        so the closing `</details>` is no longer load-bearing. This reverses
        #134's `test_unclosed_details_is_not_pullable`, which was an artifact
        of the old `<details>…</details>` delimiter approach."""
        stage = import_stage()
        item = {
            "body": (
                "Real summary.\n\n## Acceptance criteria\n\n<details>\n\n- Real criterion 1\n"
                # no closing </details>
            )
        }
        assert stage.is_pullable(item) is True


class TestNotPullableReason:
    """`not_pullable_reason` should give the operator a self-describing
    remediation hint per failure mode — not a uniform "no acceptance criteria"
    line. Covers each branch in order so a regression on one is caught locally."""

    def test_empty_body(self) -> None:
        stage = import_stage()
        assert stage.not_pullable_reason({"body": ""}) == "not pullable — empty body"

    def test_placeholder_summary(self) -> None:
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
        assert stage.not_pullable_reason(item) == "not pullable — placeholder summary"

    def test_placeholder_bullets(self) -> None:
        stage = import_stage()
        item = {
            "body": (
                "Real summary.\n\n"
                "## Acceptance criteria\n\n"
                "<details>\n<summary>Expand</summary>\n\n"
                "- Criterion 1\n"
                "- Criterion 2\n\n"
                "</details>"
            )
        }
        assert (
            stage.not_pullable_reason(item)
            == "not pullable — acceptance section has no `-`-prefixed criterion bullets "
            "(numbered lists, prose, and `- Criterion N` placeholders don't count)"
        )

    def test_numbered_list_bullets_fail(self) -> None:
        """`1.`/`2.`-prefixed bullets fail is_pullable — no `-` lines."""
        stage = import_stage()
        item = {
            "body": (
                "Real summary.\n\n"
                "## Acceptance criteria\n\n"
                "<details>\n<summary>Expand</summary>\n\n"
                "1. First criterion\n"
                "2. Second criterion\n\n"
                "</details>"
            )
        }
        assert stage.is_pullable(item) is False
        assert (
            stage.not_pullable_reason(item)
            == "not pullable — acceptance section has no `-`-prefixed criterion bullets "
            "(numbered lists, prose, and `- Criterion N` placeholders don't count)"
        )

    def test_prose_only_acceptance_fails(self) -> None:
        """Prose paragraph (no bullets at all) fails is_pullable."""
        stage = import_stage()
        item = {
            "body": (
                "Real summary.\n\n"
                "## Acceptance criteria\n\n"
                "<details>\n<summary>Expand</summary>\n\n"
                "Goals deferred until dependencies land; criteria will be concretized then.\n\n"
                "</details>"
            )
        }
        assert stage.is_pullable(item) is False
        assert (
            stage.not_pullable_reason(item)
            == "not pullable — acceptance section has no `-`-prefixed criterion bullets "
            "(numbered lists, prose, and `- Criterion N` placeholders don't count)"
        )

    def test_bullet_style_message_omits_wrapper_requirement(self) -> None:
        """#307: the wrong-bullet-style message must NOT prescribe a
        `<details>` wrapper. #195 originally required the message to restate
        the wrapper requirement (to stop a fixer dropping it); #307 decoupled
        readiness from the wrapper, so admonishing about it is now stale and
        misleading — the only remediation is a real `-` bullet."""
        stage = import_stage()
        item = {
            "body": (
                "Real summary.\n\n"
                "## Acceptance criteria\n\n"
                "<details>\n<summary>Expand</summary>\n\n"
                "1. First criterion\n"
                "2. Second criterion\n\n"
                "</details>"
            )
        }
        reason = stage.not_pullable_reason(item)
        assert "wrapper" not in reason
        assert "<details>" not in reason
        assert "`-`-prefixed criterion bullets" in reason

    def test_non_canonical_heading_short_form(self) -> None:
        """`## Acceptance` (no `criteria` suffix) is still non-canonical — the
        heading text stays a readiness requirement even though #307 dropped the
        `<details>` wrapper requirement. The remediation points at the heading."""
        stage = import_stage()
        item = {
            "body": ("Real summary.\n\n## Acceptance\n\n- Real criterion 1\n- Real criterion 2\n")
        }
        assert stage.is_pullable(item) is False
        reason = stage.not_pullable_reason(item)
        assert "non-canonical" in reason
        assert "## Acceptance criteria" in reason

    def test_no_acceptance_section_at_all(self) -> None:
        stage = import_stage()
        item = {"body": "Real summary.\n\n## Decisions\n\n(none)\n"}
        assert stage.not_pullable_reason(item) == "not pullable — no acceptance section"

    def test_prose_mention_of_acceptance_in_backticks_not_counted(self) -> None:
        """Backticked prose like `` `## Acceptance` `` must not trigger the
        non-canonical branch — only line-start headings do. Otherwise issue
        #131's own body (which discusses the variant in prose) would self-report
        as non-canonical."""
        stage = import_stage()
        item = {
            "body": (
                "Body mentions `## Acceptance` in prose, not as a heading.\n\n"
                "## Decisions\n\n(none)\n"
            )
        }
        assert stage.not_pullable_reason(item) == "not pullable — no acceptance section"


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
        # Closed blockers land in the Done column — `status`, not `content.state`,
        # is the populated signal (#298).
        blocker = {"number": 2, "status": "Done"}
        assert stage.has_no_open_blockers(target, self._items(target, blocker)) is True

    def test_native_blocker_open(self) -> None:
        stage = import_stage()
        target = {"number": 1, "body": "Summary.\n", "blocked_by_native": [2]}
        blocker = {"number": 2, "status": "In Progress"}
        assert stage.has_no_open_blockers(target, self._items(target, blocker)) is False

    def test_body_ref_blocker_open(self) -> None:
        stage = import_stage()
        target = {
            "number": 1,
            "body": "Summary.\n\n## Blocked by\n\nWaiting on #2.\n",
            "blocked_by_native": [],
        }
        blocker = {"number": 2, "status": "In Progress"}
        assert stage.has_no_open_blockers(target, self._items(target, blocker)) is False

    def test_body_ref_blocker_closed(self) -> None:
        stage = import_stage()
        target = {
            "number": 1,
            "body": "Summary.\n\n## Blocked by\n\nWaiting on #2.\n",
            "blocked_by_native": [],
        }
        blocker = {"number": 2, "status": "Done"}
        assert stage.has_no_open_blockers(target, self._items(target, blocker)) is True

    def test_mixed_native_and_body_one_open(self) -> None:
        stage = import_stage()
        target = {
            "number": 1,
            "body": "Summary.\n\n## Blocked by\n\nWaiting on #3.\n",
            "blocked_by_native": [2],
        }
        b2 = {"number": 2, "status": "Done"}
        b3 = {"number": 3, "status": "In Progress"}
        assert stage.has_no_open_blockers(target, self._items(target, b2, b3)) is False

    def test_unknown_blocker_ref_treated_as_still_blocked(self) -> None:
        stage = import_stage()
        target = {"number": 1, "body": "Summary.\n", "blocked_by_native": [999]}
        # #999 not present in the items list — conservative: treat as still blocked.
        assert stage.has_no_open_blockers(target, self._items(target)) is False

    def test_h3_subsection_blocker_still_counted(self) -> None:
        # Regression: the section-terminator lookahead must reject H3 (`\n###`)
        # so blockers nested under H3 sub-headings of `## Blocked by` are not
        # silently dropped. See #130.
        stage = import_stage()
        target = {
            "number": 1,
            "body": (
                "Summary.\n\n"
                "## Blocked by\n\n"
                "Foo #2.\n\n"
                "### Sub-context\n\n"
                "Bar #3.\n\n"
                "## Acceptance criteria\n\n"
                "- something\n"
            ),
            "blocked_by_native": [],
        }
        b2 = {"number": 2, "status": "Done"}
        b3 = {"number": 3, "status": "In Progress"}
        assert stage.has_no_open_blockers(target, self._items(target, b2, b3)) is False


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

    def test_annotation_only_inside_h3_subsection(self) -> None:
        # Regression: when prose annotation lives only inside an H3 sub-block,
        # the buggy regex truncates at the H3 and the heuristic returns False.
        # The fixed regex captures past the H3 so the annotation is detected.
        # See #130.
        stage = import_stage()
        item = {
            "body": (
                "Summary.\n\n"
                "## Blocked by\n\n"
                "#42\n\n"
                "### Context\n\n"
                "Waiting on the next non-trivial findajob session.\n\n"
                "## Acceptance criteria\n\n"
                "- something\n"
            )
        }
        assert stage.has_real_world_annotation(item) is True


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

    def test_format_milestone_renders_title_and_due_date(self) -> None:
        """#145: with a populated milestone, render `<title> (due YYYY-MM-DD, Nd)`."""
        stage = import_stage()
        item = {
            "milestone": {
                "title": "Phase 2 — perf settled",
                "due_on": "2026-05-31T00:00:00Z",
            }
        }
        result = stage._format_milestone(item, today=date(2026, 5, 16))
        assert result == "Phase 2 — perf settled (due 2026-05-31, 15d)"

    def test_format_milestone_no_milestone_returns_placeholder(self) -> None:
        stage = import_stage()
        result = stage._format_milestone({}, today=date(2026, 5, 16))
        assert result == "(no milestone)"

    def test_format_milestone_missing_due_on(self) -> None:
        """Title-only milestone (no due_on) renders title plus '(no due date)'."""
        stage = import_stage()
        item = {"milestone": {"title": "Unscheduled"}}
        result = stage._format_milestone(item, today=date(2026, 5, 16))
        assert result == "Unscheduled (no due date)"

    def test_format_milestone_missing_title(self) -> None:
        """Due_on-only milestone (no title) falls through to (unknown)."""
        stage = import_stage()
        item = {"milestone": {"due_on": "2026-05-31T00:00:00Z"}}
        result = stage._format_milestone(item, today=date(2026, 5, 16))
        assert result == "(unknown) (due 2026-05-31, 15d)"


class TestDeferredReason:
    def test_low_tier_reason(self) -> None:
        stage = import_stage()
        item = {"priority": "Low", "milestone": {"due_on": "2026-07-01T00:00:00Z"}}
        assert stage.deferred_reason(item, today=date.today()) == "Low tier"

    def test_no_milestone_reason(self) -> None:
        stage = import_stage()
        item = {"priority": "Medium"}
        assert stage.deferred_reason(item, today=date.today()) == "no milestone with due date"

    def test_below_slot_cap_reason(self) -> None:
        stage = import_stage()
        # Medium with a real milestone — only loses to age or slot cap
        item = {"priority": "Medium", "milestone": {"due_on": "2026-07-01T00:00:00Z"}}
        assert stage.deferred_reason(item, today=date.today()) == "ranked below slot cap"


def _item(
    *,
    number: int,
    status: str = "Backlog",
    priority: str = "Medium",
    title: str = "Test",
    body: str | None = None,
    milestone_due: str | None = "2026-07-01T00:00:00Z",
    created_days_ago: int = 7,
    blocked_by_native: list[int] | None = None,
    labels: list[str] | None = None,
) -> dict[str, Any]:
    """Build a stub item dict for stage_proposals tests."""
    default_body = (
        "Summary paragraph.\n\n"
        "## Acceptance criteria\n\n"
        "<details>\n<summary>Expand</summary>\n\n"
        "- Real criterion\n\n"
        "</details>"
    )
    created = datetime.now(UTC).timestamp() - created_days_ago * 86400
    return {
        "number": number,
        "status": status,
        "priority": priority,
        "title": title,
        "body": body if body is not None else default_body,
        "milestone": ({"due_on": milestone_due} if milestone_due else None),
        "createdAt": datetime.fromtimestamp(created, tz=UTC).isoformat(),
        "blocked_by_native": blocked_by_native or [],
        "labels": labels or [],
    }


class TestIsEpic:
    """#146: items with the `epic` label are durably parent-shaped — exempt
    from the not-pullable → Deferred surfacing."""

    def test_epic_labeled_item_is_epic(self) -> None:
        stage = import_stage()
        assert stage.is_epic({"labels": ["epic"]}) is True

    def test_epic_label_alongside_others(self) -> None:
        stage = import_stage()
        assert stage.is_epic({"labels": ["documentation", "epic"]}) is True

    def test_non_epic_labels_are_not_epic(self) -> None:
        stage = import_stage()
        assert stage.is_epic({"labels": ["enhancement"]}) is False
        assert stage.is_epic({"labels": ["bug"]}) is False

    def test_no_labels_is_not_epic(self) -> None:
        stage = import_stage()
        assert stage.is_epic({}) is False
        assert stage.is_epic({"labels": []}) is False

    def test_labels_none_is_not_epic(self) -> None:
        """Defensive: labels=None (e.g., absent from upstream) shouldn't crash."""
        stage = import_stage()
        assert stage.is_epic({"labels": None}) is False


class TestStageProposals:
    def test_empty_backlog_produces_empty_proposals(self) -> None:
        stage = import_stage()
        result = stage.stage_proposals([], up_next_cap=3, today=date.today())
        assert result.promotions == []
        assert result.deferred == []
        assert result.unblocked == []

    def test_three_pullable_dep_ready_items_promoted_to_full_cap(self) -> None:
        stage = import_stage()
        items = [
            _item(number=1, priority="High"),
            _item(number=2, priority="Medium"),
            _item(number=3, priority="Low"),
        ]
        result = stage.stage_proposals(items, up_next_cap=3, today=date.today())
        assert [p["number"] for p in result.promotions] == [1, 2, 3]
        assert result.deferred == []

    def test_priority_dominates_milestone(self) -> None:
        stage = import_stage()
        items = [
            _item(number=1, priority="Low", milestone_due="2026-06-01T00:00:00Z"),
            _item(number=2, priority="High", milestone_due="2027-01-01T00:00:00Z"),
        ]
        result = stage.stage_proposals(items, up_next_cap=1, today=date.today())
        assert result.promotions[0]["number"] == 2

    def test_milestone_proximity_breaks_priority_tie(self) -> None:
        stage = import_stage()
        items = [
            _item(number=1, priority="Medium", milestone_due="2027-01-01T00:00:00Z"),
            _item(number=2, priority="Medium", milestone_due="2026-06-01T00:00:00Z"),
        ]
        result = stage.stage_proposals(items, up_next_cap=1, today=date.today())
        assert result.promotions[0]["number"] == 2

    def test_up_next_full_yields_no_promotions(self) -> None:
        stage = import_stage()
        items = [
            _item(number=1, status="Up Next"),
            _item(number=2, status="Up Next"),
            _item(number=3, status="Up Next"),
            _item(number=4, status="Backlog", priority="High"),
        ]
        result = stage.stage_proposals(items, up_next_cap=3, today=date.today())
        assert result.promotions == []

    def test_unpullable_item_deferred_with_reason(self) -> None:
        stage = import_stage()
        items = [
            _item(number=1, body="Real summary.\n\n## Decisions\n\n(none)\n"),  # no ## Acceptance
        ]
        result = stage.stage_proposals(items, up_next_cap=3, today=date.today())
        assert result.promotions == []
        assert len(result.deferred) == 1
        assert result.deferred[0].item["number"] == 1
        assert result.deferred[0].reason == "not pullable — no acceptance section"

    def test_epic_labeled_unpullable_item_is_not_deferred(self) -> None:
        """#146: epic-labeled items legitimately lack acceptance criteria.

        They're durably parent-shaped (roadmaps, checklists, strategic
        anchors). The Deferred section should suppress them rather than
        re-reporting the same noise on every pass.
        """
        stage = import_stage()
        items = [
            _item(
                number=1,
                body="Roadmap parent issue.\n\n## Decisions\n\n(none)\n",  # no AC
                labels=["epic"],
            ),
        ]
        result = stage.stage_proposals(items, up_next_cap=3, today=date.today())
        assert result.deferred == []

    def test_epic_filter_doesnt_affect_pullable_items(self) -> None:
        """An epic-labeled item that happens to have AC still routes normally.

        We don't block promotion of epics with AC — the filter only suppresses
        them from the Deferred noise. If someone reshapes an epic into a
        pullable work unit, that's intentional and shouldn't be hidden.
        """
        stage = import_stage()
        items = [_item(number=1, priority="High", labels=["epic"])]
        result = stage.stage_proposals(items, up_next_cap=3, today=date.today())
        # Epic-labeled and pullable: still promoted normally.
        assert [p["number"] for p in result.promotions] == [1]
        assert result.deferred == []

    def test_non_epic_unpullable_item_still_deferred(self) -> None:
        """Regression guard: the epic filter must not over-fire on plain labels."""
        stage = import_stage()
        items = [
            _item(
                number=1,
                body="Real summary.\n\n## Decisions\n\n(none)\n",
                labels=["enhancement"],  # NOT an epic
            ),
        ]
        result = stage.stage_proposals(items, up_next_cap=3, today=date.today())
        assert len(result.deferred) == 1
        assert result.deferred[0].item["number"] == 1

    def test_blocked_item_with_closed_blocker_returns_to_backlog(self) -> None:
        stage = import_stage()
        items = [
            _item(number=1, status="Blocked", blocked_by_native=[2]),
            _item(number=2, status="Done"),
        ]
        result = stage.stage_proposals(items, up_next_cap=3, today=date.today())
        assert len(result.unblocked) == 1
        assert result.unblocked[0]["number"] == 1

    def test_blocked_item_with_real_world_annotation_stays_blocked(self) -> None:
        stage = import_stage()
        body = (
            "Summary.\n\n"
            "## Acceptance criteria\n\n<details>\n<summary>Expand</summary>\n\n"
            "- Real criterion\n\n</details>\n\n"
            "## Blocked by\n\nWaiting on next live findajob session.\n"
        )
        items = [_item(number=1, status="Blocked", body=body)]
        result = stage.stage_proposals(items, up_next_cap=3, today=date.today())
        assert result.unblocked == []
        assert len(result.real_world_still_blocked) == 1

    def test_almost_ready_surfaces_pullable_but_blocked(self) -> None:
        stage = import_stage()
        items = [
            _item(number=1, blocked_by_native=[2]),  # blocked by #2 (open)
            _item(number=2, status="In Progress"),  # blocker still open (not Done)
        ]
        result = stage.stage_proposals(items, up_next_cap=3, today=date.today())
        assert result.promotions == []
        assert len(result.almost_ready) == 1
        assert result.almost_ready[0]["number"] == 1


class TestRender:
    def test_render_empty_proposals_has_all_section_headers(self) -> None:
        stage = import_stage()
        result = stage.stage_proposals([], up_next_cap=3, today=date.today())
        out = stage.render(result, now=datetime(2026, 5, 14, 16, 45, tzinfo=UTC))
        # Every section header must be present even when its content is empty
        assert "/jared-stage — proposals 2026-05-14 16:45" in out
        assert "== Backlog → Up Next ==" in out
        assert "== Blocked revisit ==" in out
        assert "== Almost ready (advisory) ==" in out
        assert "Approve? (y / <issue numbers> / skip)" in out

    def test_render_promotion_shows_issue_metadata(self) -> None:
        stage = import_stage()
        items = [_item(number=42, priority="High", title="Add foo")]
        result = stage.stage_proposals(items, up_next_cap=3, today=date.today())
        out = stage.render(result, now=datetime(2026, 5, 14, 16, 45, tzinfo=UTC))
        assert "#42" in out
        assert "[High]" in out
        assert "Add foo" in out

    def test_render_deferred_shows_reason(self) -> None:
        stage = import_stage()
        items = [
            _item(number=1, priority="High"),
            _item(number=2, priority="High"),
            _item(number=3, priority="High"),
            _item(number=4, priority="Low"),  # deferred
        ]
        result = stage.stage_proposals(items, up_next_cap=3, today=date.today())
        out = stage.render(result, now=datetime(2026, 5, 14, 16, 45, tzinfo=UTC))
        assert "Deferred (this pass):" in out
        assert "#4" in out
        assert "Low tier" in out

    def test_render_report_only_omits_approve_prompt(self) -> None:
        stage = import_stage()
        result = stage.stage_proposals([], up_next_cap=3, today=date.today())
        out = stage.render(
            result,
            now=datetime(2026, 5, 14, 16, 45, tzinfo=UTC),
            report_only=True,
        )
        assert "Approve?" not in out


class TestFetchItemsForStage:
    def test_returns_items_with_status_priority_body_milestone(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Any
    ) -> None:
        """Milestone arrives at the top level of each raw item (#153).

        `gh project item-list --format json` returns `milestone` parallel to
        `content`, `status`, `priority`, `labels` — not nested inside `content`.
        The shape is `{title, dueOn, description}` (camelCase). stage.py
        normalises `dueOn` → `due_on` at the boundary so pure functions keep
        their snake_case access pattern.
        """
        write_minimal_board(tmp_path)
        monkeypatch.chdir(tmp_path)

        items_json = json.dumps(
            {
                "items": [
                    {
                        "content": {
                            "number": 1,
                            "title": "Test",
                            "body": "Summary.",
                            "createdAt": "2026-05-01T00:00:00Z",
                        },
                        "status": "Backlog",
                        "priority": "Medium",
                        "milestone": {
                            "title": "M1",
                            "dueOn": "2026-07-01T00:00:00Z",
                            "description": "first milestone",
                        },
                    },
                ]
            }
        )
        # fetch_blocked_by_edges → empty (no open blockers for issue #1).
        edges_json = json.dumps(
            {
                "data": {
                    "repository": {
                        "issues": {
                            "pageInfo": {"hasNextPage": False, "endCursor": None},
                            "nodes": [],
                        }
                    }
                }
            }
        )
        patch_gh_by_arg(
            monkeypatch,
            responses={"item-list": items_json, "blockedBy": edges_json},
        )

        stage = import_stage()
        from skills.jared.scripts.lib.board import Board

        board = Board.from_path(tmp_path / "docs" / "project-board.md")
        items = stage.fetch_items_for_stage(board)

        assert len(items) == 1
        assert items[0]["number"] == 1
        assert items[0]["status"] == "Backlog"
        assert items[0]["priority"] == "Medium"
        assert items[0]["body"] == "Summary."
        assert items[0]["milestone"] is not None
        assert items[0]["milestone"]["title"] == "M1"
        # dueOn normalised to snake_case due_on at the boundary.
        assert items[0]["milestone"]["due_on"] == "2026-07-01T00:00:00Z"
        # The extra `description` field is dropped — stage.py only consumes
        # title + due_on. Keep the contract minimal.
        assert "description" not in items[0]["milestone"]
        assert items[0]["blocked_by_native"] == []

    def test_items_with_no_milestone_have_milestone_none(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Any
    ) -> None:
        """When the raw item has no milestone key, the normalised item.milestone is None."""
        write_minimal_board(tmp_path)
        monkeypatch.chdir(tmp_path)

        items_json = json.dumps(
            {
                "items": [
                    {
                        "content": {
                            "number": 2,
                            "title": "Unmilestoned",
                            "body": "Summary.",
                            "createdAt": "2026-05-01T00:00:00Z",
                        },
                        "status": "Backlog",
                        "priority": "Low",
                    },
                ]
            }
        )
        empty_graphql = json.dumps(
            {
                "data": {
                    "repository": {
                        "issues": {
                            "pageInfo": {"hasNextPage": False, "endCursor": None},
                            "nodes": [],
                        }
                    }
                }
            }
        )
        patch_gh_by_arg(
            monkeypatch,
            responses={"item-list": items_json, "blockedBy": empty_graphql},
        )

        stage = import_stage()
        from skills.jared.scripts.lib.board import Board

        board = Board.from_path(tmp_path / "docs" / "project-board.md")
        items = stage.fetch_items_for_stage(board)

        assert len(items) == 1
        assert items[0]["milestone"] is None

    def test_done_blocker_reads_as_resolved_end_to_end(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Any
    ) -> None:
        """A just-closed blocker (Done column) must unblock its dependent (#298).

        Regression for the `content.state` family (#189/#223): `gh project
        item-list --format json` does NOT populate `content.state`, so the
        closed blocker's `content` block carries NO `state` key — `status:"Done"`
        at the top level is the only populated signal. This test feeds that
        realistic shape end-to-end through normalize → has_no_open_blockers;
        it fails on the pre-#298 code (Done blocker reads as still-open) and
        passes after keying resolution on `status`.
        """
        write_minimal_board(tmp_path)
        monkeypatch.chdir(tmp_path)

        # #1 is Blocked by #2; #2 is closed → sits in the Done column with NO
        # content.state key (the shape the live API actually returns).
        items_json = json.dumps(
            {
                "items": [
                    {
                        "content": {
                            "number": 1,
                            "title": "Dependent",
                            "body": "Summary.",
                            "createdAt": "2026-05-01T00:00:00Z",
                        },
                        "status": "Blocked",
                        "priority": "High",
                    },
                    {
                        "content": {
                            "number": 2,
                            "title": "Closed blocker",
                            "body": "Summary.",
                            "createdAt": "2026-05-01T00:00:00Z",
                        },
                        "status": "Done",
                        "priority": "High",
                    },
                ]
            }
        )
        # #1 (open) is blockedBy #2 via a native dependency edge.
        edges_json = json.dumps(
            {
                "data": {
                    "repository": {
                        "issues": {
                            "pageInfo": {"hasNextPage": False, "endCursor": None},
                            "nodes": [
                                {
                                    "number": 1,
                                    "blockedBy": {"nodes": [{"number": 2, "state": "CLOSED"}]},
                                },
                            ],
                        }
                    }
                }
            }
        )
        patch_gh_by_arg(
            monkeypatch,
            responses={"item-list": items_json, "blockedBy": edges_json},
        )

        stage = import_stage()
        from skills.jared.scripts.lib.board import Board

        board = Board.from_path(tmp_path / "docs" / "project-board.md")
        items = stage.fetch_items_for_stage(board)

        by_number = {i["number"]: i for i in items}
        assert by_number[1]["blocked_by_native"] == [2]
        assert stage.has_no_open_blockers(by_number[1], items) is True


class TestMain:
    def test_main_with_no_args_emits_proposals_block(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Any, capsys: Any
    ) -> None:
        write_minimal_board(tmp_path)
        monkeypatch.chdir(tmp_path)
        patch_gh(monkeypatch, stdout='{"items": []}')
        stage = import_stage()
        rc = stage.main([])
        captured = capsys.readouterr()
        assert rc == 0
        assert "/jared-stage — proposals" in captured.out
        assert "== Backlog → Up Next ==" in captured.out
        assert "Approve?" in captured.out  # interactive mode

    def test_main_report_only_omits_approve_prompt(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Any, capsys: Any
    ) -> None:
        write_minimal_board(tmp_path)
        monkeypatch.chdir(tmp_path)
        patch_gh(monkeypatch, stdout='{"items": []}')
        stage = import_stage()
        rc = stage.main(["--report-only"])
        captured = capsys.readouterr()
        assert rc == 0
        assert "Approve?" not in captured.out

    def test_main_up_next_cap_override(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Any, capsys: Any
    ) -> None:
        write_minimal_board(tmp_path)
        monkeypatch.chdir(tmp_path)
        patch_gh(monkeypatch, stdout='{"items": []}')
        stage = import_stage()
        rc = stage.main(["--up-next-cap", "5"])
        assert rc == 0
