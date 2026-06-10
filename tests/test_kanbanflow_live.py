"""Live KanbanFlow capability + degradation verification (Phase 6, Task 11).

Acceptance gate: a real KanbanFlowProvider constructs against the live
"Jared Test" board (p9vK6cR), proves its board id, and advertises
frozenset() capabilities. The degraded_or_none gate is also exercised
end-to-end — that path is network-free by design (Board.capabilities()
reads the static class attribute; it never constructs the provider or
calls the API).

Run:
    set -a; source ~/.secrets; set +a
    python -m pytest -m integration tests/test_kanbanflow_live.py -v
"""

from __future__ import annotations

import os
from pathlib import Path
from textwrap import dedent

import pytest

LIVE_BOARD_ID = "p9vK6cR"

# ---------------------------------------------------------------------------
# Module-level skip guard — none of these tests run without the token.
# ---------------------------------------------------------------------------
pytestmark = pytest.mark.integration

_SKIP_NO_TOKEN = pytest.mark.skipif(
    not os.environ.get("KANBANFLOW_API_TOKEN"),
    reason="KANBANFLOW_API_TOKEN not set",
)


def _write_kf_board_fixture(tmp_path: Path) -> Path:
    """Write a minimal KanbanFlow-backed docs/project-board.md to tmp_path."""
    board_md = tmp_path / "docs" / "project-board.md"
    board_md.parent.mkdir(parents=True)
    board_md.write_text(
        dedent(f"""\
        ## Jared config
        - backend: kanbanflow

        - Repo: brockamer/jared
        - Board ID: {LIVE_BOARD_ID}
        - Board URL: https://kanbanflow.com/board/{LIVE_BOARD_ID}

        ### Status column map
        - Backlog: Planned One Day
        - Up Next: Planned This Week
        - In Progress: Doing Now
        - Blocked: Blocked
        - Done: Done
        """)
    )
    return board_md


# ---------------------------------------------------------------------------
# Test 1: live provider construction proves capabilities() == frozenset()
# ---------------------------------------------------------------------------


@_SKIP_NO_TOKEN
def test_live_kanbanflow_provider_capabilities(tmp_path: Path) -> None:
    """Construct a real KanbanFlowProvider against the live board and assert:

    1. The provider is a KanbanFlowProvider (not a stub).
    2. The live board id matches LIVE_BOARD_ID — proves the token reached p9vK6cR,
       not some other board or a short-circuit.
    3. capabilities() == frozenset() — the static compile-time constant.
    """
    from skills.jared.scripts.lib.board import Board
    from skills.jared.scripts.lib.kanbanflow_provider import KanbanFlowProvider

    board_md = _write_kf_board_fixture(tmp_path)
    board = Board.from_path(board_md)

    # Trigger provider construction — makes live get_board() + list_custom_field_defs() calls.
    provider = board.provider

    assert isinstance(provider, KanbanFlowProvider), (
        f"expected KanbanFlowProvider, got {type(provider)}"
    )

    # This is the load-bearing live-proof assertion:
    # if the token resolves a different board the id won't match.
    assert provider._board.id == LIVE_BOARD_ID, (
        f"expected board id '{LIVE_BOARD_ID}', got '{provider._board.id}'"
    )

    # Static capability set — empty on KanbanFlow.
    assert provider.capabilities() == frozenset(), (
        f"expected frozenset(), got {provider.capabilities()!r}"
    )


# ---------------------------------------------------------------------------
# Test 2: end-to-end degraded surface via Board (network-free path)
# ---------------------------------------------------------------------------


@_SKIP_NO_TOKEN
def test_live_kanbanflow_degraded_surface_network_free(tmp_path: Path) -> None:
    """Exercise a real gated surface via Board.capabilities() + degraded_or_none.

    Board.capabilities() resolves the static per-backend constant WITHOUT
    constructing the provider — making no live API calls. This test is therefore
    network-free by design: the token env-var is required only so this test
    travels with the live integration suite (it would pass with any non-empty
    token string), but it makes no HTTP request.

    Asserts:
    (a) Board.capabilities() == frozenset() — parsed from the kanbanflow backend selector.
    (b) degraded_or_none returns a non-None note for VELOCITY_TIMESTAMPS.
    (c) The note contains "unavailable on kanbanflow" — the canonical phrasing.
    """
    from skills.jared.scripts.lib.board import Board
    from skills.jared.scripts.lib.board_provider import Capability
    from skills.jared.scripts.lib.capabilities import degraded_or_none

    board_md = _write_kf_board_fixture(tmp_path)
    board = Board.from_path(board_md)

    # (a) Static capability set — resolved from the backend selector, no API call.
    assert board.capabilities() == frozenset(), (
        f"expected frozenset(), got {board.capabilities()!r}"
    )

    # (b)+(c) A gated surface degrades correctly.
    note = degraded_or_none(board, Capability.VELOCITY_TIMESTAMPS, "velocity", "skip velocity")
    assert note is not None, "expected a degradation note, got None"
    assert "unavailable on kanbanflow" in note, (
        f"expected 'unavailable on kanbanflow' in note, got {note!r}"
    )
