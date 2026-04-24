"""Tests for bootstrap-project.py's standard field defaults and conditional rendering.

Covers #5: the script must emit a doc consistent with Jared's invariants on
the first run — Blocked is a Status column (not a label), the Labels table
must not list a `blocked` label, and Work Stream references must be
conditional on the board actually having a Work Stream field.
"""

from typing import Any

from tests.conftest import import_bootstrap

Field = dict[str, Any]


def _fake_field(name: str, options: list[str]) -> Field:
    """Minimal shape fetch_fields returns — enough for render_doc's helpers."""
    return {
        "id": f"FIELD_{name.upper().replace(' ', '_')}",
        "name": name,
        "options": [{"id": f"opt_{o.lower().replace(' ', '_')}", "name": o} for o in options],
    }


def _status_field() -> Field:
    return _fake_field("Status", ["Backlog", "Up Next", "In Progress", "Blocked", "Done"])


def _priority_field() -> Field:
    return _fake_field("Priority", ["High", "Medium", "Low"])


def _render_kwargs(
    status: Field | None, priority: Field | None, work_stream: Field | None
) -> dict[str, Any]:
    return {
        "project_title": "Test Board",
        "project_url": "https://github.com/users/alice/projects/7",
        "project_number": "7",
        "project_id": "PVT_test",
        "owner": "alice",
        "repo": "alice/demo",
        "bootstrap_date": "2026-04-24",
        "wip_limit": 3,
        "status": status,
        "priority": priority,
        "work_stream": work_stream,
    }


def test_standard_status_field_includes_blocked() -> None:
    mod = import_bootstrap()
    assert "Blocked" in mod.STANDARD_FIELDS["Status"]
    # Order is meaningful — Blocked sits between In Progress and Done.
    order = mod.STANDARD_FIELDS["Status"]
    assert order.index("In Progress") < order.index("Blocked") < order.index("Done")


def test_status_table_blocked_has_real_description() -> None:
    mod = import_bootstrap()
    table = mod.status_table(_status_field())
    # The Blocked row must not emit the (describe) placeholder.
    blocked_line = next(line for line in table.splitlines() if "**Blocked**" in line)
    assert "(describe)" not in blocked_line
    assert "dependency" in blocked_line.lower()


def test_render_doc_omits_blocked_label_row() -> None:
    mod = import_bootstrap()
    content = mod.render_doc(**_render_kwargs(_status_field(), _priority_field(), None))
    # The emitted Labels table must not contain a `blocked` row.
    assert "| `blocked` |" not in content
    # And the Do-not-create callout must be present so future users don't add one.
    assert "Do not" in content and "`blocked` label" in content


def test_render_doc_with_work_stream_present() -> None:
    mod = import_bootstrap()
    ws = _fake_field("Work Stream", ["Backend", "Frontend"])
    content = mod.render_doc(**_render_kwargs(_status_field(), _priority_field(), ws))
    # In Progress rule includes Work Stream
    assert "without Priority and Work Stream set" in content
    # Triage checklist includes the Set Work Stream step
    assert "**Set Work Stream**" in content
    # Disappears footer includes Work Stream
    assert "without Priority and Work Stream sorts" in content
    # Work Stream section has rules, not the "Not used" line
    assert "_Not used on this project._" not in content
    assert "project-specific and describe the kind of work" in content


def test_render_doc_without_work_stream_omits_it_from_rules() -> None:
    mod = import_bootstrap()
    content = mod.render_doc(**_render_kwargs(_status_field(), _priority_field(), None))
    # In Progress rule drops Work Stream
    assert "Nothing in In Progress without Priority set." in content
    assert "without Priority and Work Stream set" not in content
    # Triage checklist skips Set Work Stream entirely
    assert "**Set Work Stream**" not in content
    # Disappears footer drops Work Stream
    assert "An issue without Priority sorts to the bottom" in content
    assert "Priority and Work Stream sorts" not in content
    # Work Stream section is marked unused
    assert "_Not used on this project._" in content


def test_render_doc_triage_checklist_renumbers_without_work_stream() -> None:
    """With Work Stream absent, the numbered triage steps must stay contiguous.

    Regression guard — the original hand-patched output had 'Set Work Stream'
    simply deleted, leaving '1. Auto-add / 2. Set Priority / 4. Leave Status'
    with a missing 3. The conditional renderer must renumber.
    """
    mod = import_bootstrap()
    content = mod.render_doc(**_render_kwargs(_status_field(), _priority_field(), None))
    # Find the triage section block
    triage_block = content.split("## Triage checklist")[1].split("## Fields quick reference")[0]
    assert "1. **Auto-add to board.**" in triage_block
    assert "2. **Set Priority**" in triage_block
    assert "3. **Leave Status as Backlog**" in triage_block
    assert "4. **Apply labels**" in triage_block
    # Make sure no phantom "5." step sneaks in
    assert "5. **" not in triage_block


def test_render_doc_triage_checklist_numbers_with_work_stream() -> None:
    mod = import_bootstrap()
    ws = _fake_field("Work Stream", ["Backend"])
    content = mod.render_doc(**_render_kwargs(_status_field(), _priority_field(), ws))
    triage_block = content.split("## Triage checklist")[1].split("## Fields quick reference")[0]
    assert "1. **Auto-add to board.**" in triage_block
    assert "2. **Set Priority**" in triage_block
    assert "3. **Set Work Stream**" in triage_block
    assert "4. **Leave Status as Backlog**" in triage_block
    assert "5. **Apply labels**" in triage_block
