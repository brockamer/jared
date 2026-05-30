"""Unit tests for lib/cache.py — on-disk snapshot cache (#52)."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from textwrap import dedent

import pytest

from skills.jared.scripts.lib import cache

REPO_ROOT = Path(__file__).parents[1]
JARED_CLI = REPO_ROOT / "skills" / "jared" / "scripts" / "jared"


def test_get_item_list_returns_none_when_no_cache_file(tmp_path: Path) -> None:
    result = cache.get_item_list(project_number=4, cache_dir=tmp_path)
    assert result is None


def test_set_then_get_round_trips_items(tmp_path: Path) -> None:
    items = [{"content": {"number": 52, "title": "snapshot cache"}}]
    cache.set_item_list(project_number=4, items=items, cache_dir=tmp_path)
    result = cache.get_item_list(project_number=4, cache_dir=tmp_path)
    assert result == items


def test_get_item_list_returns_none_when_past_ttl(tmp_path: Path) -> None:
    cache.set_item_list(project_number=4, items=[{"a": 1}], cache_dir=tmp_path)
    result = cache.get_item_list(project_number=4, ttl_seconds=0, cache_dir=tmp_path)
    assert result is None


def test_invalidate_removes_cache_file(tmp_path: Path) -> None:
    cache.set_item_list(project_number=4, items=[{"a": 1}], cache_dir=tmp_path)
    cache.invalidate_item_list(project_number=4, cache_dir=tmp_path)
    assert cache.get_item_list(project_number=4, cache_dir=tmp_path) is None


def test_invalidate_is_noop_when_file_absent(tmp_path: Path) -> None:
    cache.invalidate_item_list(project_number=4, cache_dir=tmp_path)


def test_get_returns_none_on_corrupted_json(tmp_path: Path) -> None:
    path = tmp_path / "4.json"
    path.write_text("{not json")
    assert cache.get_item_list(project_number=4, cache_dir=tmp_path) is None


def test_different_projects_use_separate_cache_files(tmp_path: Path) -> None:
    cache.set_item_list(project_number=4, items=[{"a": 1}], cache_dir=tmp_path)
    cache.set_item_list(project_number=5, items=[{"b": 2}], cache_dir=tmp_path)
    assert cache.get_item_list(project_number=4, cache_dir=tmp_path) == [{"a": 1}]
    assert cache.get_item_list(project_number=5, cache_dir=tmp_path) == [{"b": 2}]


# ---------- Closed-items cache (#186) ----------
#
# Sweep needs closed board items in the snapshot so `check_off_board_issues`
# (a state-agnostic number intersection) doesn't false-positive an open repo
# issue that's already on the board under a Done column. The cache holds the
# closed subset with its current Status field. Long TTL because the closed-item
# *set* is mostly monotone; first-party Status mutations invalidate to catch the
# mutable cases (close-into-Done, reopen, manual Status reset).


def test_get_closed_items_returns_none_when_no_cache_file(tmp_path: Path) -> None:
    result = cache.get_closed_items(project_number=4, cache_dir=tmp_path)
    assert result is None


def test_set_then_get_closed_items_round_trips(tmp_path: Path) -> None:
    items = [
        {"content": {"number": 52, "state": "CLOSED"}, "status": "Done"},
        {"content": {"number": 53, "state": "CLOSED"}, "status": "In Progress"},
    ]
    cache.set_closed_items(project_number=4, items=items, cache_dir=tmp_path)
    result = cache.get_closed_items(project_number=4, cache_dir=tmp_path)
    assert result == items


def test_get_closed_items_returns_none_when_past_ttl(tmp_path: Path) -> None:
    cache.set_closed_items(project_number=4, items=[{"a": 1}], cache_dir=tmp_path)
    result = cache.get_closed_items(project_number=4, ttl_seconds=0, cache_dir=tmp_path)
    assert result is None


def test_get_closed_items_default_ttl_is_24h(tmp_path: Path) -> None:
    """Long TTL: closed-item set is mostly monotone, so the default is generous.

    The open-items cache uses a 60s TTL because open Status changes constantly;
    closed-items see far fewer mutations and the staleness window for an
    external mutation is bounded by this value.
    """
    cache.set_closed_items(project_number=4, items=[{"a": 1}], cache_dir=tmp_path)
    # Default ttl_seconds parameter — 24h = 86400s. If a closed item was cached
    # 60s ago, the default-TTL read must succeed.
    result = cache.get_closed_items(project_number=4, cache_dir=tmp_path)
    assert result == [{"a": 1}]


def test_invalidate_closed_items_removes_cache_file(tmp_path: Path) -> None:
    cache.set_closed_items(project_number=4, items=[{"a": 1}], cache_dir=tmp_path)
    cache.invalidate_closed_items(project_number=4, cache_dir=tmp_path)
    assert cache.get_closed_items(project_number=4, cache_dir=tmp_path) is None


def test_invalidate_closed_items_is_noop_when_file_absent(tmp_path: Path) -> None:
    cache.invalidate_closed_items(project_number=4, cache_dir=tmp_path)


def test_get_closed_items_returns_none_on_corrupted_json(tmp_path: Path) -> None:
    path = tmp_path / "4-closed.json"
    path.write_text("{not json")
    assert cache.get_closed_items(project_number=4, cache_dir=tmp_path) is None


def test_closed_items_cache_separate_from_open_items_cache(tmp_path: Path) -> None:
    """The two caches must live in distinct files so neither invalidates the other."""
    cache.set_item_list(project_number=4, items=[{"open": True}], cache_dir=tmp_path)
    cache.set_closed_items(project_number=4, items=[{"closed": True}], cache_dir=tmp_path)
    cache.invalidate_item_list(project_number=4, cache_dir=tmp_path)
    # Closed-items cache must survive open-items invalidation.
    assert cache.get_closed_items(project_number=4, cache_dir=tmp_path) == [{"closed": True}]
    assert cache.get_item_list(project_number=4, cache_dir=tmp_path) is None


def test_closed_items_different_projects_use_separate_files(tmp_path: Path) -> None:
    cache.set_closed_items(project_number=4, items=[{"a": 1}], cache_dir=tmp_path)
    cache.set_closed_items(project_number=5, items=[{"b": 2}], cache_dir=tmp_path)
    assert cache.get_closed_items(project_number=4, cache_dir=tmp_path) == [{"a": 1}]
    assert cache.get_closed_items(project_number=5, cache_dir=tmp_path) == [{"b": 2}]


def test_issue_etag_set_then_get_round_trips(tmp_path: Path) -> None:
    cache.set_issue_etag(
        "brockamer/jared",
        52,
        etag='W/"abc123"',
        body={"state": "closed", "number": 52},
        cache_dir=tmp_path,
    )
    result = cache.get_issue_etag("brockamer/jared", 52, cache_dir=tmp_path)
    assert result == ('W/"abc123"', {"state": "closed", "number": 52})


def test_issue_etag_returns_none_when_absent(tmp_path: Path) -> None:
    assert cache.get_issue_etag("brockamer/jared", 99, cache_dir=tmp_path) is None


def test_issue_etag_handles_repo_with_slash_in_path(tmp_path: Path) -> None:
    """The repo name 'owner/name' must produce a nested directory, not a literal slash."""
    cache.set_issue_etag(
        "brockamer/jared",
        52,
        etag='"abc"',
        body={"state": "open"},
        cache_dir=tmp_path,
    )
    expected = tmp_path / "etags" / "brockamer" / "jared" / "52.json"
    assert expected.exists()


def test_issue_etag_returns_none_on_corrupted_json(tmp_path: Path) -> None:
    path = tmp_path / "etags" / "brockamer" / "jared" / "52.json"
    path.parent.mkdir(parents=True)
    path.write_text("{not valid")
    assert cache.get_issue_etag("brockamer/jared", 52, cache_dir=tmp_path) is None


def test_issue_etag_returns_none_when_etag_missing(tmp_path: Path) -> None:
    """A payload missing the 'etag' field must not resolve to a stale hit."""
    import json as _json

    path = tmp_path / "etags" / "brockamer" / "jared" / "52.json"
    path.parent.mkdir(parents=True)
    path.write_text(_json.dumps({"body": {"state": "open"}}))
    assert cache.get_issue_etag("brockamer/jared", 52, cache_dir=tmp_path) is None


def test_issue_etag_different_issues_use_separate_files(tmp_path: Path) -> None:
    cache.set_issue_etag(
        "brockamer/jared",
        52,
        etag='"a"',
        body={"n": 52},
        cache_dir=tmp_path,
    )
    cache.set_issue_etag(
        "brockamer/jared",
        53,
        etag='"b"',
        body={"n": 53},
        cache_dir=tmp_path,
    )
    a = cache.get_issue_etag("brockamer/jared", 52, cache_dir=tmp_path)
    b = cache.get_issue_etag("brockamer/jared", 53, cache_dir=tmp_path)
    assert a == ('"a"', {"n": 52})
    assert b == ('"b"', {"n": 53})


def _minimal_board(tmp_path: Path) -> Path:
    p = tmp_path / "docs" / "project-board.md"
    p.parent.mkdir(parents=True)
    p.write_text(
        dedent("""\
        - Project URL: https://github.com/users/brockamer/projects/7
        - Project number: 7
        - Project ID: PVT_test
        - Owner: brockamer
        - Repo: brockamer/jared
        """)
    )
    return p


def test_board_items_returns_disk_cache_hit_without_calling_gh(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Pre-populate the on-disk cache; board_items() must not call gh."""
    # The autouse fixture set JARED_CACHE_DIR to an empty per-test dir;
    # find it and seed the cache for project 7 (matches _minimal_board).
    import os as _os

    from skills.jared.scripts.lib.board import Board

    cache_dir = Path(_os.environ["JARED_CACHE_DIR"])
    cache.set_item_list(
        project_number=7,
        items=[{"id": "PVTI_cached", "content": {"number": 99}}],
        cache_dir=cache_dir,
    )

    b = Board.from_path(_minimal_board(tmp_path))

    call_count = {"n": 0}

    def fake_run(args: list[str], **kw: object) -> object:
        call_count["n"] += 1
        raise AssertionError("board_items() must hit disk cache, not call gh")

    monkeypatch.setattr("skills.jared.scripts.lib.board.subprocess.run", fake_run)

    items = b.board_items()
    assert items == [{"id": "PVTI_cached", "content": {"number": 99}}]
    assert call_count["n"] == 0


