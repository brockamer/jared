from __future__ import annotations

from skills.jared.scripts.lib.board_provider import Capability
from skills.jared.scripts.lib.migrate import LossAxis, compute_loss_axes

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
