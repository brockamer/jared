---
**Shipped in #77, #77 on 2026-05-02. Final decisions captured in issue body.**
---

# Tied-Issues Pre-Pull Analysis Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Issue:** [#77 — feat(jared-start): tied-issues pre-pull analysis](https://github.com/brockamer/jared/issues/77)

**Spec:** `docs/superpowers/specs/2026-05-02-tied-issues-design.md`

**Goal:** Add a `jared ties <N>` CLI subcommand that surfaces material ties (cross-refs, blockers, milestone-mates, same-file, labels, title-tokens) between a target issue and other open issues; wire `/jared-start` to call it always-on so ties surface at pull time.

**Architecture:** Pure-Python analyzer module (`lib/ties.py`) + one new `Board` GraphQL fetch + thin CLI subcommand + skill markdown change. Six deterministic signals with confidence tagging; default-precision threshold; rate-limit-aware degraded modes (full / partial / skip via `Board.graphql_budget()`).

**Tech Stack:** Python 3.11, argparse, `gh` CLI, GitHub GraphQL v4, pytest, ruff, mypy --strict.

**Branch:** `feature/77-tied-issues-design` (already exists with the spec commit `5e493d7` on it). All implementation tasks commit on this branch.

---

## File Structure

NEW:
- `skills/jared/scripts/lib/ties.py` — dataclasses + six analyzers + combine + format + default stop-words
- `tests/test_ties_dataclasses.py` — sanity tests for `SignalHit`, `Tie`, and `OpenIssueForTies`
- `tests/test_ties_analyzers.py` — per-analyzer unit tests
- `tests/test_ties_combine.py` — combine + threshold + sort + cap tests
- `tests/test_ties_format.py` — golden output tests
- `tests/test_board_fetch_for_ties.py` — Board fetch test
- `tests/test_cmd_ties.py` — CLI smoke + budget branches + exit codes

MODIFY:
- `skills/jared/scripts/lib/board.py` — add `fetch_open_issues_for_ties()` and `tie_stop_words()` methods
- `skills/jared/scripts/jared` — add `_cmd_ties` + argparse subcommand
- `commands/jared-start.md` — call `jared ties <N>` after the drift check

---

## Task 1: Bootstrap `lib/ties.py` with dataclasses

**Files:**
- Create: `skills/jared/scripts/lib/ties.py`
- Test: `tests/test_ties_dataclasses.py`

- [ ] **Step 1: Write the failing test**

`tests/test_ties_dataclasses.py`:

```python
"""Sanity tests for the ties module's dataclasses."""

from skills.jared.scripts.lib.ties import OpenIssueForTies, SignalHit, Tie


def test_signal_hit_constructs() -> None:
    hit = SignalHit(
        related_n=42,
        name="cross_ref",
        confidence="strong",
        evidence="target body mentions #42",
    )
    assert hit.related_n == 42
    assert hit.name == "cross_ref"
    assert hit.confidence == "strong"


def test_tie_constructs() -> None:
    hit = SignalHit(
        related_n=42,
        name="cross_ref",
        confidence="strong",
        evidence="target body mentions #42",
    )
    tie = Tie(
        related_n=42,
        related_title="Some related issue",
        related_status="Backlog",
        hits=(hit,),
        combined_score=3,
        primary_relationship="cross-ref",
        secondary_relationships=(),
        suggested_action="review for bundling vs separate",
    )
    assert tie.related_n == 42
    assert tie.combined_score == 3
    assert len(tie.hits) == 1


def test_open_issue_for_ties_constructs() -> None:
    issue = OpenIssueForTies(
        number=42,
        title="Some issue",
        body="Body text mentioning #99",
        labels=("enhancement",),
        milestone="v0.9 — soon",
        status="Backlog",
        priority="Medium",
        blocked_by=(),
    )
    assert issue.number == 42
    assert issue.labels == ("enhancement",)


def test_dataclasses_are_frozen() -> None:
    """Tie / SignalHit / OpenIssueForTies must be immutable for hashing / sets."""
    import dataclasses

    hit = SignalHit(
        related_n=1, name="cross_ref", confidence="strong", evidence=""
    )
    try:
        hit.related_n = 2  # type: ignore[misc]
        raise AssertionError("expected FrozenInstanceError")
    except dataclasses.FrozenInstanceError:
        pass
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_ties_dataclasses.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'skills.jared.scripts.lib.ties'`.

- [ ] **Step 3: Write minimal implementation**

`skills/jared/scripts/lib/ties.py`:

```python
"""Tied-issues analysis — pure Python, no I/O.

Six deterministic signals tagged by confidence (strong/medium/weak), combined
into a per-related-issue score, filtered by threshold, sorted, capped at 8,
formatted for the /jared-start announce block.

See docs/superpowers/specs/2026-05-02-tied-issues-design.md for the full
design.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

SignalName = Literal[
    "cross_ref",
    "blocked_by",
    "milestone",
    "title_tokens",
    "labels",
    "file_paths",
]
Confidence = Literal["strong", "medium", "weak"]
Threshold = Literal["weak", "medium", "strong"]

# Default stop-words for label-intersection signal. Project-board.md may override.
DEFAULT_LABEL_STOP_WORDS: frozenset[str] = frozenset(
    {"enhancement", "bug", "documentation", "refactor"}
)

# Output cap on number of ties surfaced.
MAX_TIES_DISPLAYED = 8

# Confidence weights for combined_score.
CONFIDENCE_WEIGHT: dict[Confidence, int] = {"strong": 3, "medium": 2, "weak": 1}

# Score cap so a single candidate firing every signal doesn't dominate sorting.
MAX_COMBINED_SCORE = 5


@dataclass(frozen=True)
class SignalHit:
    related_n: int
    name: SignalName
    confidence: Confidence
    evidence: str


@dataclass(frozen=True)
class Tie:
    related_n: int
    related_title: str
    related_status: str
    hits: tuple[SignalHit, ...]
    combined_score: int
    primary_relationship: str
    secondary_relationships: tuple[str, ...]
    suggested_action: str


@dataclass(frozen=True)
class OpenIssueForTies:
    """Single record returned by Board.fetch_open_issues_for_ties().

    body may be empty string in partial mode (low GraphQL budget). All other
    fields are always populated.
    """

    number: int
    title: str
    body: str
    labels: tuple[str, ...]
    milestone: str | None
    status: str
    priority: str | None
    blocked_by: tuple[int, ...]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_ties_dataclasses.py -v && ruff check skills/jared/scripts/lib/ties.py && mypy skills/jared/scripts/lib/ties.py`
Expected: 4 tests pass, ruff clean, mypy clean.

- [ ] **Step 5: Commit**

```bash
git add skills/jared/scripts/lib/ties.py tests/test_ties_dataclasses.py
git commit -m "feat(ties): bootstrap lib/ties.py with dataclasses (#77)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: Implement `analyze_blocked_by`

Simplest analyzer first to set the TDD pattern. Reads the `blocked_by` edge already on each `OpenIssueForTies` record.

**Files:**
- Modify: `skills/jared/scripts/lib/ties.py` (append the analyzer)
- Test: `tests/test_ties_analyzers.py` (create)

- [ ] **Step 1: Write the failing test**

`tests/test_ties_analyzers.py`:

```python
"""Tests for individual signal analyzers."""

from skills.jared.scripts.lib.ties import (
    OpenIssueForTies,
    SignalHit,
    analyze_blocked_by,
)


def _make_issue(
    number: int,
    *,
    title: str = "Title",
    body: str = "",
    labels: tuple[str, ...] = (),
    milestone: str | None = None,
    blocked_by: tuple[int, ...] = (),
) -> OpenIssueForTies:
    return OpenIssueForTies(
        number=number,
        title=title,
        body=body,
        labels=labels,
        milestone=milestone,
        status="Backlog",
        priority="Medium",
        blocked_by=blocked_by,
    )


class TestAnalyzeBlockedBy:
    def test_target_blocked_by_other_fires(self) -> None:
        target = _make_issue(1, blocked_by=(2,))
        others = [_make_issue(2)]
        hits = analyze_blocked_by(target, others)
        assert len(hits) == 1
        assert hits[0] == SignalHit(
            related_n=2,
            name="blocked_by",
            confidence="strong",
            evidence="target #1 is blocked by #2",
        )

    def test_other_blocked_by_target_fires(self) -> None:
        target = _make_issue(1)
        others = [_make_issue(2, blocked_by=(1,))]
        hits = analyze_blocked_by(target, others)
        assert len(hits) == 1
        assert hits[0] == SignalHit(
            related_n=2,
            name="blocked_by",
            confidence="strong",
            evidence="#2 is blocked by target #1",
        )

    def test_no_relationship_no_hit(self) -> None:
        target = _make_issue(1, blocked_by=(99,))
        others = [_make_issue(2, blocked_by=(98,))]
        hits = analyze_blocked_by(target, others)
        assert hits == []

    def test_self_is_never_a_hit(self) -> None:
        target = _make_issue(1, blocked_by=(1,))
        others = [_make_issue(1, blocked_by=(1,))]
        hits = analyze_blocked_by(target, others)
        assert hits == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_ties_analyzers.py -v`
Expected: FAIL with `ImportError: cannot import name 'analyze_blocked_by'`.

- [ ] **Step 3: Write minimal implementation**

Append to `skills/jared/scripts/lib/ties.py`:

```python
def analyze_blocked_by(
    target: OpenIssueForTies, open_issues: list[OpenIssueForTies]
) -> list[SignalHit]:
    """Strong signal: native GitHub addBlockedBy edge in either direction."""
    hits: list[SignalHit] = []
    for related in open_issues:
        if related.number == target.number:
            continue
        if related.number in target.blocked_by:
            hits.append(
                SignalHit(
                    related_n=related.number,
                    name="blocked_by",
                    confidence="strong",
                    evidence=f"target #{target.number} is blocked by #{related.number}",
                )
            )
        elif target.number in related.blocked_by:
            hits.append(
                SignalHit(
                    related_n=related.number,
                    name="blocked_by",
                    confidence="strong",
                    evidence=f"#{related.number} is blocked by target #{target.number}",
                )
            )
    return hits
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_ties_analyzers.py -v && ruff check . && mypy skills/jared/scripts/lib/ties.py`
Expected: 4 tests pass, ruff and mypy clean.

- [ ] **Step 5: Commit**

```bash
git add skills/jared/scripts/lib/ties.py tests/test_ties_analyzers.py
git commit -m "feat(ties): analyze_blocked_by — native dependency-edge signal (#77)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: Implement `analyze_milestone_overlap`

