"""Pullability classification — is a Backlog item ready to be worked?

Extracted from `stage.py` in #429 so more than one surface can ask the same
question and get the same answer. `stage.py` uses it to decide what to defer;
`sweep.py` uses it to emit the "Pullability gaps" section that `/jared-groom`
then offers to repair. One definition, one set of reason strings — a second
copy would drift, and the operator would see two different verdicts on one
item depending on which command they ran.

Leaf module: stdlib only. It never imports `board`, a provider, or anything
that touches the network, so any surface can pull it in without cost.

The judgement this module encodes is "pullable", from SKILL.md's discipline:
a real summary paragraph plus at least one substantive acceptance-criteria
bullet under the canonical heading. Epic-labeled issues are exempt — see
`is_epic`.
"""

from __future__ import annotations

import re
from typing import Any

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
_ACCEPTANCE_HEADING_ANY = re.compile(r"^##\s+Acceptance\b", re.MULTILINE)


def is_epic(item: dict[str, Any]) -> bool:
    """True if the item carries the `epic` label.

    Epic-labeled issues are durably parent-shaped — roadmaps, checklists,
    strategic anchors. They legitimately lack acceptance criteria and exist
    on Backlog as long-horizon containers, so /jared-stage exempts them from
    the "Deferred (this pass)" surface (#146), and /jared-groom's pullability
    sweep exempts them for the same reason (#429). See docs/project-board.md
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
