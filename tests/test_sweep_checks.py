"""Tests for sweep.py check functions.

Narrow-scope tests for the drift detectors in the batch sweep script. Kept
separate from the full sweep flow (which shells out to gh and reads live
board state) — these only exercise the pure list-processing logic.
"""

from pathlib import Path
from textwrap import dedent
from typing import Any

import pytest

from tests.conftest import import_sweep


def _item(number: int, state: str, status: str, title: str = "") -> dict[str, Any]:
    """Shape matches what `gh project item-list --format json` returns."""
    return {
        "content": {"number": number, "state": state, "title": title or f"Issue {number}"},
        "status": status,
    }


def test_check_closed_not_done_returns_empty_when_all_closed_on_done() -> None:
    mod = import_sweep()
    items = [
        _item(1, "CLOSED", "Done"),
        _item(2, "CLOSED", "Done"),
        _item(3, "OPEN", "In Progress"),
    ]
    assert mod.check_closed_not_done(items) == []


def test_check_closed_not_done_flags_stuck_items() -> None:
    mod = import_sweep()
    items = [
        _item(42, "CLOSED", "Done", title="Done properly"),
        _item(92, "CLOSED", "Backlog", title="Stuck in Backlog"),
        _item(93, "CLOSED", "In Progress", title="Stuck in In Progress"),
        _item(100, "OPEN", "Backlog", title="Open — not stuck"),
    ]
    stuck = mod.check_closed_not_done(items)
    numbers = [entry["number"] for entry in stuck]
    assert numbers == [92, 93]
    assert stuck[0]["current_status"] == "Backlog"
    assert stuck[1]["current_status"] == "In Progress"


def test_check_closed_not_done_handles_no_status() -> None:
    """An item that's CLOSED but missing the status key entirely (older API
    responses, or pre-workflow boards) still gets flagged — its
    current_status renders as 'no Status' so the downstream format is
    still readable."""
    mod = import_sweep()
    items = [{"content": {"number": 99, "state": "CLOSED", "title": "No status at all"}}]
    [entry] = mod.check_closed_not_done(items)
    assert entry["number"] == 99
    assert entry["current_status"] == "no Status"


def test_check_closed_not_done_ignores_missing_content() -> None:
    """Items without a `content` payload (e.g. draft items) must not crash."""
    mod = import_sweep()
    items = [
        {"status": "Backlog"},  # no content at all
        _item(5, "CLOSED", "Backlog"),
    ]
    stuck = mod.check_closed_not_done(items)
    # Only the well-formed closed item is flagged.
    assert len(stuck) == 1
    assert stuck[0]["number"] == 5


