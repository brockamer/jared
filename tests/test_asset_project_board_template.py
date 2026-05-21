"""Tests for the asset scaffold `skills/jared/assets/project-board.md.template`.

The asset file is the convention-doc scaffold referenced from SKILL.md and
references/new-board.md — it's documentation that humans and Claude sessions
read to understand the shape of a Jared-stewarded board.

`bootstrap-project.py` does NOT render from this file (it has its own inline
TEMPLATE — covered by test_bootstrap_project_defaults.py). So drift on the
asset isn't caught by the rendering tests. #159 was exactly that drift: the
asset's Labels table listed `blocked` as a default label, contradicting
Jared's column-not-label rule and the live docs/project-board.md.

This file pins the same `blocked`-rule invariants on the asset that
test_bootstrap_project_defaults.py pins on the rendered TEMPLATE.
"""

from pathlib import Path

ASSET_PATH = (
    Path(__file__).resolve().parent.parent
    / "skills"
    / "jared"
    / "assets"
    / "project-board.md.template"
)


def test_asset_template_omits_blocked_label_row() -> None:
    content = ASSET_PATH.read_text()
    assert "| `blocked` |" not in content


def test_asset_template_has_blocked_label_callout() -> None:
    content = ASSET_PATH.read_text()
    assert "Do not" in content and "`blocked` label" in content


def test_asset_template_has_epic_label_row() -> None:
    content = ASSET_PATH.read_text()
    assert "| `epic` |" in content


def test_asset_template_has_scope_labels_paragraph() -> None:
    content = ASSET_PATH.read_text()
    assert "Project-specific scope labels" in content
    assert "`infra`" in content and "`frontend`" in content and "`customer-facing`" in content


def test_template_documents_operator_docs_section() -> None:
    """The project-board template ships the optional `### Current-state
    operator docs` block as a documented opt-in (covers AC for #163)."""
    text = ASSET_PATH.read_text()
    assert "### Current-state operator docs" in text
    assert "- Docs:" in text
    assert "- Code surface:" in text
    # Pattern-semantics surprise should be called out in the inline note.
    assert "fnmatch" in text or "crosses `/`" in text or "no need for `**" in text
