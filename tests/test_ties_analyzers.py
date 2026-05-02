"""Tests for individual signal analyzers."""

from skills.jared.scripts.lib.ties import (
    OpenIssueForTies,
    SignalHit,
    analyze_blocked_by,
    analyze_milestone_overlap,
)


def _make_issue(
    number: int,
    *,
    title: str = "Title",
    body: str = "",
    labels: tuple[str, ...] = (),
    milestone: str | None = None,
    blocked_by: tuple[int, ...] = (),
) -> OpenIssueForTies:
    return OpenIssueForTies(
        number=number,
        title=title,
        body=body,
        labels=labels,
        milestone=milestone,
        status="Backlog",
        priority="Medium",
        blocked_by=blocked_by,
    )


class TestAnalyzeBlockedBy:
    def test_target_blocked_by_other_fires(self) -> None:
        target = _make_issue(1, blocked_by=(2,))
        others = [_make_issue(2)]
        hits = analyze_blocked_by(target, others)
        assert len(hits) == 1
        assert hits[0] == SignalHit(
            related_n=2,
            name="blocked_by",
            confidence="strong",
            evidence="target #1 is blocked by #2",
        )

    def test_other_blocked_by_target_fires(self) -> None:
        target = _make_issue(1)
        others = [_make_issue(2, blocked_by=(1,))]
        hits = analyze_blocked_by(target, others)
        assert len(hits) == 1
        assert hits[0] == SignalHit(
            related_n=2,
            name="blocked_by",
            confidence="strong",
            evidence="#2 is blocked by target #1",
        )

    def test_no_relationship_no_hit(self) -> None:
        target = _make_issue(1, blocked_by=(99,))
        others = [_make_issue(2, blocked_by=(98,))]
        hits = analyze_blocked_by(target, others)
        assert hits == []

    def test_self_is_never_a_hit(self) -> None:
        target = _make_issue(1, blocked_by=(1,))
        others = [_make_issue(1, blocked_by=(1,))]
        hits = analyze_blocked_by(target, others)
        assert hits == []

    def test_target_with_multiple_blockers(self) -> None:
        """All blockers in target.blocked_by produce hits — no short-circuit."""
        target = _make_issue(1, blocked_by=(2, 3))
        others = [_make_issue(2), _make_issue(3), _make_issue(4)]
        hits = analyze_blocked_by(target, others)
        related_ns = {h.related_n for h in hits}
        assert related_ns == {2, 3}


class TestAnalyzeMilestoneOverlap:
    def test_same_milestone_fires(self) -> None:
        target = _make_issue(1, milestone="v0.9 — soon")
        others = [_make_issue(2, milestone="v0.9 — soon")]
        hits = analyze_milestone_overlap(target, others)
        assert len(hits) == 1
        assert hits[0].related_n == 2
        assert hits[0].confidence == "strong"
        assert hits[0].name == "milestone"
        assert "v0.9 — soon" in hits[0].evidence

    def test_different_milestone_no_hit(self) -> None:
        target = _make_issue(1, milestone="v0.9 — soon")
        others = [_make_issue(2, milestone="v1.0 — GA")]
        hits = analyze_milestone_overlap(target, others)
        assert hits == []

    def test_target_no_milestone_no_hit(self) -> None:
        target = _make_issue(1, milestone=None)
        others = [_make_issue(2, milestone="v0.9 — soon")]
        hits = analyze_milestone_overlap(target, others)
        assert hits == []

    def test_both_no_milestone_no_hit(self) -> None:
        """None ≠ None for tie purposes — un-milestoned issues aren't ties."""
        target = _make_issue(1, milestone=None)
        others = [_make_issue(2, milestone=None)]
        hits = analyze_milestone_overlap(target, others)
        assert hits == []

    def test_self_is_never_a_hit(self) -> None:
        target = _make_issue(1, milestone="v0.9")
        others = [_make_issue(1, milestone="v0.9")]
        hits = analyze_milestone_overlap(target, others)
        assert hits == []
