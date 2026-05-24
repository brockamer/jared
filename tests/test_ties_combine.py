"""Tests for combine() — threshold, sort, cap, suggested-action mapping."""

from skills.jared.scripts.lib.ties import (
    OpenIssueForTies,
    SignalHit,
    combine,
)


def _hit(
    related_n: int,
    name: str,
    confidence: str = "strong",
    evidence: str = "",
) -> SignalHit:
    return SignalHit(
        related_n=related_n,
        name=name,  # type: ignore[arg-type]
        confidence=confidence,  # type: ignore[arg-type]
        evidence=evidence or f"{name} fired for #{related_n}",
    )


def _open_issues(*pairs: tuple[int, str]) -> list[OpenIssueForTies]:
    return [
        OpenIssueForTies(
            number=n,
            title=t,
            body="",
            labels=(),
            milestone=None,
            status="Backlog",
            priority="Medium",
            blocked_by=(),
        )
        for n, t in pairs
    ]


def _target() -> OpenIssueForTies:
    return OpenIssueForTies(
        number=1,
        title="target",
        body="",
        labels=(),
        milestone=None,
        status="In Progress",
        priority="High",
        blocked_by=(),
    )


class TestCombineThreshold:
    def test_single_strong_at_medium_surfaces(self) -> None:
        hits = [_hit(2, "milestone", "strong")]
        ties = combine(hits, "medium", _target(), _open_issues((2, "B")))
        assert len(ties) == 1

    def test_single_strong_at_strong_surfaces(self) -> None:
        hits = [_hit(2, "milestone", "strong")]
        ties = combine(hits, "strong", _target(), _open_issues((2, "B")))
        assert len(ties) == 1

    def test_two_weak_at_weak_surfaces(self) -> None:
        hits = [
            _hit(2, "title_tokens", "weak"),
            _hit(2, "labels", "weak"),
        ]
        ties = combine(hits, "weak", _target(), _open_issues((2, "B")))
        assert len(ties) == 1

    def test_two_weak_at_medium_does_not_surface(self) -> None:
        hits = [
            _hit(2, "title_tokens", "weak"),
            _hit(2, "labels", "weak"),
        ]
        ties = combine(hits, "medium", _target(), _open_issues((2, "B")))
        assert ties == []

    def test_medium_plus_weak_at_medium_surfaces(self) -> None:
        """combined = 2 + 1 = 3 ≥ 3."""
        hits = [
            _hit(2, "file_paths", "medium"),
            _hit(2, "labels", "weak"),
        ]
        ties = combine(hits, "medium", _target(), _open_issues((2, "B")))
        assert len(ties) == 1

    def test_medium_plus_weak_at_strong_does_not_surface(self) -> None:
        """combined = 3 but no strong-signal hit → fails strict-strong gate."""
        hits = [
            _hit(2, "file_paths", "medium"),
            _hit(2, "labels", "weak"),
        ]
        ties = combine(hits, "strong", _target(), _open_issues((2, "B")))
        assert ties == []


class TestCombineSortAndCap:
    def test_sort_by_combined_score_desc_then_number_asc(self) -> None:
        hits = [
            _hit(20, "milestone", "strong"),  # combined 3
            _hit(10, "milestone", "strong"),  # combined 3 (lower number first)
            _hit(30, "milestone", "strong"),
            _hit(30, "file_paths", "medium"),  # combined 5
        ]
        ties = combine(hits, "medium", _target(), _open_issues((10, "B"), (20, "C"), (30, "D")))
        assert [t.related_n for t in ties] == [30, 10, 20]

    def test_cap_at_8(self) -> None:
        hits = [_hit(n, "milestone", "strong") for n in range(2, 20)]  # 18 candidates
        issues = _open_issues(*[(n, f"I{n}") for n in range(2, 20)])
        ties = combine(hits, "medium", _target(), issues)
        assert len(ties) == 8


class TestCombineMultiRelationship:
    def test_primary_is_strongest_signal(self) -> None:
        hits = [
            _hit(2, "milestone", "strong"),
            _hit(2, "file_paths", "medium"),
        ]
        ties = combine(hits, "medium", _target(), _open_issues((2, "B")))
        assert ties[0].primary_relationship == "milestone-mate"
        assert "same-file" in ties[0].secondary_relationships

    def test_score_capped_at_max(self) -> None:
        hits = [
            _hit(2, "cross_ref", "strong"),
            _hit(2, "blocked_by", "strong"),
            _hit(2, "milestone", "strong"),
            _hit(2, "file_paths", "medium"),
            _hit(2, "title_tokens", "weak"),
            _hit(2, "labels", "weak"),
        ]
        ties = combine(hits, "weak", _target(), _open_issues((2, "B")))
        assert ties[0].combined_score == 5  # MAX_COMBINED_SCORE


