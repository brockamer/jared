"""Runtime enforcement of jared's Python floor (F13, #371).

`pyproject.toml` declares `requires-python = ">=3.11"`, but that declaration
is inert for a marketplace install: jared's scripts run via their shebang,
and shebang execution never consults project metadata. Without this guard a
stranger on Python 3.10 gets a raw `ImportError` out of `/jared-stage`, or a
raw `AttributeError` partway through a `jared` subcommand, with nothing
naming the real cause.

The floor is 3.11 because `datetime.UTC` is a 3.11 addition and jared uses it
in `stage.py`, `sweep.py`, `board.py`, `github_provider.py`,
`kanbanflow_provider.py` and the `jared` CLI itself. The fix is to make the
floor visible, not to loosen it.

**This module must stay importable on the versions it rejects.** It imports
only `sys` and uses no syntax newer than 3.8; a guard that cannot load on
3.10 cannot report anything to a 3.10 user. `tests/test_python_version_guard.py`
asserts both that property and the guard's placement in each script.
"""

from __future__ import annotations

import sys

MINIMUM_PYTHON = (3, 11)


def require_python(version_info: tuple[int, ...] | None = None) -> None:
    """Exit with a legible message when the interpreter is below the floor.

    Reads `sys.version_info` at call time when `version_info` is None — a
    `version_info=sys.version_info` default would bind at import time and
    could not be exercised by a test.

    Raises SystemExit (never returns) below the floor; returns None above it.
    """
    current = tuple(sys.version_info if version_info is None else version_info)[:3]
    if current >= MINIMUM_PYTHON:
        return None

    found = ".".join(str(part) for part in current)
    required = ".".join(str(part) for part in MINIMUM_PYTHON)
    raise SystemExit(
        f"jared requires Python {required} or later, but {sys.executable} "
        f"is Python {found}.\n"
        f"Install Python {required}+ and run jared with that interpreter."
    )
