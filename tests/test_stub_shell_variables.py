"""Guards against shell variables that cannot reach the command reading them (#468).

Jared's slash-command stubs and references are executed by Claude one fenced
block at a time, and **every Bash call starts a fresh shell**. A variable set
in one call is empty in the next. An empty variable fails silently: finding J23
of the showcase audit found `${SESSION_FLAG:+--session $SESSION_FLAG}` in
`/jared-start`, where no step ever assigned `SESSION_FLAG`, so `--session` was
dropped and `session-resolve` gave a solo verdict to an operator who had asked
for a worktree. `/jared-wrap` carried the same shape (`$TITLE`, `$BODY`, `$msg`,
`$PR`, and a `$REPO_ROOT` assigned one block earlier).

The rule the stubs now state is: a value produced by an earlier step or command
is written into the next command as a literal. A variable is safe only inside
the one block that assigns it. These tests pin that rule on three shapes:

1. **No `${NAME:+...}` expansion anywhere.** The idiom exists only to make a
   flag vanish when its variable is unset — which is the failure itself.
2. **Every variable in a fenced `bash`/`sh` block is assigned in that block,**
   or is one the harness provides on every call (`HARNESS_NAMES`).
3. **Every variable in an inline code span that contains a space** is on the
   same allowlist. A span with a space is a command someone will run; a span
   without one (`$DEFAULT_BRANCH`, `origin/$DEFAULT_BRANCH`) is prose *naming* a
   variable, which is how the stubs explain this very hazard.

Text inside a quoted heredoc (`<<'EOF'`) is literal to bash and is skipped.

Like `tests/test_autoclose_guard.py`, this module checks its own instrument
first: the scanner is run on known-armed and known-safe snippets before it is
trusted on the real files.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

# Runtime prose that Claude reads and executes.
PROSE_SURFACES = sorted(
    [
        *(REPO_ROOT / "commands").glob("*.md"),
        REPO_ROOT / "skills" / "jared" / "SKILL.md",
        *(REPO_ROOT / "skills" / "jared" / "references").glob("*.md"),
    ]
)

# Names that hold a value on every call without a prior step setting them.
# CLAUDE_PLUGIN_ROOT and ARGUMENTS are substituted by Claude Code into the stub
# text before Claude reads it; CLAUDE_EFFORT is in the Bash tool's environment.
HARNESS_NAMES = frozenset({"CLAUDE_PLUGIN_ROOT", "ARGUMENTS", "CLAUDE_EFFORT"})

_COLON_PLUS = re.compile(r"\$\{[A-Za-z_]\w*:\+")
_FENCE = re.compile(r"```(?:bash|sh)\n(.*?)```", re.DOTALL)
_INLINE = re.compile(r"(?<!`)`([^`\n]+)`(?!`)")
_QUOTED_HEREDOC = re.compile(r"<<-?[ \t]*'(\w+)'\n.*?^[ \t]*\1$", re.DOTALL | re.MULTILINE)
_REFERENCE = re.compile(r"\$\{?([A-Za-z_]\w*)")
_ASSIGNMENT = re.compile(
    r"(?:^|[\s;&|(])([A-Za-z_]\w*)="  # NAME=value
    r"|\bfor\s+([A-Za-z_]\w*)\s+in\b"  # for NAME in ...
    r"|\bread\s+(?:-\w+\s+)*([A-Za-z_]\w*)",  # read [-r] NAME
    re.MULTILINE,
)


def _line_of(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def unassigned_in_block(block: str) -> set[str]:
    """Variables a shell block reads but neither assigns nor gets from the harness."""
    code = _QUOTED_HEREDOC.sub("", block)
    used = set(_REFERENCE.findall(code))
    assigned = {name for groups in _ASSIGNMENT.findall(code) for name in groups if name}
    return used - assigned - HARNESS_NAMES


def violations(text: str) -> list[str]:
    """Every place in one prose surface that breaks the rule, as `line N: detail`."""
    found = [
        f"line {_line_of(text, m.start())}: `${{…:+…}}` expansion"
        for m in _COLON_PLUS.finditer(text)
    ]
    for m in _FENCE.finditer(text):
        missing = unassigned_in_block(m.group(1))
        if missing:
            found.append(
                f"line {_line_of(text, m.start())}: fenced block reads {sorted(missing)} "
                f"without assigning it in the same block"
            )
    fenced = [(m.start(), m.end()) for m in _FENCE.finditer(text)]
    for m in _INLINE.finditer(text):
        if any(start <= m.start() < end for start, end in fenced):
            continue
        span = m.group(1)
        if " " not in span:
            continue
        missing = set(_REFERENCE.findall(span)) - HARNESS_NAMES
        if missing:
            found.append(
                f"line {_line_of(text, m.start())}: inline command `{span}` reads {sorted(missing)}"
            )
    return found


# --- the instrument, on cases whose answer is known ---------------------------------------


@pytest.mark.parametrize(
    "snippet",
    [
        # The J23 shape, verbatim from the pre-#468 stub.
        "```bash\njared next-session-prompt ${SESSION_FLAG:+--session $SESSION_FLAG}\n```\n",
        # Assigned in one block, read in the next.
        "```bash\nREPO_ROOT=$(pwd)\n```\n\n"
        '```bash\njared session-resolve --repo-root "$REPO_ROOT"\n```\n',
        # Never assigned anywhere.
        '```bash\ngh pr create --title "$TITLE" --body "$BODY"\n```\n',
        # An inline command.
        'On a message: run `git commit -m "$msg"`.\n',
    ],
    ids=["colon-plus", "cross-block", "never-assigned", "inline-command"],
)
def test_scanner_flags_known_armed_snippets(snippet: str) -> None:
    assert violations(snippet), f"scanner missed a known-armed snippet:\n{snippet}"


@pytest.mark.parametrize(
    "snippet",
    [
        # Assigned and read in the same block.
        "```bash\nTITLE=$(gh issue view 7 --json title -q .title)\n"
        'jared worktree-add --title "$TITLE"\n```\n',
        # A for-loop variable (skills/jared/references/migration.md).
        '```bash\nfor label in a b; do\n  gh issue list --label "$label"\ndone\n```\n',
        # `$` inside a quoted heredoc is literal text, not an expansion.
        "```bash\ngit commit -F - <<'EOF'\nfix: keep $HOME literal\nEOF\n```\n",
        # Harness-provided names.
        "```bash\n${CLAUDE_PLUGIN_ROOT}/skills/jared/scripts/jared summary\n"
        'echo "$CLAUDE_EFFORT"\n```\n',
        # Prose naming a variable, not running it.
        "Do not carry `$DEFAULT_BRANCH` over from the guard.\n",
        # Command substitution is not a variable.
        "Run `git push -u origin $(git rev-parse --abbrev-ref HEAD)`.\n",
    ],
    ids=["same-block", "for-loop", "quoted-heredoc", "harness", "prose-mention", "cmd-subst"],
)
def test_scanner_passes_known_safe_snippets(snippet: str) -> None:
    assert violations(snippet) == [], f"scanner flagged a known-safe snippet:\n{snippet}"


def test_surfaces_are_found() -> None:
    """A glob that silently matches nothing would make the real check vacuous."""
    names = {p.name for p in PROSE_SURFACES}
    assert {"jared-start.md", "jared-wrap.md", "SKILL.md", "operations.md"} <= names


# --- the real surfaces ----------------------------------------------------------------------


def _surface_id(path: Path) -> str:
    return path.relative_to(REPO_ROOT).as_posix()


@pytest.mark.parametrize("surface", PROSE_SURFACES, ids=_surface_id)
def test_no_shell_variable_crosses_a_bash_call(surface: Path) -> None:
    found = violations(surface.read_text(encoding="utf-8"))
    assert found == [], (
        f"{surface.relative_to(REPO_ROOT)} reads a shell variable that no earlier line in the "
        f"same Bash call sets. Every Bash call starts a fresh shell, so the value is empty "
        f"and its flag vanishes without an error (#468). Write the literal value into the "
        f"command instead, or assign the variable in the same block:\n  " + "\n  ".join(found)
    )
