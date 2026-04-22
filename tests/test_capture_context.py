"""Pure-logic tests for capture-context.py's body section parse/replace.

The script's gh I/O (fetch_body / write_body) is covered by smoke-running
against a real issue; these tests exercise the deterministic parsing and
reassembly so regressions in the section invariants — preamble preservation,
section ordering, idempotent decision append — get caught before they hit
a real issue body.
"""

from __future__ import annotations

import importlib.util
from importlib.machinery import SourceFileLoader
from pathlib import Path
from types import ModuleType

REPO_ROOT = Path(__file__).parents[1]
SCRIPT_PATH = REPO_ROOT / "skills" / "jared" / "scripts" / "capture-context.py"


def _import_capture_context() -> ModuleType:
    """Load capture-context.py as a module despite the dash in its name."""
    loader = SourceFileLoader("capture_context", str(SCRIPT_PATH))
    spec = importlib.util.spec_from_loader("capture_context", loader)
    assert spec is not None
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


cc = _import_capture_context()


def test_split_sections_extracts_preamble_and_sections() -> None:
    body = (
        "One-line summary before any heading.\n"
        "\n"
        "## Current state\n"
        "\n"
        "Implemented X.\n"
        "\n"
        "## Decisions\n"
        "\n"
        "(none yet)\n"
    )
    preamble, sections, order = cc.split_sections(body)

    assert "One-line summary" in preamble
    assert order == ["Current state", "Decisions"]
    assert "Implemented X" in sections["Current state"]
    assert "(none yet)" in sections["Decisions"]


def test_split_sections_handles_body_with_no_headings() -> None:
    body = "Just some prose with no ## headings.\n"
    preamble, sections, order = cc.split_sections(body)
    assert preamble == body
    assert sections == {}
    assert order == []


def test_update_current_state_replaces_body_preserves_heading() -> None:
    body = "## Current state\n\nOld content.\n\n## Acceptance criteria\n\nCriterion A.\n"
    _, sections, _ = cc.split_sections(body)
    cc.update_current_state(sections, "New content line 1.\nLine 2.")

    assert "## Current state" in sections["Current state"]
    assert "Old content" not in sections["Current state"]
    assert "New content line 1." in sections["Current state"]
    # Acceptance criteria section must be untouched.
    assert "Criterion A." in sections["Acceptance criteria"]


def test_update_current_state_creates_section_if_missing() -> None:
    sections: dict[str, str] = {}
    cc.update_current_state(sections, "Brand new state.")
    assert "Current state" in sections
    assert "## Current state" in sections["Current state"]
    assert "Brand new state." in sections["Current state"]


def test_append_decision_replaces_placeholder_body() -> None:
    body = "## Decisions\n\n(none yet)\n"
    _, sections, _ = cc.split_sections(body)
    cc.append_decision(sections, "Chose X over Y because Z.")

    result = sections["Decisions"]
    assert "(none yet)" not in result
    assert "Chose X over Y because Z." in result
    assert "### " in result  # dated sub-heading


def test_append_decision_is_idempotent_for_same_text() -> None:
    sections: dict[str, str] = {}
    cc.append_decision(sections, "A decision.")
    before = sections["Decisions"]
    cc.append_decision(sections, "A decision.")
    after = sections["Decisions"]

    assert before == after, "same decision text twice must not duplicate"


def test_reassemble_orders_known_sections_and_preserves_unknowns() -> None:
    body = (
        "Summary line.\n"
        "\n"
        "## Depends on\n"
        "\n"
        "#5\n"
        "\n"
        "## Current state\n"
        "\n"
        "Mid-implementation.\n"
        "\n"
        "## Custom Section\n"
        "\n"
        "Project-specific content.\n"
    )
    preamble, sections, order = cc.split_sections(body)

    result = cc.reassemble(preamble, sections, order)

    # Current state must come before Depends on per SECTION_ORDER, despite
    # appearing after it in the input.
    current_idx = result.index("## Current state")
    depends_idx = result.index("## Depends on")
    assert current_idx < depends_idx

    # Unknown section must still be present (placed after known ones).
    assert "## Custom Section" in result
    assert "Project-specific content." in result

    # Preamble preserved.
    assert result.startswith("Summary line.")


def test_end_to_end_update_cycle_preserves_unrelated_sections() -> None:
    body = (
        "One-line summary.\n"
        "\n"
        "## Current state\n"
        "\n"
        "Starting out.\n"
        "\n"
        "## Acceptance criteria\n"
        "\n"
        "<details>\n<summary>Expand</summary>\n\n- done it\n</details>\n"
    )
    preamble, sections, order = cc.split_sections(body)

    cc.update_current_state(sections, "Midway through implementation.")
    cc.append_decision(sections, "Chose approach A because of constraint B.")

    new_body = cc.reassemble(preamble, sections, order)

    assert "Midway through implementation." in new_body
    assert "Chose approach A because of constraint B." in new_body
    # Acceptance criteria block must round-trip unchanged in substance.
    assert "<details>" in new_body
    assert "done it" in new_body
    # Preamble survives.
    assert new_body.startswith("One-line summary.")
