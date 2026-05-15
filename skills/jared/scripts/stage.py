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

import re
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


_TEMPLATE_FIRST_PARA = "One-sentence summary of what this issue is about and why it matters."
_PLACEHOLDER_CRITERIA = re.compile(r"^\s*-\s*Criterion\s*\d+\s*$", re.MULTILINE)
_ACCEPTANCE_SECTION = re.compile(
    r"##\s+Acceptance criteria\s*\n+<details>\s*\n+<summary>Expand</summary>(.*?)</details>",
    re.DOTALL,
)
_BLOCKED_BY_SECTION = re.compile(r"##\s+Blocked by\s*\n(.*?)(?=\n##|\Z)", re.DOTALL)
_ISSUE_REF = re.compile(r"#(\d+)")


def _blocker_refs(item: dict[str, Any]) -> set[int]:
    """Union of native edges + #N references parsed from ## Blocked by body section."""
    native: set[int] = set(item.get("blocked_by_native", []) or [])
    body = item.get("body", "") or ""
    section = _BLOCKED_BY_SECTION.search(body)
    body_refs: set[int] = set()
    if section:
        body_refs = {int(m.group(1)) for m in _ISSUE_REF.finditer(section.group(1))}
    return native | body_refs


def has_real_world_annotation(item: dict[str, Any]) -> bool:
    """True if `## Blocked by` body has substantive text after stripping #N refs.

    Heuristic: ≥10 non-whitespace characters remain after removing `#\\d+` matches.
    Surfaces patterns like #60's "waiting on next non-trivial findajob session"
    where the blocker is a real-world event, not another issue.
    """
    body = item.get("body", "") or ""
    section = _BLOCKED_BY_SECTION.search(body)
    if not section:
        return False
    stripped = _ISSUE_REF.sub("", section.group(1))
    non_whitespace = "".join(stripped.split())
    return len(non_whitespace) >= 10


def has_no_open_blockers(item: dict[str, Any], items: list[dict[str, Any]]) -> bool:
    """True if every blocker reference points to a closed (Done) issue."""
    refs = _blocker_refs(item)
    if not refs:
        return True
    by_number = {i["number"]: i for i in items if "number" in i}
    for ref in refs:
        blocker = by_number.get(ref)
        if blocker is None:
            # Unknown blocker reference — treat as still blocked (conservative).
            return False
        if blocker.get("state", "").upper() != "CLOSED":
            return False
    return True


def is_pullable(item: dict[str, Any]) -> bool:
    """An item is pullable if its body has a real summary + non-placeholder
    acceptance criteria. See spec § "Filter semantics"."""
    body = item.get("body", "") or ""
    if not body.strip():
        return False

    first_para = body.split("\n\n", 1)[0].strip()
    if not first_para or first_para == _TEMPLATE_FIRST_PARA:
        return False

    match = _ACCEPTANCE_SECTION.search(body)
    if not match:
        return False

    criteria_block = match.group(1)
    real_bullets = [
        line.strip()
        for line in criteria_block.splitlines()
        if line.strip().startswith("-") and not _PLACEHOLDER_CRITERIA.match(line)
    ]
    return len(real_bullets) >= 1
