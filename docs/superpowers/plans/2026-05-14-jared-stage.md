# /jared-stage Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement `/jared-stage`, an advisory + scheduled command that proposes Backlog → Up Next promotions and Blocked revisits, per `docs/superpowers/specs/2026-05-14-jared-stage-design.md` (issue #128).

**Architecture:** New batch script `skills/jared/scripts/stage.py` computes proposals via pure functions; slash command `commands/jared-stage.md` wraps it with an operator approval flow; applies via existing `jared move` CLI subcommand. TDD throughout — pure functions get unit tests in `tests/test_stage.py`.

**Tech Stack:** Python 3.11+, pytest, ruff, mypy --strict, gh CLI via `skills/jared/scripts/lib/board.py`.

---

## File Structure

**Created:**
- `skills/jared/scripts/stage.py` — eval logic + rendering + CLI entry (~300 lines)
- `commands/jared-stage.md` — slash command wrapper (~80 lines)
- `tests/test_stage.py` — unit tests (~200 lines)

**Modified (light):**
- `tests/conftest.py` — add `import_stage()` loader helper (~10 lines added)
- `skills/jared/SKILL.md` — § "Staging" subsection under existing "Periodically — groom" (~15 lines added)
- `skills/jared/references/board-sweep.md` — one-paragraph cross-reference to staging (~5 lines)
- `commands/jared-wrap.md` — optional "see also" line (~2 lines)

**Versioning:** Release as v0.15.0 (minor bump — additive feature, no breaking changes).

---

## Phase 1: Test infrastructure + data model

### Task 1.1: Add `import_stage()` to conftest.py

**Files:**
- Modify: `tests/conftest.py`

- [ ] **Step 1: Read conftest.py to confirm location for the new helper**

Run: `head -80 tests/conftest.py`
Look for the existing `import_sweep()` helper around line 69-77; the new helper goes just below it for alphabetical-ish grouping.

- [ ] **Step 2: Add `import_stage()` helper after `import_sweep()`**

Edit `tests/conftest.py` — add this function after the `import_sweep()` definition (around line 77):

```python
def import_stage() -> ModuleType:
    """Load `stage.py` as a module. Same SourceFileLoader trick as the others."""
    path = SKILL_SCRIPTS / "stage.py"
    loader = SourceFileLoader("stage", str(path))
    spec = importlib.util.spec_from_loader("stage", loader)
    assert spec is not None
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod
```

- [ ] **Step 3: Commit conftest helper**

```bash
git add tests/conftest.py
git commit -m "test(stage): add import_stage() conftest helper for upcoming stage.py tests"
```

---

### Task 1.2: Skeleton stage.py + dataclasses

**Files:**
- Create: `skills/jared/scripts/stage.py`
- Create: `tests/test_stage.py`

- [ ] **Step 1: Write failing test for module import + dataclass shapes**

Create `tests/test_stage.py`:

```python
"""Unit tests for skills/jared/scripts/stage.py — /jared-stage eval engine."""

from __future__ import annotations

import math
from dataclasses import is_dataclass

from tests.conftest import import_stage


def test_stage_module_imports() -> None:
    stage = import_stage()
    assert stage is not None


def test_stage_proposals_dataclass_shape() -> None:
    stage = import_stage()
    assert is_dataclass(stage.StageProposals)
    assert is_dataclass(stage.DeferredItem)

    fields = {f.name for f in stage.StageProposals.__dataclass_fields__.values()}
    assert fields == {
        "promotions",
        "deferred",
        "unblocked",
        "real_world_still_blocked",
        "almost_ready",
    }
```

- [ ] **Step 2: Run test, verify failure**

Run: `pytest tests/test_stage.py -v`
Expected: FAIL — `ModuleNotFoundError` or similar, because `stage.py` doesn't exist yet.

- [ ] **Step 3: Create stage.py skeleton with dataclasses**

Create `skills/jared/scripts/stage.py`:

```python
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
```

- [ ] **Step 4: Run test, verify pass**

Run: `pytest tests/test_stage.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add skills/jared/scripts/stage.py tests/test_stage.py
git commit -m "feat(stage): scaffold stage.py + StageProposals/DeferredItem dataclasses (#128)"
```

---

## Phase 2: Pure filter functions (TDD)

### Task 2.1: `is_pullable(item)` filter

**Files:**
- Modify: `skills/jared/scripts/stage.py`
- Modify: `tests/test_stage.py`

- [ ] **Step 1: Write failing tests for is_pullable**

Append to `tests/test_stage.py`:

```python
class TestIsPullable:
    def test_well_shaped_item_is_pullable(self) -> None:
        stage = import_stage()
        item = {
            "body": (
                "Real summary paragraph describing the work.\n\n"
                "## Acceptance criteria\n\n"
                "<details>\n<summary>Expand</summary>\n\n"
                "- Real criterion 1\n"
                "- Real criterion 2\n\n"
                "</details>"
            )
        }
        assert stage.is_pullable(item) is True

    def test_empty_body_is_not_pullable(self) -> None:
        stage = import_stage()
        assert stage.is_pullable({"body": ""}) is False

    def test_template_placeholder_first_para_is_not_pullable(self) -> None:
        stage = import_stage()
        item = {
            "body": (
                "One-sentence summary of what this issue is about and why it matters.\n\n"
                "## Acceptance criteria\n\n"
                "<details>\n<summary>Expand</summary>\n\n"
                "- Real criterion\n\n"
                "</details>"
            )
        }
        assert stage.is_pullable(item) is False

    def test_no_acceptance_criteria_section_is_not_pullable(self) -> None:
        stage = import_stage()
        item = {"body": "Real summary.\n\n## Decisions\n\n(none)\n"}
        assert stage.is_pullable(item) is False

    def test_placeholder_criteria_only_is_not_pullable(self) -> None:
        stage = import_stage()
        item = {
            "body": (
                "Real summary.\n\n"
                "## Acceptance criteria\n\n"
                "<details>\n<summary>Expand</summary>\n\n"
                "- Criterion 1\n"
                "- Criterion 2\n"
                "- Criterion 3\n\n"
                "</details>"
            )
        }
        assert stage.is_pullable(item) is False
```

