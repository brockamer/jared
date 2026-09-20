"""Drift guards for the `## Jared config` knob set across every board-doc surface (#433).

Four surfaces hand an operator a `docs/project-board.md`, and every project-level
knob is doctrine-only — no Python parses `voice:`, `model-advice:` or `admin-merge:`;
the slash-command stubs read them out of the doc. **The doc is therefore the entire
discoverability surface.** A surface that omits a knob does not disable it; it hides it.

The four surfaces:

1. `skills/jared/assets/project-board.md.template` — the hand-scaffold.
2. `bootstrap-project.py`'s `TEMPLATE` — what `--backend github` writes.
3. `bootstrap-project.py`'s `render_kanbanflow_doc()` — what `--backend kanbanflow` writes.
4. `docs/project-board.md` — jared's own board, the worked example.

#433 is what this guard exists to catch: surface 2 carried no `## Jared config`
section at all, so a bootstrapped GitHub board documented none of the knobs while a
hand-scaffolded one documented two of them.

**Why `tests/test_model_advice_doctrine.py` did not catch it.** That file asserts
`"model-advice" in path.read_text()` against `bootstrap-project.py` as a *whole file*.
The string was present — inside the KanbanFlow template — so the assertion passed
while the GitHub template was empty of it. A file-level check cannot see a
template-level hole. This file extracts each template and checks it on its own.

**The extractor is validated before it is trusted.** `_board_doc_templates` walks the
AST for string and f-string nodes carrying the board-doc title. The KanbanFlow template
is not a module-level constant — it is an f-string returned inline from a function — so
an extractor that only looked at module-level assignments would find one template, not
two, and every knob assertion would then pass vacuously on a surface it never read.
`test_extractor_finds_both_bootstrap_templates` pins the known case first.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

import pytest

from tests.conftest import import_bootstrap

REPO_ROOT = Path(__file__).resolve().parent.parent
BOOTSTRAP = REPO_ROOT / "skills" / "jared" / "scripts" / "bootstrap-project.py"
SCAFFOLD = REPO_ROOT / "skills" / "jared" / "assets" / "project-board.md.template"
OWN_DOC = REPO_ROOT / "docs" / "project-board.md"

# Every board doc a surface emits opens with this title. It is the extractor's anchor.
BOARD_DOC_TITLE = "# Project Board — How It Works"

# The canonical knob set. Adding a knob means adding it here and to all four surfaces
# in the same change — which is the whole point of this file. See `docs/project-board.md`
# § "Jared config" for what each one does.
KNOBS = ("voice", "model-advice", "admin-merge")


def _enclosing_name(tree: ast.Module, node: ast.expr) -> str:
    """The innermost function or assignment that contains `node`, by name."""
    best: tuple[int, str] | None = None
    node_start = node.lineno
    node_end = node.end_lineno or node_start
    for cand in ast.walk(tree):
        if isinstance(cand, ast.FunctionDef):
            name = cand.name
        elif isinstance(cand, ast.Assign):
            names = [t.id for t in cand.targets if isinstance(t, ast.Name)]
            if not names:
                continue
            name = names[0]
        else:
            continue
        end = cand.end_lineno or cand.lineno
        if (
            cand.lineno <= node_start
            and node_end <= end
            and (best is None or cand.lineno > best[0])
        ):
            best = (cand.lineno, name)
    return best[1] if best else "<module>"


def _board_doc_templates() -> dict[str, str]:
    """Every inline board-doc template in `bootstrap-project.py`, keyed by its scope.

    Keyed by the enclosing constant or function name, so a failure message names the
    template a reader can go and find.
    """
    src = BOOTSTRAP.read_text()
    tree = ast.parse(src)

    # An f-string is a JoinedStr whose own children include the literal chunks between
    # the placeholders. `ast.walk` descends into them, so the leading chunk of the
    # KanbanFlow template matches the title anchor too — and, sharing a scope with its
    # parent, silently overwrites the full template with its first 100 characters.
    # Skip every node that lives inside a JoinedStr so only the whole f-string matches.
    inner = {
        id(child)
        for node in ast.walk(tree)
        if isinstance(node, ast.JoinedStr)
        for child in ast.walk(node)
        if child is not node
    }

    found: dict[str, str] = {}
    for node in ast.walk(tree):
        if id(node) in inner:
            continue
        if isinstance(node, ast.Constant) and not isinstance(node.value, str):
            continue
        if not isinstance(node, (ast.Constant, ast.JoinedStr)):
            continue
        segment = ast.get_source_segment(src, node) or ""
        if BOARD_DOC_TITLE in segment:
            found[_enclosing_name(tree, node)] = segment
    return found


def _surfaces() -> dict[str, str]:
    """The four board-doc surfaces, keyed by a name that reads in a failure message."""
    templates = _board_doc_templates()
    return {
        "assets/project-board.md.template": SCAFFOLD.read_text(),
        "bootstrap TEMPLATE (github)": templates["TEMPLATE"],
        "bootstrap render_kanbanflow_doc": templates["render_kanbanflow_doc"],
        "docs/project-board.md": OWN_DOC.read_text(),
    }


SURFACE_NAMES = sorted(
    [
        "assets/project-board.md.template",
        "bootstrap TEMPLATE (github)",
        "bootstrap render_kanbanflow_doc",
        "docs/project-board.md",
    ]
)

# The three surfaces that are *templates* — what a new project is handed. jared's own
# `docs/project-board.md` is a live board and is excluded: it legitimately carries an
# active `admin-merge` sanction, which a template must never ship.
TEMPLATE_SURFACE_NAMES = sorted(n for n in SURFACE_NAMES if n != "docs/project-board.md")


def test_extractor_finds_both_bootstrap_templates() -> None:
    """Validate the instrument on the known case before trusting it on the unknown one.

    `bootstrap-project.py` holds exactly two board-doc templates. If this drops to one,
    every knob assertion against the missing surface would pass vacuously instead of
    failing — so the extractor is pinned before it is used.
    """
    found = _board_doc_templates()
    assert sorted(found) == ["TEMPLATE", "render_kanbanflow_doc"], (
        f"expected the github TEMPLATE and render_kanbanflow_doc, found {sorted(found)} — "
        f"a template was renamed, added, or moved out of reach of the AST extractor"
    )


@pytest.mark.parametrize(
    ("scope", "tail"),
    [
        ("TEMPLATE", "## Further conventions"),
        ("render_kanbanflow_doc", "- Options: High, Medium, Low"),
    ],
)
def test_extractor_returns_whole_templates_not_fragments(scope: str, tail: str) -> None:
    """Checking the template *names* is not checking the template *contents*.

    The first run of this guard passed `test_extractor_finds_both_bootstrap_templates`
    while handing back a KanbanFlow template truncated to its first literal chunk —
    both names present, one body 100 characters long. Every knob assertion against it
    then failed for the wrong reason. Anchoring on text from the end of each template
    is what makes a truncated extraction fail loudly instead of looking like drift.
    """
    segment = _board_doc_templates()[scope]
    assert tail in segment, (
        f"{scope} was extracted without its tail ({tail!r}) — the segment is a fragment, "
        f"not the template, and every assertion against it is unreliable"
    )


@pytest.mark.parametrize("surface", SURFACE_NAMES)
def test_every_surface_has_a_jared_config_section(surface: str) -> None:
    """A board doc without the section documents none of the knobs. That is #433."""
    text = _surfaces()[surface]
    assert "## Jared config" in text, (
        f"{surface} emits a board doc with no `## Jared config` section — an operator "
        f"handed this doc cannot discover that the knobs exist"
    )


