"""Tests for `jared set-milestone` (#427).

`BoardProvider.set_milestone` was implemented on both backends but reachable
only from `migrate`'s apply loop, so no operator route assigned a milestone to
an issue already on the board. That matters because `stage.py` defers an item
with `no milestone with due date` instead of ranking it.

The clear path is a paired `clear_milestone`, not a nullable `name` — see the
issue's 2026-09-19 decision. KanbanFlow's `update_task` already uses `None` to
mean *leave unchanged*, so a widened `set_milestone(ref, None)` would POST an
empty body and return success having changed nothing.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from textwrap import dedent

import pytest

from skills.jared.scripts.lib import cache
from tests.conftest import (
    import_cli,
    patch_gh_by_arg,
    restrict_capabilities,
    write_minimal_board,
)

# What `gh issue edit` actually prints: the issue URL, not JSON. The first
# draft of these tests used "{}" and passed while the real CLI exited 1 on a
# write that had already landed (#427).
GH_ISSUE_EDIT_STDOUT = "https://github.com/brockamer/jared/issues/42"

OPEN_MILESTONES = json.dumps(
    [
        {
            "title": "Marketplace readiness",
            "description": "",
            "state": "open",
            "due_on": "2026-10-01T00:00:00Z",
        },
        {
            "title": "KanbanFlow parity",
            "description": "",
            "state": "open",
            "due_on": None,
        },
    ]
)


def test_set_milestone_assigns_by_title(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A documented invocation assigns an open milestone to an existing issue."""
    board_md = write_minimal_board(tmp_path)
    calls = patch_gh_by_arg(
        monkeypatch,
        {"milestones": OPEN_MILESTONES, "issue edit": GH_ISSUE_EDIT_STDOUT},
    )

    mod = import_cli()
    rc = mod.main(["--board", str(board_md), "set-milestone", "42", "Marketplace readiness"])

    captured = capsys.readouterr()
    assert rc == 0, captured.err

    edit = next(c for c in calls if "edit" in c)
    joined = " ".join(edit)
    assert "--milestone" in joined
    assert "Marketplace readiness" in joined
    assert "42" in joined