- [ ] **Step 2: Run tests, verify failure**

Run: `pytest tests/test_stage.py::TestIsPullable -v`
Expected: FAIL — `AttributeError: module 'stage' has no attribute 'is_pullable'`.

- [ ] **Step 3: Implement is_pullable in stage.py**

Add to `stage.py` (below the dataclasses, before any future functions):

```python
import re

_TEMPLATE_FIRST_PARA = "One-sentence summary of what this issue is about and why it matters."
_PLACEHOLDER_CRITERIA = re.compile(r"^\s*-\s*Criterion\s*\d+\s*$", re.MULTILINE)
_ACCEPTANCE_SECTION = re.compile(
    r"##\s+Acceptance criteria\s*\n+<details>\s*\n+<summary>Expand</summary>(.*?)</details>",
    re.DOTALL,
)


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
```

- [ ] **Step 4: Run tests, verify pass**

Run: `pytest tests/test_stage.py::TestIsPullable -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add skills/jared/scripts/stage.py tests/test_stage.py
git commit -m "feat(stage): is_pullable() — pullable-shape filter for Backlog items (#128)"
```

---

### Task 2.2: `has_no_open_blockers(item, items)` filter

**Files:**
- Modify: `skills/jared/scripts/stage.py`
- Modify: `tests/test_stage.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_stage.py`:

```python
class TestHasNoOpenBlockers:
    def _items(self, *defs: dict[str, Any]) -> list[dict[str, Any]]:
        return list(defs)

    def test_no_blockers_at_all(self) -> None:
        stage = import_stage()
        item = {"number": 1, "body": "Summary.\n", "blocked_by_native": []}
        assert stage.has_no_open_blockers(item, self._items(item)) is True

    def test_native_blocker_closed(self) -> None:
        stage = import_stage()
        target = {"number": 1, "body": "Summary.\n", "blocked_by_native": [2]}
        blocker = {"number": 2, "state": "CLOSED"}
        assert stage.has_no_open_blockers(target, self._items(target, blocker)) is True

    def test_native_blocker_open(self) -> None:
        stage = import_stage()
        target = {"number": 1, "body": "Summary.\n", "blocked_by_native": [2]}
        blocker = {"number": 2, "state": "OPEN"}
        assert stage.has_no_open_blockers(target, self._items(target, blocker)) is False

    def test_body_ref_blocker_open(self) -> None:
        stage = import_stage()
        target = {
            "number": 1,
            "body": "Summary.\n\n## Blocked by\n\nWaiting on #2.\n",
            "blocked_by_native": [],
        }
        blocker = {"number": 2, "state": "OPEN"}
        assert stage.has_no_open_blockers(target, self._items(target, blocker)) is False

    def test_body_ref_blocker_closed(self) -> None:
        stage = import_stage()
        target = {
            "number": 1,
            "body": "Summary.\n\n## Blocked by\n\nWaiting on #2.\n",
            "blocked_by_native": [],
        }
        blocker = {"number": 2, "state": "CLOSED"}
        assert stage.has_no_open_blockers(target, self._items(target, blocker)) is True

    def test_mixed_native_and_body_one_open(self) -> None:
        stage = import_stage()
        target = {
            "number": 1,
            "body": "Summary.\n\n## Blocked by\n\nWaiting on #3.\n",
            "blocked_by_native": [2],
        }
        b2 = {"number": 2, "state": "CLOSED"}
        b3 = {"number": 3, "state": "OPEN"}
        assert stage.has_no_open_blockers(target, self._items(target, b2, b3)) is False
```

- [ ] **Step 2: Run tests, verify failure**

Run: `pytest tests/test_stage.py::TestHasNoOpenBlockers -v`
Expected: FAIL — `has_no_open_blockers` undefined.

- [ ] **Step 3: Implement has_no_open_blockers**

Add to `stage.py`:

```python
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
```

- [ ] **Step 4: Run tests, verify pass**

Run: `pytest tests/test_stage.py::TestHasNoOpenBlockers -v`
Expected: PASS (6 tests).

- [ ] **Step 5: Commit**

```bash
git add skills/jared/scripts/stage.py tests/test_stage.py
git commit -m "feat(stage): has_no_open_blockers() — native edges + body refs (#128)"
```

---

### Task 2.3: `has_real_world_annotation(item)` heuristic

**Files:**
- Modify: `skills/jared/scripts/stage.py`
- Modify: `tests/test_stage.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_stage.py`:

```python
class TestHasRealWorldAnnotation:
    def test_only_issue_refs_no_annotation(self) -> None:
        stage = import_stage()
        item = {"body": "Summary.\n\n## Blocked by\n\n#42, #51\n"}
        assert stage.has_real_world_annotation(item) is False

    def test_substantial_prose_is_annotation(self) -> None:
        stage = import_stage()
        item = {
            "body": (
                "Summary.\n\n"
                "## Blocked by\n\n"
                "Waiting on next non-trivial findajob session — no code change unblocks it.\n"
            )
        }
        assert stage.has_real_world_annotation(item) is True

    def test_short_text_after_stripping_refs_is_not_annotation(self) -> None:
        stage = import_stage()
        item = {"body": "Summary.\n\n## Blocked by\n\nWaiting on #42\n"}
        # "Waiting on " stripped of #42 = "Waiting on " — under 10 non-whitespace chars
        assert stage.has_real_world_annotation(item) is False

    def test_no_blocked_by_section_returns_false(self) -> None:
        stage = import_stage()
        item = {"body": "Summary.\n\n## Decisions\n\n(none)\n"}
        assert stage.has_real_world_annotation(item) is False
```

- [ ] **Step 2: Run tests, verify failure**

Run: `pytest tests/test_stage.py::TestHasRealWorldAnnotation -v`
Expected: FAIL — function undefined.

- [ ] **Step 3: Implement has_real_world_annotation**

Add to `stage.py`:

```python
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
```

- [ ] **Step 4: Run tests, verify pass**