class TestSuggestedAction:
    def test_blocked_by_target_blocks_related(self) -> None:
        target = OpenIssueForTies(
            number=1,
            title="t",
            body="",
            labels=(),
            milestone=None,
            status="In Progress",
            priority="High",
            blocked_by=(2,),
        )
        hits = [
            _hit(2, "blocked_by", "strong", evidence="target #1 is blocked by #2"),
        ]
        ties = combine(hits, "medium", target, _open_issues((2, "B")))
        assert "sequence" in ties[0].suggested_action.lower()

    def test_milestone_only_action(self) -> None:
        hits = [_hit(2, "milestone", "strong")]
        ties = combine(hits, "medium", _target(), _open_issues((2, "B")))
        assert "bundling" in ties[0].suggested_action.lower()

    def test_file_paths_action(self) -> None:
        hits = [_hit(2, "file_paths", "medium")]
        ties = combine(hits, "weak", _target(), _open_issues((2, "B")))
        assert "fold" in ties[0].suggested_action.lower()

    def test_blocked_by_target_unblocks_related(self) -> None:
        """Related is blocked by target — different action than target-blocked-by-related."""
        target = _target()  # target.blocked_by == ()
        hits = [
            _hit(2, "blocked_by", "strong", evidence="#2 is blocked by target #1"),
        ]
        ties = combine(hits, "medium", target, _open_issues((2, "B")))
        assert "unblocked" in ties[0].suggested_action.lower()
        assert "flag in PR" in ties[0].suggested_action


class TestCombineEdgeCases:
    def test_hit_referencing_unknown_related_n_is_dropped(self) -> None:
        """Race: hit references related_n that's not in open_issues — silently drop."""
        hits = [_hit(99, "milestone", "strong")]
        ties = combine(hits, "weak", _target(), _open_issues())
        assert ties == []


class TestCombineSignalPriority:
    """When multiple signals fire at the same confidence for one related_n,
    _SIGNAL_PRIORITY picks the primary — not analyzer call order. Structured-
    edge signals beat text-scrape signals."""

    def test_blocked_by_beats_cross_ref_when_both_strong(self) -> None:
        """Native blocked-by edge wins the primary tag over body cross-ref,
        regardless of which analyzer ran first. This is the canonical
        bug-#230 case: an issue with both a native blockedBy edge AND a
        body mention of the same blocker."""
        target = OpenIssueForTies(
            number=1,
            title="t",
            body="references #2",
            labels=(),
            milestone=None,
            status="In Progress",
            priority="High",
            blocked_by=(2,),
        )
        # Insert cross_ref FIRST to prove insertion order doesn't bind.
        hits = [
            _hit(2, "cross_ref", "strong", evidence="target #1 body mentions #2"),
            _hit(2, "blocked_by", "strong", evidence="target #1 is blocked by #2"),
        ]
        ties = combine(hits, "medium", target, _open_issues((2, "B")))
        assert ties[0].primary_relationship == "blocker"
        assert "cross-ref" in ties[0].secondary_relationships
        # Suggested action is blocker-flavored, not cross-ref-flavored.
        assert "sequence" in ties[0].suggested_action.lower()

    def test_blocked_by_beats_cross_ref_reverse_insertion_order(self) -> None:
        """Same as above but with blocked_by inserted FIRST — the result
        must still be blocked-by-primary. Guards against a regression where
        only stable-sort happens to put it first."""
        target = OpenIssueForTies(
            number=1,
            title="t",
            body="references #2",
            labels=(),
            milestone=None,
            status="In Progress",
            priority="High",
            blocked_by=(2,),
        )
        hits = [
            _hit(2, "blocked_by", "strong", evidence="target #1 is blocked by #2"),
            _hit(2, "cross_ref", "strong", evidence="target #1 body mentions #2"),
        ]
        ties = combine(hits, "medium", target, _open_issues((2, "B")))
        assert ties[0].primary_relationship == "blocker"

    def test_title_tokens_beats_labels_when_both_weak(self) -> None:
        """Priority axis is independent of confidence: when two weak signals
        fire for the same related_n, title_tokens (priority 4) beats labels
        (priority 5)."""
        hits = [
            _hit(2, "labels", "weak"),
            _hit(2, "title_tokens", "weak"),
        ]
        ties = combine(hits, "weak", _target(), _open_issues((2, "B")))
        assert ties[0].primary_relationship == "adjacent"
        # Both labels and title_tokens map to "adjacent"; primary's source
        # hit is the first sorted element, which should be title_tokens.
        assert ties[0].hits[0].name == "title_tokens"
