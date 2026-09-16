"""F13 — the Python floor is >=3.11 and must be enforced at runtime.

Three facts compose into the finding (see #371 and the marketplace-readiness
ledger):

* `stage.py` has a module-level `from datetime import UTC`, and `UTC` is a
  3.11 addition — so on 3.10 the script dies with a raw `ImportError`.
* The `jared` CLI's *import chain* is 3.10-safe (`board.py` does
  `import datetime as dt`, so its `dt.UTC` uses are runtime attribute
  lookups), so on 3.10 it starts fine and then dies with a raw
  `AttributeError` partway through a subcommand.
* `pyproject.toml` declares `requires-python = ">=3.11"` correctly, but that
  declaration is inert for a marketplace install: shebang execution never
  consults it.

Two kinds of test are needed, and neither alone is sufficient:

1. *Behavioral* — loading each script with a sub-3.11 `sys.version_info`
   must raise `SystemExit` with a legible message. This proves the guard
   fires.
2. *Ordering* — the guard must appear before the first module-level
   statement that needs 3.11. The behavioral test cannot prove this,
   because on the 3.11+ interpreter running this suite `from datetime
   import UTC` succeeds regardless of where the guard sits. Without the
   ordering assertion a guard placed below that import would pass every
   test here and still never fire for the stranger it exists for.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

from tests.conftest import CLI_PATH, SKILL_SCRIPTS

STAGE_PATH = SKILL_SCRIPTS / "stage.py"

# Every surface a stranger can reach that runs as its own script. `jared` is
# the CLI entry point; the rest are invoked directly by slash commands, each
# with its own shebang and its own `if __name__ == "__main__"`, so each needs
# its own guard — `lib/pyversion.py` cannot be reached through a sibling.
GUARDED_SCRIPTS = [
    CLI_PATH,
    STAGE_PATH,
    SKILL_SCRIPTS / "sweep.py",
    SKILL_SCRIPTS / "dependency-graph.py",
    SKILL_SCRIPTS / "capture-context.py",
    SKILL_SCRIPTS / "bootstrap-project.py",
    SKILL_SCRIPTS / "archive-plan.py",
]


# --- the shared helper ------------------------------------------------------


def test_require_python_exits_below_311() -> None:
    from skills.jared.scripts.lib.pyversion import require_python

    with pytest.raises(SystemExit) as exc:
        require_python((3, 10, 12))

    message = str(exc.value)
    assert "3.11" in message, message
    assert "3.10.12" in message, message


def test_require_python_message_names_the_interpreter() -> None:
    """The stranger needs to know *which* interpreter is too old."""
    from skills.jared.scripts.lib.pyversion import require_python

    with pytest.raises(SystemExit) as exc:
        require_python((3, 9, 0))

    assert sys.executable in str(exc.value)


@pytest.mark.parametrize("version", [(3, 11, 0), (3, 12, 3), (4, 0, 0)])
def test_require_python_passes_on_supported_versions(version: tuple[int, ...]) -> None:
    from skills.jared.scripts.lib.pyversion import require_python

    require_python(version)  # must not raise


def test_require_python_defaults_to_the_live_interpreter() -> None:
    """Called with no argument it reads sys.version_info at call time.

    A `version_info=sys.version_info` default argument would bind at def
    time, which is subtly wrong and untestable; this pins the behavior.
    """
    from skills.jared.scripts.lib import pyversion

    pyversion.require_python()  # must not raise


def test_pyversion_module_imports_nothing_that_needs_311() -> None:
    """The guard module must itself load on the version it rejects."""
    tree = ast.parse((SKILL_SCRIPTS / "lib" / "pyversion.py").read_text())
    imported = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }
    assert imported <= {"sys", "annotations"}, imported


# --- the scripts actually call it -------------------------------------------


def _load(path: Path, name: str) -> None:
    """Execute a script as a fresh module, the way conftest.import_cli does."""
    import importlib.util
    from importlib.machinery import SourceFileLoader

    loader = SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(name, loader)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    # @dataclass resolves annotations via sys.modules[cls.__module__], so the
    # module must be registered while it executes (stage.py has dataclasses).
    sys.modules[name] = module
    try:
        loader.exec_module(module)
    finally:
        sys.modules.pop(name, None)


@pytest.mark.parametrize("path", GUARDED_SCRIPTS, ids=lambda p: p.name)
def test_script_refuses_to_run_below_311(path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "version_info", (3, 10, 12, "final", 0))

    with pytest.raises(SystemExit) as exc:
        _load(path, f"{path.stem}_guardtest")

    assert "3.11" in str(exc.value)


@pytest.mark.parametrize("path", GUARDED_SCRIPTS, ids=lambda p: p.name)
def test_script_loads_normally_on_a_supported_version(path: Path) -> None:
    _load(path, f"{path.stem}_okversion")  # must not raise


# --- the guard is early enough to matter ------------------------------------


def _module_level_linenos(path: Path) -> tuple[int | None, int | None]:
    """Return (guard call lineno, first 3.11-dependent import lineno).

    "3.11-dependent" means either `from datetime import UTC` (an
    import-time failure on 3.10) or any `from lib...` import (lib modules
    already contain a module-level `from datetime import UTC` — see
    kanbanflow_provider.py — so the guard must precede them too).
    """
    tree = ast.parse(path.read_text())
    guard: int | None = None
    risky: int | None = None

    for node in tree.body:
        if (
            guard is None
            and isinstance(node, ast.Expr)
            and isinstance(node.value, ast.Call)
            and isinstance(node.value.func, ast.Name)
            and node.value.func.id == "require_python"
        ):
            guard = node.lineno
        if risky is None and isinstance(node, ast.ImportFrom):
            names = {a.name for a in node.names}
            module = node.module or ""
            if module == "lib.pyversion":
                continue  # the guard itself; proven 3.11-safe by the test above
            if (module == "datetime" and "UTC" in names) or module.startswith("lib."):
                risky = node.lineno

    return guard, risky


@pytest.mark.parametrize("path", GUARDED_SCRIPTS, ids=lambda p: p.name)
def test_guard_precedes_every_311_dependent_import(path: Path) -> None:
    guard, risky = _module_level_linenos(path)

    assert guard is not None, f"{path.name} never calls require_python() at module level"
    assert risky is not None, f"{path.name} has no 3.11-dependent import to guard"
    assert guard < risky, (
        f"{path.name}: require_python() at line {guard} runs after the "
        f"3.11-dependent import at line {risky}; on 3.10 the import raises first "
        f"and the guard never fires"
    )
