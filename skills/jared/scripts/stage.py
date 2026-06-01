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

import argparse
import math
import re
import sys
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

# Extend sys.path so `from lib.board import …` resolves when this script is
# loaded directly (CLI) or via SourceFileLoader in tests.  Mirrors the pattern
# used by sweep.py and dependency-graph.py.
_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from lib.board import Board  # type: ignore[import-not-found]  # noqa: E402
from lib.board import (  # noqa: E402
    fetch_blocked_by_edges as _fetch_blocked_by_edges,
)


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
# Capture the `## Acceptance criteria` section body up to the next `## ` (h2)
# heading or end-of-body. Wrapper-agnostic by design (#307): the `<details>`
# fold is a *display* convention (see design-rationale.md § "reference, not
# surface"), not a readiness signal. Readiness is "≥1 substantive bullet under
# the canonical heading" — whether or not the bullets sit inside `<details>`.
# `<details>`/`<summary>`/`</details>` lines don't start with `-`, so the
# bullet counter below ignores them naturally. The heading text stays canonical
# (`## Acceptance criteria`) — a short-form `## Acceptance` is still flagged
# non-canonical by not_pullable_reason.
_ACCEPTANCE_SECTION = re.compile(
    r"^##\s+Acceptance criteria\s*\n(.*?)(?=\n##(?!#)|\Z)",
    re.DOTALL | re.MULTILINE,
)
_BLOCKED_BY_SECTION = re.compile(r"##\s+Blocked by\s*\n(.*?)(?=\n##(?!#)|\Z)", re.DOTALL)
_ACCEPTANCE_HEADING_ANY = re.compile(r"^##\s+Acceptance\b", re.MULTILINE)
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
        # Key on the populated `status` field, not `content.state`: `gh project
        # item-list --format json` never populates `content.state` (see
        # sweep.py's cold-path note + #189/#223), so the closed-blocker signal
        # is its Done column placement. Assumes blockers reach Done via the
        # normal close→auto-Done flow; an issue closed entirely outside the
        # board would read as still-blocked, where the native blocked-by edge
        # `state` (dropped in fetch_items_for_stage) would be the authority.
        if blocker.get("status") != "Done":
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


def is_epic(item: dict[str, Any]) -> bool:
    """True if the item carries the `epic` label.

    Epic-labeled issues are durably parent-shaped — roadmaps, checklists,
    strategic anchors. They legitimately lack acceptance criteria and exist
    on Backlog as long-horizon containers, so /jared-stage exempts them from
    the "Deferred (this pass)" surface (#146). See docs/project-board.md
    `## Labels` for the convention.

    `labels` arrives from gh project item-list as a plain list of strings
    (top-level on the raw item; plumbed through fetch_items_for_stage).
    """
    labels = item.get("labels") or []
    return "epic" in labels


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
    # `"- "` (dash + space), not `"-"`: the wrapper-agnostic capture (#307) now
    # extends past `</details>` to the next `## ` heading, so it swallows the
    # template's trailing HTML comment. Its closing `-->` line starts with `-`
    # but has no space — requiring the space excludes it while still matching
    # every real bullet (`- text`, `- [ ] text`) and `- Criterion N`
    # placeholders (which the next clause rejects).
    real_bullets = [
        line.strip()
        for line in criteria_block.splitlines()
        if line.strip().startswith("- ") and not _PLACEHOLDER_CRITERIA.match(line)
    ]
    return len(real_bullets) >= 1


def not_pullable_reason(item: dict[str, Any]) -> str:
    """Classify why an item failed is_pullable. Mirrors is_pullable's checks.

    Surfaces the specific remediation each failure mode needs, so the smoke
    output doubles as a normalisation hint instead of a uniform "no acceptance
    criteria" line for every failure shape. Precondition: is_pullable(item)
    is False — callers filter first.
    """
    body = item.get("body", "") or ""
    if not body.strip():
        return "not pullable — empty body"

    first_para = body.split("\n\n", 1)[0].strip()
    if not first_para or first_para == _TEMPLATE_FIRST_PARA:
        return "not pullable — placeholder summary"

    if _ACCEPTANCE_SECTION.search(body):
        # Wrapper-agnostic since #307: the remediation is "add a real bullet",
        # not "wrap it" — the `<details>` fold is display tidiness, not a
        # readiness gate. Don't admonish about the wrapper here.
        return (
            "not pullable — acceptance section has no `-`-prefixed criterion bullets "
            "(numbered lists, prose, and `- Criterion N` placeholders don't count)"
        )

    if _ACCEPTANCE_HEADING_ANY.search(body):
        return (
            "not pullable — non-canonical acceptance heading; "
            "use the canonical '## Acceptance criteria'"
        )

    return "not pullable — no acceptance section"


