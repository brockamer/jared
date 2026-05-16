"""Cross-process on-disk snapshot cache for `gh project item-list` results (#52).

The `Board.board_items()` Layer-1 in-memory cache only spans one Python process.
This module provides Layer-2: a JSON file at `<cache_dir>/<project_number>.json`
that multiple processes can share within a configurable TTL.

Concurrency: writes use atomic-rename (`os.replace` on a `.tmp` sibling), so a
concurrent reader either sees the old file or the new file — never a partial
write. Multiple concurrent writers race to last-write-wins; both produce valid
snapshots, so the race is safe (each wasted a `gh` call but the file is sane).
"""

from __future__ import annotations

import contextlib
import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any


def _default_cache_dir() -> Path:
    override = os.environ.get("JARED_CACHE_DIR")
    if override:
        return Path(override)
    return Path(tempfile.gettempdir()) / "jared-cache"


def _cache_path(project_number: int, cache_dir: Path | None) -> Path:
    base = cache_dir if cache_dir is not None else _default_cache_dir()
    return base / f"{project_number}.json"


def set_item_list(
    project_number: int,
    *,
    items: list[dict[str, Any]],
    cache_dir: Path | None = None,
) -> None:
    """Atomically write items to the cache file for this project.

    Uses a `.tmp` sibling + `os.replace` so concurrent readers never see a
    partial write. Creates the cache directory if missing.
    """
    path = _cache_path(project_number, cache_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"fetched_at": time.time(), "items": items}
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload))
    os.replace(tmp, path)


def invalidate_item_list(
    project_number: int,
    *,
    cache_dir: Path | None = None,
) -> None:
    """Remove the cache file for this project. No-op if absent."""
    path = _cache_path(project_number, cache_dir)
    with contextlib.suppress(FileNotFoundError):
        path.unlink()


def get_item_list(
    project_number: int,
    *,
    ttl_seconds: int = 60,
    cache_dir: Path | None = None,
) -> list[dict[str, Any]] | None:
    """Return cached items if the cache file exists and is within TTL, else None."""
    path = _cache_path(project_number, cache_dir)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return None
    fetched_at = payload.get("fetched_at")
    items = payload.get("items")
    if not isinstance(fetched_at, (int, float)) or not isinstance(items, list):
        return None
    if time.time() - fetched_at > ttl_seconds:
        return None
    return items
