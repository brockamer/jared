"""Drift guards for the `advisor()` scoping doctrine (#412).

The rule is doctrine: `SKILL.md` § "The lane" carries the canonical statement and the
four routine command stubs carry the operational copy. Claude reads it; no Python runs
it. So — following `tests/test_model_advice_doctrine.py` and `test_wrap_stub_guards.py` —
these are **drift guards, not behaviour guards**. No text assertion can tell whether a
session actually skipped an advisor call.

What they *can* pin is the pair of things that would break silently:

1. **The five-copy rule.** #412 decided the rule is in lane only because it describes
   Jared's own commands. `SKILL.md` alone does not load when a `/jared-*` command runs —
   the session that decided #412 ran the whole `/jared-start` flow without it — so the
   four routine stubs each carry the note, exactly as the Voice rule is duplicated across
   all nine stubs. A copy dropped from one stub reintroduces the original bug there only,
   which is the hardest shape to notice.

2. **`/jared-audit` is the exception and must stay one.** It is the single sanctioned
   `advisor()` call. A future session that "consistently" added the no-advisor note to
   every stub would silently delete the one pass Jared does prescribe.
"""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SKILL = REPO_ROOT / "skills" / "jared" / "SKILL.md"
AUDIT_STUB = REPO_ROOT / "commands" / "jared-audit.md"

ROUTINE_STUBS = [
    REPO_ROOT / "commands" / "jared.md",
    REPO_ROOT / "commands" / "jared-start.md",
    REPO_ROOT / "commands" / "jared-stage.md",
    REPO_ROOT / "commands" / "jared-file.md",
]

MARKER = "**No advisor pass.**"


@pytest.mark.parametrize("path", ROUTINE_STUBS, ids=lambda p: p.name)
def test_routine_stub_carries_the_no_advisor_note(path: Path) -> None:
    """Each routine stub carries the note, or the rule has drifted out of that command."""
    text = path.read_text()
    assert "**Voice.**" in text, f"{path.name} is no longer a Jared command stub — update this test"
    assert MARKER in text, (
        f"{path.name} carries the Voice block but not {MARKER} — the advisor-scope note "
        f"has drifted out of one of its copies, so the rule stops applying to this command"
    )


@pytest.mark.parametrize("path", ROUTINE_STUBS, ids=lambda p: p.name)
def test_routine_stub_note_points_at_the_audit_exception(path: Path) -> None:
    """The note names the one sanctioned call, so a reader is not left with a bare ban."""
    text = path.read_text()
    at = text.find(MARKER)
    assert at != -1, f"{path.name} does not carry {MARKER} at all"
    window = text[at : at + 600]
    assert "/jared-audit" in window, (
        f"{path.name}'s advisor note does not name `/jared-audit` as the exception — "
        f"a bare prohibition would also suppress the one pass Jared prescribes"
    )


def test_audit_stub_is_not_given_the_no_advisor_note() -> None:
    """`/jared-audit` is the exception; adding the note there deletes the sanctioned pass."""
    text = AUDIT_STUB.read_text()
    assert MARKER not in text, (
        "commands/jared-audit.md carries the no-advisor note — it is the one command that "
        "does prescribe an advisor() pass (#412 left it intact and unmodified)"
    )
    assert "Optional advisor pass" in text, (
        "commands/jared-audit.md no longer prescribes its optional advisor pass — #412's "
        "acceptance criteria required it be left intact and unmodified"
    )


def test_skill_carries_the_canonical_statement() -> None:
    """`SKILL.md` § "The lane" holds the canonical rule the stubs point back at."""
    text = SKILL.read_text()
    at = text.find("Jared prescribes exactly one")
    assert at != -1, (
        "SKILL.md no longer carries the canonical advisor-scope statement — the four stub "
        "copies now point at a section that does not state the rule (#412)"
    )
    window = text[at : at + 900]
    assert "/jared-audit" in window, "the canonical statement no longer names the sanctioned pass"
    assert "#265" in window, (
        "the canonical statement no longer cites #265 — the in-lane decision rests on the "
        "distinction from that issue's generalized tier-scheme"
    )
