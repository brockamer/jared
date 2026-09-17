"""The one backend-neutral row source every batch surface consumes.

`sweep.py`, `stage.py`, `dependency-graph.py` and `jared audit fetch` each read
board rows as dicts (`i.get("status")`, `item["content"]["number"]`).
Historically each built those dicts from a GitHub call — `gh project item-list`
or `gh issue list` — which is why all four broke on a KanbanFlow board
(#386, #388, #389, #402).

This module is the seam: the provider returns neutral `BoardItem`s on either
backend, and `board_item_to_row` maps one to the dict shape the existing checks
already read. The checks are untouched; only their source changes. That is what
keeps GitHub output byte-identical through the migration.

Why a dict and not the dataclass: converting every check to `BoardItem` would
be a larger, riskier change with no user-visible benefit. YAGNI.

Precedent: `Board.fetch_open_issues_for_ties` already routes through
`provider.list_open_items()` under a capability gate (Phase 6). This
generalises that pattern to the remaining batch surfaces.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .board import Board
    from .board_provider import BoardItem


def board_item_to_row(item: BoardItem) -> dict[str, Any]:
    """Map a neutral BoardItem to the dict shape the batch checks read.

    `status` and `priority` stay `None` when absent. The metadata-completeness
    check distinguishes a missing value from a set one, so coercing to `""` or
    the string `"None"` would silently pass a defective item.

    Lists are copied, not aliased: the checks sort and filter rows in place.
    """
    row: dict[str, Any] = {
        "status": item.status,
        "priority": item.priority,
        "labels": list(item.labels),
        "milestone": item.milestone,
        "blocked_by": list(item.blocked_by),
        "content": {
            "number": item.number,
            "title": item.title,
            "body": item.body,
        },
    }
    # Custom single-selects sit at top level, lowercased — the casing
    # `sweep.field(item, "priority")` looks for and the casing
    # `BoardItem.fields` already uses. `setdefault` so a board with a custom
    # field named e.g. "status" cannot shadow the real Status column.
    for name, value in item.fields.items():
        row.setdefault(name, value)
    return row


def neutral_open_rows(board: Board) -> list[dict[str, Any]]:
    """Open board items as check-shaped rows, on any backend."""
    return [board_item_to_row(item) for item in board.provider.list_open_items()]


def board_item_to_issue(item: BoardItem) -> dict[str, Any]:
    """Map a neutral BoardItem to the `gh issue list --json` row shape.

    A second projection alongside `board_item_to_row`, for the surfaces that
    read issue rows rather than board rows: `dependency-graph.py` (#389) and
    `fetch_audit_window` (#402). Both were built around
    `gh issue list --json number,title,body,labels,state`.

    `labels` are dicts with a `name` key, matching what `gh` emits — audit
    passes them through verbatim to its consumers, so flattening them to
    bare strings here would be a GitHub-visible behaviour change.

    `state` is always "OPEN": every source feeding this is a list of open
    items. The key exists because the GitHub shape carries it.
    """
    return {
        "number": item.number,
        "title": item.title,
        "body": item.body,
        "labels": [{"name": name} for name in item.labels],
        "state": "OPEN",
        "milestone": item.milestone,
    }


def neutral_issue_rows(board: Board) -> list[dict[str, Any]]:
    """Open items as `gh issue list`-shaped rows, on any backend."""
    return [board_item_to_issue(item) for item in board.provider.list_open_items()]
