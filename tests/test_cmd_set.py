import os
from pathlib import Path
from textwrap import dedent

import pytest

from skills.jared.scripts.lib import cache
from tests.conftest import graphql_item_response, import_cli, patch_gh_by_arg


def _write_board_with_priority(tmp_path: Path) -> Path:
    board_md = tmp_path / "docs" / "project-board.md"
    board_md.parent.mkdir(parents=True)
    board_md.write_text(
        dedent("""\
        - Project URL: https://github.com/users/brockamer/projects/7
        - Project number: 7
        - Project ID: PVT_kwHO_xyz
        - Owner: brockamer
        - Repo: brockamer/findajob

        ### Priority
        - Field ID: PVTSSF_prio
        - High: OPTION_high
        - Medium: OPTION_med
        - Low: OPTION_low
    """)
    )
    return board_md


def _write_board_with_status_and_priority(tmp_path: Path) -> Path:
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
        - Field ID: PVTSSF_stat
        - Backlog: OPTION_bk
        - Up Next: OPTION_un
        - In Progress: OPTION_ip
        - Blocked: OPTION_bl
        - Done: OPTION_dn

        ### Priority
        - Field ID: PVTSSF_prio
        - High: OPTION_high
        - Medium: OPTION_med
        - Low: OPTION_low
    """)
    )
    return board_md


def test_set_invokes_item_edit_with_resolved_ids(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    board_md = _write_board_with_priority(tmp_path)
    calls = patch_gh_by_arg(
        monkeypatch,
        {
            "api graphql": graphql_item_response(project_number=7, item_id="PVTI_aaa"),
            "item-edit": "{}",
        },
    )

    mod = import_cli()
    rc = mod.main(["--board", str(board_md), "set", "42", "Priority", "High"])

    captured = capsys.readouterr()
    assert rc == 0, captured.err

    edit = next(c for c in calls if "item-edit" in c)
    joined = " ".join(edit)
    assert "PVT_kwHO_xyz" in joined
    assert "PVTI_aaa" in joined
    assert "PVTSSF_prio" in joined
    assert "OPTION_high" in joined


def test_set_unknown_field_exits_nonzero(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    board_md = _write_board_with_priority(tmp_path)
    patch_gh_by_arg(
        monkeypatch,
        {"api graphql": graphql_item_response(project_number=7, item_id="PVTI_aaa")},
    )

    mod = import_cli()
    rc = mod.main(["--board", str(board_md), "set", "42", "Nonexistent", "Anything"])

    captured = capsys.readouterr()
    assert rc != 0
    assert "Nonexistent" in captured.err or "not found" in captured.err.lower()


def test_set_unknown_option_exits_nonzero(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    board_md = _write_board_with_priority(tmp_path)
    patch_gh_by_arg(
        monkeypatch,
        {"api graphql": graphql_item_response(project_number=7, item_id="PVTI_aaa")},
    )

    mod = import_cli()
    rc = mod.main(["--board", str(board_md), "set", "42", "Priority", "Urgent"])

    captured = capsys.readouterr()
    assert rc != 0
    assert "Urgent" in captured.err or "not found" in captured.err.lower()


# ---------- Closed-cache invalidation on Status mutation (#186) ----------
#
# Status mutations are the only first-party path that can move an item
# into or out of the closed-cache's set. `jared set N Status Done`,
# `jared move N Done`, and `jared close N` all funnel through `_cmd_set`
# with field_name="Status", so the invalidation hook lives here.
# Non-Status mutations (Priority, Work Stream, etc.) must NOT invalidate
# the closed-cache — that would force a needless full-board refetch on
# every priority adjustment.


def test_set_status_invalidates_closed_cache(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    board_md = _write_board_with_status_and_priority(tmp_path)
    patch_gh_by_arg(
        monkeypatch,
        {
            "api graphql": graphql_item_response(project_number=7, item_id="PVTI_aaa"),
            "item-edit": "{}",
        },
    )

    cache_dir = Path(os.environ["JARED_CACHE_DIR"])
    cache.set_closed_items(
        project_number=7,
        items=[{"content": {"number": 42, "state": "CLOSED"}, "status": "Done"}],
        cache_dir=cache_dir,
    )
    assert cache.get_closed_items(project_number=7, cache_dir=cache_dir) is not None

    mod = import_cli()
    rc = mod.main(["--board", str(board_md), "set", "42", "Status", "Done"])
    assert rc == 0

    assert cache.get_closed_items(project_number=7, cache_dir=cache_dir) is None, (
        "Status mutation must drop the closed-items cache so the next sweep "
        "refetches with the new state."
    )


def test_set_priority_does_not_invalidate_closed_cache(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Non-Status mutations must leave the closed-cache intact — the closed
    set's contents are unaffected by Priority changes, so invalidating here
    would force a wasted full-board refetch on next sweep.
    """
    board_md = _write_board_with_status_and_priority(tmp_path)
    patch_gh_by_arg(
        monkeypatch,
        {
            "api graphql": graphql_item_response(project_number=7, item_id="PVTI_aaa"),
            "item-edit": "{}",
        },
    )

    cache_dir = Path(os.environ["JARED_CACHE_DIR"])
    seeded = [{"content": {"number": 42, "state": "CLOSED"}, "status": "Done"}]
    cache.set_closed_items(project_number=7, items=seeded, cache_dir=cache_dir)

    mod = import_cli()
    rc = mod.main(["--board", str(board_md), "set", "42", "Priority", "High"])
    assert rc == 0

    assert cache.get_closed_items(project_number=7, cache_dir=cache_dir) == seeded, (
        "Priority mutation must not touch the closed-cache."
    )
