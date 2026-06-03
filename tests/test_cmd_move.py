from pathlib import Path
from textwrap import dedent

import pytest

from tests.conftest import graphql_item_response, import_cli, patch_gh_by_arg


def _write_board_with_status(tmp_path: Path) -> Path:
    board_md = tmp_path / "docs" / "project-board.md"
    board_md.parent.mkdir(parents=True)
    board_md.write_text(
        dedent("""\
        - Project URL: https://github.com/users/brockamer/projects/7
        - Project number: 7
        - Project ID: PVT_kwHO_xyz
        - Owner: brockamer
        - Repo: brockamer/findajob

        ### Status
        - Field ID: PVTSSF_status
        - Backlog: OPTION_backlog
        - Up Next: OPTION_up_next
        - In Progress: OPTION_in_progress
        - Done: OPTION_done
        - Blocked: OPTION_blocked
    """)
    )
    return board_md


def test_move_sets_status_field(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    board_md = _write_board_with_status(tmp_path)
    calls = patch_gh_by_arg(
        monkeypatch,
        {
            "api graphql": graphql_item_response(project_number=7, item_id="PVTI_aaa"),
            "item-edit": "{}",
        },
    )

    mod = import_cli()
    rc = mod.main(["--board", str(board_md), "move", "42", "In Progress"])

    captured = capsys.readouterr()
    assert rc == 0, captured.err
    edit = next(c for c in calls if "item-edit" in c)
    joined = " ".join(edit)
    assert "PVTSSF_status" in joined
    assert "OPTION_in_progress" in joined


def test_move_on_kanbanflow_backend_routes_status_to_column(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """`jared move` against a KanbanFlow board moves the task's column.

    Regression guard (#316 final review): the CLI drives `move` through
    set_field("Status") (_cmd_move -> _cmd_set -> provider.set_field). On the
    KanbanFlow backend Status is a structural column, not a custom field, so
    set_field must route "Status" to a column move rather than raising
    FieldNotFound. A direct provider.move() test does not exercise this path.
    """
    mod = import_cli()  # inserts scripts/ on sys.path, so the CLI's lib.* path resolves

    from tests.fake_kanbanflow import FakeKanbanFlowClient

    fake = FakeKanbanFlowClient()
    task = fake.create_task(name="work", column_id="col-backlog", number_value=1)
    # Patch from_env on the CLI's import path (lib.*, distinct from the test's
    # skills.* module object — see CLAUDE.md "Dual import path"). String target so
    # mypy doesn't try to statically resolve the runtime-only `lib` package.
    monkeypatch.setattr(
        "lib.kanbanflow_client.KanbanFlowClient.from_env",
        classmethod(lambda cls, **kw: fake),
    )
    monkeypatch.setenv("JARED_CACHE_DIR", str(tmp_path))

    board_md = tmp_path / "docs" / "project-board.md"
    board_md.parent.mkdir(parents=True)
    board_md.write_text(
        dedent("""\
        - Project URL: https://github.com/users/brockamer/projects/7
        - Project number: 7
        - Project ID: PVT_kwHO_xyz
        - Owner: brockamer
        - Repo: brockamer/findajob

        ## Jared config
        - backend: kanbanflow
    """)
    )

    rc = mod.main(["--board", str(board_md), "move", "1", "In Progress"])

    captured = capsys.readouterr()
    assert rc == 0, captured.err
    assert fake.tasks[task.id].column_id == "col-inprog"
