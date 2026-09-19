"""Tests for lib/pullable.py — the shared pullability classifier (#429).

The behavioural cases live in `test_stage.py`, which has exercised
`is_pullable` / `not_pullable_reason` / `is_epic` since /jared-stage shipped
and still reaches them through `stage.<name>`. Those tests passing unchanged
after the extraction is the real proof the move was behaviour-neutral, so
duplicating them here would buy nothing.

What this file pins instead is the property the extraction exists for: that
`stage.py` and `sweep.py` share ONE definition rather than two that can drift.
An identity assertion catches a re-introduced local copy; a behavioural
assertion would not — two copies agree on the day they are forked.
"""

from __future__ import annotations

from skills.jared.scripts.lib import pullable
from tests.conftest import import_stage

_WELL_SHAPED = {
    "body": (
        "Real summary paragraph describing the work.\n\n"
        "## Acceptance criteria\n\n"
        "- Real criterion 1\n"
    )
}


def test_module_exposes_the_three_classifier_entry_points() -> None:
    assert callable(pullable.is_pullable)
    assert callable(pullable.not_pullable_reason)
    assert callable(pullable.is_epic)


def test_stage_reexports_the_shared_definitions_not_local_copies() -> None:
    """`stage.is_pullable is pullable.is_pullable` — same function object.

    stage.py is loaded by SourceFileLoader and imports `lib.pullable`, while
    this test imports `skills.jared.scripts.lib.pullable`. The dual import
    path (see conftest's module docstring) means these resolve to two
    different module objects, so identity is asserted by qualified name and
    source, which survives that split.
    """
    stage = import_stage()
    for name in ("is_pullable", "not_pullable_reason", "is_epic"):
        stage_fn = getattr(stage, name)
        lib_fn = getattr(pullable, name)
        assert stage_fn.__module__.endswith("pullable"), (
            f"stage.{name} came from {stage_fn.__module__}, not lib.pullable — "
            "a local copy was re-introduced"
        )
        assert stage_fn.__code__.co_code == lib_fn.__code__.co_code


def test_stage_no_longer_defines_the_classifier_itself() -> None:
    """Guards the other half of the extraction: the source moved, not copied."""
    from pathlib import Path

    src = (Path(__file__).parent.parent / "skills/jared/scripts/stage.py").read_text()
    assert "def is_pullable(" not in src
    assert "def not_pullable_reason(" not in src
    assert "def is_epic(" not in src
    assert "_ACCEPTANCE_SECTION = " not in src


def test_classifier_still_answers_the_canonical_shapes() -> None:
    """A smoke case per verdict, so an import-only test file cannot pass while
    the module is broken."""
    assert pullable.is_pullable(_WELL_SHAPED) is True
    assert pullable.is_pullable({"body": ""}) is False
    assert pullable.not_pullable_reason({"body": ""}) == "not pullable — empty body"
    assert pullable.is_epic({"labels": ["epic"]}) is True
    assert pullable.is_epic({"labels": ["enhancement"]}) is False