Run: `pytest tests/test_stage.py::TestHasRealWorldAnnotation -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add skills/jared/scripts/stage.py tests/test_stage.py
git commit -m "feat(stage): has_real_world_annotation() — surfaces non-issue ## Blocked by deps (#128)"
```

---

## Phase 3: Pure ranking functions (TDD)

### Task 3.1: `priority_rank(priority)` + `milestone_proximity_days(item)` + `days_in_backlog(item)`

Batched as one task — each is a trivial lookup and shipping them together avoids three near-identical TDD cycles.

**Files:**
- Modify: `skills/jared/scripts/stage.py`
- Modify: `tests/test_stage.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_stage.py`:

```python
from datetime import date, datetime, timezone


class TestRankingHelpers:
    def test_priority_rank_canonical_order(self) -> None:
        stage = import_stage()
        assert stage.priority_rank("High") == 0
        assert stage.priority_rank("Medium") == 1
        assert stage.priority_rank("Low") == 2

    def test_priority_rank_unknown_sorts_last(self) -> None:
        stage = import_stage()
        assert stage.priority_rank(None) == 3
        assert stage.priority_rank("") == 3
        assert stage.priority_rank("Whatever") == 3

    def test_milestone_proximity_days_with_future_due(self) -> None:
        stage = import_stage()
        future = (date.today().toordinal() + 30)
        future_iso = date.fromordinal(future).isoformat()
        item = {"milestone": {"due_on": f"{future_iso}T00:00:00Z"}}
        assert stage.milestone_proximity_days(item, today=date.today()) == 30

    def test_milestone_proximity_days_no_milestone(self) -> None:
        stage = import_stage()
        assert stage.milestone_proximity_days({}, today=date.today()) == math.inf

    def test_milestone_proximity_days_no_due_on(self) -> None:
        stage = import_stage()
        item = {"milestone": {"title": "Phase 2"}}
        assert stage.milestone_proximity_days(item, today=date.today()) == math.inf

    def test_days_in_backlog_uses_created_at_fallback(self) -> None:
        stage = import_stage()
        # Item created 14 days ago
        created = (datetime.now(timezone.utc).timestamp() - 14 * 86400)
        item = {"createdAt": datetime.fromtimestamp(created, tz=timezone.utc).isoformat()}
        days = stage.days_in_backlog(item, today=date.today())
        assert 13 <= days <= 15  # allow 1d slack for test timing
```

- [ ] **Step 2: Run tests, verify failure**

Run: `pytest tests/test_stage.py::TestRankingHelpers -v`
Expected: FAIL — functions undefined.

- [ ] **Step 3: Implement ranking helpers**

Add to `stage.py`:

```python
from datetime import date, datetime, timezone

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
```

- [ ] **Step 4: Run tests, verify pass**

Run: `pytest tests/test_stage.py::TestRankingHelpers -v`
Expected: PASS (6 tests).

- [ ] **Step 5: Commit**

```bash
git add skills/jared/scripts/stage.py tests/test_stage.py
git commit -m "feat(stage): priority_rank / milestone_proximity_days / days_in_backlog helpers (#128)"
```

---

### Task 3.2: `deferred_reason(item, today)` heuristic

**Files:**
- Modify: `skills/jared/scripts/stage.py`
- Modify: `tests/test_stage.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_stage.py`:

```python
class TestDeferredReason:
    def test_low_tier_reason(self) -> None:
        stage = import_stage()
        item = {"priority": "Low", "milestone": {"due_on": "2026-07-01T00:00:00Z"}}
        assert stage.deferred_reason(item, today=date.today()) == "Low tier"

    def test_no_milestone_reason(self) -> None:
        stage = import_stage()
        item = {"priority": "Medium"}
        assert stage.deferred_reason(item, today=date.today()) == "no milestone with due date"

    def test_below_slot_cap_reason(self) -> None:
        stage = import_stage()
        # Medium with a real milestone — only loses to age or slot cap
        item = {"priority": "Medium", "milestone": {"due_on": "2026-07-01T00:00:00Z"}}
        assert stage.deferred_reason(item, today=date.today()) == "ranked below slot cap"
```

- [ ] **Step 2: Run tests, verify failure**

Run: `pytest tests/test_stage.py::TestDeferredReason -v`
Expected: FAIL.

- [ ] **Step 3: Implement deferred_reason**

Add to `stage.py`:

```python
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
```

- [ ] **Step 4: Run tests, verify pass**

Run: `pytest tests/test_stage.py::TestDeferredReason -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add skills/jared/scripts/stage.py tests/test_stage.py
git commit -m "feat(stage): deferred_reason() — one-line reason per non-promoted item (#128)"
```

---

## Phase 4: Orchestration (TDD)

### Task 4.1: `stage_proposals(items, up_next_cap, today)` — pure orchestration

This is the integration of all the filter + ranking functions. Tested in isolation by passing items dicts directly (no Board fetch).

**Files:**
- Modify: `skills/jared/scripts/stage.py`
- Modify: `tests/test_stage.py`

- [ ] **Step 1: Write failing tests for the orchestration**

Append to `tests/test_stage.py`:

