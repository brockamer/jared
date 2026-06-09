from __future__ import annotations

from skills.jared.scripts.lib.board_provider import Capability
from skills.jared.scripts.lib.migrate import (
    LossAxis,
    NumberMap,
    compute_loss_axes,
    rewrite_cross_refs,
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
