from __future__ import annotations

from skills.jared.scripts.lib.board_provider import Capability, Edge
from skills.jared.scripts.lib.migrate import (
    LossAxis,
    MigrationLedger,
    NumberMap,
    compute_loss_axes,
    estimate_kf_calls,
    render_report,
    rewrite_cross_refs,
    translate_edges,
)

_FULL = frozenset(Capability)
_NONE: frozenset[Capability] = frozenset()


def test_github_to_kanbanflow_loss_axes() -> None:
    axes = compute_loss_axes(source_caps=_FULL, target_caps=_NONE, direction="github->kanbanflow")
    keys = {a.key for a in axes}
    # Capabilities present at source but absent at target each become a loss.
    assert "native_dependencies" in keys  # edges -> blocked-by:<N> label markers
    assert "milestone_state" in keys  # due-date + open/close dropped
    assert "closed_state" in keys
    assert "markdown_body" in keys
    # Renumber is NOT a loss in this direction (GH->KF preserves #N).
    assert "renumber" not in keys
    assert all(isinstance(a, LossAxis) and a.description for a in axes)


def test_kanbanflow_to_github_adds_renumber_axis() -> None:
    axes = compute_loss_axes(source_caps=_NONE, target_caps=_FULL, direction="kanbanflow->github")
    keys = {a.key for a in axes}
    # KF->GitHub renumbers (GitHub auto-assigns), so cross-refs need rewriting.
    assert "renumber" in keys
    # Capabilities the target ADDS are not losses.
    assert "milestone_state" not in keys


def test_number_map_identity_for_gh_to_kf() -> None:
    nm = NumberMap.identity([1, 2, 3])
    assert nm.to_new(2) == 2
    assert nm.keys() == {1, 2, 3}


def test_rewrite_cross_refs_only_touches_mapped_numbers() -> None:
    nm = NumberMap({10: 101, 11: 102})
    text = "Depends on #10 and #11, but #9999 is an external tracker ref."
    out = rewrite_cross_refs(text, nm)
    assert out == "Depends on #101 and #102, but #9999 is an external tracker ref."


def test_rewrite_cross_refs_is_word_boundaried() -> None:
    nm = NumberMap({1: 50})
    # '#10' must NOT be rewritten by the '#1' mapping (no partial-number match).
    assert rewrite_cross_refs("see #1 and #10", nm) == "see #50 and #10"


def test_translate_edges_through_number_map() -> None:
    nm = NumberMap({1: 101, 2: 102, 3: 103})
    edges = [Edge(dependent=2, blocker=1), Edge(dependent=3, blocker=2)]
    out = translate_edges(edges, nm)
    assert out == [Edge(dependent=102, blocker=101), Edge(dependent=103, blocker=102)]


def test_translate_edges_drops_unmapped() -> None:
    nm = NumberMap({2: 102})  # blocker 1 is unmapped
    assert translate_edges([Edge(dependent=2, blocker=1)], nm) == []


def test_estimate_kf_calls_counts_create_fields_edges_comments() -> None:
    # 2 items, each with 1 extra custom field beyond Priority; 1 edge; 3 comments.
    # create(1) + Priority(1) + extra-field(1) = 3 per item -> 6; +1 edge label; +3 comments = 10.
    n = estimate_kf_calls(item_count=2, extra_fields_per_item=1, edge_count=1, comment_count=3)
    assert n == 10


def test_render_report_lists_every_loss_and_estimate() -> None:
    axes = [LossAxis(key="renumber", description="reassigned", count=5)]
    text = render_report(
        direction="kanbanflow->github", item_count=5, axes=axes, kf_call_estimate=0
    )
    assert "kanbanflow->github" in text
    assert "5 items" in text
    assert "reassigned" in text


def test_ledger_round_trips_and_marks_completed() -> None:
    led = MigrationLedger(direction="github->kanbanflow")
    led.mark(old=1, new=1)
    led.mark(old=2, new=2)
    blob = led.to_json()
    back = MigrationLedger.from_json(blob)
    assert back.is_done(1) and back.is_done(2)
    assert not back.is_done(3)
    assert back.number_map().to_new(2) == 2


def test_ledger_tracks_second_pass_completion_separately_from_creation() -> None:
    """Creation (completed) and second-pass completion (ported/edges) are distinct.

    The second pass (body+comment portage, blocked-by edges) is NOT idempotent on
    a live backend — comment() duplicates on every replay. So the ledger records
    second-pass progress separately from creation, and that progress round-trips
    through JSON so a resume re-run skips already-ported items and already-applied
    edges. Creation tracking (completed/is_done/number_map) is untouched.
    """
    led = MigrationLedger(direction="github->kanbanflow")
    led.mark(old=1, new=1)
    led.mark(old=2, new=2)
    led.mark_ported(1)
    led.mark_edge(dependent=2, blocker=1)
    back = MigrationLedger.from_json(led.to_json())
    # Second-pass flags round-trip and are independent of creation.
    assert back.is_ported(1)
    assert not back.is_ported(2)
    assert back.is_edge_applied(dependent=2, blocker=1)
    assert not back.is_edge_applied(dependent=1, blocker=2)
    # Creation tracking is unchanged: both items are still "done" / mapped.
    assert back.is_done(1) and back.is_done(2)
    assert back.number_map().to_new(2) == 2


def test_ledger_from_json_defaults_second_pass_fields_empty() -> None:
    """A pre-4.x artifact (no ported/edges_applied keys) loads with both empty, so
    a resume against it runs the second pass exactly once (the regression guard for
    the existing skip-done-items resume test)."""
    blob = '{"direction": "github->kanbanflow", "completed": {"1": 1}, "losses": []}'
    back = MigrationLedger.from_json(blob)
    assert not back.is_ported(1)
    assert not back.is_edge_applied(dependent=1, blocker=1)