```python
def _item(
    *,
    number: int,
    status: str = "Backlog",
    priority: str = "Medium",
    title: str = "Test",
    body: str | None = None,
    milestone_due: str | None = "2026-07-01T00:00:00Z",
    state: str = "OPEN",
    created_days_ago: int = 7,
    blocked_by_native: list[int] | None = None,
) -> dict[str, Any]:
    """Build a stub item dict for stage_proposals tests."""
    default_body = (
        "Summary paragraph.\n\n"
        "## Acceptance criteria\n\n"
        "<details>\n<summary>Expand</summary>\n\n"
        "- Real criterion\n\n"
        "</details>"
    )
    created = (datetime.now(timezone.utc).timestamp() - created_days_ago * 86400)
    return {
        "number": number,
        "status": status,
        "priority": priority,
        "title": title,
        "body": body if body is not None else default_body,
        "milestone": ({"due_on": milestone_due} if milestone_due else None),
        "state": state,
        "createdAt": datetime.fromtimestamp(created, tz=timezone.utc).isoformat(),
        "blocked_by_native": blocked_by_native or [],
    }


class TestStageProposals:
    def test_empty_backlog_produces_empty_proposals(self) -> None:
        stage = import_stage()
        result = stage.stage_proposals([], up_next_cap=3, today=date.today())
        assert result.promotions == []
        assert result.deferred == []
        assert result.unblocked == []

    def test_three_pullable_dep_ready_items_promoted_to_full_cap(self) -> None:
        stage = import_stage()
        items = [
            _item(number=1, priority="High"),
            _item(number=2, priority="Medium"),
            _item(number=3, priority="Low"),
        ]
        result = stage.stage_proposals(items, up_next_cap=3, today=date.today())
        assert [p["number"] for p in result.promotions] == [1, 2, 3]
        assert result.deferred == []

    def test_priority_dominates_milestone(self) -> None:
        stage = import_stage()
        items = [
            # Low with sooner milestone
            _item(number=1, priority="Low", milestone_due="2026-06-01T00:00:00Z"),
            # High with later milestone
            _item(number=2, priority="High", milestone_due="2027-01-01T00:00:00Z"),
        ]
        result = stage.stage_proposals(items, up_next_cap=1, today=date.today())
        assert result.promotions[0]["number"] == 2

    def test_milestone_proximity_breaks_priority_tie(self) -> None:
        stage = import_stage()
        items = [
            _item(number=1, priority="Medium", milestone_due="2027-01-01T00:00:00Z"),
            _item(number=2, priority="Medium", milestone_due="2026-06-01T00:00:00Z"),
        ]
        result = stage.stage_proposals(items, up_next_cap=1, today=date.today())
        assert result.promotions[0]["number"] == 2

    def test_up_next_full_yields_no_promotions(self) -> None:
        stage = import_stage()
        items = [
            _item(number=1, status="Up Next"),
            _item(number=2, status="Up Next"),
            _item(number=3, status="Up Next"),
            _item(number=4, status="Backlog", priority="High"),
        ]
        result = stage.stage_proposals(items, up_next_cap=3, today=date.today())
        assert result.promotions == []

    def test_unpullable_item_deferred_with_reason(self) -> None:
        stage = import_stage()
        items = [
            _item(number=1, body="Real summary.\n\n## Decisions\n\n(none)\n"),  # no ## Acceptance
        ]
        result = stage.stage_proposals(items, up_next_cap=3, today=date.today())
        assert result.promotions == []
        assert len(result.deferred) == 1
        assert result.deferred[0].item["number"] == 1
        assert "not pullable" in result.deferred[0].reason

    def test_blocked_item_with_closed_blocker_returns_to_backlog(self) -> None:
        stage = import_stage()
        items = [
            _item(number=1, status="Blocked", blocked_by_native=[2]),
            _item(number=2, status="Done", state="CLOSED"),
        ]
        result = stage.stage_proposals(items, up_next_cap=3, today=date.today())
        assert len(result.unblocked) == 1
        assert result.unblocked[0]["number"] == 1

    def test_blocked_item_with_real_world_annotation_stays_blocked(self) -> None:
        stage = import_stage()
        body = (
            "Summary.\n\n"
            "## Acceptance criteria\n\n<details>\n<summary>Expand</summary>\n\n"
            "- Real criterion\n\n</details>\n\n"
            "## Blocked by\n\nWaiting on next live findajob session.\n"
        )
        items = [_item(number=1, status="Blocked", body=body)]
        result = stage.stage_proposals(items, up_next_cap=3, today=date.today())
        assert result.unblocked == []
        assert len(result.real_world_still_blocked) == 1

    def test_almost_ready_surfaces_pullable_but_blocked(self) -> None:
        stage = import_stage()
        items = [
            _item(number=1, blocked_by_native=[2]),     # pullable + body-blocked-by? actually native
            _item(number=2, status="Done", state="OPEN"),  # blocker still open
        ]
        result = stage.stage_proposals(items, up_next_cap=3, today=date.today())
        assert result.promotions == []
        assert len(result.almost_ready) == 1
        assert result.almost_ready[0]["number"] == 1
```

- [ ] **Step 2: Run tests, verify failure**

Run: `pytest tests/test_stage.py::TestStageProposals -v`
Expected: FAIL — `stage_proposals` undefined.

- [ ] **Step 3: Implement stage_proposals**

Add to `stage.py`:

```python
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
```

- [ ] **Step 4: Run tests, verify pass**

Run: `pytest tests/test_stage.py::TestStageProposals -v`
Expected: PASS (9 tests).

- [ ] **Step 5: Run the full test_stage.py file to ensure nothing regressed**

Run: `pytest tests/test_stage.py -v`
Expected: PASS for all tests across all classes.

- [ ] **Step 6: Commit**

```bash
git add skills/jared/scripts/stage.py tests/test_stage.py
git commit -m "feat(stage): stage_proposals() — pure orchestration of filters + ranking (#128)"
```

---

## Phase 5: I/O + rendering

### Task 5.1: `render(proposals, *, now)` — output formatter

The renderer takes the dataclass and emits the text block documented in the spec.

**Files:**
- Modify: `skills/jared/scripts/stage.py`
- Modify: `tests/test_stage.py`

- [ ] **Step 1: Write failing tests for render()**

Append to `tests/test_stage.py`:

```python
class TestRender:
    def test_render_empty_proposals_has_all_section_headers(self) -> None:
        stage = import_stage()
        result = stage.stage_proposals([], up_next_cap=3, today=date.today())
        out = stage.render(result, now=datetime(2026, 5, 14, 16, 45, tzinfo=timezone.utc))
        # Every section header must be present even when its content is empty
        assert "/jared-stage — proposals 2026-05-14 16:45" in out
        assert "== Backlog → Up Next ==" in out
        assert "== Blocked revisit ==" in out
        assert "== Almost ready (advisory) ==" in out
        assert "Approve? (y / <issue numbers> / skip)" in out

    def test_render_promotion_shows_issue_metadata(self) -> None:
        stage = import_stage()
        items = [_item(number=42, priority="High", title="Add foo")]
        result = stage.stage_proposals(items, up_next_cap=3, today=date.today())
        out = stage.render(result, now=datetime(2026, 5, 14, 16, 45, tzinfo=timezone.utc))
        assert "#42" in out
        assert "[High]" in out
        assert "Add foo" in out

    def test_render_deferred_shows_reason(self) -> None:
        stage = import_stage()
        items = [
            _item(number=1, priority="High"),
            _item(number=2, priority="High"),
            _item(number=3, priority="High"),
            _item(number=4, priority="Low"),  # deferred
        ]
        result = stage.stage_proposals(items, up_next_cap=3, today=date.today())
        out = stage.render(result, now=datetime(2026, 5, 14, 16, 45, tzinfo=timezone.utc))
        assert "Deferred (this pass):" in out
        assert "#4" in out
        assert "Low tier" in out

    def test_render_report_only_omits_approve_prompt(self) -> None:
        stage = import_stage()
        result = stage.stage_proposals([], up_next_cap=3, today=date.today())
        out = stage.render(
            result,
            now=datetime(2026, 5, 14, 16, 45, tzinfo=timezone.utc),
            report_only=True,
        )
        assert "Approve?" not in out
```

- [ ] **Step 2: Run tests, verify failure**

Run: `pytest tests/test_stage.py::TestRender -v`
Expected: FAIL — `render` undefined.

- [ ] **Step 3: Implement render()**

Add to `stage.py`:

```python
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
    lines.append("")  # spec leaves caller to compute slots — we render what we have
    if proposals.promotions:
        lines.append("Promote:")
        for item in proposals.promotions:
            lines.append(f"  #{item['number']} [{item.get('priority', '?')}] {item.get('title', '')}")
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
        lines.append("Unblocked: (none — all Blocked items still have open blockers or real-world annotations)")
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
```

- [ ] **Step 4: Run tests, verify pass**

Run: `pytest tests/test_stage.py::TestRender -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add skills/jared/scripts/stage.py tests/test_stage.py
git commit -m "feat(stage): render() — stdout formatter with --report-only support (#128)"
```

---

### Task 5.2: `fetch_items_for_stage(board)` — integration with lib/board.py

This wraps Board's fetch logic to produce the dict shape our pure functions expect. Tested via patch_gh with a fake project item-list response.

**Files:**
- Modify: `skills/jared/scripts/stage.py`
- Modify: `tests/test_stage.py`

- [ ] **Step 1: Read lib/board.py to understand the existing fetch shape**

Run: `grep -n "def fetch_items\|def fetch_blocked_by_edges\|def item_list" skills/jared/scripts/lib/board.py`

Note the exact method names and their return shapes. The implementation in step 3 should pass through those exact shapes — `fetch_items_for_stage` is a thin adapter, not a re-implementation.

- [ ] **Step 2: Write failing test for fetch_items_for_stage**

Append to `tests/test_stage.py`:

```python
import json
from tests.conftest import patch_gh, write_minimal_board


class TestFetchItemsForStage:
    def test_returns_items_with_status_priority_body_milestone(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Any
    ) -> None:
        write_minimal_board(tmp_path)
        monkeypatch.chdir(tmp_path)
        # Fake item-list response — real schema lives in gh project docs; the
        # adapter just normalizes the fields stage.py needs.
        fake = json.dumps({
            "items": [
                {
                    "content": {
                        "number": 1,
                        "title": "Test",
                        "body": "Summary.",
                        "state": "OPEN",
                        "milestone": {"title": "M1", "due_on": "2026-07-01T00:00:00Z"},
                        "createdAt": "2026-05-01T00:00:00Z",
                    },
                    "status": "Backlog",
                    "priority": "Medium",
                },
            ]
        })
        patch_gh(monkeypatch, stdout=fake)
        stage = import_stage()
        # Import Board through the unit-test path
        from skills.jared.scripts.lib.board import Board
        board = Board.from_doc(tmp_path / "docs" / "project-board.md")
        items = stage.fetch_items_for_stage(board)
        assert len(items) == 1
        assert items[0]["number"] == 1
        assert items[0]["status"] == "Backlog"
        assert items[0]["priority"] == "Medium"
        assert items[0]["body"] == "Summary."
        assert items[0]["milestone"]["title"] == "M1"
```

> Note: the exact shape of `Board.from_doc`, `fetch_items`, etc. may differ — adjust during implementation. The test asserts on the adapter's output dict shape, which is fixed by stage.py's pure functions.

- [ ] **Step 3: Run test, verify failure**

Run: `pytest tests/test_stage.py::TestFetchItemsForStage -v`
Expected: FAIL — `fetch_items_for_stage` undefined.

- [ ] **Step 4: Implement fetch_items_for_stage**

Add to `stage.py`:

```python
def fetch_items_for_stage(board: Any) -> list[dict[str, Any]]:
    """Fetch all open items from the board and normalize to stage.py's expected dict shape.

    The pure functions in this module take dicts with these keys:
      number, status, priority, title, body, state, milestone, createdAt,
      blocked_by_native (list[int], from board.fetch_blocked_by_edges per item).

    This adapter consolidates fetches so callers don't need to remember the
    multi-step pattern. Uses board.run_gh* wrappers internally (already
    cache-disciplined via lib/board.py).
    """
    raw_items = board.fetch_items()
    # Build a map of issue number → blocked-by edges (one fetch per Blocked item)
    blocked_edges_by_number: dict[int, list[int]] = {}
    for raw in raw_items:
        if raw.get("status") == "Blocked":
            number = raw.get("content", {}).get("number")
            if number is not None:
                blocked_edges_by_number[number] = board.fetch_blocked_by_edges(number)

    normalized: list[dict[str, Any]] = []
    for raw in raw_items:
        content = raw.get("content", {}) or {}
        number = content.get("number")
        if number is None:
            continue
        normalized.append({
            "number": number,
            "status": raw.get("status"),
            "priority": raw.get("priority"),
            "title": content.get("title", ""),
            "body": content.get("body", ""),
            "state": content.get("state", "OPEN"),
            "milestone": content.get("milestone"),
            "createdAt": content.get("createdAt") or content.get("created_at"),
            "blocked_by_native": blocked_edges_by_number.get(number, []),
        })
    return normalized
```