**Files:**
- Modify: `skills/jared/scripts/lib/ties.py`
- Modify: `tests/test_ties_analyzers.py` (append test class)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_ties_analyzers.py`:

```python
from skills.jared.scripts.lib.ties import analyze_milestone_overlap


class TestAnalyzeMilestoneOverlap:
    def test_same_milestone_fires(self) -> None:
        target = _make_issue(1, milestone="v0.9 — soon")
        others = [_make_issue(2, milestone="v0.9 — soon")]
        hits = analyze_milestone_overlap(target, others)
        assert len(hits) == 1
        assert hits[0].related_n == 2
        assert hits[0].confidence == "strong"
        assert hits[0].name == "milestone"
        assert "v0.9 — soon" in hits[0].evidence

    def test_different_milestone_no_hit(self) -> None:
        target = _make_issue(1, milestone="v0.9 — soon")
        others = [_make_issue(2, milestone="v1.0 — GA")]
        hits = analyze_milestone_overlap(target, others)
        assert hits == []

    def test_target_no_milestone_no_hit(self) -> None:
        target = _make_issue(1, milestone=None)
        others = [_make_issue(2, milestone="v0.9 — soon")]
        hits = analyze_milestone_overlap(target, others)
        assert hits == []

    def test_both_no_milestone_no_hit(self) -> None:
        """None ≠ None for tie purposes — un-milestoned issues aren't ties."""
        target = _make_issue(1, milestone=None)
        others = [_make_issue(2, milestone=None)]
        hits = analyze_milestone_overlap(target, others)
        assert hits == []

    def test_self_is_never_a_hit(self) -> None:
        target = _make_issue(1, milestone="v0.9")
        others = [_make_issue(1, milestone="v0.9")]
        hits = analyze_milestone_overlap(target, others)
        assert hits == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_ties_analyzers.py::TestAnalyzeMilestoneOverlap -v`
Expected: FAIL with `ImportError: cannot import name 'analyze_milestone_overlap'`.

- [ ] **Step 3: Write minimal implementation**

Append to `skills/jared/scripts/lib/ties.py`:

```python
def analyze_milestone_overlap(
    target: OpenIssueForTies, open_issues: list[OpenIssueForTies]
) -> list[SignalHit]:
    """Strong signal: same milestone as target. None ≠ None — un-milestoned
    issues aren't tied to each other on this signal."""
    if target.milestone is None:
        return []
    hits: list[SignalHit] = []
    for related in open_issues:
        if related.number == target.number:
            continue
        if related.milestone == target.milestone:
            hits.append(
                SignalHit(
                    related_n=related.number,
                    name="milestone",
                    confidence="strong",
                    evidence=f"shares milestone {target.milestone!r}",
                )
            )
    return hits
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_ties_analyzers.py -v && ruff check . && mypy skills/jared/scripts/lib/ties.py`
Expected: 9 tests pass total (4 + 5).

- [ ] **Step 5: Commit**

```bash
git add skills/jared/scripts/lib/ties.py tests/test_ties_analyzers.py
git commit -m "feat(ties): analyze_milestone_overlap — same-milestone strong signal (#77)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: Implement `analyze_cross_references` (forward + bidirectional)

