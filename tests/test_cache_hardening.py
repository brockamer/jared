"""Cache location, permission and owner-key rules for lib/cache.py and lib/kf_number_index.py.

The disk cache holds board data, including private-repo issue bodies, and jared
reads it back as trusted input. So the directory must be private to the user,
and a directory another user could write to must never be read from or written
to. Snapshot files are also keyed by owner, because project numbers are only
unique per owner.
"""

from __future__ import annotations

import json
import os
import stat
from collections.abc import Iterator
from pathlib import Path

import pytest

from skills.jared.scripts.lib import cache
from skills.jared.scripts.lib.kf_number_index import KfNumberIndex
from tests.conftest import import_sweep, patch_gh_by_arg


def _mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


@pytest.fixture
def open_umask() -> Iterator[None]:
    """Run with umask 000, so a 0700/0600 result cannot be the umask's doing."""
    old = os.umask(0)
    try:
        yield
    finally:
        os.umask(old)


# ---------- Default location ----------


def test_default_dir_is_xdg_cache_home_jared(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("JARED_CACHE_DIR", raising=False)
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg"))
    assert cache._default_cache_dir() == tmp_path / "xdg" / "jared"


def test_default_dir_falls_back_to_home_dot_cache(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("JARED_CACHE_DIR", raising=False)
    monkeypatch.delenv("XDG_CACHE_HOME", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    assert cache._default_cache_dir() == tmp_path / "home" / ".cache" / "jared"


def test_default_dir_ignores_a_relative_xdg_cache_home(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # The XDG spec says a relative value is invalid and must be ignored.
    monkeypatch.delenv("JARED_CACHE_DIR", raising=False)
    monkeypatch.setenv("XDG_CACHE_HOME", "relative/dir")
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    assert cache._default_cache_dir() == tmp_path / "home" / ".cache" / "jared"


def test_jared_cache_dir_override_wins_over_xdg(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("JARED_CACHE_DIR", str(tmp_path / "chosen"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg"))
    assert cache._default_cache_dir() == tmp_path / "chosen"


# ---------- Modes on create ----------


def test_set_item_list_creates_dir_0700_and_file_0600(open_umask: None, tmp_path: Path) -> None:
    root = tmp_path / "fresh"
    cache.set_item_list(4, owner="alice", items=[{"a": 1}], cache_dir=root)
    assert _mode(root) == 0o700
    (written,) = root.glob("*.json")
    assert _mode(written) == 0o600


def test_set_closed_items_creates_dir_0700_and_file_0600(open_umask: None, tmp_path: Path) -> None:
    root = tmp_path / "fresh"
    cache.set_closed_items(4, owner="alice", items=[{"a": 1}], cache_dir=root)
    assert _mode(root) == 0o700
    (written,) = root.glob("*.json")
    assert _mode(written) == 0o600


def test_set_issue_etag_makes_every_directory_level_0700(open_umask: None, tmp_path: Path) -> None:
    # `mkdir(parents=True, mode=...)` applies the mode to the leaf only, and
    # this path is etags/<owner>/<repo>/<n>.json, so each level is checked.
    root = tmp_path / "fresh"
    cache.set_issue_etag("alice/proj", 7, etag='"e"', body={"b": 1}, cache_dir=root)
    leaf = root / "etags" / "alice" / "proj"
    for level in (root, root / "etags", root / "etags" / "alice", leaf):
        assert _mode(level) == 0o700, level
    assert _mode(leaf / "7.json") == 0o600


def test_a_stale_loose_tmp_file_does_not_leak_its_mode(open_umask: None, tmp_path: Path) -> None:
    cache.set_item_list(4, owner="alice", items=[{"a": 1}], cache_dir=tmp_path)
    (final,) = tmp_path.glob("*.json")
    stale = final.with_suffix(final.suffix + ".tmp")
    stale.write_text("old")
    os.chmod(stale, 0o644)
    cache.set_item_list(4, owner="alice", items=[{"a": 2}], cache_dir=tmp_path)
    assert _mode(final) == 0o600


def test_kf_number_index_creates_dir_0700_and_file_0600(open_umask: None, tmp_path: Path) -> None:
    root = tmp_path / "fresh"
    KfNumberIndex.for_board("B1", cache_dir=root).put(1, "task-a")
    assert _mode(root) == 0o700
    (written,) = root.glob("*.json")
    assert _mode(written) == 0o600


# ---------- Refusing an unsafe existing directory ----------


@pytest.mark.parametrize("mode", [0o770, 0o775, 0o772, 0o757, 0o777])
def test_group_or_world_writable_dir_is_refused(
    mode: int, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "shared"
    root.mkdir()
    os.chmod(root, mode)
    cache.set_item_list(4, owner="alice", items=[{"a": 1}], cache_dir=root)
    assert list(root.iterdir()) == []
    err = capsys.readouterr().err
    assert str(root) in err
    assert "writable" in err


def test_a_dir_that_turns_writable_is_not_read_from(tmp_path: Path) -> None:
    root = tmp_path / "shared"
    cache.set_item_list(4, owner="alice", items=[{"a": 1}], cache_dir=root)
    assert cache.get_item_list(4, owner="alice", cache_dir=root) == [{"a": 1}]
    os.chmod(root, 0o777)  # another user could now have planted the file
    assert cache.get_item_list(4, owner="alice", cache_dir=root) is None


def test_dir_owned_by_someone_else_is_refused(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "theirs"
    cache.set_item_list(4, owner="alice", items=[{"a": 1}], cache_dir=root)
    monkeypatch.setattr(cache, "_current_uid", lambda: os.getuid() + 1)
    assert cache.get_item_list(4, owner="alice", cache_dir=root) is None
    cache.set_item_list(4, owner="alice", items=[{"a": 2}], cache_dir=root)
    err = capsys.readouterr().err
    assert str(root) in err
    assert "owned" in err
    monkeypatch.undo()
    assert cache.get_item_list(4, owner="alice", cache_dir=root) == [{"a": 1}]


def test_a_private_existing_dir_is_used(tmp_path: Path) -> None:
    root = tmp_path / "mine"
    root.mkdir()
    os.chmod(root, 0o700)
    cache.set_item_list(4, owner="alice", items=[{"a": 1}], cache_dir=root)
    assert cache.get_item_list(4, owner="alice", cache_dir=root) == [{"a": 1}]


def test_a_readable_but_not_writable_existing_dir_is_used(tmp_path: Path) -> None:
    # The rule is "not writable by others". 0755 owned by the user passes.
    root = tmp_path / "mine"
    root.mkdir()
    os.chmod(root, 0o755)
    cache.set_item_list(4, owner="alice", items=[{"a": 1}], cache_dir=root)
    assert cache.get_item_list(4, owner="alice", cache_dir=root) == [{"a": 1}]


def test_the_refusal_is_reported_once_per_directory(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "shared"
    root.mkdir()
    os.chmod(root, 0o777)
    for _ in range(3):
        cache.set_item_list(4, owner="alice", items=[], cache_dir=root)
        cache.get_item_list(4, owner="alice", cache_dir=root)
    assert capsys.readouterr().err.count(str(root)) == 1


def test_a_read_does_not_create_the_directory(tmp_path: Path) -> None:
    root = tmp_path / "absent"
    assert cache.get_item_list(4, owner="alice", cache_dir=root) is None
    assert not root.exists()


def test_etag_cache_honours_the_refusal(tmp_path: Path) -> None:
    root = tmp_path / "shared"
    cache.set_issue_etag("alice/proj", 7, etag='"e"', body={"b": 1}, cache_dir=root)
    assert cache.get_issue_etag("alice/proj", 7, cache_dir=root) is not None
    os.chmod(root, 0o777)
    assert cache.get_issue_etag("alice/proj", 7, cache_dir=root) is None
    cache.set_issue_etag("alice/proj", 8, etag='"f"', body={}, cache_dir=root)
    assert not (root / "etags" / "alice" / "proj" / "8.json").exists()


def test_kf_number_index_in_a_refused_dir_keeps_working_in_memory(tmp_path: Path) -> None:
    root = tmp_path / "shared"
    KfNumberIndex.for_board("B1", cache_dir=root).put(1, "task-a")
    os.chmod(root, 0o777)
    index = KfNumberIndex.for_board("B1", cache_dir=root)
    assert index.is_empty()  # the planted-file risk: the old file is not loaded
    index.put(2, "task-b")  # does not raise
    assert index.get(2) == "task-b"
    os.chmod(root, 0o700)
    assert KfNumberIndex.for_board("B1", cache_dir=root).get(2) is None  # nothing was written


# ---------- Owner in the snapshot key (#449) ----------


def test_same_project_number_with_different_owners_never_shares_a_snapshot(tmp_path: Path) -> None:
    cache.set_item_list(4, owner="alice", items=[{"who": "alice"}], cache_dir=tmp_path)
    assert cache.get_item_list(4, owner="bob", cache_dir=tmp_path) is None
    cache.set_item_list(4, owner="bob", items=[{"who": "bob"}], cache_dir=tmp_path)
    assert cache.get_item_list(4, owner="alice", cache_dir=tmp_path) == [{"who": "alice"}]
    assert cache.get_item_list(4, owner="bob", cache_dir=tmp_path) == [{"who": "bob"}]


def test_closed_items_are_keyed_by_owner_too(tmp_path: Path) -> None:
    cache.set_closed_items(4, owner="alice", items=[{"who": "alice"}], cache_dir=tmp_path)
    assert cache.get_closed_items(4, owner="bob", cache_dir=tmp_path) is None
    assert cache.get_closed_items(4, owner="alice", cache_dir=tmp_path) == [{"who": "alice"}]


def test_invalidating_one_owner_leaves_the_other_intact(tmp_path: Path) -> None:
    for owner in ("alice", "bob"):
        cache.set_item_list(4, owner=owner, items=[{"who": owner}], cache_dir=tmp_path)
        cache.set_closed_items(4, owner=owner, items=[{"who": owner}], cache_dir=tmp_path)
    cache.invalidate_item_list(4, owner="alice", cache_dir=tmp_path)
    cache.invalidate_closed_items(4, owner="alice", cache_dir=tmp_path)
    assert cache.get_item_list(4, owner="alice", cache_dir=tmp_path) is None
    assert cache.get_closed_items(4, owner="alice", cache_dir=tmp_path) is None
    assert cache.get_item_list(4, owner="bob", cache_dir=tmp_path) == [{"who": "bob"}]
    assert cache.get_closed_items(4, owner="bob", cache_dir=tmp_path) == [{"who": "bob"}]


def test_an_owner_with_path_characters_stays_inside_the_cache_dir(tmp_path: Path) -> None:
    root = tmp_path / "cache"
    cache.set_item_list(4, owner="../escape", items=[{"a": 1}], cache_dir=root)
    assert cache.get_item_list(4, owner="../escape", cache_dir=root) == [{"a": 1}]
    assert not (tmp_path / "escape-4.json").exists()
    assert [p.parent for p in root.rglob("*.json")] == [root]


def test_owners_that_differ_only_in_punctuation_get_different_files(tmp_path: Path) -> None:
    cache.set_item_list(4, owner="a/b", items=[{"who": "slash"}], cache_dir=tmp_path)
    cache.set_item_list(4, owner="a_b", items=[{"who": "underscore"}], cache_dir=tmp_path)
    assert cache.get_item_list(4, owner="a/b", cache_dir=tmp_path) == [{"who": "slash"}]
    assert cache.get_item_list(4, owner="a_b", cache_dir=tmp_path) == [{"who": "underscore"}]


def test_an_empty_owner_is_a_programming_error(tmp_path: Path) -> None:
    # An empty owner would put every board back in one shared key.
    with pytest.raises(ValueError, match="owner"):
        cache.set_item_list(4, owner="", items=[], cache_dir=tmp_path)


def _two_owner_gh(monkeypatch: pytest.MonkeyPatch) -> list[list[str]]:
    """Fake `gh project item-list` so each owner's board holds one distinct item."""
    monkeypatch.delenv("JARED_NO_CACHE", raising=False)
    return patch_gh_by_arg(
        monkeypatch,
        {
            "--owner alice": json.dumps(
                {"items": [{"id": "from-alice", "content": {"number": 1}}]}
            ),
            "--owner bob": json.dumps({"items": [{"id": "from-bob", "content": {"number": 1}}]}),
        },
    )


def test_board_items_never_serves_one_owners_snapshot_to_another(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from skills.jared.scripts.lib.board import Board

    calls = _two_owner_gh(monkeypatch)
    assert Board(project_number=4, owner="alice").board_items()[0]["id"] == "from-alice"
    assert Board(project_number=4, owner="bob").board_items()[0]["id"] == "from-bob"
    assert len(calls) == 2  # bob's read missed alice's snapshot and went to gh

    # Each owner now has a warm snapshot of its own: no further gh call.
    assert Board(project_number=4, owner="alice").board_items()[0]["id"] == "from-alice"
    assert Board(project_number=4, owner="bob").board_items()[0]["id"] == "from-bob"
    assert len(calls) == 2


def test_board_invalidation_drops_only_its_own_owners_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from skills.jared.scripts.lib.board import Board

    calls = _two_owner_gh(monkeypatch)
    Board(project_number=4, owner="alice").board_items()
    Board(project_number=4, owner="bob").board_items()
    Board(project_number=4, owner="alice").invalidate_items()

    Board(project_number=4, owner="bob").board_items()
    assert len(calls) == 2  # bob's snapshot survived
    Board(project_number=4, owner="alice").board_items()
    assert len(calls) == 3  # alice's was dropped and refetched


def test_sweep_fetch_items_is_keyed_by_owner(monkeypatch: pytest.MonkeyPatch) -> None:
    sweep = import_sweep()
    calls = _two_owner_gh(monkeypatch)
    assert sweep.fetch_items("alice", "4")[0]["id"] == "from-alice"
    assert sweep.fetch_items("bob", "4")[0]["id"] == "from-bob"
    assert len(calls) == 2