> Note: the exact `Board.fetch_items()` and `Board.fetch_blocked_by_edges()` method signatures must be verified against the real `lib/board.py`. Adjust this adapter to match — including renaming or restructuring if board.py exposes the data differently than assumed.

- [ ] **Step 5: Run test, verify pass**

Run: `pytest tests/test_stage.py::TestFetchItemsForStage -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add skills/jared/scripts/stage.py tests/test_stage.py
git commit -m "feat(stage): fetch_items_for_stage() — adapter over lib/board.py (#128)"
```

---

### Task 5.3: `main(argv)` — CLI entry with --report-only

Wires everything together. Argparse for the flag; stdout for output. Returns exit code.

**Files:**
- Modify: `skills/jared/scripts/stage.py`
- Modify: `tests/test_stage.py`

- [ ] **Step 1: Write failing tests for main()**

Append to `tests/test_stage.py`:

```python
class TestMain:
    def test_main_with_no_args_emits_proposals_block(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Any, capsys: Any
    ) -> None:
        write_minimal_board(tmp_path)
        monkeypatch.chdir(tmp_path)
        patch_gh(monkeypatch, stdout='{"items": []}')
        stage = import_stage()
        rc = stage.main([])
        captured = capsys.readouterr()
        assert rc == 0
        assert "/jared-stage — proposals" in captured.out
        assert "== Backlog → Up Next ==" in captured.out
        assert "Approve?" in captured.out  # interactive mode

    def test_main_report_only_omits_approve_prompt(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Any, capsys: Any
    ) -> None:
        write_minimal_board(tmp_path)
        monkeypatch.chdir(tmp_path)
        patch_gh(monkeypatch, stdout='{"items": []}')
        stage = import_stage()
        rc = stage.main(["--report-only"])
        captured = capsys.readouterr()
        assert rc == 0
        assert "Approve?" not in captured.out

    def test_main_up_next_cap_override(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Any, capsys: Any
    ) -> None:
        write_minimal_board(tmp_path)
        monkeypatch.chdir(tmp_path)
        patch_gh(monkeypatch, stdout='{"items": []}')
        stage = import_stage()
        rc = stage.main(["--up-next-cap", "5"])
        assert rc == 0
```

- [ ] **Step 2: Run tests, verify failure**

Run: `pytest tests/test_stage.py::TestMain -v`
Expected: FAIL.

- [ ] **Step 3: Implement main() in stage.py**

Add at the bottom of `stage.py`:

```python
import argparse
import sys


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
        default=3,
        help="Maximum items allowed in Up Next column (default: 3).",
    )
    args = parser.parse_args(argv)

    # Import Board here, not at module top, so unit tests of pure functions
    # don't trigger board-doc parsing at import time.
    from lib.board import Board  # CLI-side import path; see CLAUDE.md dual-import note.

    board = Board.from_local_doc()
    items = fetch_items_for_stage(board)
    today = date.today()
    proposals = stage_proposals(items, up_next_cap=args.up_next_cap, today=today)
    now = datetime.now(timezone.utc).astimezone()
    output = render(proposals, now=now, today=today, report_only=args.report_only)
    print(output)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
```

> Note: `Board.from_local_doc()` is illustrative — use whatever constructor `lib/board.py` actually exposes for "load the convention doc relative to cwd." Adjust during implementation.

- [ ] **Step 4: Run tests, verify pass**

Run: `pytest tests/test_stage.py::TestMain -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Run the full test_stage.py to ensure no regression**

Run: `pytest tests/test_stage.py -v`
Expected: PASS for all classes.

- [ ] **Step 6: Run ruff + mypy on the new code**

Run: `ruff check skills/jared/scripts/stage.py tests/test_stage.py`
Expected: no findings.

Run: `mypy skills/jared/scripts/stage.py`
Expected: no errors.

If either fails, fix inline before commit.

- [ ] **Step 7: Make stage.py executable + commit**

```bash
chmod +x skills/jared/scripts/stage.py
git add skills/jared/scripts/stage.py tests/test_stage.py
git commit -m "feat(stage): main() — CLI entry with --report-only and --up-next-cap (#128)"
```

---

## Phase 6: Slash command

### Task 6.1: Create commands/jared-stage.md

**Files:**
- Create: `commands/jared-stage.md`

- [ ] **Step 1: Create the slash command file**

Write `commands/jared-stage.md`:

````markdown
---
description: Propose Backlog → Up Next promotions and Blocked revisits. Advisory; you approve before any move applies.
---

Invoke the Jared skill to evaluate the board and propose staging changes. The flow is advisory — Jared proposes; you approve per item or as a batch before any `jared move` runs.

Flow:

1. **Run `${CLAUDE_PLUGIN_ROOT}/skills/jared/scripts/stage.py`** to emit the proposal block. The script:
   - Fetches Backlog + Blocked items via `lib/board.py`.
   - Filters Backlog by pullable + dependency-ready.
   - Ranks survivors by Priority > milestone proximity > age.
   - Re-evaluates Blocked items; surfaces unblocked items (propose move to Backlog) and items still blocked by real-world annotations (surface only — never auto-revisit).
   - Emits a structured proposal block to stdout.

2. **Display the output verbatim** — section headers, deferred-with-reason list, and almost-ready advisory all carry signal even when their content is empty. Greppable structure across runs.

3. **Walk approval:**
   ```
   Approve? (y / <issue numbers> / skip)
     y               apply all proposed promotions + unblocks
     <numbers>       apply only those (e.g., "y #111 #54")
     skip            apply nothing; output is record only
   ```

4. **On approval, apply:**
   - For each promotion: `${CLAUDE_PLUGIN_ROOT}/skills/jared/scripts/jared move <N> "Up Next"`
   - For each unblock: `${CLAUDE_PLUGIN_ROOT}/skills/jared/scripts/jared move <N> "Backlog"`
   - Print one confirmation line per `jared move`. Errors surface inline; continue with remaining items; exit with success/failure count. `jared move` is idempotent, so the operator can retry failed items manually.

5. **On cherry-pick (`y <numbers>`):**
   - Validate each named number appears in the current proposal. If any don't, print a stderr line listing them, do not apply anything.
   - Otherwise apply only the named promotions/unblocks via the same `jared move` flow.

6. **On `skip`:**
   - No moves applied. The proposal block remains in the session record only.

## Scheduling

To run /jared-stage automatically:

```
/schedule jared-stage daily at 9am
```

The schedule skill fires `/jared-stage --report-only` at the configured times. The `--report-only` flag suppresses the "Approve?" prompt; the output lands wherever `/schedule` delivers it (notification, log thread). To apply scheduled-fire output, re-run `/jared-stage` interactively in a session.

## Flags

- `--report-only`: emit proposals only; skip the approval prompt. Intended for scheduled fires.
- `--up-next-cap <N>`: override the default Up Next cap of 3. Useful for projects with different WIP norms.

See `docs/superpowers/specs/2026-05-14-jared-stage-design.md` for the full design.
````

- [ ] **Step 2: Commit**

```bash
git add commands/jared-stage.md
git commit -m "feat(stage): /jared-stage slash command with approval flow + schedule docs (#128)"
```

---

## Phase 7: Doctrine updates

### Task 7.1: Add SKILL.md "Staging" subsection

**Files:**
- Modify: `skills/jared/SKILL.md`

- [ ] **Step 1: Find the insertion point**

Run: `grep -n "Periodically — groom\|### Periodically" skills/jared/SKILL.md`

The new subsection goes just after the existing "Periodically — groom" subsection.

- [ ] **Step 2: Add the Staging subsection**

Edit `skills/jared/SKILL.md` — add this subsection immediately after the end of "Periodically — groom" (and before the next H3, likely "Plan and spec integration" or "Session continuity"):

```markdown
### Periodically — stage (forward-looking complement to groom)

