"""Tests for individual signal analyzers."""

from skills.jared.scripts.lib.ties import (
    OpenIssueForTies,
    SignalHit,
    analyze_blocked_by,
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