def test_check_plan_spec_drift_recognizes_bare_hash_issue_refs(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Regression for #48 — the section-body terminator used `^#` which in
    MULTILINE mode matched bare `#229`-style issue references at column zero,
    so the body capture group came back empty and the file got reported
    as `## Issue section but no #N references`. Fixed by tightening the
    terminator to `^#{1,3}\\s` (a real heading shape).
    """
    mod = import_sweep()

    # Plan whose Issue section uses bare `#N` refs — the broken regex
    # would terminate the body match at the `#229` line and report the
    # file as having no refs.
    plan_dir = tmp_path / "plans"
    plan_dir.mkdir()
    bare_form = plan_dir / "metric-layer-c0.md"
    bare_form.write_text(
        dedent("""\
        # Some plan

        ## Issue(s)
        #229 — Metric Layer C.0
        #230 — follow-up

        ## Approach

        Words.
        """)
    )
    # Same plan, but with the user's old workaround (- prefix).
    listed_form = plan_dir / "feature-x.md"
    listed_form.write_text(
        dedent("""\
        # Other plan

        ## Issue
        - #301 — Feature X

        ## Approach

        Words.
        """)
    )

    # Stub gh issue view so we don't hit the network — every referenced
    # issue is reported open. The check only emits "no #N references" or
    # "no ## Issue section" findings if the regex breaks; a working regex
    # produces *no* findings for these well-formed plans.
    class FakeResult:
        returncode = 0
        stdout = '{"state": "OPEN"}'
        stderr = ""

    monkeypatch.setattr(
        "skills.jared.scripts.lib.board.subprocess.run",
        lambda *a, **kw: FakeResult(),
    )

    findings = mod.check_plan_spec_drift([plan_dir], "brockamer/jared")

    # The two false-positives the broken regex used to emit:
    bug_messages = [f for f in findings if "no #N references" in f or "no ## Issue section" in f]
    assert bug_messages == [], (
        f"Plan files with bare #N refs should NOT be reported as missing — got {bug_messages}"
    )


def test_check_plan_spec_drift_accepts_bold_line_issue_form(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Regression for #88 — sweep used a stricter parser than archive-plan,
    so plans using the legacy `**Issue:** #N` bold-line form (no `## Issue`
    heading) were reported as orphaned. The shared parser in lib/board.py
    accepts the bold-line fallback; sweep now inherits that behavior.
    """
    mod = import_sweep()

    plan_dir = tmp_path / "plans"
    plan_dir.mkdir()
    (plan_dir / "legacy-bold-line.md").write_text(
        dedent("""\
        # An older plan

        **Spec:** path/to/spec.md
        **Issue:** brockamer/jared#339

        ## Approach

        Words.
        """)
    )

    class FakeResult:
        returncode = 0
        stdout = '{"state": "OPEN"}'
        stderr = ""

    monkeypatch.setattr(
        "skills.jared.scripts.lib.board.subprocess.run",
        lambda *a, **kw: FakeResult(),
    )

    findings = mod.check_plan_spec_drift([plan_dir], "brockamer/jared")
    bug_messages = [f for f in findings if "no ## Issue section" in f or "no #N references" in f]
    assert bug_messages == [], (
        "Plans using **Issue:** bold-line fallback should NOT be reported as "
        f"orphaned — got {bug_messages}"
    )


def test_check_plan_spec_drift_ignores_inline_prose_refs(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Sweep must not query issue state for stray prose `#NNN` mentions
    inside the `## Issue` section — only list-item / line-start refs count.
    """
    mod = import_sweep()
    plan_dir = tmp_path / "plans"
    plan_dir.mkdir()
    (plan_dir / "with-prose.md").write_text(
        dedent("""\
        # Plan

        ## Issue

        - #408
        - #310

        > agentic-workers note...

        **Goal:** ...closes #310...

        **Issue:** [#408](...); spawns [#410](...), [#411](...).

        ## Approach

        Words.
        """)
    )

    seen_numbers: list[str] = []

    class FakeResult:
        returncode = 0
        stdout = '{"state": "OPEN"}'
        stderr = ""

    def fake_run(*args: Any, **kwargs: Any) -> FakeResult:
        cmd = args[0] if args else kwargs.get("args", [])
        for tok in cmd or []:
            if isinstance(tok, str) and tok.isdigit():
                seen_numbers.append(tok)
        return FakeResult()

    monkeypatch.setattr("skills.jared.scripts.lib.board.subprocess.run", fake_run)

    mod.check_plan_spec_drift([plan_dir], "brockamer/jared")
    assert sorted(set(seen_numbers)) == ["310", "408"], (
        f"sweep should only query refs from list-item lines, not inline prose; "
        f"got {sorted(set(seen_numbers))}"
    )


def test_check_plan_spec_drift_still_flags_genuinely_orphaned_plans(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The fix must not silence the legitimate orphan-plan finding: a plan
    file with no `## Issue` section at all should still be reported."""
    mod = import_sweep()

    plan_dir = tmp_path / "plans"
    plan_dir.mkdir()
    (plan_dir / "no-issue-section.md").write_text(
        dedent("""\
        # Plan with no Issue section

        ## Approach

        We just start writing without filing.
        """)
    )

    findings = mod.check_plan_spec_drift([plan_dir], "brockamer/jared")
    assert any("no ## Issue section" in f for f in findings)


def test_format_closed_not_done_line_includes_propose_command() -> None:
    """The render-site formatter names the remediation command so the groom
    flow has a concrete next action to propose with per-item approval.

    Format lives here, not in check_closed_not_done — so next sweep-check
    that needs a Propose-style suffix can follow the same
    detector-returns-data / renderer-formats-line split.
    """
    mod = import_sweep()
    entry = {"number": 92, "current_status": "Backlog", "title": "Stuck"}
    line = mod.format_closed_not_done_line(entry)
    assert "jared set 92 Status Done" in line
    assert "[Backlog]" in line
    assert "Stuck" in line
