"""Drift guards for the `/jared-start` model + reasoning-effort recommendation (#430).

The feature is doctrine: `commands/jared-start.md` step 7 instructs the block and
`references/model-and-effort.md` carries the rubric. Claude renders it; no Python
runs it. So — following the honesty of `tests/test_wrap_stub_guards.py`'s docstring —
these are **drift guards, not behaviour guards**. A text assertion cannot tell a good
recommendation from a bad one.

What it *can* pin is the two things that would break silently:

1. **The three-copy config bullet.** `model-advice:` is documented in the asset
   template, in `bootstrap-project.py`'s inline template, and in jared's own
   `docs/project-board.md`. `voice:` already lives in the same three places. A knob
   documented in one copy and not the others is the exact drift #159 caught on the
   Labels table.

2. **No `model:` / `effort:` frontmatter on a command stub.** Settled 2026-09-19
   against Claude Code v2.1.278: a stub's `model:` override "applies for the rest of
   the current turn and isn't saved to settings", so it would govern the turn that
   *prints* the announce and revert at handback — before any implementation work. A
   future session adding it would produce a silent no-op that looks like a feature.
   This is the finding encoded as a guard.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
START_STUB = REPO_ROOT / "commands" / "jared-start.md"
RUBRIC = REPO_ROOT / "skills" / "jared" / "references" / "model-and-effort.md"

BULLET_COPIES = [
    REPO_ROOT / "skills" / "jared" / "assets" / "project-board.md.template",
    REPO_ROOT / "skills" / "jared" / "scripts" / "bootstrap-project.py",
    REPO_ROOT / "docs" / "project-board.md",
]


@pytest.mark.parametrize("path", BULLET_COPIES, ids=lambda p: p.name)
def test_model_advice_bullet_documented_in_every_copy(path: Path) -> None:
    """The knob is documented wherever `voice:` is documented, or it has drifted."""
    text = path.read_text()
    assert "voice:" in text, f"{path.name} is no longer a Jared-config surface — update this test"
    assert "model-advice" in text, (
        f"{path.name} documents `voice:` but not `model-advice:` — the config bullet "
        f"has drifted out of sync across its three copies"
    )


@pytest.mark.parametrize("path", BULLET_COPIES, ids=lambda p: p.name)
def test_model_advice_bullet_is_doctrine_only(path: Path) -> None:
    """Each copy states the doctrine-only contract, so #114 is not repeated."""
    text = path.read_text()
    at = text.find("model-advice")
    assert at != -1, f"{path.name} does not document `model-advice:` at all"
    window = text[at : at + 1400]
    assert "doctrine-only" in window, f"{path.name} omits the doctrine-only contract"
    assert "#114" in window, f"{path.name} omits the #114 rationale"


def _frontmatter(path: Path) -> str:
    """The YAML frontmatter block of a command stub, or '' when there is none."""
    m = re.match(r"^---\n(.*?)\n---\n", path.read_text(), flags=re.DOTALL)
    return m.group(1) if m else ""


@pytest.mark.parametrize(
    "stub", sorted((REPO_ROOT / "commands").glob("*.md")), ids=lambda p: p.name
)
def test_no_stub_carries_model_or_effort_frontmatter(stub: Path) -> None:
    """A stub-level `model:`/`effort:` override cannot govern the work after handback.

    `model:` is documented as reverting at the end of the command's own turn. `effort:`
    exists too, but its row does not state reversion — same-turn scope is inferred by
    parallel construction, not quoted. Both are blocked here anyway: frontmatter is a
    static string and this recommendation is computed per issue, so one pinned value
    could not express it even with session scope.

    Jared's contract is to recommend and let the operator run `/model` / `/effort`.
    If a future Claude Code release gives these keys session scope, delete this test
    deliberately rather than letting it be deleted to make a red run go green.
    """
    fm = _frontmatter(stub)
    for key in ("model", "effort"):
        assert not re.search(rf"^{key}\s*:", fm, flags=re.MULTILINE), (
            f"{stub.name} frontmatter sets `{key}:`. That override applies only for the "
            f"command's own turn and reverts at handback, so it cannot govern the "
            f"implementation work. See references/model-and-effort.md § 'The control "
            f"question — settled 2026-09-19'."
        )


def test_start_stub_names_the_commands_the_operator_runs() -> None:
    """AC3's no-control branch: the announce names the exact settings to change."""
    text = START_STUB.read_text()
    assert "/model" in text and "/effort" in text
    assert "$CLAUDE_EFFORT" in text, "the effort line's `current:` note needs the live value"


def test_rubric_does_not_promise_a_readable_model() -> None:
    """There is no `$CLAUDE_MODEL`; the rubric must not grow one."""
    text = RUBRIC.read_text()
    assert "$CLAUDE_MODEL" not in text.replace("no `$CLAUDE_MODEL`", "")
