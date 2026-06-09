"""Phase 6 — capability-aware degradation (epic #313).

The single consistency anchor: ONE note phrasing, ONE per-surface gate. CLI
subcommands and batch scripts read `board.capabilities()` (static, by backend)
and route every degradation through `degraded_or_none`, keyed per rendered
section. Prose surfaces (slash-command stubs, SKILL.md, references) do NOT call
this module — they branch on the `- backend:` bullet directly (spec Resolved
decision 1).

Leaf module: imports only `Capability` from board_provider, so it never
participates in the board.py <-> provider import cycle.
"""

from __future__ import annotations

from typing import Protocol

from .board_provider import Capability


class _CapBoard(Protocol):
    """The Board surface this module needs: a backend name + the static
    per-backend capability set. ``Board.capabilities()`` resolves it WITHOUT
    constructing the provider (which, on KanbanFlow, would make live API calls).
    """

    backend: str

    def capabilities(self) -> frozenset[Capability]: ...


def degraded_note(feature: str, instead: str, *, backend: str) -> str:
    """The single Phase-6 degradation phrasing (spec §33):

    ``degraded: <feature> unavailable on <backend> — <instead>``
    """
    return f"degraded: {feature} unavailable on {backend} — {instead}"


def degraded_or_none(
    board: _CapBoard,
    capability: Capability,
    feature: str,
    instead: str,
) -> str | None:
    """Return the degradation note when `capability` is absent, else None.

    The universal per-surface gate: callers print the note (or route it to
    stderr + exit nonzero for whole-scope-absent invocations) when this returns
    a string, and run their normal logic when it returns None.
    """
    if capability in board.capabilities():
        return None
    return degraded_note(feature, instead, backend=board.backend)
