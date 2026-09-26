"""Live KanbanFlow capability + degradation verification (Phase 6, Task 11).

Acceptance gate: a real KanbanFlowProvider constructs against a live test
board, proves its board id, and advertises exactly
{MILESTONE_ASSIGNMENT} capabilities (#390). The degraded_or_none gate is also
exercised end-to-end — that path is network-free by design (Board.capabilities()
reads the static class attribute; it never constructs the provider or
calls the API).

Configuration is read at runtime and never committed. The token comes from
the environment only; the board ID comes from the environment or from the
gitignored tests/testbed.env (template: tests/testbed.env.example).

Run:
    export KANBANFLOW_API_TOKEN=<token> KANBANFLOW_TEST_BOARD_ID=<board-id>
    python -m pytest -m integration tests/test_kanbanflow_live.py -v
"""

from __future__ import annotations

import os
from pathlib import Path
from textwrap import dedent

import pytest


def _live_board_id() -> str:
    """KANBANFLOW_TEST_BOARD_ID from the environment, else from tests/testbed.env."""
    if board_id := os.environ.get("KANBANFLOW_TEST_BOARD_ID", "").strip():
        return board_id
    env_path = Path(__file__).parent / "testbed.env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            key, sep, value = line.strip().partition("=")
            if sep and key == "KANBANFLOW_TEST_BOARD_ID":
                return value.strip()
    return ""


LIVE_BOARD_ID = _live_board_id()

# ---------------------------------------------------------------------------
# Module-level skip guard — none of these tests run without the token and board ID.
# ---------------------------------------------------------------------------
pytestmark = pytest.mark.integration

_SKIP_NO_TOKEN = pytest.mark.skipif(
    not os.environ.get("KANBANFLOW_API_TOKEN") or not LIVE_BOARD_ID,
    reason="KANBANFLOW_API_TOKEN or KANBANFLOW_TEST_BOARD_ID not set",
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
# Test 1: live provider construction proves capabilities() == {MILESTONE_ASSIGNMENT}
# ---------------------------------------------------------------------------


@_SKIP_NO_TOKEN
def test_live_kanbanflow_provider_capabilities(tmp_path: Path) -> None:
    """Construct a real KanbanFlowProvider against the live board and assert:

    1. The provider is a KanbanFlowProvider (not a stub).
    2. The live board id matches LIVE_BOARD_ID — proves the token reached the configured board,
       not some other board or a short-circuit.
    3. capabilities() == {MILESTONE_ASSIGNMENT} — the static compile-time constant (#390).
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

    # Static capability set — MILESTONE_ASSIGNMENT only on KanbanFlow (#390).
    from skills.jared.scripts.lib.board_provider import Capability

    expected = frozenset({Capability.MILESTONE_ASSIGNMENT})
    got = provider.capabilities()
    assert got == expected, f"expected {expected!r}, got {got!r}"


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
    (a) Board.capabilities() == {MILESTONE_ASSIGNMENT} — parsed from the kanbanflow backend
        selector (#390 — the one capability KanbanFlow supports beyond the core board loop).
    (b) degraded_or_none returns a non-None note for VELOCITY_TIMESTAMPS.
    (c) The note contains "unavailable on kanbanflow" — the canonical phrasing.
    """
    from skills.jared.scripts.lib.board import Board
    from skills.jared.scripts.lib.board_provider import Capability
    from skills.jared.scripts.lib.capabilities import degraded_or_none

    board_md = _write_kf_board_fixture(tmp_path)
    board = Board.from_path(board_md)

    # (a) Static capability set — resolved from the backend selector, no API call.
    expected = frozenset({Capability.MILESTONE_ASSIGNMENT})
    assert board.capabilities() == expected, f"expected {expected!r}, got {board.capabilities()!r}"

    # (b)+(c) A gated surface degrades correctly.
    note = degraded_or_none(board, Capability.VELOCITY_TIMESTAMPS, "velocity", "skip velocity")
    assert note is not None, "expected a degradation note, got None"
    assert "unavailable on kanbanflow" in note, (
        f"expected 'unavailable on kanbanflow' in note, got {note!r}"
    )
