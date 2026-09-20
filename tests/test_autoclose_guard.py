"""Pin the auto-close guard pattern that CLAUDE.md documents.

GitHub's reference parser closes an issue when a closing keyword sits beside a
literal issue number in a commit message, a PR title, or a PR body. In this repo
that has fired three times (2026-06-11 and 2026-09-12 on #350; 2026-09-16 during
#369), every time from text that was *explaining or negating* the danger.

The guard is doctrine, not code: AGENTS.md tells a human or Claude to grep before
`git commit` (CLAUDE.md is a one-line `@AGENTS.md` import; AGENTS.md is the real
authored file). Per AGENTS.md's own "Evolving Jared's discipline" rule, no CLI
surface gates on this, so there is nothing to parse into `Board`. What this module
does instead is stop the *documented pattern* from silently regressing — it reads
the regex out of AGENTS.md and asserts it against known-armed and known-safe
fixtures. Narrowing the pattern in the doc fails here rather than failing at merge
time, on an issue that closes itself.

**Why this shells out to `grep` instead of using `re`.** The documented pattern is
a POSIX ERE meant for `grep -nEi`, and the two engines disagree on exactly the
construct that caused the third firing. Python's `re` has no POSIX bracket
expressions, so it reads `[[:space:]]` as the literal set `[:spaceh]` — under `re`
the old narrow pattern fails to match even `Closes #350`, which makes a
`re`-based test report the right verdict for entirely the wrong reason, and
report nonsense for any future pattern using POSIX classes. Testing the engine
the doctrine actually names is the only version of this test that means anything.

Note on the fixtures: they contain literal armed strings. That is safe — GitHub
parses commit messages and PR title/body, never file contents or diffs. Do not
"fix" them into concatenations; the test is worth less if it does not exercise
the real bytes.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
# CLAUDE.md is a one-line `@AGENTS.md` import (adopted 2026-09-20); AGENTS.md
# holds the real, authored content this guard reads.
AGENTS_MD = REPO_ROOT / "AGENTS.md"

# Text GitHub would act on, or that is close enough that a human must look.
ARMED = [
    "Closes #350",
    "fixes #350",
    "Resolved: #350",
    "Does not close #350",  # negation is no protection (2026-06-11)
    "`closes #350`",  # backticks are no protection (60ccc9e, 2026-09-12)
    "a **resolved** #369 suffix",  # markdown emphasis (2026-09-16)
    "*closes* #77",
    "_fixed_ #77",
    "(fixes #12)",
]

# Ordinary prose this repo writes constantly; flagging these would make the
# guard noise, and noise gets ignored.
SAFE = [
    "fix(371): guard all seven entry points",
    "docs(369): clear 15 document-surface findings",
    "refactor(369): delete the session-handoff-prompt knob",
    "Part of #369",
    "a closing keyword paired with the issue number",
    "This unblocks #352",
    "see #350 for the incident",
    "merged #373 on 2026-09-13",
    "prefix fixture #4 in the table",
]

requires_grep = pytest.mark.skipif(shutil.which("grep") is None, reason="grep not on PATH")


def _documented_pattern() -> str:
    """Extract the guard regex from AGENTS.md's fenced bash blocks.

    Anchored on `grep -nEi '<pattern>'` so the doc stays the single source of
    truth — there is no second copy of the regex here to drift from it.
    """
    text = AGENTS_MD.read_text(encoding="utf-8")
    # re.findall is typed list[Any]; the single capture group makes it list[str].
    found: list[str] = re.findall(r"grep -nEi '([^']+)'", text)
    assert found, "AGENTS.md no longer contains a `grep -nEi '...'` guard pattern"
    # Every occurrence must be identical; a divergent copy inside the same
    # document is the drift this module exists to catch.
    assert len(set(found)) == 1, (
        f"AGENTS.md documents {len(set(found))} different patterns: {sorted(set(found))}"
    )
    return found[0]


def _grep_flags(text: str, pattern: str) -> bool:
    """True when `grep -nEi <pattern>` matches `text`. Exit 0 = match, 1 = no match."""
    proc = subprocess.run(
        ["grep", "-nEi", pattern],
        input=text,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert proc.returncode in (0, 1), f"grep errored ({proc.returncode}): {proc.stderr.strip()}"
    return proc.returncode == 0


@pytest.fixture(scope="module")
def pattern() -> str:
    return _documented_pattern()


@requires_grep
@pytest.mark.parametrize("text", ARMED)
def test_guard_flags_armed_text(pattern: str, text: str) -> None:
    assert _grep_flags(text, pattern), (
        f"CLAUDE.md's documented pattern does not flag {text!r}. "
        "This is the regression that let the landmine fire three times — "
        "do not narrow the separator class."
    )


@requires_grep
@pytest.mark.parametrize("text", SAFE)
def test_guard_ignores_safe_text(pattern: str, text: str) -> None:
    assert not _grep_flags(text, pattern), (
        f"CLAUDE.md's documented pattern flags ordinary prose {text!r}. "
        "An over-broad guard becomes noise and gets ignored."
    )


def test_guard_separator_class_is_not_whitespace_only(pattern: str) -> None:
    """The specific regression that caused the 2026-09-16 firing.

    A whitespace-only separator class passes markdown emphasis through.
    """
    assert "[[:space:]]*:?[[:space:]]*" not in pattern, (
        "The guard pattern has been narrowed back to a whitespace-only separator. "
        "That form scans `**resolved** #369` clean, which is exactly how the "
        "landmine reached a pushed commit on 2026-09-16."
    )


@requires_grep
def test_this_branch_is_clean_under_the_guard(pattern: str) -> None:
    """Run the guard against this branch's own commit messages.

    Self-application: the suite refuses to go green on a branch that is itself
    carrying an armed commit message. Skips when the base ref is unavailable
    (shallow clone, detached checkout) rather than failing on infrastructure.
    """
    try:
        proc = subprocess.run(
            ["git", "log", "origin/main..HEAD", "--format=%B"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as exc:  # pragma: no cover
        pytest.skip(f"git unavailable: {exc}")
    if proc.returncode != 0:  # pragma: no cover
        pytest.skip(f"origin/main not resolvable: {proc.stderr.strip()}")
    if not proc.stdout.strip():
        pytest.skip("no commits on this branch beyond origin/main")

    assert not _grep_flags(proc.stdout, pattern), (
        "This branch has commit message lines that pair a closing keyword with a "
        "literal issue number. Run the guard from CLAUDE.md to see them."
    )