Most subtle of the analyzers. Must:
- Find `#N` mentions with word-boundary regex (so `v1.0` is not `#0`).
- Skip `#N` inside fenced code blocks (```).
- Support `direction` parameter — `forward` only checks target body; `both` also checks each related body for target mentions.

**Files:**
- Modify: `skills/jared/scripts/lib/ties.py`
- Modify: `tests/test_ties_analyzers.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_ties_analyzers.py`:

```python
from skills.jared.scripts.lib.ties import analyze_cross_references


class TestAnalyzeCrossReferences:
    def test_target_body_mentions_other_fires_forward(self) -> None:
        target = _make_issue(1, body="See #42 for context.")
        others = [_make_issue(42)]
        hits = analyze_cross_references(target, others, direction="forward")
        assert len(hits) == 1
        assert hits[0].related_n == 42
        assert hits[0].confidence == "strong"

    def test_other_body_mentions_target_fires_both(self) -> None:
        target = _make_issue(1)
        others = [_make_issue(42, body="Follow-up to #1 — see there.")]
        hits = analyze_cross_references(target, others, direction="both")
        assert len(hits) == 1
        assert hits[0].related_n == 42

    def test_other_body_mentions_target_does_not_fire_forward_only(self) -> None:
        target = _make_issue(1)
        others = [_make_issue(42, body="Follow-up to #1.")]
        hits = analyze_cross_references(target, others, direction="forward")
        assert hits == []

    def test_default_direction_is_both(self) -> None:
        target = _make_issue(1)
        others = [_make_issue(42, body="See #1.")]
        hits = analyze_cross_references(target, others)
        assert len(hits) == 1

    def test_ignores_references_in_fenced_code_blocks(self) -> None:
        target = _make_issue(
            1,
            body="```\ndef foo():\n    return #42  # not a real ref\n```\n",
        )
        others = [_make_issue(42)]
        hits = analyze_cross_references(target, others, direction="forward")
        assert hits == []

    def test_word_boundary_required(self) -> None:
        """`v1.0` should not match as `#0`; `1#42` should not match."""
        target = _make_issue(1, body="version v1.0 ships and item123#42 is unrelated")
        others = [_make_issue(42)]
        hits = analyze_cross_references(target, others, direction="forward")
        assert hits == []

    def test_self_is_never_a_hit(self) -> None:
        target = _make_issue(1, body="see #1")
        others = [_make_issue(1)]
        hits = analyze_cross_references(target, others)
        assert hits == []

    def test_dedupe_multiple_mentions_of_same_issue(self) -> None:
        target = _make_issue(1, body="See #42, again #42, also #42.")
        others = [_make_issue(42)]
        hits = analyze_cross_references(target, others, direction="forward")
        assert len(hits) == 1  # one hit per related, not per mention
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_ties_analyzers.py::TestAnalyzeCrossReferences -v`
Expected: FAIL with `ImportError: cannot import name 'analyze_cross_references'`.

- [ ] **Step 3: Write minimal implementation**

Append to `skills/jared/scripts/lib/ties.py`:

```python
import re

# Match #N with word boundary, where N is a positive integer.
# Not preceded by an alphanumeric (so item123#42 doesn't match) and N is
# captured. Trailing word boundary handles ", " or end-of-line cleanly.
_ISSUE_REF_RE = re.compile(r"(?<![A-Za-z0-9])#(\d+)\b")


def _strip_fenced_code(text: str) -> str:
    """Remove triple-fenced code blocks so #N inside code doesn't count."""
    return re.sub(r"```.*?```", "", text, flags=re.DOTALL)


def _refs_in_body(body: str) -> set[int]:
    """Return the set of #N references in body, excluding fenced code blocks."""
    if not body:
        return set()
    cleaned = _strip_fenced_code(body)
    return {int(m.group(1)) for m in _ISSUE_REF_RE.finditer(cleaned)}


def analyze_cross_references(
    target: OpenIssueForTies,
    open_issues: list[OpenIssueForTies],
    *,
    direction: Literal["forward", "both"] = "both",
) -> list[SignalHit]:
    """Strong signal: target body mentions #N (forward) or #N body mentions
    target (reverse). Reverse direction skipped when direction='forward'
    (used in low-budget partial mode where other-issue bodies aren't fetched).

    `#N` inside fenced code blocks is ignored. Word-boundary required so
    `v1.0` is not `#0`. Multiple mentions of the same issue produce one hit.
    """
    target_refs = _refs_in_body(target.body)
    hits: list[SignalHit] = []
    seen: set[int] = set()

    for related in open_issues:
        if related.number == target.number or related.number in seen:
            continue
        # Forward: target body → related?
        if related.number in target_refs:
            hits.append(
                SignalHit(
                    related_n=related.number,
                    name="cross_ref",
                    confidence="strong",
                    evidence=f"target #{target.number} body mentions #{related.number}",
                )
            )
            seen.add(related.number)
            continue
        # Reverse: related body → target?
        if direction == "both":
            related_refs = _refs_in_body(related.body)
            if target.number in related_refs:
                hits.append(
                    SignalHit(
                        related_n=related.number,
                        name="cross_ref",
                        confidence="strong",
                        evidence=f"#{related.number} body mentions target #{target.number}",
                    )
                )
                seen.add(related.number)

    return hits
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_ties_analyzers.py -v && ruff check . && mypy skills/jared/scripts/lib/ties.py`
Expected: 17 tests pass total (9 + 8).

- [ ] **Step 5: Commit**

```bash
git add skills/jared/scripts/lib/ties.py tests/test_ties_analyzers.py
git commit -m "feat(ties): analyze_cross_references — bidirectional #N signal (#77)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: Implement `analyze_labels` (with stop-words)

**Files:**
- Modify: `skills/jared/scripts/lib/ties.py`
- Modify: `tests/test_ties_analyzers.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_ties_analyzers.py`:

```python
from skills.jared.scripts.lib.ties import analyze_labels


class TestAnalyzeLabels:
    def test_shared_non_stop_word_label_fires(self) -> None:
        target = _make_issue(1, labels=("perf",))
        others = [_make_issue(2, labels=("perf",))]
        hits = analyze_labels(target, others, stop_words=frozenset({"enhancement"}))
        assert len(hits) == 1
        assert hits[0].related_n == 2
        assert hits[0].confidence == "weak"
        assert hits[0].name == "labels"
        assert "perf" in hits[0].evidence

    def test_only_stop_word_overlap_no_hit(self) -> None:
        target = _make_issue(1, labels=("enhancement",))
        others = [_make_issue(2, labels=("enhancement",))]
        hits = analyze_labels(target, others, stop_words=frozenset({"enhancement"}))
        assert hits == []

    def test_partial_overlap_with_stop_word_still_fires_on_non_stop(self) -> None:
        target = _make_issue(1, labels=("enhancement", "perf"))
        others = [_make_issue(2, labels=("enhancement", "perf"))]
        hits = analyze_labels(target, others, stop_words=frozenset({"enhancement"}))
        assert len(hits) == 1
        assert "perf" in hits[0].evidence

    def test_no_label_overlap_no_hit(self) -> None:
        target = _make_issue(1, labels=("perf",))
        others = [_make_issue(2, labels=("docs",))]
        hits = analyze_labels(target, others, stop_words=frozenset())
        assert hits == []

    def test_target_no_labels_no_hit(self) -> None:
        target = _make_issue(1, labels=())
        others = [_make_issue(2, labels=("perf",))]
        hits = analyze_labels(target, others, stop_words=frozenset())
        assert hits == []

    def test_self_is_never_a_hit(self) -> None:
        target = _make_issue(1, labels=("perf",))
        others = [_make_issue(1, labels=("perf",))]
        hits = analyze_labels(target, others, stop_words=frozenset())
        assert hits == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_ties_analyzers.py::TestAnalyzeLabels -v`
Expected: FAIL with `ImportError: cannot import name 'analyze_labels'`.

- [ ] **Step 3: Write minimal implementation**

Append to `skills/jared/scripts/lib/ties.py`:

```python
def analyze_labels(
    target: OpenIssueForTies,
    open_issues: list[OpenIssueForTies],
    *,
    stop_words: frozenset[str],
) -> list[SignalHit]:
    """Weak signal: shared non-stop-word label between target and related.

    Stop-words are common type labels (enhancement, bug, ...) that fire on
    nearly every issue and would drown the signal. Caller passes the
    project-specific set; defaults are in DEFAULT_LABEL_STOP_WORDS.
    """
    target_labels = frozenset(target.labels) - stop_words
    if not target_labels:
        return []
    hits: list[SignalHit] = []
    for related in open_issues:
        if related.number == target.number:
            continue
        related_labels = frozenset(related.labels) - stop_words
        shared = target_labels & related_labels
        if shared:
            shared_list = sorted(shared)
            hits.append(
                SignalHit(
                    related_n=related.number,
                    name="labels",
                    confidence="weak",
                    evidence=f"shares non-stop-word label(s): {', '.join(shared_list)}",
                )
            )
    return hits
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_ties_analyzers.py -v && ruff check . && mypy skills/jared/scripts/lib/ties.py`
Expected: 23 tests pass total.

- [ ] **Step 5: Commit**

```bash
git add skills/jared/scripts/lib/ties.py tests/test_ties_analyzers.py
git commit -m "feat(ties): analyze_labels — non-stop-word label intersection (#77)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 6: Implement `analyze_title_tokens`

Title token Jaccard with stop-word stripping.

**Files:**
- Modify: `skills/jared/scripts/lib/ties.py`
- Modify: `tests/test_ties_analyzers.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_ties_analyzers.py`:

```python
from skills.jared.scripts.lib.ties import analyze_title_tokens


class TestAnalyzeTitleTokens:
    def test_strong_token_overlap_fires(self) -> None:
        target = _make_issue(1, title="perf(file): batched mutations for jared file")
        others = [_make_issue(2, title="perf(file): on-disk snapshot cache for jared")]
        hits = analyze_title_tokens(target, others)
        assert len(hits) == 1
        assert hits[0].related_n == 2
        assert hits[0].confidence == "weak"

    def test_weak_overlap_no_hit_below_threshold(self) -> None:
        """A single common token (esp. a stop-word like 'for') shouldn't fire."""
        target = _make_issue(1, title="add cache for jared file")
        others = [_make_issue(2, title="rewrite docs for findajob")]
        hits = analyze_title_tokens(target, others)
        assert hits == []

    def test_case_insensitive(self) -> None:
        target = _make_issue(1, title="Cache GraphQL Calls")
        others = [_make_issue(2, title="cache graphql responses across runs")]
        hits = analyze_title_tokens(target, others)
        assert len(hits) == 1

    def test_self_is_never_a_hit(self) -> None:
        target = _make_issue(1, title="perf(file): batched mutations")
        others = [_make_issue(1, title="perf(file): batched mutations")]
        hits = analyze_title_tokens(target, others)
        assert hits == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_ties_analyzers.py::TestAnalyzeTitleTokens -v`
Expected: FAIL with `ImportError: cannot import name 'analyze_title_tokens'`.

- [ ] **Step 3: Write minimal implementation**

Append to `skills/jared/scripts/lib/ties.py`:

```python
# Title-token stop-words: common English connectors that produce noise.
_TITLE_STOP_WORDS: frozenset[str] = frozenset(
    {
        "a", "an", "the", "and", "or", "but", "for", "of", "to",
        "in", "on", "at", "by", "with", "from", "into", "is", "be",
        "as", "it", "this", "that", "these", "those", "make", "add",
    }
)

# Minimum number of shared non-stop-word tokens to fire the signal.
_TITLE_TOKEN_OVERLAP_MIN = 2


def _tokenize_title(title: str) -> frozenset[str]:
    """Lowercase, drop punctuation, split, drop stop-words, drop length-1 tokens."""
    cleaned = re.sub(r"[^a-z0-9\s]+", " ", title.lower())
    return frozenset(
        tok for tok in cleaned.split()
        if len(tok) > 1 and tok not in _TITLE_STOP_WORDS
    )


def analyze_title_tokens(
    target: OpenIssueForTies, open_issues: list[OpenIssueForTies]
) -> list[SignalHit]:
    """Weak signal: target and related share at least N non-stop-word title tokens.

    Case-insensitive; punctuation stripped; stop-words removed.
    """
    target_toks = _tokenize_title(target.title)
    if len(target_toks) < _TITLE_TOKEN_OVERLAP_MIN:
        return []
    hits: list[SignalHit] = []
    for related in open_issues:
        if related.number == target.number:
            continue
        related_toks = _tokenize_title(related.title)
        shared = target_toks & related_toks
        if len(shared) >= _TITLE_TOKEN_OVERLAP_MIN:
            shared_list = sorted(shared)
            hits.append(
                SignalHit(
                    related_n=related.number,
                    name="title_tokens",
                    confidence="weak",
                    evidence=f"shares title tokens: {', '.join(shared_list)}",
                )
            )
    return hits
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_ties_analyzers.py -v && ruff check . && mypy skills/jared/scripts/lib/ties.py`
Expected: 27 tests pass total.

- [ ] **Step 5: Commit**

```bash
git add skills/jared/scripts/lib/ties.py tests/test_ties_analyzers.py
git commit -m "feat(ties): analyze_title_tokens — Jaccard-style title overlap (#77)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 7: Implement `analyze_file_paths`

Detects same-file polish bundling. Both bodies must mention the same file path. Generic substrings excluded.

**Files:**
- Modify: `skills/jared/scripts/lib/ties.py`
- Modify: `tests/test_ties_analyzers.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_ties_analyzers.py`:

```python
from skills.jared.scripts.lib.ties import analyze_file_paths


class TestAnalyzeFilePaths:
    def test_shared_python_file_fires(self) -> None:
        target = _make_issue(1, body="Touches `lib/board.py:380`.")
        others = [_make_issue(2, body="Polish for `lib/board.py`.")]
        hits = analyze_file_paths(target, others)
        assert len(hits) == 1
        assert hits[0].related_n == 2
        assert hits[0].confidence == "medium"
        assert "lib/board.py" in hits[0].evidence

    def test_shared_markdown_file_fires(self) -> None:
        target = _make_issue(1, body="See `docs/superpowers/specs/foo.md`.")
        others = [_make_issue(2, body="Update `docs/superpowers/specs/foo.md`.")]
        hits = analyze_file_paths(target, others)
        assert len(hits) == 1

    def test_generic_filename_excluded(self) -> None:
        """README, CHANGELOG, etc. are too generic to be tie-relevant."""
        target = _make_issue(1, body="Update README and CHANGELOG.")
        others = [_make_issue(2, body="Touch README.")]
        hits = analyze_file_paths(target, others)
        assert hits == []

    def test_no_overlap_no_hit(self) -> None:
        target = _make_issue(1, body="Touches `lib/board.py`.")
        others = [_make_issue(2, body="Touches `lib/ties.py`.")]
        hits = analyze_file_paths(target, others)
        assert hits == []

    def test_target_no_paths_no_hit(self) -> None:
        target = _make_issue(1, body="No file mentions here.")
        others = [_make_issue(2, body="Touches `lib/board.py`.")]
        hits = analyze_file_paths(target, others)
        assert hits == []

    def test_self_is_never_a_hit(self) -> None:
        target = _make_issue(1, body="Touches `lib/board.py`.")
        others = [_make_issue(1, body="Touches `lib/board.py`.")]
        hits = analyze_file_paths(target, others)
        assert hits == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_ties_analyzers.py::TestAnalyzeFilePaths -v`
Expected: FAIL with `ImportError: cannot import name 'analyze_file_paths'`.

- [ ] **Step 3: Write minimal implementation**

Append to `skills/jared/scripts/lib/ties.py`:

```python
# Path-like token: at least one '/' or a recognized file extension, with
# common code/doc extensions. Generic single-word names like README are
# excluded by requiring either a slash or an extension.
_FILE_PATH_RE = re.compile(
    r"(?<![A-Za-z0-9])"
    r"([A-Za-z0-9_.\-]+(?:/[A-Za-z0-9_.\-]+)+\.[a-z]+|"
    r"[A-Za-z0-9_.\-]+\.(?:py|md|ts|tsx|js|jsx|go|rs|java|sh|toml|yaml|yml|json))"
    r"(?:[:#]\d+)?"
    r"(?![A-Za-z0-9])"
)

# Filenames that are too generic to count as tie-relevant.
_GENERIC_FILES: frozenset[str] = frozenset(
    {"README.md", "CHANGELOG.md", "LICENSE", "TODO.md", "NOTES.md"}
)


def _file_paths_in_body(body: str) -> frozenset[str]:
    """Extract path-like tokens from body. Generic filenames excluded."""
    if not body:
        return frozenset()
    paths = {m.group(1) for m in _FILE_PATH_RE.finditer(body)}
    return frozenset(p for p in paths if p not in _GENERIC_FILES)


def analyze_file_paths(
    target: OpenIssueForTies, open_issues: list[OpenIssueForTies]
) -> list[SignalHit]:
    """Medium signal: target and related body both mention the same file path.

    Path-like tokens require a slash OR a code/doc file extension. Generic
    filenames (README, CHANGELOG, etc.) are excluded. Requires bodies on
    both sides — caller skips this analyzer in low-budget partial mode.
    """
    target_paths = _file_paths_in_body(target.body)
    if not target_paths:
        return []
    hits: list[SignalHit] = []
    for related in open_issues:
        if related.number == target.number:
            continue
        related_paths = _file_paths_in_body(related.body)
        shared = target_paths & related_paths
        if shared:
            shared_list = sorted(shared)
            hits.append(
                SignalHit(
                    related_n=related.number,
                    name="file_paths",
                    confidence="medium",
                    evidence=f"both bodies mention: {', '.join(shared_list)}",
                )
            )
    return hits
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_ties_analyzers.py -v && ruff check . && mypy skills/jared/scripts/lib/ties.py`
Expected: 33 tests pass total.

- [ ] **Step 5: Commit**

```bash
git add skills/jared/scripts/lib/ties.py tests/test_ties_analyzers.py
git commit -m "feat(ties): analyze_file_paths — same-file body-mention signal (#77)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 8: Implement `combine` + threshold + sort + cap + suggested-action

**Files:**
- Modify: `skills/jared/scripts/lib/ties.py`
- Test: `tests/test_ties_combine.py` (create)

- [ ] **Step 1: Write the failing test**

`tests/test_ties_combine.py`:

```python
"""Tests for combine() — threshold, sort, cap, suggested-action mapping."""

from skills.jared.scripts.lib.ties import (
    OpenIssueForTies,
    SignalHit,
    Tie,
    combine,
)


def _hit(
    related_n: int,
    name: str,
    confidence: str = "strong",
    evidence: str = "",
) -> SignalHit:
    return SignalHit(
        related_n=related_n,
        name=name,  # type: ignore[arg-type]
        confidence=confidence,  # type: ignore[arg-type]
        evidence=evidence or f"{name} fired for #{related_n}",
    )


def _open_issues(*pairs: tuple[int, str]) -> list[OpenIssueForTies]:
    return [
        OpenIssueForTies(
            number=n,
            title=t,
            body="",
            labels=(),
            milestone=None,
            status="Backlog",
            priority="Medium",
            blocked_by=(),
        )
        for n, t in pairs
    ]


def _target() -> OpenIssueForTies:
    return OpenIssueForTies(
        number=1,
        title="target",
        body="",
        labels=(),
        milestone=None,
        status="In Progress",
        priority="High",
        blocked_by=(),
    )


class TestCombineThreshold:
    def test_single_strong_at_medium_surfaces(self) -> None:
        hits = [_hit(2, "milestone", "strong")]
        ties = combine(hits, "medium", _target(), _open_issues((2, "B")))
        assert len(ties) == 1

    def test_single_strong_at_strong_surfaces(self) -> None:
        hits = [_hit(2, "milestone", "strong")]
        ties = combine(hits, "strong", _target(), _open_issues((2, "B")))
        assert len(ties) == 1

    def test_two_weak_at_weak_surfaces(self) -> None:
        hits = [
            _hit(2, "title_tokens", "weak"),
            _hit(2, "labels", "weak"),
        ]
        ties = combine(hits, "weak", _target(), _open_issues((2, "B")))
        assert len(ties) == 1

    def test_two_weak_at_medium_does_not_surface(self) -> None:
        hits = [
            _hit(2, "title_tokens", "weak"),
            _hit(2, "labels", "weak"),
        ]
        ties = combine(hits, "medium", _target(), _open_issues((2, "B")))
        assert ties == []

    def test_medium_plus_weak_at_medium_surfaces(self) -> None:
        """combined = 2 + 1 = 3 ≥ 3."""
        hits = [
            _hit(2, "file_paths", "medium"),
            _hit(2, "labels", "weak"),
        ]
        ties = combine(hits, "medium", _target(), _open_issues((2, "B")))
        assert len(ties) == 1

    def test_medium_plus_weak_at_strong_does_not_surface(self) -> None:
        """combined = 3 but no strong-signal hit → fails strict-strong gate."""
        hits = [
            _hit(2, "file_paths", "medium"),
            _hit(2, "labels", "weak"),
        ]
        ties = combine(hits, "strong", _target(), _open_issues((2, "B")))
        assert ties == []


class TestCombineSortAndCap:
    def test_sort_by_combined_score_desc_then_number_asc(self) -> None:
        hits = [
            _hit(20, "milestone", "strong"),  # combined 3
            _hit(10, "milestone", "strong"),  # combined 3 (lower number first)
            _hit(30, "milestone", "strong"),
            _hit(30, "file_paths", "medium"),  # combined 5
        ]
        ties = combine(
            hits, "medium", _target(),
            _open_issues((10, "B"), (20, "C"), (30, "D"))
        )
        assert [t.related_n for t in ties] == [30, 10, 20]

    def test_cap_at_8(self) -> None:
        hits = [_hit(n, "milestone", "strong") for n in range(2, 20)]  # 18 candidates
        issues = _open_issues(*[(n, f"I{n}") for n in range(2, 20)])
        ties = combine(hits, "medium", _target(), issues)
        assert len(ties) == 8


class TestCombineMultiRelationship:
    def test_primary_is_strongest_signal(self) -> None:
        hits = [
            _hit(2, "milestone", "strong"),
            _hit(2, "file_paths", "medium"),
        ]
        ties = combine(hits, "medium", _target(), _open_issues((2, "B")))
        assert ties[0].primary_relationship == "milestone-mate"
        assert "same-file" in ties[0].secondary_relationships

    def test_score_capped_at_max(self) -> None:
        hits = [
            _hit(2, "cross_ref", "strong"),
            _hit(2, "blocked_by", "strong"),
            _hit(2, "milestone", "strong"),
            _hit(2, "file_paths", "medium"),
            _hit(2, "title_tokens", "weak"),
            _hit(2, "labels", "weak"),
        ]
        ties = combine(hits, "weak", _target(), _open_issues((2, "B")))
        assert ties[0].combined_score == 5  # MAX_COMBINED_SCORE


class TestSuggestedAction:
    def test_blocked_by_target_blocks_related(self) -> None:
        target = OpenIssueForTies(
            number=1, title="t", body="", labels=(), milestone=None,
            status="In Progress", priority="High", blocked_by=(2,),
        )
        hits = [
            _hit(2, "blocked_by", "strong",
                 evidence="target #1 is blocked by #2"),
        ]
        ties = combine(hits, "medium", target, _open_issues((2, "B")))
        assert "sequence" in ties[0].suggested_action.lower()

    def test_milestone_only_action(self) -> None:
        hits = [_hit(2, "milestone", "strong")]
        ties = combine(hits, "medium", _target(), _open_issues((2, "B")))
        assert "bundling" in ties[0].suggested_action.lower()

    def test_file_paths_action(self) -> None:
        hits = [_hit(2, "file_paths", "medium")]
        ties = combine(hits, "weak", _target(), _open_issues((2, "B")))
        assert "fold" in ties[0].suggested_action.lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_ties_combine.py -v`
Expected: FAIL with `ImportError: cannot import name 'combine'`.

- [ ] **Step 3: Write minimal implementation**

Append to `skills/jared/scripts/lib/ties.py`:

```python
# Map signal name → human-readable relationship label (used as primary +
# secondary_relationships in the Tie). Suggested action is derived separately
# below.
_RELATIONSHIP_LABELS: dict[SignalName, str] = {
    "cross_ref": "cross-ref",
    "blocked_by": "blocker",
    "milestone": "milestone-mate",
    "file_paths": "same-file",
    "title_tokens": "adjacent",
    "labels": "adjacent",
}


def _suggested_action(
    primary: SignalName,
    target: OpenIssueForTies,
    related_n: int,
    hits: tuple[SignalHit, ...],
) -> str:
    """Heuristic suggested-action mapping. Heuristic, not gospel — the
    output block carries a header note saying so."""
    if primary == "blocked_by":
        # Direction matters: did target block related, or related block target?
        for h in hits:
            if h.name == "blocked_by":
                if related_n in target.blocked_by:
                    return f"blocking — sequence #{related_n} first"
                return "unblocked by target — flag in PR"
        return "blocking — sequence first"
    if primary == "cross_ref":
        return "review for bundling vs separate"
    if primary == "milestone":
        return "bundling vs fast-follow — your call"
    if primary == "file_paths":
        return "fold into target's PR"
    # title_tokens or labels
    return "review for bundling vs separate"


def combine(
    hits: list[SignalHit],
    threshold: Threshold,
    target: OpenIssueForTies,
    open_issues: list[OpenIssueForTies],
) -> list[Tie]:
    """Group hits by related_n, compute combined_score (capped), apply
    threshold, derive primary/secondary relationships + suggested action,
    sort by score desc + number asc, cap at MAX_TIES_DISPLAYED.
    """
    # Group hits by related_n.
    by_related: dict[int, list[SignalHit]] = {}
    for h in hits:
        by_related.setdefault(h.related_n, []).append(h)

    # Lookup for related issue metadata.
    by_number = {i.number: i for i in open_issues}

    candidates: list[Tie] = []
    for related_n, related_hits in by_related.items():
        if related_n not in by_number:
            continue  # related issue isn't in the open set (race)
        related = by_number[related_n]

        score = min(
            sum(CONFIDENCE_WEIGHT[h.confidence] for h in related_hits),
            MAX_COMBINED_SCORE,
        )

        if not _passes_threshold(score, related_hits, threshold):
            continue

        # Sort hits strong → weak so primary is the strongest signal.
        # Within same confidence, keep stable order.
        sorted_hits = sorted(
            related_hits, key=lambda h: -CONFIDENCE_WEIGHT[h.confidence]
        )
        primary_signal = sorted_hits[0].name
        primary_label = _RELATIONSHIP_LABELS[primary_signal]
        secondary_labels: list[str] = []
        seen_labels = {primary_label}
        for h in sorted_hits[1:]:
            label = _RELATIONSHIP_LABELS[h.name]
            if label not in seen_labels:
                secondary_labels.append(label)
                seen_labels.add(label)

        suggested = _suggested_action(
            primary_signal, target, related_n, tuple(sorted_hits)
        )

        candidates.append(
            Tie(
                related_n=related_n,
                related_title=related.title,
                related_status=related.status,
                hits=tuple(sorted_hits),
                combined_score=score,
                primary_relationship=primary_label,
                secondary_relationships=tuple(secondary_labels),
                suggested_action=suggested,
            )
        )

    # Sort: combined_score desc, then related_n asc.
    candidates.sort(key=lambda t: (-t.combined_score, t.related_n))
    return candidates[:MAX_TIES_DISPLAYED]


def _passes_threshold(
    score: int, hits: list[SignalHit], threshold: Threshold
) -> bool:
    if threshold == "weak":
        return score >= 1
    if threshold == "medium":
        return score >= 3
    # threshold == "strong"
    return score >= 3 and any(h.confidence == "strong" for h in hits)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_ties_combine.py -v && ruff check . && mypy skills/jared/scripts/lib/ties.py`
Expected: all combine tests pass.

- [ ] **Step 5: Commit**

```bash
git add skills/jared/scripts/lib/ties.py tests/test_ties_combine.py
git commit -m "feat(ties): combine — threshold, sort, cap, suggested actions (#77)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 9: Implement `format_ties_block` (golden tests)

**Files:**
- Modify: `skills/jared/scripts/lib/ties.py`
- Test: `tests/test_ties_format.py` (create)

- [ ] **Step 1: Write the failing test**

`tests/test_ties_format.py`:

```python
"""Golden output tests for format_ties_block()."""

from skills.jared.scripts.lib.ties import SignalHit, Tie, format_ties_block


def _tie(
    related_n: int,
    title: str = "Some related issue",
    *,
    confidence: str = "strong",
    primary: str = "cross-ref",
    secondaries: tuple[str, ...] = (),
    score: int = 3,
    action: str = "review for bundling vs separate",
) -> Tie:
    return Tie(
        related_n=related_n,
        related_title=title,
        related_status="Backlog",
        hits=(
            SignalHit(
                related_n=related_n,
                name="cross_ref",  # type: ignore[arg-type]
                confidence=confidence,  # type: ignore[arg-type]
                evidence="",
            ),
        ),
        combined_score=score,
        primary_relationship=primary,
        secondary_relationships=secondaries,
        suggested_action=action,
    )


def test_empty_returns_empty_string() -> None:
    assert format_ties_block([], degraded=False, diagnostic=None) == ""


def test_single_tie_no_secondaries() -> None:
    out = format_ties_block(
        [_tie(212, primary="superseded",
              action="close as superseded after target ships")],
        degraded=False,
        diagnostic=None,
    )
    assert "Ties to consider:" in out
    assert (
        "  #212 [strong, superseded]   "
        "close as superseded after target ships" in out
    )
    assert "(Suggestions are heuristic — operator decides.)" in out


def test_tie_with_secondaries_shows_parenthetical() -> None:
    out = format_ties_block(
        [_tie(372, primary="adjacent", secondaries=("same-file",),
              action="bundling vs fast-follow — your call")],
        degraded=False,
        diagnostic=None,
    )
    assert "(also same-file)" in out


def test_tie_with_no_secondaries_no_parenthetical() -> None:
    out = format_ties_block(
        [_tie(212, primary="cross-ref")],
        degraded=False,
        diagnostic=None,
    )
    assert "(also" not in out


def test_degraded_mode_includes_diagnostic() -> None:
    out = format_ties_block(
        [_tie(212)],
        degraded=True,
        diagnostic="(low GraphQL budget — body-aware signals deferred)",
    )
    assert "(low GraphQL budget" in out


def test_diagnostic_only_no_ties() -> None:
    """When ties is empty but a diagnostic is set, render diagnostic alone."""
    out = format_ties_block(
        [],
        degraded=False,
        diagnostic="(GraphQL budget exhausted — ties analysis skipped)",
    )
    assert out == "(GraphQL budget exhausted — ties analysis skipped)"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_ties_format.py -v`
Expected: FAIL with `ImportError: cannot import name 'format_ties_block'`.

- [ ] **Step 3: Write minimal implementation**

Append to `skills/jared/scripts/lib/ties.py`:

```python
def format_ties_block(
    ties: list[Tie], *, degraded: bool, diagnostic: str | None
) -> str:
    """Render the locked compact output shape for the announce block.

    Empty ties + no diagnostic → empty string (signals "suppress block" to
    the skill). Empty ties + diagnostic → diagnostic alone. Non-empty ties
    → header + line-per-tie + footer note + optional diagnostic.
    """
    if not ties and not diagnostic:
        return ""
    if not ties and diagnostic:
        return diagnostic

    lines: list[str] = ["Ties to consider:"]
    for t in ties:
        line = (
            f"  #{t.related_n} [{t.hits[0].confidence}, {t.primary_relationship}]"
            f"   {t.suggested_action}"
        )
        if t.secondary_relationships:
            secondaries = ", ".join(t.secondary_relationships)
            line = f"{line}  (also {secondaries})"
        lines.append(line)
    lines.append("  (Suggestions are heuristic — operator decides.)")
    if diagnostic:
        lines.append(f"  {diagnostic}")
    return "\n".join(lines)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_ties_format.py -v && ruff check . && mypy skills/jared/scripts/lib/ties.py`
Expected: 6 tests pass.

- [ ] **Step 5: Commit**

```bash
git add skills/jared/scripts/lib/ties.py tests/test_ties_format.py
git commit -m "feat(ties): format_ties_block — compact one-liner output (#77)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 10: Add `Board.tie_stop_words()`

Reads `### Tie Analysis` section from `docs/project-board.md` for project-specific stop-words; falls back to defaults.

**Files:**
- Modify: `skills/jared/scripts/lib/board.py` (add method)
- Test: `tests/test_board.py` (append test class) — or create new `tests/test_board_tie_stop_words.py`. Use an append.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_board.py`:

```python
def test_tie_stop_words_uses_project_override(tmp_path: Path) -> None:
    """If docs/project-board.md has a `### Tie Analysis` section with a
    `- Label stop-words: x, y, z` bullet, those override the built-in defaults."""
    from skills.jared.scripts.lib.board import Board
    from skills.jared.scripts.lib.ties import DEFAULT_LABEL_STOP_WORDS

    doc = tmp_path / "project-board.md"
    doc.write_text(
        "# Project\n\n"
        "- Project URL: https://github.com/users/x/projects/1\n"
        "- Project number: 1\n"
        "- Project ID: PVT_x\n"
        "- Owner: x\n"
        "- Repo: x/y\n\n"
        "### Status\n- Field ID: F1\n- Backlog: A\n- Up Next: B\n"
        "- In Progress: C\n- Blocked: D\n- Done: E\n\n"
        "### Priority\n- Field ID: F2\n- High: H\n- Medium: M\n- Low: L\n\n"
        "### Tie Analysis\n- Label stop-words: chore, wip, draft\n"
    )
    board = Board.from_path(doc)
    assert board.tie_stop_words() == frozenset({"chore", "wip", "draft"})
    # Defaults are not merged in — override is total.
    assert "enhancement" not in board.tie_stop_words()


def test_tie_stop_words_falls_back_to_defaults(tmp_path: Path) -> None:
    """No `### Tie Analysis` section → use ties.DEFAULT_LABEL_STOP_WORDS."""
    from skills.jared.scripts.lib.board import Board
    from skills.jared.scripts.lib.ties import DEFAULT_LABEL_STOP_WORDS

    doc = tmp_path / "project-board.md"
    doc.write_text(
        "# Project\n\n"
        "- Project URL: https://github.com/users/x/projects/1\n"
        "- Project number: 1\n"
        "- Project ID: PVT_x\n"
        "- Owner: x\n"
        "- Repo: x/y\n\n"
        "### Status\n- Field ID: F1\n- Backlog: A\n- Up Next: B\n"
        "- In Progress: C\n- Blocked: D\n- Done: E\n\n"
        "### Priority\n- Field ID: F2\n- High: H\n- Medium: M\n- Low: L\n"
    )
    board = Board.from_path(doc)
    assert board.tie_stop_words() == DEFAULT_LABEL_STOP_WORDS
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_board.py::test_tie_stop_words_uses_project_override tests/test_board.py::test_tie_stop_words_falls_back_to_defaults -v`
Expected: FAIL with `AttributeError: 'Board' object has no attribute 'tie_stop_words'`.

- [ ] **Step 3: Write minimal implementation**

Add to `skills/jared/scripts/lib/board.py`, near the other parsing methods on `Board` (and import `ties` lazily to avoid circulars):

```python
def tie_stop_words(self) -> frozenset[str]:
    """Project-specific label stop-words for ties analysis.

    Reads `### Tie Analysis` section from project-board.md if present:

        ### Tie Analysis
        - Label stop-words: foo, bar, baz

    Falls back to ties.DEFAULT_LABEL_STOP_WORDS otherwise. Override is
    total — defaults are NOT merged with project-specific words.
    """
    from skills.jared.scripts.lib.ties import DEFAULT_LABEL_STOP_WORDS

    text = self._raw_doc  # the verbatim project-board.md content
    # Find the heading.
    section_re = re.compile(
        r"^###\s+Tie Analysis\s*$(?P<body>.*?)(?=^###\s|\Z)",
        re.MULTILINE | re.DOTALL,
    )
    match = section_re.search(text)
    if not match:
        return DEFAULT_LABEL_STOP_WORDS
    bullet_re = re.compile(
        r"^\s*-\s*Label stop-words:\s*(?P<words>.+?)\s*$", re.MULTILINE
    )
    bullet_match = bullet_re.search(match.group("body"))
    if not bullet_match:
        return DEFAULT_LABEL_STOP_WORDS
    words = [w.strip() for w in bullet_match.group("words").split(",")]
    return frozenset(w for w in words if w)
```

Note: this requires `Board` to expose `_raw_doc` (the original text). If `Board.from_path` already stores the parsed content in a different attribute, adapt — read `lib/board.py` first to find the right field. If no raw text is stored, store it during `from_path`:

```python
@classmethod
def from_path(cls, path: Path) -> "Board":
    text = path.read_text()
    # ... existing parsing ...
    board = cls(...)  # existing
    board._raw_doc = text
    return board
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_board.py -v && ruff check . && mypy skills/jared/scripts/lib/board.py`
Expected: all board tests pass including the two new ones.

- [ ] **Step 5: Commit**

```bash
git add skills/jared/scripts/lib/board.py tests/test_board.py
git commit -m "feat(board): tie_stop_words() — project-board.md override hook (#77)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 11: Add `Board.fetch_open_issues_for_ties()`

Single batched GraphQL query, cached 5min, body-optional via `include_bodies`.

**Files:**
- Modify: `skills/jared/scripts/lib/board.py`
- Test: `tests/test_board_fetch_for_ties.py` (create)

- [ ] **Step 1: Write the failing test**

`tests/test_board_fetch_for_ties.py`:

```python
"""Tests for Board.fetch_open_issues_for_ties()."""

from pathlib import Path
from typing import Any
from unittest.mock import patch

from skills.jared.scripts.lib.board import Board
from skills.jared.scripts.lib.ties import OpenIssueForTies


def _board(tmp_path: Path) -> Board:
    doc = tmp_path / "project-board.md"
    doc.write_text(
        "# X\n\n"
        "- Project URL: https://github.com/users/x/projects/1\n"
        "- Project number: 1\n"
        "- Project ID: PVT_x\n"
        "- Owner: x\n"
        "- Repo: x/y\n\n"
        "### Status\n- Field ID: F1\n- Backlog: A\n- Up Next: B\n"
        "- In Progress: C\n- Blocked: D\n- Done: E\n\n"
        "### Priority\n- Field ID: F2\n- High: H\n- Medium: M\n- Low: L\n"
    )
    return Board.from_path(doc)


_GRAPHQL_RESPONSE_FULL: dict[str, Any] = {
    "data": {
        "repository": {
            "issues": {
                "nodes": [
                    {
                        "number": 10,
                        "title": "Issue 10",
                        "body": "Mentions #20",
                        "labels": {"nodes": [{"name": "perf"}, {"name": "enhancement"}]},
                        "milestone": {"title": "Phase 2 — perf settled"},
                        "projectItems": {
                            "nodes": [
                                {
                                    "fieldValueByName": {"name": "Backlog"},
                                    "priority": {"name": "Medium"},
                                }
                            ]
                        },
                        "trackedInIssues": {"nodes": []},
                    },
                    {
                        "number": 20,
                        "title": "Issue 20",
                        "body": "follow-up",
                        "labels": {"nodes": []},
                        "milestone": None,
                        "projectItems": {"nodes": [
                            {"fieldValueByName": {"name": "Backlog"},
                             "priority": {"name": "Low"}}
                        ]},
                        "trackedInIssues": {"nodes": [{"number": 10}]},
                    },
                ],
                "pageInfo": {"hasNextPage": False, "endCursor": None},
            }
        }
    }
}


def test_fetch_returns_typed_records(tmp_path: Path) -> None:
    board = _board(tmp_path)
    captured: list[list[str]] = []

    def fake_run_gh(args: list[str], **kwargs: Any) -> Any:
        captured.append(args)
        return _GRAPHQL_RESPONSE_FULL

    with patch.object(Board, "run_graphql",
                       lambda self, q, **kw: _GRAPHQL_RESPONSE_FULL["data"]):
        results = board.fetch_open_issues_for_ties()

    assert len(results) == 2
    assert all(isinstance(r, OpenIssueForTies) for r in results)
    by_n = {r.number: r for r in results}
    assert by_n[10].title == "Issue 10"
    assert by_n[10].body == "Mentions #20"
    assert "perf" in by_n[10].labels
    assert by_n[10].milestone == "Phase 2 — perf settled"
    assert by_n[20].blocked_by == (10,)


def test_fetch_partial_mode_omits_body(tmp_path: Path) -> None:
    board = _board(tmp_path)
    response_no_body = {
        "repository": {
            "issues": {
                "nodes": [
                    {
                        "number": 10,
                        "title": "Issue 10",
                        "labels": {"nodes": []},
                        "milestone": None,
                        "projectItems": {"nodes": [
                            {"fieldValueByName": {"name": "Backlog"},
                             "priority": {"name": "Medium"}}
                        ]},
                        "trackedInIssues": {"nodes": []},
                    }
                ],
                "pageInfo": {"hasNextPage": False, "endCursor": None},
            }
        }
    }
    captured_queries: list[str] = []

    def fake_run_graphql(self: Board, query: str, **kw: Any) -> Any:
        captured_queries.append(query)
        return response_no_body

    with patch.object(Board, "run_graphql", fake_run_graphql):
        results = board.fetch_open_issues_for_ties(include_bodies=False)

    assert len(results) == 1
    assert results[0].body == ""
    # Verify the body field was NOT in the query.
    assert "body" not in captured_queries[0]


def test_fetch_uses_5m_cache(tmp_path: Path) -> None:
    board = _board(tmp_path)
    captured_cache: list[str | None] = []

    def fake_run_graphql(self: Board, query: str, *, cache: str | None = None, **kw: Any) -> Any:
        captured_cache.append(cache)
        return {"repository": {"issues": {"nodes": [], "pageInfo": {"hasNextPage": False, "endCursor": None}}}}

    with patch.object(Board, "run_graphql", fake_run_graphql):
        board.fetch_open_issues_for_ties()

    assert captured_cache == ["5m"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_board_fetch_for_ties.py -v`
Expected: FAIL with `AttributeError: 'Board' object has no attribute 'fetch_open_issues_for_ties'`.

- [ ] **Step 3: Write minimal implementation**

Add to `skills/jared/scripts/lib/board.py`:

```python
def fetch_open_issues_for_ties(
    self, *, include_bodies: bool = True
) -> "list[OpenIssueForTies]":
    """Single batched GraphQL fetch for ties analysis.

    Returns OPEN issues only; excludes Done. When include_bodies=False, the
    body field is omitted from the query (saves response size + bandwidth)
    and OpenIssueForTies.body is "" on every record.

    Cached 5 minutes via run_graphql(cache="5m"). Two cache keys via the
    distinct query strings.
    """
    from skills.jared.scripts.lib.ties import OpenIssueForTies

    body_field = "body" if include_bodies else ""
    query = f"""
    query OpenIssuesForTies($owner: String!, $name: String!, $cursor: String) {{
      repository(owner: $owner, name: $name) {{
        issues(states: OPEN, first: 100, after: $cursor) {{
          nodes {{
            number
            title
            {body_field}
            labels(first: 20) {{ nodes {{ name }} }}
            milestone {{ title }}
            projectItems(first: 5) {{
              nodes {{
                fieldValueByName(name: "Status") {{
                  ... on ProjectV2ItemFieldSingleSelectValue {{ name }}
                }}
                priority: fieldValueByName(name: "Priority") {{
                  ... on ProjectV2ItemFieldSingleSelectValue {{ name }}
                }}
              }}
            }}
            trackedInIssues(first: 10) {{ nodes {{ number }} }}
          }}
          pageInfo {{ hasNextPage endCursor }}
        }}
      }}
    }}
    """
    cursor: str | None = None
    all_records: list[OpenIssueForTies] = []
    while True:
        data = self.run_graphql(
            query, cache="5m", owner=self.owner, name=self.repo_name, cursor=cursor
        )
        page = data["repository"]["issues"]
        for node in page["nodes"]:
            project_item = (node.get("projectItems", {}).get("nodes") or [{}])[0]
            status_field = project_item.get("fieldValueByName") or {}
            priority_field = project_item.get("priority") or {}
            milestone_obj = node.get("milestone") or {}
            tracked_in = node.get("trackedInIssues", {}).get("nodes") or []
            all_records.append(
                OpenIssueForTies(
                    number=int(node["number"]),
                    title=str(node["title"]),
                    body=str(node.get("body") or ""),
                    labels=tuple(
                        n["name"] for n in (node.get("labels", {}).get("nodes") or [])
                    ),
                    milestone=milestone_obj.get("title"),
                    status=str(status_field.get("name") or "Backlog"),
                    priority=priority_field.get("name"),
                    blocked_by=tuple(int(t["number"]) for t in tracked_in),
                )
            )
        if not page["pageInfo"]["hasNextPage"]:
            break
        cursor = page["pageInfo"]["endCursor"]
    # Filter Done if any leaked in (defensive — `states: OPEN` should already exclude).
    return [r for r in all_records if r.status != "Done"]
```

`self.owner` and `self.repo_name` may need to be derived from `self.repo` (`"owner/repo"`); split if needed. Read `lib/board.py` to confirm the existing field name conventions.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_board_fetch_for_ties.py -v && ruff check . && mypy skills/jared/scripts/lib/board.py`
Expected: 3 tests pass.

- [ ] **Step 5: Commit**

```bash
git add skills/jared/scripts/lib/board.py tests/test_board_fetch_for_ties.py
git commit -m "feat(board): fetch_open_issues_for_ties — batched fetch w/ 5m cache (#77)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 12: Implement `_cmd_ties` argparse subcommand

**Files:**
- Modify: `skills/jared/scripts/jared`
- Test: `tests/test_cmd_ties.py` (create)

- [ ] **Step 1: Write the failing test**

`tests/test_cmd_ties.py`:

```python
"""Tests for the `jared ties` CLI subcommand."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from tests.conftest import import_cli  # type: ignore[attr-defined]


def _board_doc(tmp_path: Path) -> Path:
    doc = tmp_path / "project-board.md"
    doc.write_text(
        "# X\n\n"
        "- Project URL: https://github.com/users/x/projects/1\n"
        "- Project number: 1\n"
        "- Project ID: PVT_x\n"
        "- Owner: x\n"
        "- Repo: x/y\n\n"
        "### Status\n- Field ID: F1\n- Backlog: A\n- Up Next: B\n"
        "- In Progress: C\n- Blocked: D\n- Done: E\n\n"
        "### Priority\n- Field ID: F2\n- High: H\n- Medium: M\n- Low: L\n"
    )
    return doc


def _stub_open_issues() -> list[dict[str, Any]]:
    """Used by mocks to return a small fixture set."""
    from skills.jared.scripts.lib.ties import OpenIssueForTies

    return [
        OpenIssueForTies(
            number=42,
            title="related issue",
            body="see #1",
            labels=("perf",),
            milestone="Phase 2",
            status="Backlog",
            priority="Medium",
            blocked_by=(),
        )
    ]


def _stub_target() -> Any:
    from skills.jared.scripts.lib.ties import OpenIssueForTies

    return OpenIssueForTies(
        number=1,
        title="target issue",
        body="references #42",
        labels=("perf",),
        milestone="Phase 2",
        status="In Progress",
        priority="High",
        blocked_by=(),
    )


def test_ties_smoke_renders_block(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    cli = import_cli()
    doc = _board_doc(tmp_path)

    with patch.object(
        cli.Board, "graphql_budget", lambda self: (5000, 5000, 0)
    ), patch.object(
        cli.Board, "fetch_open_issues_for_ties", lambda self, **kw: _stub_open_issues()
    ), patch.object(
        cli.Board, "get_issue", lambda self, n: _stub_target()
    ), patch.object(
        cli.Board, "tie_stop_words", lambda self: frozenset()
    ):
        rc = cli.main(["--board", str(doc), "ties", "1"])

    assert rc == 0
    out = capsys.readouterr().out
    assert "Ties to consider:" in out
    assert "#42" in out


def test_ties_budget_exhausted_emits_skip_line(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    cli = import_cli()
    doc = _board_doc(tmp_path)
    with patch.object(
        cli.Board, "graphql_budget", lambda self: (25, 5000, 0)
    ), patch.object(
        cli.Board, "get_issue", lambda self, n: _stub_target()
    ):
        rc = cli.main(["--board", str(doc), "ties", "1"])
    assert rc == 0
    out = capsys.readouterr().out.strip()
    assert out == "(GraphQL budget exhausted — ties analysis skipped)"


def test_ties_partial_mode_emits_diagnostic(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    cli = import_cli()
    doc = _board_doc(tmp_path)
    captured_kw: dict[str, Any] = {}

    def fake_fetch(self: Any, **kw: Any) -> list[Any]:
        captured_kw.update(kw)
        return _stub_open_issues()

    with patch.object(
        cli.Board, "graphql_budget", lambda self: (100, 5000, 0)
    ), patch.object(
        cli.Board, "fetch_open_issues_for_ties", fake_fetch
    ), patch.object(
        cli.Board, "get_issue", lambda self, n: _stub_target()
    ), patch.object(
        cli.Board, "tie_stop_words", lambda self: frozenset()
    ):
        rc = cli.main(["--board", str(doc), "ties", "1"])

    assert rc == 0
    out = capsys.readouterr().out
    assert "low GraphQL budget" in out
    assert captured_kw == {"include_bodies": False}


def test_ties_target_closed_returns_1(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    cli = import_cli()
    doc = _board_doc(tmp_path)
    with patch.object(cli.Board, "get_issue", lambda self, n: None):
        rc = cli.main(["--board", str(doc), "ties", "1"])
    assert rc == 1


def test_ties_json_format(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    cli = import_cli()
    doc = _board_doc(tmp_path)
    with patch.object(
        cli.Board, "graphql_budget", lambda self: (5000, 5000, 0)
    ), patch.object(
        cli.Board, "fetch_open_issues_for_ties", lambda self, **kw: _stub_open_issues()
    ), patch.object(
        cli.Board, "get_issue", lambda self, n: _stub_target()
    ), patch.object(
        cli.Board, "tie_stop_words", lambda self: frozenset()
    ):
        rc = cli.main(["--board", str(doc), "ties", "1", "--format", "json"])
    assert rc == 0
    out = capsys.readouterr().out
    parsed = json.loads(out)
    assert isinstance(parsed, list)
    assert parsed[0]["related_n"] == 42
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_cmd_ties.py -v`
Expected: FAIL with `argparse: error: invalid choice: 'ties'` or similar (the subcommand isn't registered yet).

- [ ] **Step 3: Write minimal implementation**

Add to `skills/jared/scripts/jared`. The current entry point uses argparse subparsers — read the existing `_cmd_*` functions and `parser.add_subparsers()` block first to find the registration pattern.

Add a new subparser stanza (near the others):

```python
ties_p = subparsers.add_parser(
    "ties",
    help="Surface board-level ties between target issue and other open issues.",
)
ties_p.add_argument("issue_number", type=int)
ties_p.add_argument(
    "--threshold",
    choices=("weak", "medium", "strong"),
    default="medium",
)
ties_p.add_argument(
    "--format",
    choices=("human", "json"),
    default="human",
)
ties_p.set_defaults(func=_cmd_ties)
```

Add the `_cmd_ties` function (near the other `_cmd_*`):

```python
def _cmd_ties(args: argparse.Namespace) -> int:
    """Surface board-level ties between target issue and other open issues."""
    import json as _json
    from dataclasses import asdict

    # Imports kept local to avoid pulling ties module into every other command.
    from lib.ties import (
        analyze_blocked_by,
        analyze_cross_references,
        analyze_file_paths,
        analyze_labels,
        analyze_milestone_overlap,
        analyze_title_tokens,
        combine,
        format_ties_block,
    )

    board = Board.from_path(Path(args.board))
    target = board.get_issue(args.issue_number)
    if target is None or getattr(target, "status", None) == "Done":
        print(f"jared: target #{args.issue_number} not found or closed", file=sys.stderr)
        return 1

    remaining, _, _ = board.graphql_budget()
    if remaining < 50:
        print("(GraphQL budget exhausted — ties analysis skipped)")
        return 0

    full_mode = remaining >= 200
    diagnostic: str | None = None if full_mode else (
        "(low GraphQL budget — body-aware signals deferred, "
        "run jared ties <N> later for full pass)"
    )

    open_issues = board.fetch_open_issues_for_ties(include_bodies=full_mode)
    stop_words = board.tie_stop_words()

    hits = []
    analyzer_specs: list[tuple[str, Any]] = [
        (
            "cross_ref",
            lambda t, o: analyze_cross_references(
                t, o, direction="both" if full_mode else "forward"
            ),
        ),
        ("blocked_by", analyze_blocked_by),
        ("milestone", analyze_milestone_overlap),
        ("title_tokens", analyze_title_tokens),
        ("labels", lambda t, o: analyze_labels(t, o, stop_words=stop_words)),
    ]
    if full_mode:
        analyzer_specs.append(("file_paths", analyze_file_paths))

    for name, analyze in analyzer_specs:
        try:
            hits.extend(analyze(target, open_issues))
        except Exception as e:  # noqa: BLE001 — never let analyzer crash the start
            piece = f"(analyzer {name} failed: {e})"
            diagnostic = f"{diagnostic} {piece}".strip() if diagnostic else piece

    ties = combine(hits, args.threshold, target, open_issues)

    if args.format == "human":
        output = format_ties_block(
            ties, degraded=not full_mode, diagnostic=diagnostic
        )
    else:
        output = _json.dumps([asdict(t) for t in ties], indent=2)

    if output:
        print(output)
    return 0
```

`board.get_issue()` may not exist. If not, add a thin helper to `Board`:

```python
def get_issue(self, number: int) -> "OpenIssueForTies | None":
    """Return one issue's tie-relevant record, or None if it's not open
    on this repo. Used by `_cmd_ties` to confirm target is pullable."""
    matching = [
        i for i in self.fetch_open_issues_for_ties(include_bodies=True)
        if i.number == number
    ]
    return matching[0] if matching else None
```

(Acceptable to defer pagination/efficiency; for v1 this is fine.)

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_cmd_ties.py -v && pytest -v 2>&1 | tail -5 && ruff check . && mypy`
Expected: 5 cmd_ties tests pass; total suite green; ruff and mypy clean.

- [ ] **Step 5: Commit**

```bash
git add skills/jared/scripts/jared skills/jared/scripts/lib/board.py tests/test_cmd_ties.py
git commit -m "feat(cli): jared ties <N> subcommand (#77)

Wires lib/ties.py + Board.fetch_open_issues_for_ties + budget pre-flight
into the canonical jared ties CLI. Two output formats (human, json),
three thresholds (weak, medium, strong, default medium), three budget
modes (full / partial / skip).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 13: Wire `commands/jared-start.md` skill

Add a step calling `jared ties <N>` after the drift check.

**Files:**
- Modify: `commands/jared-start.md`

- [ ] **Step 1: Read the existing file**

Run: `cat commands/jared-start.md`. Locate the step that says "Drift-check the issue", "Check pullable", or similar — the announce step is later. The new step lands between "drift check" and "announce."

- [ ] **Step 2: Edit — insert tied-issues step**

Use the Edit tool. Find the section in the markdown that describes the post-drift-check / pre-announce flow. Insert this step:

```markdown
### Tied-issues pre-pull analysis

After the drift check passes and before the announce, run:

```bash
${CLAUDE_PLUGIN_ROOT}/skills/jared/scripts/jared ties <N>
```

Capture stdout. If non-empty, prepend it as a "Ties to consider" block at the top of the announce, before the per-issue summary. If exit code is non-zero or stdout is empty, suppress the block and proceed.

The block is **advisory** — never gate the start on tie resolution. Operators may close superseded predecessors, sequence feeders first, fold same-file issues into the target's PR, or ignore the block entirely.
```

- [ ] **Step 3: Verify by reading**

Run: `cat commands/jared-start.md | grep -A 5 "Tied-issues"`
Expected: the new section is present.

- [ ] **Step 4: Commit**

```bash
git add commands/jared-start.md
git commit -m "feat(skill): /jared-start calls jared ties <N> always-on (#77)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 14: Manual smoke test on the live jared board

Verify the always-on integration end-to-end against the actual board.

- [ ] **Step 1: Reload the plugin so the new skill markdown is picked up**

In Claude Code, run `/plugin update jared` then `/reload-plugins`. (Per CLAUDE.md, the plugin cache copy is what's loaded; on-disk edits don't propagate without reload.)

- [ ] **Step 2: Pick a target issue with known ties**

#52, #54, or #60 are all in the same Phase 2 milestone, so any of them as target should surface the others as `[strong, milestone-mate]`. Use #52 as the smoke target.

- [ ] **Step 3: Run `jared ties` standalone first**

```bash
/home/brockamer/Code/jared/skills/jared/scripts/jared ties 52
```

Expected output (rough shape):

```
Ties to consider:
  #54 [strong, milestone-mate]   bundling vs fast-follow — your call
  #60 [strong, milestone-mate]   bundling vs fast-follow — your call
  (Suggestions are heuristic — operator decides.)
```

If the output looks wrong (missing ties, wrong order, wrong format), debug before continuing. Don't proceed to step 4 with broken output.

- [ ] **Step 4: Run `/jared-start 52` end-to-end**

In Claude Code: `/jared-start 52`. Verify the announce includes the Ties block above (or whatever shape the cheap helper finds against the live board).

If `/jared-start` doesn't render the block: re-check the markdown change in `commands/jared-start.md`, ensure the plugin was reloaded, ensure stdout was captured.

- [ ] **Step 5: Move #52 back to Backlog after the smoke**

```bash
/home/brockamer/Code/jared/skills/jared/scripts/jared move 52 Backlog
```

(The smoke-test pull put it In Progress; we don't actually want to start it now per the locked Phase 2 gate.)

- [ ] **Step 6: Record results in #77 as a Session note**

```bash
cat > /tmp/77-smoke.md << 'EOF'
## Session 2026-05-02

**Smoke test:** ran `jared ties 52` standalone and `/jared-start 52` end-to-end. Both surfaced the expected milestone-mate ties (#54, #60). Ties block rendered at top of announce as designed. Suppression on empty-output verified by running against #76 (no ties). Restored #52 → Backlog after the pull.

**State:** v0.9.0-dev candidate, all 36+ new tests passing, ruff + mypy clean.
EOF
/home/brockamer/Code/jared/skills/jared/scripts/jared comment 77 --body-file /tmp/77-smoke.md
```

- [ ] **Step 7: Commit any post-smoke fixups (typically none)**

```bash
git status
```

If the working tree is clean, no commit needed. If smoke turned up a bug, fix → test → commit before the PR.

---

## Task 15: PR + post-merge cleanup

- [ ] **Step 1: Push the branch**

```bash
git push -u origin feature/77-tied-issues-design
```

- [ ] **Step 2: Open the PR**

```bash
gh pr create --title "feat(ties): tied-issues pre-pull analysis (#77)" --body "$(cat <<'EOF'
## Summary

- New `jared ties <N>` CLI subcommand with six deterministic signals (cross-ref, blocked-by, milestone, file-paths, labels, title-tokens), confidence-graded, capped at 8 surfaced ties
- New `lib/ties.py` (pure Python, ~400 LOC) with full unit coverage
- `Board.fetch_open_issues_for_ties()` — single batched GraphQL fetch, 5-min cached, body-optional for partial-mode
- `Board.tie_stop_words()` — project-board.md override hook
- `/jared-start` calls `jared ties <N>` always-on after the drift check; output rendered as "Ties to consider" block; non-empty-only, advisory, never gates the start
- Three rate-limit modes via `Board.graphql_budget()`: full (≥200 pts), partial (50–199, body-aware signals deferred), skip (<50)
- Default threshold = `medium` (precision-biased); `--threshold weak|strong` override available

## Spec / Plan

- Spec: `docs/superpowers/specs/2026-05-02-tied-issues-design.md`
- Plan: `docs/superpowers/plans/2026-05-02-tied-issues.md`

## Test plan

- [x] 36+ new tests across `test_ties_dataclasses.py`, `test_ties_analyzers.py`, `test_ties_combine.py`, `test_ties_format.py`, `test_board_fetch_for_ties.py`, `test_cmd_ties.py`
- [x] Manual smoke against the live board with `jared ties 52` and `/jared-start 52` — both surface the expected Phase 2 milestone-mate ties
- [x] `pytest`, `ruff check`, `ruff format --check`, `mypy --strict` all clean

Closes #77.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

- [ ] **Step 3: After human review + merge, file the LLM follow-up issue**

```bash
cat > /tmp/77-llm-followup.md << 'EOF'
## Context

Follow-up to #77 (tied-issues pre-pull analysis). The cheap deterministic helper shipped in #77 covers six signals (cross-ref, blocked-by, milestone, file-paths, labels, title-tokens). The signal **g (possibly-already-done)** was deferred because it requires semantic judgment about whether code-mentioned-in-an-issue-body has since changed in a way that makes the issue stale — a job for an LLM, not a regex.

This issue tracks adding an opt-in LLM overlay on top of `jared ties <N>`'s structured output:

- `jared ties <N> --llm` invokes a small Claude API call with the target body + JSON of the cheap helper's output + open-issue digest (titles, labels, first paragraph)
- Returns additional semantic ties tagged `[llm, possibly-already-done]` or `[llm, semantic-overlap]`
- Surfaced as a separate sub-block in the announce: `Semantic ties (LLM):` after `Ties to consider:`
- Off by default; opt-in via flag or via `### Tie Analysis` config in `docs/project-board.md`

## Acceptance

- `jared ties <N> --llm` produces structured semantic-tie output
- LLM-pass output JSON-roundtrips into `Tie` objects with appended `confidence="llm"` SignalHits
- `/jared-start` skill is updated to optionally invoke `--llm` (controlled by project-board.md flag)
- Cost budgeting: token estimate per call, with a configurable per-session cap

## Planning

- Parent: #77 (cheap helper)
- Spec: `docs/superpowers/specs/2026-05-02-tied-issues-design.md` (deferred-LLM section)
EOF
/home/brockamer/Code/jared/skills/jared/scripts/jared file \
  --title "feat(ties): LLM-pass overlay for semantic ties (follow-up to #77)" \
  --body-file /tmp/77-llm-followup.md \
  --priority Low \
  --status Backlog \
  --label enhancement
```

- [ ] **Step 4: Pull main, delete branch**

```bash
git checkout main && git pull --ff-only origin main
git branch -d feature/77-tied-issues-design
```

---

## Self-review

**Spec coverage:** All sections covered:
- Layer (Q1) → Tasks 1–9 build the cheap helper; Task 15 files LLM follow-up
- Surface (Q2) → Tasks 12 (CLI) + 13 (skill)
- Signals (Q3) → Tasks 2–7
- No bound (Q4) → batched fetch in Task 11
- Output shape (Q5) → Task 9 with goldens
- Threshold (Q6) → Task 8 with all three threshold tests
- Rate-limit defenses → Task 11 (cache + body-optional) + Task 12 (budget pre-flight)
- Stop-word config → Task 10 + Task 5

**Placeholders:** Scanned. None found. Each step has actual code or actual commands.

**Type consistency:** `OpenIssueForTies` defined in Task 1, used through Task 11. `analyze_*` signatures consistent. `combine(hits, threshold, target, open_issues)` signature matches between Task 8 (definition) and Task 12 (caller). `format_ties_block(ties, *, degraded, diagnostic)` matches across Tasks 9 and 12.

One known integration risk: `Board.from_path` may not currently store the raw doc text; Task 10 step 3 notes this and provides the patch. Likewise `Board.get_issue` doesn't currently exist; Task 12 adds it. Both are flagged inline.