@pytest.mark.parametrize("surface", SURFACE_NAMES)
@pytest.mark.parametrize("knob", KNOBS)
def test_every_knob_is_documented_on_every_surface(knob: str, surface: str) -> None:
    """The knob set agrees across all four surfaces, or it has drifted."""
    text = _surfaces()[surface]
    assert knob in text, (
        f"{surface} does not document the `{knob}:` knob. The knob set has drifted — "
        f"add it here, or remove it from KNOBS if it no longer exists"
    )


def _active_admin_merge_lines(text: str) -> list[str]:
    """Lines that *set* `admin-merge` to a strategy, as opposed to describing the knob."""
    hits = []
    for line in text.splitlines():
        stripped = line.lstrip().lstrip("-").strip().strip("`")
        if stripped.startswith("admin-merge: -"):
            hits.append(line.strip())
    return hits


# Known-armed and known-safe fixtures for the predicate above. The armed form is the
# live bullet jared's own `docs/project-board.md` carries; a predicate that does not
# fire on it is not evidence of anything on a template.
ARMED_ADMIN_MERGE = [
    "- `admin-merge: --merge` — sanctions the `blocked_on_review` escape path.",
    "- admin-merge: --squash",
    "  - `admin-merge: --merge`",
]
SAFE_ADMIN_MERGE = [
    "- `admin-merge:` — **not set by default.** When present it sanctions the escape.",
    "Add `- admin-merge: --merge` to this section to sanction the escape.",
    "- `model-advice: on` — controls the settings block.",
]


