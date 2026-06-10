from skills.jared.scripts.lib.board_provider import Capability
from skills.jared.scripts.lib.capabilities import degraded_note, degraded_or_none


class _Board:
    def __init__(self, backend: str, caps: set[Capability]) -> None:
        self.backend = backend
        self._caps = caps

    def capabilities(self) -> frozenset[Capability]:
        return frozenset(self._caps)


def test_degraded_note_uses_the_canonical_phrasing() -> None:
    assert (
        degraded_note("aging checks", "no creation timestamps", backend="kanbanflow")
        == "degraded: aging checks unavailable on kanbanflow — no creation timestamps"
    )


def test_degraded_or_none_returns_note_when_capability_absent() -> None:
    board = _Board("kanbanflow", set())
    note = degraded_or_none(
        board, Capability.VELOCITY_TIMESTAMPS, "stale High Backlog", "no creation timestamps"
    )
    assert note == "degraded: stale High Backlog unavailable on kanbanflow — no creation timestamps"


def test_degraded_or_none_returns_none_when_capability_present() -> None:
    board = _Board("github", set(Capability))
    assert degraded_or_none(board, Capability.VELOCITY_TIMESTAMPS, "x", "y") is None
