"""`jared get-item --body` on a KanbanFlow-backed board (#410).

`references/jared-cli.md` advertises `--body` as "the supported route to an
issue body on **either** backend". These tests pin that claim at the CLI
dispatch layer: the GitHub-side tests in test_cmd_get_item.py cannot catch a
regression in how the flag threads through to the KanbanFlow provider, whose
get_body() reads the task's `description` field rather than a REST body.

Ordering trap: `import_cli()` must run BEFORE `patch_kf_board_provider`.
The helper patches both Board class objects, but its `lib.board` branch is
wrapped in `except ModuleNotFoundError: pass` — and `lib.board` only enters
sys.modules when the CLI is loaded. Patch first and the CLI silently uses an
unpatched Board, which then calls the real KanbanFlowClient.from_env() and
fails on a missing token. See the conftest module docstring on dual imports.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from tests.conftest import (
    KfTaskSpec,
    import_cli,
    patch_kf_board_provider,
    write_minimal_kanbanflow_board,
)

_BODY_MD = """Summary line.

## Current state

- [x] done
- [ ] not done

```python
x = 1
```
"""

KF_TASKS: list[KfTaskSpec] = [
    {
        "number": 2,
        "name": "beta",
        "column": "Up Next",
        "priority": "Medium",
        "description": _BODY_MD,
    },
]


def test_get_item_body_returns_description_on_kanbanflow(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """--body returns the task description, round-tripped unchanged."""
    mod = import_cli()  # must precede the patch — see module docstring
    board_md = write_minimal_kanbanflow_board(tmp_path)
    patch_kf_board_provider(monkeypatch, tmp_path, KF_TASKS)

    rc = mod.main(["--board", str(board_md), "get-item", "2", "--body"])

    captured = capsys.readouterr()
    assert rc == 0, captured.err
    out = json.loads(captured.out)
    assert out["body"] == _BODY_MD
    assert "- [x] done" in out["body"]
    assert "```python" in out["body"]


def test_get_item_body_does_not_call_gh_on_kanbanflow(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Pin the data source: the body must come from the provider, never `gh`.

    Without this, a GitHub-shaped fallback could satisfy the assertion above
    on a machine where `gh` happens to work, which is the #402/#389 failure
    shape one layer down.
    """
    import subprocess as _subprocess

    mod = import_cli()  # must precede the patch — see module docstring
    board_md = write_minimal_kanbanflow_board(tmp_path)
    patch_kf_board_provider(monkeypatch, tmp_path, KF_TASKS)

    gh_calls: list[list[str]] = []
    real_run = _subprocess.run

    def _record(args: list[str], **kw: Any) -> Any:
        # Board loading legitimately shells out to `git remote get-url origin`;
        # only a `gh` invocation would mean a GitHub-shaped fallback.
        if args and args[0] == "gh":
            gh_calls.append(args)
        return real_run(args, **kw)

    monkeypatch.setattr("skills.jared.scripts.lib.board.subprocess.run", _record)

    rc = mod.main(["--board", str(board_md), "get-item", "2", "--body"])

    captured = capsys.readouterr()
    assert rc == 0, captured.err
    assert gh_calls == [], f"get-item --body shelled out to gh on kanbanflow: {gh_calls}"


def test_get_item_without_body_omits_key_on_kanbanflow(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The opt-in shape holds on this backend too."""
    mod = import_cli()  # must precede the patch — see module docstring
    board_md = write_minimal_kanbanflow_board(tmp_path)
    patch_kf_board_provider(monkeypatch, tmp_path, KF_TASKS)

    rc = mod.main(["--board", str(board_md), "get-item", "2"])

    captured = capsys.readouterr()
    assert rc == 0, captured.err
    assert "body" not in json.loads(captured.out)
