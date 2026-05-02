"""Sanity tests for the ties module's dataclasses."""

import dataclasses

import pytest

from skills.jared.scripts.lib.ties import OpenIssueForTies, SignalHit, Tie


def test_signal_hit_constructs() -> None:
    hit = SignalHit(
        related_n=42,
        name="cross_ref",
        confidence="strong",
        evidence="target body mentions #42",
    )
    assert hit.related_n == 42
    assert hit.name == "cross_ref"
    assert hit.confidence == "strong"


def test_tie_constructs() -> None:
    hit = SignalHit(
        related_n=42,
        name="cross_ref",
        confidence="strong",
        evidence="target body mentions #42",
    )
    tie = Tie(
        related_n=42,
        related_title="Some related issue",
        related_status="Backlog",
        hits=(hit,),
        combined_score=3,
        primary_relationship="cross-ref",
        secondary_relationships=(),
        suggested_action="review for bundling vs separate",
    )
    assert tie.related_n == 42
    assert tie.combined_score == 3
    assert len(tie.hits) == 1


def test_open_issue_for_ties_constructs() -> None:
    issue = OpenIssueForTies(
        number=42,
        title="Some issue",
        body="Body text mentioning #99",
        labels=("enhancement",),
        milestone="v0.9 — soon",
        status="Backlog",
        priority="Medium",
        blocked_by=(),
    )
    assert issue.number == 42
    assert issue.labels == ("enhancement",)


def test_dataclasses_are_frozen() -> None:
    """Tie / SignalHit / OpenIssueForTies must be immutable for hashing / sets."""
    hit = SignalHit(
        related_n=1, name="cross_ref", confidence="strong", evidence=""
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        hit.related_n = 2  # type: ignore[misc]
