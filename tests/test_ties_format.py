"""Golden output tests for format_ties_block()."""

from skills.jared.scripts.lib.ties import SignalHit, Tie, format_ties_block


def _tie(
    related_n: int,
    title: str = "Some related issue",
    *,
    confidence: str = "strong",
    primary: str = "cross-ref",
    secondaries: tuple[str, ...] = (),
    score: int = 3,
    action: str = "review for bundling vs separate",
) -> Tie:
    return Tie(
        related_n=related_n,
        related_title=title,
        related_status="Backlog",
        hits=(
            SignalHit(
                related_n=related_n,
                name="cross_ref",
                confidence=confidence,  # type: ignore[arg-type]
                evidence="",
            ),
        ),
        combined_score=score,
        primary_relationship=primary,
        secondary_relationships=secondaries,
        suggested_action=action,
    )


def test_empty_returns_empty_string() -> None:
    assert format_ties_block([], degraded=False, diagnostic=None) == ""


def test_single_tie_no_secondaries() -> None:
    out = format_ties_block(
        [_tie(212, primary="superseded", action="close as superseded after target ships")],
        degraded=False,
        diagnostic=None,
    )
    assert "Ties to consider:" in out
    assert "  #212 [strong, superseded]   close as superseded after target ships" in out
    assert "(Suggestions are heuristic — operator decides.)" in out


def test_tie_with_secondaries_shows_parenthetical() -> None:
    out = format_ties_block(
        [
            _tie(
                372,
                primary="adjacent",
                secondaries=("same-file",),
                action="bundling vs fast-follow — your call",
            )
        ],
        degraded=False,
        diagnostic=None,
    )
    assert "(also same-file)" in out


def test_tie_with_no_secondaries_no_parenthetical() -> None:
    out = format_ties_block(
        [_tie(212, primary="cross-ref")],
        degraded=False,
        diagnostic=None,
    )
    assert "(also" not in out


def test_degraded_mode_includes_diagnostic() -> None:
    out = format_ties_block(
        [_tie(212)],
        degraded=True,
        diagnostic="(low GraphQL budget — body-aware signals deferred)",
    )
    assert "(low GraphQL budget" in out


def test_diagnostic_only_no_ties() -> None:
    """When ties is empty but a diagnostic is set, render diagnostic alone."""
    out = format_ties_block(
        [],
        degraded=False,
        diagnostic="(GraphQL budget exhausted — ties analysis skipped)",
    )
    assert out == "(GraphQL budget exhausted — ties analysis skipped)"