def test_board_invalidate_items_also_nukes_disk_cache(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """invalidate_items() must remove the on-disk cache so other processes refetch."""
    from skills.jared.scripts.lib.board import Board

    b = Board.from_path(_minimal_board(tmp_path))

    class FakeResult:
        returncode = 0
        stdout = '{"items": [{"id": "PVTI_aaa", "content": {"number": 42}}]}'
        stderr = ""

    monkeypatch.setattr(
        "skills.jared.scripts.lib.board.subprocess.run",
        lambda *a, **kw: FakeResult(),
    )

    b.board_items()  # populates on-disk cache
    b.invalidate_items()

    import os as _os

    cache_dir = Path(_os.environ["JARED_CACHE_DIR"])
    assert cache.get_item_list(project_number=7, cache_dir=cache_dir) is None


def test_subprocess_jared_summary_does_not_call_project_item_list(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Post-#185 regression guard: `jared summary` must not route through
    `gh project item-list`, whose cost scales with total board size on
    mature boards. The hot path now uses a single batched GraphQL query
    via `repository.issues(states: OPEN)`.

    Replaces the older "two summary calls share one item-list" assertion
    (#52 era) — that contract is obsolete because summary no longer pulls
    items from the project at all. Same fake-gh-on-PATH structure used to
    catch a future regression that re-introduces board_items() into the
    summary path.
    """
    fake_gh_dir = tmp_path / "bin"
    fake_gh_dir.mkdir()
    log_file = tmp_path / "gh-calls.log"
    fake_gh = fake_gh_dir / "gh"
    fake_gh.write_text(
        dedent(f"""\
        #!/usr/bin/env python3
        import sys
        with open({str(log_file)!r}, "a") as f:
            f.write(" ".join(sys.argv[1:]) + "\\n")
        if sys.argv[1:3] == ["issue", "list"]:
            print("[]")
        elif sys.argv[1:3] == ["api", "graphql"]:
            # batched open-items query returns empty pageInfo + nodes
            print('{{"data": {{"repository": {{"issues": '
                  '{{"pageInfo": {{"hasNextPage": false}}, "nodes": []}}}}}}}}')
        else:
            pass
        """)
    )
    fake_gh.chmod(0o755)

    project_dir = tmp_path / "project"
    docs = project_dir / "docs"
    docs.mkdir(parents=True)
    (docs / "project-board.md").write_text(
        dedent("""\
        - Project URL: https://github.com/users/brockamer/projects/7
        - Project number: 7
        - Project ID: PVT_test
        - Owner: brockamer
        - Repo: brockamer/jared

        ### Status
        - Field ID: PVTSSF_test
        - Backlog: bk
        - Up Next: un
        - In Progress: ip
        - Blocked: bl
        - Done: dn

        ### Priority
        - Field ID: PVTSSF_pri
        - High: hi
        - Medium: me
        - Low: lo
        """)
    )

    env = {
        **os.environ,
        "PATH": f"{fake_gh_dir}:{os.environ['PATH']}",
        "JARED_CACHE_DIR": str(tmp_path / "cache"),
        "JARED_CACHE_TTL_SECONDS": "60",
    }
    env.pop("JARED_NO_CACHE", None)

    result = subprocess.run(
        [sys.executable, str(JARED_CLI), "summary"],
        cwd=project_dir,
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"jared summary failed: {result.stderr}"

    calls = log_file.read_text().splitlines() if log_file.exists() else []
    item_list_calls = [c for c in calls if c.startswith("project item-list")]
    assert item_list_calls == [], (
        f"jared summary must NOT call `gh project item-list` (#185); "
        f"saw: {item_list_calls!r}. All calls: {calls}"
    )


def test_subprocess_jared_move_invalidates_disk_cache(tmp_path: Path) -> None:
    """Cross-process invalidation discipline: a mutating subcommand in one
    process must remove the on-disk `board_items()` snapshot so any other
    process reading the cache afterward refetches.

    `stage.py` (run from cron / `/jared-stage`) is the active reader of
    `board_items()` post-#185 — summary moved to the open-only path that
    doesn't use this cache at all. The discipline still matters: any
    `jared` CLI mutation should leave stage's next run with a fresh view.

    Seeds the disk cache, runs `jared move`, asserts the cache file is
    gone. Doesn't assert anything about summary's gh-call count (summary
    no longer touches this cache).
    """
    fake_gh_dir = tmp_path / "bin"
    fake_gh_dir.mkdir()
    fake_gh = fake_gh_dir / "gh"
    fake_gh.write_text(
        dedent("""\
        #!/usr/bin/env python3
        import sys
        if sys.argv[1:4] == ["api", "graphql", "-f"]:
            # find_item_id uses the scoped projectItems query (fix for #109).
            print(
                '{"data": {"repository": {"issue": {"projectItems": '
                '{"nodes": [{"id": "PVTI_x", "project": {"number": 7}, '
                '"fieldValues": {"nodes": []}}]}}}}}'
            )
        elif sys.argv[1:3] == ["project", "item-edit"]:
            print('{"id": "PVTI_x"}')
        else:
            pass
        """)
    )
    fake_gh.chmod(0o755)

    project_dir = tmp_path / "project"
    docs = project_dir / "docs"
    docs.mkdir(parents=True)
    (docs / "project-board.md").write_text(
        dedent("""\
        - Project URL: https://github.com/users/brockamer/projects/7
        - Project number: 7
        - Project ID: PVT_test
        - Owner: brockamer
        - Repo: brockamer/jared

        ### Status
        - Field ID: PVTSSF_test
        - Backlog: bk
        - Up Next: un
        - In Progress: ip
        - Blocked: bl
        - Done: dn

        ### Priority
        - Field ID: PVTSSF_pri
        - High: hi
        - Medium: me
        - Low: lo
        """)
    )

    cache_dir = tmp_path / "cache"
    env = {
        **os.environ,
        "PATH": f"{fake_gh_dir}:{os.environ['PATH']}",
        "JARED_CACHE_DIR": str(cache_dir),
        "JARED_CACHE_TTL_SECONDS": "60",
    }
    env.pop("JARED_NO_CACHE", None)

    # Pre-seed the disk cache so we can assert it gets nuked.
    cache.set_item_list(
        project_number=7,
        items=[{"id": "STALE_BEFORE_MOVE"}],
        cache_dir=cache_dir,
    )
    assert cache.get_item_list(project_number=7, cache_dir=cache_dir) is not None

    result = subprocess.run(
        [sys.executable, str(JARED_CLI), "move", "1", "In Progress"],
        cwd=project_dir,
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"jared move failed: {result.stderr}"

    # After mutation, the cache must be gone — stage's next read refetches.
    assert cache.get_item_list(project_number=7, cache_dir=cache_dir) is None, (
        "jared move must invalidate the cross-process board_items() cache; "
        "stage.py's next run would otherwise see the pre-mutation snapshot."
    )


def test_board_items_bypasses_cache_when_no_cache_env_set(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """JARED_NO_CACHE=1 bypasses the on-disk cache; every call hits gh."""
    import os as _os

    from skills.jared.scripts.lib.board import Board

    cache_dir = Path(_os.environ["JARED_CACHE_DIR"])
    # Seed cache so we'd hit it if cache were enabled.
    cache.set_item_list(
        project_number=7,
        items=[{"id": "STALE"}],
        cache_dir=cache_dir,
    )
    monkeypatch.setenv("JARED_NO_CACHE", "1")

    b = Board.from_path(_minimal_board(tmp_path))

    call_count = {"n": 0}

    class FakeResult:
        returncode = 0
        stdout = '{"items": [{"id": "FRESH"}]}'
        stderr = ""

    def fake_run(args: list[str], **kw: object) -> object:
        call_count["n"] += 1
        return FakeResult()

    monkeypatch.setattr("skills.jared.scripts.lib.board.subprocess.run", fake_run)

    items = b.board_items()
    assert items == [{"id": "FRESH"}]
    assert call_count["n"] == 1