def test_set_milestone_unknown_title_refuses_before_mutating(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """An unmatched title exits 2 and names the open milestones.

    Asserting no `issue edit` reached gh is the point: a refusal that exits
    non-zero *after* writing is still a defect, and only the call log
    distinguishes the two. Matches the unmatched-milestone refusal in `_cmd_file` — refuse with a
    listing rather than create one silently.
    """
    board_md = write_minimal_board(tmp_path)
    calls = patch_gh_by_arg(
        monkeypatch,
        {"milestones": OPEN_MILESTONES, "issue edit": GH_ISSUE_EDIT_STDOUT},
    )

    mod = import_cli()
    rc = mod.main(["--board", str(board_md), "set-milestone", "42", "Nonexistent"])

    captured = capsys.readouterr()
    assert rc == 2, captured.err
    assert "Nonexistent" in captured.err
    assert "Marketplace readiness" in captured.err, "must list the open milestones"
    assert not [c for c in calls if "edit" in c], "must not mutate on a rejected title"


def test_set_milestone_none_clears_the_assignment(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """`--none` is the spelled-out clear, and reaches gh's own remove flag.

    `gh issue edit` models the clear as `--remove-milestone`, a distinct flag
    rather than an empty `--milestone`. Asserting the two never travel together
    is what pins the paired-method seam: a nullable `name` would have to branch
    here anyway.
    """
    board_md = write_minimal_board(tmp_path)
    calls = patch_gh_by_arg(
        monkeypatch,
        {"milestones": OPEN_MILESTONES, "issue edit": GH_ISSUE_EDIT_STDOUT},
    )

    mod = import_cli()
    rc = mod.main(["--board", str(board_md), "set-milestone", "42", "--none"])

    captured = capsys.readouterr()
    assert rc == 0, captured.err

    edit = next(c for c in calls if "edit" in c)
    joined = " ".join(edit)
    assert "--remove-milestone" in joined
    assert "--milestone" not in joined.replace("--remove-milestone", ""), (
        "clear must not also send an assignment flag"
    )


def test_set_milestone_requires_a_title_or_none(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Neither a title nor `--none` is a refusal, not a silent clear.

    Criterion 3: an empty value must not reach the clear path. Without this
    gate, `set-milestone 42` would be one argparse default away from wiping an
    assignment the operator never named.
    """
    board_md = write_minimal_board(tmp_path)
    calls = patch_gh_by_arg(
        monkeypatch,
        {"milestones": OPEN_MILESTONES, "issue edit": GH_ISSUE_EDIT_STDOUT},
    )

    mod = import_cli()
    rc = mod.main(["--board", str(board_md), "set-milestone", "42"])

    captured = capsys.readouterr()
    assert rc == 2, captured.err
    assert "--none" in captured.err
    assert not [c for c in calls if "edit" in c], "must not mutate when intent is undeclared"


def test_set_milestone_rejects_title_and_none_together(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A title plus `--none` is contradictory and must not pick a winner."""
    board_md = write_minimal_board(tmp_path)
    calls = patch_gh_by_arg(
        monkeypatch,
        {"milestones": OPEN_MILESTONES, "issue edit": GH_ISSUE_EDIT_STDOUT},
    )

    mod = import_cli()
    rc = mod.main(
        ["--board", str(board_md), "set-milestone", "42", "Marketplace readiness", "--none"]
    )

    captured = capsys.readouterr()
    assert rc != 0, captured.err
    assert not [c for c in calls if "edit" in c], "must not mutate on contradictory intent"


# ---------------------------------------------------------------------------
# Criterion 4: MILESTONE_ASSIGNMENT whole-scope-absent refusal (Phase 6, #319;
# capability refined from MILESTONE_STATE to MILESTONE_ASSIGNMENT by #390)
# ---------------------------------------------------------------------------


def test_set_milestone_refuses_when_milestone_assignment_absent(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The whole subcommand is scope-absent without MILESTONE_ASSIGNMENT.

    Matches `_cmd_file`'s MILESTONE_ASSIGNMENT gate — exit 2 with the standard
    `degraded:` note. The assertion that no milestones listing was
    fetched is what proves the gate runs *first*: reaching validation would
    mean a capability-absent backend reports "no open milestones" instead of
    saying the backend has none at all.
    """
    board_md = write_minimal_board(tmp_path)
    restrict_capabilities(monkeypatch)
    calls = patch_gh_by_arg(
        monkeypatch,
        {"milestones": OPEN_MILESTONES, "issue edit": GH_ISSUE_EDIT_STDOUT},
    )

    mod = import_cli()
    rc = mod.main(["--board", str(board_md), "set-milestone", "42", "Marketplace readiness"])

    captured = capsys.readouterr()
    assert rc == 2, captured.err
    assert "degraded" in captured.err
    assert "milestone" in captured.err.lower()
    assert not [c for c in calls if "milestones" in " ".join(c)], (
        "the capability gate must refuse before listing milestones"
    )
    assert not [c for c in calls if "edit" in c], "must not mutate on a capability-absent backend"


def test_set_milestone_works_the_moment_the_capability_is_present(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Criterion 5: the gate is the *only* thing holding KanbanFlow back.

    A guard, not a driver — it passes on arrival, and that is the claim being
    pinned. `_cmd_set_milestone` reaches the board solely through
    `provider.list_milestones` and `provider.set_milestone`, with no `run_gh`,
    `field_id` or `option_id` of its own. #390 added `MILESTONE_ASSIGNMENT`
    (KanbanFlow already advertises it, via swimlanes) — when this gate keys on
    that capability and it is present, execution falls through to
    `kanbanflow_provider.set_milestone`, and this subcommand does not change.
    Granting the capability alone is the whole experiment.
    """
    from skills.jared.scripts.lib.board_provider import Capability

    board_md = write_minimal_board(tmp_path)
    restrict_capabilities(monkeypatch, keep={Capability.MILESTONE_ASSIGNMENT})
    calls = patch_gh_by_arg(
        monkeypatch,
        {"milestones": OPEN_MILESTONES, "issue edit": GH_ISSUE_EDIT_STDOUT},
    )

    mod = import_cli()
    rc = mod.main(["--board", str(board_md), "set-milestone", "42", "Marketplace readiness"])

    captured = capsys.readouterr()
    assert rc == 0, captured.err
    assert "degraded" not in captured.err
    assert [c for c in calls if "edit" in c], (
        "must reach the provider once the capability is present"
    )


def test_set_milestone_invalidates_the_items_cache(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The headline use case is assign-then-stage, so the snapshot must drop.

    `board_items()` is a 60s-TTL on-disk cache shared across processes, and on
    the github backend `fetch_items_for_stage` reads it directly. `milestone`
    sits at the top level of those rows and `stage.py` ranks on
    `milestone.due_on`. Without this invalidation, assigning a milestone to
    make a Backlog item competitive and then running `/jared-stage` still
    reports `no milestone with due date` until the TTL lapses — the exact
    deferral this subcommand exists to clear.

    Mirrors `test_set_status_invalidates_closed_cache`, one cache over.
    """
    board_md = write_minimal_board(tmp_path)
    patch_gh_by_arg(
        monkeypatch,
        {"milestones": OPEN_MILESTONES, "issue edit": GH_ISSUE_EDIT_STDOUT},
    )

    cache_dir = Path(os.environ["JARED_CACHE_DIR"])
    cache.set_item_list(
        7,
        items=[{"content": {"number": 42}, "status": "Backlog", "milestone": None}],
        cache_dir=cache_dir,
    )
    assert cache.get_item_list(7, cache_dir=cache_dir) is not None

    mod = import_cli()
    rc = mod.main(["--board", str(board_md), "set-milestone", "42", "Marketplace readiness"])
    assert rc == 0

    assert cache.get_item_list(7, cache_dir=cache_dir) is None, (
        "milestone assignment must drop the items snapshot so the next stage "
        "run sees the new milestone instead of the stale null"
    )


def test_clear_milestone_invalidates_the_items_cache(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The clear path moves the same field, so it invalidates the same cache."""
    board_md = write_minimal_board(tmp_path)
    patch_gh_by_arg(monkeypatch, {"issue edit": GH_ISSUE_EDIT_STDOUT})

    cache_dir = Path(os.environ["JARED_CACHE_DIR"])
    cache.set_item_list(
        7,
        items=[{"content": {"number": 42}, "status": "Backlog", "milestone": {"title": "x"}}],
        cache_dir=cache_dir,
    )

    mod = import_cli()
    rc = mod.main(["--board", str(board_md), "set-milestone", "42", "--none"])
    assert rc == 0

    assert cache.get_item_list(7, cache_dir=cache_dir) is None


def test_set_milestone_does_not_invalidate_the_closed_cache(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A milestone moves nothing into or out of Done.

    Same reasoning as `_cmd_set`'s Priority branch: invalidating the closed
    snapshot here would force a wasted full refetch of every closed item on
    the next sweep.
    """
    board_md = write_minimal_board(tmp_path)
    patch_gh_by_arg(
        monkeypatch,
        {"milestones": OPEN_MILESTONES, "issue edit": GH_ISSUE_EDIT_STDOUT},
    )

    cache_dir = Path(os.environ["JARED_CACHE_DIR"])
    seeded = [{"content": {"number": 9, "state": "CLOSED"}, "status": "Done"}]
    cache.set_closed_items(project_number=7, items=seeded, cache_dir=cache_dir)

    mod = import_cli()
    rc = mod.main(["--board", str(board_md), "set-milestone", "42", "Marketplace readiness"])
    assert rc == 0

    assert cache.get_closed_items(project_number=7, cache_dir=cache_dir) == seeded


def test_set_milestone_none_refuses_when_milestone_assignment_absent(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The clear path is gated too — the capability governs the whole scope."""
    board_md = write_minimal_board(tmp_path)
    restrict_capabilities(monkeypatch)
    calls = patch_gh_by_arg(monkeypatch, {"issue edit": GH_ISSUE_EDIT_STDOUT})

    mod = import_cli()
    rc = mod.main(["--board", str(board_md), "set-milestone", "42", "--none"])

    captured = capsys.readouterr()
    assert rc == 2, captured.err
    assert "degraded" in captured.err
    assert not [c for c in calls if "edit" in c], "must not mutate on a capability-absent backend"


# ---------------------------------------------------------------------------
# End-to-end against a real KanbanFlowProvider (fake client, no network) — #390.
# Mirrors test_cmd_move.py's KanbanFlow wiring pattern: patch
# KanbanFlowClient.from_env on the CLI's `lib.*` import path, not the test's
# `skills.*` one (see AGENTS.md "Dual import path").
# ---------------------------------------------------------------------------


def _write_kf_board(tmp_path: Path) -> Path:
    board_md = tmp_path / "docs" / "project-board.md"
    board_md.parent.mkdir(parents=True)
    board_md.write_text(
        dedent("""\
        - Project URL: https://github.com/users/brockamer/projects/7
        - Project number: 7
        - Project ID: PVT_kwHO_xyz
        - Owner: brockamer
        - Repo: brockamer/findajob

        ### Status column map
        - Backlog: Backlog
        - Up Next: Up Next
        - In Progress: In Progress
        - Blocked: Blocked
        - Done: Done

        ## Jared config
        - backend: kanbanflow
    """)
    )
    return board_md


def test_set_milestone_assigns_on_kanbanflow_via_swimlane(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The MILESTONE_ASSIGNMENT gate opens the path straight through to the
    already-working `_swimlane_id` machinery (#390) — granting the capability
    is the whole experiment; `_cmd_set_milestone` itself does not change.
    """
    mod = import_cli()  # inserts scripts/ on sys.path, so the CLI's lib.* path resolves

    from tests.fake_kanbanflow import FakeKanbanFlowClient

    fake = FakeKanbanFlowClient()
    task = fake.create_task(name="work", column_id="col-backlog", number_value=1)
    monkeypatch.setattr(
        "lib.kanbanflow_client.KanbanFlowClient.from_env",
        classmethod(lambda cls, **kw: fake),
    )
    monkeypatch.setenv("JARED_CACHE_DIR", str(tmp_path))

    board_md = _write_kf_board(tmp_path)
    rc = mod.main(["--board", str(board_md), "set-milestone", "1", "v1.0"])

    captured = capsys.readouterr()
    assert rc == 0, captured.err
    assert fake.tasks[task.id].swimlane_id == "sw-v1"


def test_set_milestone_none_refuses_on_kanbanflow_task_always_has_swimlane(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """`--none` reaches `clear_milestone`, which refuses rather than no-opping
    (#390 makes this reachable for the first time via the CLI): a KanbanFlow
    task always occupies a swimlane, so there is no cleared state to move to.
    """
    mod = import_cli()

    from tests.fake_kanbanflow import FakeKanbanFlowClient

    fake = FakeKanbanFlowClient()
    task = fake.create_task(
        name="work", column_id="col-backlog", number_value=1, swimlane_id="sw-v1"
    )
    monkeypatch.setattr(
        "lib.kanbanflow_client.KanbanFlowClient.from_env",
        classmethod(lambda cls, **kw: fake),
    )
    monkeypatch.setenv("JARED_CACHE_DIR", str(tmp_path))

    board_md = _write_kf_board(tmp_path)
    rc = mod.main(["--board", str(board_md), "set-milestone", "1", "--none"])

    captured = capsys.readouterr()
    assert rc == 1, captured.err
    assert "swimlane" in captured.err.lower()
    assert fake.tasks[task.id].swimlane_id == "sw-v1", "must not mutate on refusal"
