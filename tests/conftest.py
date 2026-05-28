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
import json as _json
import subprocess
import sys
from importlib.machinery import SourceFileLoader
from pathlib import Path
from textwrap import dedent
from types import ModuleType

import pytest

REPO_ROOT = Path(__file__).parents[1]
SKILL_SCRIPTS = REPO_ROOT / "skills" / "jared" / "scripts"
CLI_PATH = SKILL_SCRIPTS / "jared"


@pytest.fixture(autouse=True)
def _isolate_jared_cache(
    tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Point the on-disk snapshot cache (#52) at a per-test tmp dir.

    Without this, tests would share `${TMPDIR}/jared-cache/` across runs and
    leak board snapshots between tests. Tests that want to disable caching
    entirely can additionally set `JARED_NO_CACHE=1` via monkeypatch.
    """
    cache_dir = tmp_path_factory.mktemp("jared-cache")
    monkeypatch.setenv("JARED_CACHE_DIR", str(cache_dir))


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


def import_bootstrap() -> ModuleType:
    """Load `bootstrap-project.py` as a module.

    The hyphen in the filename blocks a normal `import`, and the script
    isn't on sys.path; SourceFileLoader sidesteps both so tests can exercise
    the pure helpers (legacy-doc detection, header rendering, etc.) without
    running the full gh-backed main().
    """
    path = SKILL_SCRIPTS / "bootstrap-project.py"
    loader = SourceFileLoader("bootstrap_project", str(path))
    spec = importlib.util.spec_from_loader("bootstrap_project", loader)
    assert spec is not None
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


def import_sweep() -> ModuleType:
    """Load `sweep.py` as a module. Same SourceFileLoader trick as the others."""
    path = SKILL_SCRIPTS / "sweep.py"
    loader = SourceFileLoader("sweep", str(path))
    spec = importlib.util.spec_from_loader("sweep", loader)
    assert spec is not None
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


def import_stage() -> ModuleType:
    """Load `stage.py` as a module. Same SourceFileLoader trick as the others.

    Registers the module in sys.modules before exec_module so that Python
    3.14's dataclass machinery can resolve string annotations (from
    ``from __future__ import annotations``) via cls.__module__ lookups.
    """
    path = SKILL_SCRIPTS / "stage.py"
    loader = SourceFileLoader("stage", str(path))
    spec = importlib.util.spec_from_loader("stage", loader)
    assert spec is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["stage"] = mod
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
    board_md.write_text(
        dedent("""\
        - Project URL: https://github.com/users/brockamer/projects/7
        - Project number: 7
        - Project ID: PVT_kwHO_xyz
        - Owner: brockamer
        - Repo: brockamer/findajob
    """)
    )
    return board_md


class FakeGhResult:
    """Minimal stand-in for subprocess.CompletedProcess used by Board.run_gh."""

    def __init__(self, stdout: str = "{}", returncode: int = 0, stderr: str = "") -> None:
        self.stdout = stdout
        self.returncode = returncode
        self.stderr = stderr


def graphql_item_response(
    *,
    project_number: int,
    item_id: str = "PVTI_aaa",
    status: str | None = None,
    priority: str | None = None,
) -> str:
    """Build a repository.issue.projectItems GraphQL payload for mocking.

    Used by tests that exercise code paths going through find_item_id /
    fetch_item_for_issue, which now issues a scoped projectItems query
    instead of a full item-list scan (fix for #109).
    """
    import json as _json

    field_nodes = []
    if status is not None:
        field_nodes.append({"name": status, "field": {"name": "Status"}})
    if priority is not None:
        field_nodes.append({"name": priority, "field": {"name": "Priority"}})
    return _json.dumps(
        {
            "data": {
                "repository": {
                    "issue": {
                        "projectItems": {
                            "nodes": [
                                {
                                    "id": item_id,
                                    "project": {"number": project_number},
                                    "fieldValues": {"nodes": field_nodes},
                                }
                            ]
                        }
                    }
                }
            }
        }
    )


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


def _projectitems_node(status: str | None, priority: str | None) -> dict[str, object]:
    """Build a projectItems.nodes entry for project number 7 with the given fields."""
    field_nodes: list[dict[str, object]] = []
    if status is not None:
        field_nodes.append({"name": status, "field": {"name": "Status"}})
    if priority is not None:
        field_nodes.append({"name": priority, "field": {"name": "Priority"}})
    return {
        "id": "PVTI_aaa",
        "project": {"number": 7},
        "fieldValues": {"nodes": field_nodes},
    }


def patch_gh_multi(
    monkeypatch: pytest.MonkeyPatch,
    *,
    open_issues: list[dict[str, object]] | None = None,
    statuses: dict[int, tuple[str, str]] | None = None,
    closed_issues: list[dict[str, object]] | None = None,
    closed_statuses: dict[int, tuple[str, str]] | None = None,
    comments_batch_json: str | None = None,
    labels_by_number: dict[int, list[str]] | None = None,
) -> None:
    """Patch the multi-gh-call shape produced by the batched open-only path (#185).

    Routes by argv shape:
    - `gh api graphql` with `issues(states: OPEN, first: 100)` → synthesized
      batched response with each open issue and its projectItems embedded
      (built from `open_issues` + `statuses`).
    - `gh issue list --state closed --search ...` → top-level JSON list
      from `closed_issues`.
    - `gh api graphql` with aliased `i<N>: issue(number: <N>) { projectItems`
      pattern → synthesized batched response keyed by alias, built from
      `closed_statuses` (issues missing from the map come back as null).
    - `gh api graphql` with aliased `i<N>: ... { comments(last:` →
      `comments_batch_json`, or empty-repository if not provided.

    Most tests only need `open_issues` + `statuses`. Stuck-closed tests
    additionally provide `closed_issues` + `closed_statuses`. The handoff
    test needs the comments batch too.
    """
    closed_list_json = _json.dumps(closed_issues or [])
    open_issues = open_issues or []
    statuses = statuses or {}
    closed_statuses = closed_statuses or {}
    labels_by_number = labels_by_number or {}
    empty_comments_json = '{"data": {"repository": {}}}'

    def _open_items_batched_response() -> str:
        nodes: list[dict[str, object]] = []
        for issue in open_issues:
            number = issue.get("number")
            assert isinstance(number, int)
            project_items: dict[str, object] = {"nodes": []}
            if number in statuses:
                status, priority = statuses[number]
                project_items = {"nodes": [_projectitems_node(status, priority)]}
            label_nodes = [{"name": name} for name in labels_by_number.get(number, [])]
            nodes.append(
                {
                    "number": number,
                    "title": issue.get("title", ""),
                    "state": issue.get("state", "OPEN"),
                    "body": issue.get("body", ""),
                    "labels": {"nodes": label_nodes},
                    "projectItems": project_items,
                    "milestone": None,
                    "blockedBy": {"nodes": []},
                }
            )
        return _json.dumps(
            {
                "data": {
                    "repository": {
                        "issues": {
                            "pageInfo": {"hasNextPage": False},
                            "nodes": nodes,
                        }
                    }
                }
            }
        )

    def _project_items_batched_response(query_arg: str) -> str:
        # Extract i<N> aliases from the query string — only fabricate
        # responses for numbers the test actually requested.
        import re as _re

        repo_block: dict[str, object] = {}
        for n_str in _re.findall(r"i(\d+):\s*issue\(number:\s*\d+\)", query_arg):
            n = int(n_str)
            if n in closed_statuses:
                status, priority = closed_statuses[n]
                repo_block[f"i{n}"] = {
                    "projectItems": {"nodes": [_projectitems_node(status, priority)]},
                }
            else:
                repo_block[f"i{n}"] = {"projectItems": {"nodes": []}}
        return _json.dumps({"data": {"repository": repo_block}})

    def fake_run(args: list[str], **_: object) -> FakeGhResult:
        joined = " ".join(args)
        if "issue list" in joined and "--state closed" in joined:
            return FakeGhResult(stdout=closed_list_json)
        if "api graphql" in joined:
            query_arg = next(
                (
                    args[i + 1]
                    for i, tok in enumerate(args)
                    if tok == "-f" and i + 1 < len(args) and args[i + 1].startswith("query=")
                ),
                "",
            )
            if "issues(states: OPEN" in query_arg:
                return FakeGhResult(stdout=_open_items_batched_response())
            if "comments(last:" in query_arg:
                return FakeGhResult(stdout=comments_batch_json or empty_comments_json)
            if "projectItems(first: 10)" in query_arg:
                # Aliased batched form used by fetch_project_items_batch.
                return FakeGhResult(stdout=_project_items_batched_response(query_arg))
        return FakeGhResult(stdout="{}")

    monkeypatch.setattr(
        "skills.jared.scripts.lib.board.subprocess.run",
        fake_run,
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


# ---------------------------------------------------------------------------
# Shared git-repo helpers (used by test_worktree.py and test_cli.py)
# ---------------------------------------------------------------------------


def git_cmd(repo: Path, *args: str) -> str:
    """Run a git command in `repo` and return stdout (stripped)."""
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


@pytest.fixture
def main_repo(tmp_path: Path) -> Path:
    """Create a fresh git repo with one commit on `main`."""
    repo = tmp_path / "main-repo"
    repo.mkdir()
    git_cmd(repo, "init", "-b", "main")
    git_cmd(repo, "config", "user.email", "test@example.com")
    git_cmd(repo, "config", "user.name", "test")
    (repo / "README.md").write_text("initial\n")
    git_cmd(repo, "add", "README.md")
    git_cmd(repo, "commit", "-m", "initial")
    return repo