`/jared-stage` evaluates the Backlog under fixed criteria and proposes the next N items to promote to Up Next, sized to keep Up Next at the WIP cap. Same advisory pattern as `/jared-groom` (Jared proposes; you approve), but the focus is forward-looking — what should we work on next — rather than grooming's backward-looking sweep for drift.

Trigger when:
- Up Next is empty or thin (the natural pull cadence)
- A complex piece just shipped and you want to reset the pipeline
- You want a scheduled daily nudge — set up `/schedule jared-stage daily at 9am`

The eval is deterministic: pullable + dependency-ready Backlog items are ranked by Priority > milestone proximity > age in Backlog; Blocked items are re-evaluated for closed blockers and proposed back to Backlog when unblocked. See `commands/jared-stage.md` and `docs/superpowers/specs/2026-05-14-jared-stage-design.md` for the full algorithm.

Critically, `/jared-stage` never applies changes without operator approval — even on scheduled fires (the `--report-only` flag suppresses the approval prompt; the operator re-runs interactively to apply). The discipline preserves "Jared mirrors decisions, doesn't make them" while removing the "remembering to evaluate" burden.
```

- [ ] **Step 3: Commit**

```bash
git add skills/jared/SKILL.md
git commit -m "doctrine(stage): SKILL.md § 'Periodically — stage' (#128)"
```

---

### Task 7.2: Cross-reference staging from board-sweep.md

**Files:**
- Modify: `skills/jared/references/board-sweep.md`

- [ ] **Step 1: Read board-sweep.md to find a natural insertion point**

Run: `grep -n "promote\|Up Next\|aging" skills/jared/references/board-sweep.md | head -10`

The cross-reference goes near the existing "promote / downgrade / close" line, around line 50 per earlier grep.

- [ ] **Step 2: Add the cross-reference**

Edit the relevant section of `skills/jared/references/board-sweep.md`. Find the line:

```
- High-priority Backlog items >14 days old: propose promote / downgrade / close.
```

Add immediately after:

```
**See also:** `/jared-stage` is the forward-looking complement to grooming — it evaluates the Backlog under priority + milestone criteria and proposes Up Next promotions. Use `/jared-stage` when you want to pick the next item; use `/jared-groom` when you want to check for drift.
```

- [ ] **Step 3: Commit**

```bash
git add skills/jared/references/board-sweep.md
git commit -m "doctrine(stage): cross-reference /jared-stage from board-sweep.md (#128)"
```

---

### Task 7.3: Optional "see also" in jared-wrap.md

**Files:**
- Modify: `commands/jared-wrap.md`

- [ ] **Step 1: Find the right line in jared-wrap.md**

Run: `grep -n "Next session:\|/jared-start\|Wrapped" commands/jared-wrap.md`

The "see also" goes in step 6's closing summary line.

- [ ] **Step 2: Update the closing line**

Find this line in `commands/jared-wrap.md`:

```
6. **Confirm and close out.** Print a one-line summary: *"Wrapped N issues, filed N new, archived N plans, reconciled N drift items. Next session: `/jared-start`."*
```

Change to:

```
6. **Confirm and close out.** Print a one-line summary: *"Wrapped N issues, filed N new, archived N plans, reconciled N drift items. Next session: `/jared-start` to pull, or `/jared-stage` to see staging proposals."*
```

- [ ] **Step 3: Commit**

```bash
git add commands/jared-wrap.md
git commit -m "doctrine(stage): mention /jared-stage in /jared-wrap closing summary (#128)"
```

---

## Phase 8: Verification + release

### Task 8.1: Full test suite + lint + typecheck

- [ ] **Step 1: Run pytest**

Run: `pytest -v`
Expected: PASS for all tests (existing + new stage tests).

- [ ] **Step 2: Run ruff**

Run: `ruff check .`
Expected: no findings. If any, fix inline.

- [ ] **Step 3: Run mypy**

Run: `mypy`
Expected: no errors. If any, fix inline.

- [ ] **Step 4: If anything failed, fix and re-run before continuing.**

---

### Task 8.2: Manual smoke against live brockamer/jared board

- [ ] **Step 1: Run stage.py directly against the live board**

Run: `cd /home/brockamer/Code/jared && skills/jared/scripts/stage.py`

Expected: a proposal block matching what the operator would intuitively choose given the current Backlog state. Specifically (as of the 2026-05-14 design session, may have drifted):
- Up Next is empty, so 3 slots available
- Backlog contains ~7 Medium + Low items
- Top promotions should be the highest-Priority items with the soonest-due milestones
- #60 (Blocked with real-world annotation) should appear in "Still Blocked, real-world annotation"

- [ ] **Step 2: Verify the deferred-with-reason output is useful**

Inspect the "Deferred" sub-list. Each deferred item should have a clear, one-line reason. If any reason reads as "ranked below slot cap" without more context, consider whether `deferred_reason()` needs to be more specific.

- [ ] **Step 3: Test the --report-only flag**

Run: `skills/jared/scripts/stage.py --report-only`
Expected: same content as Step 1 but without the "Approve?" prompt.

- [ ] **Step 4: If anything looks wrong, fix and re-run; commit any fixes as their own commit.**

---

### Task 8.3: feature-dev:code-reviewer pass

- [ ] **Step 1: Dispatch the reviewer**

Use Agent tool with subagent_type `feature-dev:code-reviewer`, model `opus` (per `feedback_model_selection`: review work goes on Opus). Brief the reviewer on:
- What the branch ships (Phase 1 + Phase 2 + Phase 3 etc., the file list, the spec link)
- What to check specifically: cross-file consistency between SKILL.md / jared-stage.md / spec; algorithm matches the spec; tests cover all spec-named edge cases; doctrine doesn't drift from #126's just-shipped imperative-guidance shape
- What NOT to flag: doctrine-first prose-only choices for the slash command surface; the deferred-with-reason heuristic-not-contract framing

- [ ] **Step 2: Apply review findings**

Each blocker becomes a "fix(128): review pass — <specific>" commit. Nits get judgment calls — fold in if cheap, defer to follow-up issue if real but out of scope.

---

### Task 8.4: PR + merge + release v0.15.0

- [ ] **Step 1: Push branch**

```bash
git push -u origin feat/128-jared-stage
```

- [ ] **Step 2: Open PR**

Use `gh pr create --base main --head feat/128-jared-stage` with:
- Title: `feat(128): /jared-stage — continuous staging discipline`
- Body: summary referencing the spec, the test plan checklist with manual smoke item, and phase-trail commits.

- [ ] **Step 3: Merge**

```bash
gh pr merge <PR_NUMBER> --repo brockamer/jared --merge --delete-branch
```

`--merge` (not squash) to preserve the phase trail per `feedback_jared_git_workflow`.

- [ ] **Step 4: Pull main + verify #128 closed and on Done**

```bash
git checkout main && git pull --ff-only
gh issue view 128 --repo brockamer/jared --json state,closedAt
skills/jared/scripts/jared get-item 128
```

Expected: state=CLOSED, Status=Done.

- [ ] **Step 5: Bump version → v0.15.0**

Edit `.claude-plugin/plugin.json`: `"version": "0.14.0"` → `"version": "0.15.0"`.
Edit `pyproject.toml`: `version = "0.14.0"` → `version = "0.15.0"`.

- [ ] **Step 6: Commit release + tag + push**

```bash
git add .claude-plugin/plugin.json pyproject.toml
git commit -m "$(cat <<'EOF'
release: v0.15.0 — /jared-stage continuous staging (#128)

New /jared-stage slash command + skills/jared/scripts/stage.py batch script
implementing advisory + scheduled staging discipline. Evaluates Backlog
under pullable + dep-ready filters; ranks by Priority > milestone proximity
> age in Backlog; re-evaluates Blocked items for closed blockers. Operator
approves promotions per item or as a batch.

Designed in session 2026-05-14 brainstorming pass; spec at
docs/superpowers/specs/2026-05-14-jared-stage-design.md.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"

git tag -a v0.15.0 -m "v0.15.0 — /jared-stage continuous staging (#128)"
git push origin main
git push origin v0.15.0
```

- [ ] **Step 7: Plugin update + reload (operator action)**

User runs in their session:
```
/plugin update jared
/reload-plugins
```

After reload, `/jared-stage` is available.

---

## Self-Review

After completing all tasks, the implementer should:

1. **Spec coverage check** — confirm every section of `docs/superpowers/specs/2026-05-14-jared-stage-design.md` maps to at least one task above. Specifically: all six design decisions, the architecture file list, the algorithm pseudocode, the filter semantics, the output shape, the approval flow, and the verification plan. Gaps become follow-up commits or a follow-up issue.

2. **Placeholder scan** — verify no task contains TODO, TBD, "implement later," or vague "add appropriate error handling" prose. Every step's code block contains real code; every command line is the exact command to run.

3. **Type consistency** — `StageProposals` has the same five fields everywhere it's mentioned. `DeferredItem` always carries `(item, reason)`. Function signatures in tests match function signatures in implementation.

4. **Ambiguity** — every filter and ranking function has a documented edge case in tests. The slash command's approval verbs (`y` / `<numbers>` / `skip`) are documented identically in `commands/jared-stage.md` and the render() output.

---

## Notes for the executor

- **Dual-import gotcha:** `lib.board` in stage.py's `main()` (CLI-side path) vs `skills.jared.scripts.lib.board` in tests (test-side path). Both produce different `Board` module objects in `sys.modules`. See `tests/conftest.py` docstring for the full subtlety. For this plan, the orchestration test fixtures use the test-side path; the CLI uses the CLI-side path. Don't mix.
- **Cache discipline:** every `gh` read-only call passes `--cache 60s` per `lib/board.py` convention. `fetch_items_for_stage` uses Board's helpers, which already apply this.
- **Method-name drift risk:** Tasks 5.2 and 5.3 reference `Board.from_doc`, `Board.fetch_items`, `Board.fetch_blocked_by_edges`, `Board.from_local_doc`. The exact names may differ — adjust during implementation to match what `lib/board.py` actually exposes. Run `grep -n "def " skills/jared/scripts/lib/board.py` to enumerate the actual surface before writing the adapter.
- **Skip docs/superpowers/plans/ archival** of this plan until #128 is closed. Per `feedback_jared_git_workflow` + Jared's plan/spec discipline, archival happens at close via `scripts/archive-plan.py`.
