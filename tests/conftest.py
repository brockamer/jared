"""Shared pytest fixtures and helpers for jared's test suite.

Module-import subtlety
======================
This project has TWO valid import paths for the same Board module file:

1. `from skills.jared.scripts.lib.board import Board` — used by unit tests
   under tests/ because pytest's `pythonpath = ["."]` puts the repo root
   on sys.path.
2. `from lib.board import Board` — used by the `skills/jared/scripts/jared`
   CLI, which does `sys.path.insert(0, <scripts/>)` at startup.

These two imports produce *different* module objects in `sys.modules`
(one per name), each with its own `Board` class. For the most common
monkeypatch target — `subprocess.run` — this doesn't matter: both
modules share the same global `subprocess` object, so patching
`<either>.subprocess.run` mutates the one global.

If you ever need to patch something that's defined directly on the
Board class (e.g., a classmethod), patch it on both module objects
— or better, refactor so the CLI and tests import via the same path.
"""

from __future__ import annotations

import importlib.util
from importlib.machinery import SourceFileLoader
from pathlib import Path
from textwrap import dedent
from types import ModuleType

import pytest

REPO_ROOT = Path(__file__).parents[1]
SKILL_SCRIPTS = REPO_ROOT / "skills" / "jared" / "scripts"
CLI_PATH = SKILL_SCRIPTS / "jared"


def import_cli() -> ModuleType:
    """Load the extension-less `jared` CLI script as a module.

    Lets tests call `main(argv)` in-process so monkeypatches apply.
    """
    loader = SourceFileLoader("jared_cli", str(CLI_PATH))
    spec = importlib.util.spec_from_loader("jared_cli", loader)
    assert spec is not None
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


def write_minimal_board(tmp_path: Path) -> Path:
    """Write a minimal valid docs/project-board.md into tmp_path/docs/.

    Covers the required header fields (URL, number, ID, owner, repo) with
    no field definitions. Tests that need Status/Priority/etc. options
    should write a richer board file inline.
    """
    board_md = tmp_path / "docs" / "project-board.md"
    board_md.parent.mkdir(parents=True)
    board_md.write_text(dedent("""\
        - Project URL: https://github.com/users/brockamer/projects/7
        - Project number: 7
        - Project ID: PVT_kwHO_xyz
        - Owner: brockamer
        - Repo: brockamer/findajob
    """))
    return board_md


class FakeGhResult:
    """Minimal stand-in for subprocess.CompletedProcess used by Board.run_gh."""

    def __init__(self, stdout: str = "{}", returncode: int = 0, stderr: str = "") -> None:
        self.stdout = stdout
        self.returncode = returncode
        self.stderr = stderr


def patch_gh(
    monkeypatch: pytest.MonkeyPatch,
    stdout: str = "{}",
    returncode: int = 0,
    stderr: str = "",
) -> None:
    """Monkeypatch subprocess.run in board.py to return a fixed fake result.

    Because subprocess is a shared global module, this patch is visible
    through both module-import paths (see docstring at top of this file).
    """
    fake = FakeGhResult(stdout=stdout, returncode=returncode, stderr=stderr)
    monkeypatch.setattr(
        "skills.jared.scripts.lib.board.subprocess.run",
        lambda *a, **kw: fake,
    )


def patch_gh_by_arg(
    monkeypatch: pytest.MonkeyPatch,
    responses: dict[str, str],
    default: str = "{}",
) -> list[list[str]]:
    """Patch subprocess.run with routing by substring in the args.

    `responses` maps a substring → stdout JSON. The fake_run scans the
    argv list for the first matching substring and returns that response.
    Useful when a subcommand makes multiple gh calls (e.g. `set` does
    item-list then item-edit) and each needs a distinct stdout.

    Returns a list that captures all invocation argvs in call order, for
    assertions like "the second call contained --field-id PVTSSF_foo".
    """
    calls: list[list[str]] = []

    def fake_run(args: list[str], **kw: object) -> FakeGhResult:
        calls.append(args)
        joined = " ".join(args)
        for substring, stdout in responses.items():
            if substring in joined:
                return FakeGhResult(stdout=stdout)
        return FakeGhResult(stdout=default)

    monkeypatch.setattr(
        "skills.jared.scripts.lib.board.subprocess.run",
        fake_run,
    )
    return calls
