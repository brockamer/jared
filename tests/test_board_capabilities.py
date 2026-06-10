from skills.jared.scripts.lib.board import Board
from skills.jared.scripts.lib.board_provider import Capability


def _board(backend: str) -> Board:
    b = Board.__new__(Board)  # bypass __init__; capabilities() only reads .backend
    b.backend = backend
    return b


def test_github_advertises_full_capability_set() -> None:
    assert _board("github").capabilities() == frozenset(Capability)


def test_kanbanflow_advertises_empty_capability_set() -> None:
    # Resolved offline — no KANBANFLOW_API_TOKEN, no network.
    assert _board("kanbanflow").capabilities() == frozenset()