@pytest.mark.parametrize("line", ARMED_ADMIN_MERGE)
def test_admin_merge_predicate_fires_on_a_live_sanction(line: str) -> None:
    """Validate the predicate on the armed case before trusting a clean result."""
    assert _active_admin_merge_lines(line) == [line.strip()]


@pytest.mark.parametrize("line", SAFE_ADMIN_MERGE)
def test_admin_merge_predicate_ignores_a_documented_knob(line: str) -> None:
    """Documenting the knob, or naming it in prose, is not setting it."""
    assert _active_admin_merge_lines(line) == []


def _rendered_github_doc() -> str:
    """The `docs/project-board.md` a `--backend github` bootstrap actually writes."""

    def field(name: str, options: list[str]) -> dict[str, Any]:
        return {
            "id": f"FIELD_{name}",
            "name": name,
            "options": [{"id": f"opt_{o}", "name": o} for o in options],
        }

    doc: str = import_bootstrap().render_doc(
        project_title="Test Board",
        project_url="https://github.com/users/alice/projects/7",
        project_number="7",
        project_id="PVT_test",
        owner="alice",
        repo="alice/demo",
        bootstrap_date="2026-04-24",
        wip_limit=4,
        status=field("Status", ["Backlog", "Up Next", "In Progress", "Blocked", "Done"]),
        priority=field("Priority", ["High", "Medium", "Low"]),
        work_stream=None,
    )
    return doc


@pytest.mark.parametrize("knob", KNOBS)
def test_bootstrapped_github_doc_documents_every_knob(knob: str) -> None:
    """The check that actually matters — the doc the operator is handed, after rendering.

    Every other assertion in this file reads template *source*. A template can carry the
    section and still fail to emit it: `TEMPLATE` is `.format()`-ed, so a stray brace in
    the added prose raises at render time rather than at import. This renders it.
    """
    doc = _rendered_github_doc()
    assert "## Jared config" in doc, "a bootstrapped GitHub board doc has no knob section"
    assert knob in doc, f"a bootstrapped GitHub board doc does not document `{knob}:`"


def test_bootstrapped_github_doc_ships_no_active_admin_merge_sanction() -> None:
    """A fresh board must not arrive with `gh pr merge --admin` already sanctioned."""
    hits = _active_admin_merge_lines(_rendered_github_doc())
    assert hits == [], f"a bootstrapped GitHub board doc sanctions admin-merge: {hits!r}"


@pytest.mark.parametrize("surface", TEMPLATE_SURFACE_NAMES)
def test_no_template_ships_an_active_admin_merge_sanction(surface: str) -> None:
    """`admin-merge` is documented on a template, never set by one.

    This is a guard, not a red-green test: it passes before the #433 fix and must keep
    passing after it. `admin-merge: <strategy>` sanctions `gh pr merge --admin`, which
    bypasses branch protection. Its default is *absence* — `/jared-wrap` offers the
    escape only when the bullet is present. A template that shipped a live value would
    hand every newly bootstrapped project a protection bypass it never asked for.
    """
    hits = _active_admin_merge_lines(_surfaces()[surface])
    assert hits == [], (
        f"{surface} ships an active admin-merge sanction: {hits!r}. Document the knob "
        f"without setting it — absence is what leaves `gh pr merge --admin` "
        f"unsanctioned on a newly bootstrapped project."
    )
