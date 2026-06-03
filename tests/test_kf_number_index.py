"""Unit tests for KfNumberIndex (disk-backed number -> KanbanFlow _id store)."""

from __future__ import annotations

from pathlib import Path

from skills.jared.scripts.lib.kf_number_index import KfNumberIndex


def test_put_get_roundtrip_persists_across_instances(tmp_path: Path) -> None:
    path = tmp_path / "kf-index-B1.json"
    idx = KfNumberIndex(path)
    idx.put(312, "task-abc")
    # A fresh instance reads the same file.
    reloaded = KfNumberIndex(path)
    assert reloaded.get(312) == "task-abc"


def test_get_missing_returns_none(tmp_path: Path) -> None:
    idx = KfNumberIndex(tmp_path / "kf-index-B1.json")
    assert idx.get(999) is None


def test_max_number_empty_is_zero(tmp_path: Path) -> None:
    idx = KfNumberIndex(tmp_path / "kf-index-B1.json")
    assert idx.is_empty() is True
    assert idx.max_number() == 0


def test_max_number_returns_highest_key(tmp_path: Path) -> None:
    idx = KfNumberIndex(tmp_path / "kf-index-B1.json")
    idx.put(3, "c")
    idx.put(11, "k")
    idx.put(7, "g")
    assert idx.max_number() == 11
    assert idx.is_empty() is False


def test_replace_overwrites_whole_map(tmp_path: Path) -> None:
    idx = KfNumberIndex(tmp_path / "kf-index-B1.json")
    idx.put(1, "a")
    idx.replace({5: "e", 6: "f"})
    assert idx.get(1) is None
    assert idx.get(5) == "e"
    assert idx.max_number() == 6


def test_for_board_uses_cache_dir_and_board_id(tmp_path: Path) -> None:
    idx = KfNumberIndex.for_board("BOARD9", cache_dir=tmp_path)
    idx.put(2, "b")
    assert (tmp_path / "kf-index-BOARD9.json").exists()


def test_corrupt_file_is_treated_as_empty(tmp_path: Path) -> None:
    path = tmp_path / "kf-index-B1.json"
    path.write_text("{ not json")
    idx = KfNumberIndex(path)
    assert idx.is_empty() is True
