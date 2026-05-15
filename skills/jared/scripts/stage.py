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

import math
import re
from dataclasses import dataclass, field
from datetime import date, datetime
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

_PRIORITY_RANK = {"High": 0, "Medium": 1, "Low": 2}


def priority_rank(priority: str | None) -> int:
    """0=High, 1=Medium, 2=Low, 3=unknown/missing (sorts last)."""
    return _PRIORITY_RANK.get(priority or "", 3)


def milestone_proximity_days(item: dict[str, Any], *, today: date) -> float:
    """Days from `today` until item's milestone.due_on. No milestone or no
    due_on → math.inf (sorts last in tier).
    """
    milestone = item.get("milestone") or {}
    due_on = milestone.get("due_on") if isinstance(milestone, dict) else None
    if not due_on:
        return math.inf
    try:
        due_date = datetime.fromisoformat(due_on.replace("Z", "+00:00")).date()
    except (ValueError, AttributeError):
        return math.inf
    return float((due_date - today).days)


def days_in_backlog(item: dict[str, Any], *, today: date) -> int:
    """Days since item entered Status=Backlog.

    Fallback to (today - created_at).days when transition history isn't
    available — acceptable approximation since most items don't migrate
    columns repeatedly. See spec § Filter semantics.
    """
    created_at = item.get("createdAt") or item.get("created_at")
    if not created_at:
        return 0
    try:
        created_date = datetime.fromisoformat(created_at.replace("Z", "+00:00")).date()
    except (ValueError, AttributeError):
        return 0
    return (today - created_date).days


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


def deferred_reason(item: dict[str, Any], *, today: date) -> str:
    """One-line reason this Backlog item didn't make the slot cut.

    Picks the most-specific applicable signal. Output is advisory text,
    not a contract — implementation may refine the wording.
    """
    if priority_rank(item.get("priority")) == 2:
        return "Low tier"
    if milestone_proximity_days(item, today=today) == math.inf:
        return "no milestone with due date"
    return "ranked below slot cap"


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


def _format_milestone(item: dict[str, Any], *, today: date) -> str:
    milestone = item.get("milestone") or {}
    if not isinstance(milestone, dict):
        return "(no milestone)"
    title = milestone.get("title") or "(unknown)"
    due_on = milestone.get("due_on")
    if not due_on:
        return f"{title} (no due date)"
    try:
        due_date = datetime.fromisoformat(due_on.replace("Z", "+00:00")).date()
        delta = (due_date - today).days
        return f"{title} (due {due_date.isoformat()}, {delta}d)"
    except (ValueError, AttributeError):
        return f"{title} (no due date)"


def render(
    proposals: StageProposals,
    *,
    now: datetime,
    today: date | None = None,
    report_only: bool = False,
) -> str:
    """Format StageProposals as the stdout block documented in the spec."""
    if today is None:
        today = now.date()
    lines: list[str] = []
    lines.append(f"/jared-stage — proposals {now.strftime('%Y-%m-%d %H:%M')}")
    lines.append("")
    lines.append("== Backlog → Up Next ==")
    lines.append("")
    if proposals.promotions:
        lines.append("Promote:")
        for item in proposals.promotions:
            pri = item.get("priority", "?")
            title = item.get("title", "")
            lines.append(f"  #{item['number']} [{pri}] {title}")
            lines.append(f"        {_format_milestone(item, today=today)}")
    else:
        lines.append("(no promotions this pass)")
    lines.append("")
    if proposals.deferred:
        lines.append("Deferred (this pass):")
        for d in proposals.deferred:
            it = d.item
            lines.append(
                f"  #{it['number']} [{it.get('priority', '?')}] "
                f"{it.get('title', '')} — {d.reason}"
            )
        lines.append("")
    lines.append("== Blocked revisit ==")
    lines.append("")
    if proposals.unblocked:
        lines.append("Unblocked (propose moving to Backlog):")
        for it in proposals.unblocked:
            lines.append(f"  #{it['number']} {it.get('title', '')}")
    else:
        lines.append(
            "Unblocked: (none — all Blocked items still have open blockers"
            " or real-world annotations)"
        )
    lines.append("")
    if proposals.real_world_still_blocked:
        lines.append("Still Blocked, real-world annotation — check manually:")
        for it in proposals.real_world_still_blocked:
            lines.append(f"  #{it['number']} {it.get('title', '')}")
    lines.append("")
    lines.append("== Almost ready (advisory) ==")
    lines.append("")
    if proposals.almost_ready:
        lines.append("Pullable but blocked by open issue(s):")
        for it in proposals.almost_ready:
            lines.append(f"  #{it['number']} [{it.get('priority', '?')}] {it.get('title', '')}")
    else:
        lines.append("(none — no Backlog items have open native or body-ref blockers)")
    lines.append("")
    if not report_only:
        lines.append("──────────────────────────────────────────────────")
        lines.append("Approve? (y / <issue numbers> / skip)")
        lines.append("  y               apply all proposed promotions + unblocks")
        lines.append("  <numbers>       apply only those (e.g., \"y #1 #4\")")
        lines.append("  skip            apply nothing; output is record only")
    return "\n".join(lines)


def _count_status(items: list[dict[str, Any]], status: str) -> int:
    return sum(1 for i in items if i.get("status") == status)


def stage_proposals(
    items: list[dict[str, Any]],
    *,
    up_next_cap: int = 3,
    today: date,
) -> StageProposals:
    """Compute one /jared-stage evaluation pass over the given items.

    Pure function: no I/O. The caller (typically main()) fetches items
    via lib/board.py and passes them in.
    """
    slots_available = max(0, up_next_cap - _count_status(items, "Up Next"))
    backlog = [i for i in items if i.get("status") == "Backlog"]
    deferred: list[DeferredItem] = []

    pullable = [i for i in backlog if is_pullable(i)]
    not_pullable = [i for i in backlog if not is_pullable(i)]
    for item in not_pullable:
        deferred.append(DeferredItem(item, "not pullable — no acceptance criteria"))

    dep_ready = [i for i in pullable if has_no_open_blockers(i, items)]
    dep_blocked = [i for i in pullable if not has_no_open_blockers(i, items)]

    def rank_key(it: dict[str, Any]) -> tuple[int, float, int]:
        return (
            priority_rank(it.get("priority")),
            milestone_proximity_days(it, today=today),
            -days_in_backlog(it, today=today),
        )

    ranked = sorted(dep_ready, key=rank_key)
    promotions = ranked[:slots_available]
    for item in ranked[slots_available:]:
        deferred.append(DeferredItem(item, deferred_reason(item, today=today)))

    unblocked: list[dict[str, Any]] = []
    real_world_still_blocked: list[dict[str, Any]] = []
    for item in [i for i in items if i.get("status") == "Blocked"]:
        if not has_no_open_blockers(item, items):
            continue
        if has_real_world_annotation(item):
            real_world_still_blocked.append(item)
        else:
            unblocked.append(item)

    almost_ready = sorted(dep_blocked, key=rank_key)[:3]

    return StageProposals(
        promotions=promotions,
        deferred=deferred,
        unblocked=unblocked,
        real_world_still_blocked=real_world_still_blocked,
        almost_ready=almost_ready,
    )