def _format_milestone(item: dict[str, Any], *, today: date) -> str:
    """Render an item's milestone for the stage output line.

    Pre-#145 this function fell through to "(unknown) (no due date)" for items
    without a milestone — the exact string that triggered the original bug
    report. Now: None / empty-dict / non-dict all return "(no milestone)"
    honestly. Title-only and full milestones render their respective shapes.
    """
    milestone = item.get("milestone")
    if not isinstance(milestone, dict) or not milestone:
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
                f"  #{it['number']} [{it.get('priority', '?')}] {it.get('title', '')} — {d.reason}"
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
        lines.append('  <numbers>       apply only those (e.g., "y #1 #4")')
        lines.append("  skip            apply nothing; output is record only")
    return "\n".join(lines)


def _count_status(items: list[dict[str, Any]], status: str) -> int:
    return sum(1 for i in items if i.get("status") == status)


def stage_proposals(
    items: list[dict[str, Any]],
    *,
    up_next_cap: int = 8,
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
        if is_epic(item):
            # #146: epics are durably parent-shaped and stay in Backlog by
            # design; surfacing them as "deferred" every pass is noise.
            continue
        deferred.append(DeferredItem(item, not_pullable_reason(item)))

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


def _normalise_milestone(raw_milestone: Any) -> dict[str, Any] | None:
    """gh project item-list returns milestone as `{title, dueOn, description}`
    at the top level of each raw item. Normalise to `{title, due_on}` so
    stage.py's pure functions keep their existing snake_case access pattern.
    Items with no milestone come through as None.
    """
    if not isinstance(raw_milestone, dict):
        return None
    return {"title": raw_milestone.get("title"), "due_on": raw_milestone.get("dueOn")}


def fetch_items_for_stage(board: Any) -> list[dict[str, Any]]:
    """Fetch all open items from the board and normalise to stage.py's dict shape.

    Pure functions in this module take dicts with these keys:
      number, status, priority, title, body, milestone, createdAt,
      blocked_by_native (list[int]), labels (list[str]).

    `gh project item-list` returns most fields at the top level of each raw
    item — including `milestone`, `labels`, `status`, `priority`. The one
    exception is blocked-by edges, which need a separate paginated GraphQL
    pass via fetch_blocked_by_edges. Items with no content.number (draft
    cards, legacy entries) are skipped.
    """
    raw_items: list[dict[str, Any]] = board.board_items()
    if not raw_items:
        return []

    edges_map: dict[int, list[dict[str, Any]]] = _fetch_blocked_by_edges(board.repo)

    normalised: list[dict[str, Any]] = []
    for raw in raw_items:
        content: dict[str, Any] = raw.get("content") or {}
        number: int | None = content.get("number")
        if number is None:
            continue
        blocked_by_native: list[int] = [edge["number"] for edge in edges_map.get(number, [])]
        normalised.append(
            {
                "number": number,
                "status": raw.get("status"),
                "priority": raw.get("priority"),
                "title": content.get("title", ""),
                "body": content.get("body", ""),
                "milestone": _normalise_milestone(raw.get("milestone")),
                "createdAt": content.get("createdAt") or content.get("created_at"),
                "blocked_by_native": blocked_by_native,
                "labels": raw.get("labels") or [],
            }
        )
    return normalised


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="stage",
        description="Propose Backlog→Up Next promotions and Blocked revisits.",
    )
    parser.add_argument(
        "--report-only",
        action="store_true",
        help="Emit proposals only; suppress the 'Approve?' prompt (for scheduled fires).",
    )
    parser.add_argument(
        "--up-next-cap",
        type=int,
        default=8,
        help="Maximum items allowed in Up Next column (default: 8).",
    )
    args = parser.parse_args(argv)

    board = Board.from_default()
    items = fetch_items_for_stage(board)
    today = date.today()
    proposals = stage_proposals(items, up_next_cap=args.up_next_cap, today=today)
    now = datetime.now(UTC).astimezone()
    output = render(proposals, now=now, today=today, report_only=args.report_only)
    print(output)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
