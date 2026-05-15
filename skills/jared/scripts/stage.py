#!/usr/bin/env python3
"""/jared-stage — continuous staging discipline.

Evaluates Backlog → Up Next promotion candidates and Blocked revisits.
Advisory: emits proposals to stdout; never applies changes itself.
The `commands/jared-stage.md` slash command wraps this script with
the operator approval flow.

See docs/superpowers/specs/2026-05-14-jared-stage-design.md for the
full design rationale.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class DeferredItem:
    """A Backlog item that was not promoted in this pass, with the reason why."""

    item: dict[str, Any]
    reason: str


@dataclass(frozen=True)
class StageProposals:
    """Result of one /jared-stage evaluation pass."""

    promotions: list[dict[str, Any]] = field(default_factory=list)
    deferred: list[DeferredItem] = field(default_factory=list)
    unblocked: list[dict[str, Any]] = field(default_factory=list)
    real_world_still_blocked: list[dict[str, Any]] = field(default_factory=list)
    almost_ready: list[dict[str, Any]] = field(default_factory=list)
