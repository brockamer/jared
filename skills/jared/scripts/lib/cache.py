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


# ---------- Closed-items cache (#186) ----------
#
# Separate file namespace (`<project>-closed.json`) so the open-items snapshot
# and the closed-items snapshot can be invalidated independently. The closed
# set is mostly monotone — what changes is each record's Status field (Done ↔
# stuck), which the invalidation hook in `_cmd_set` catches for first-party
# mutations. External mutations (raw `gh`, UI, PR-merge auto-close) accept
# staleness within TTL by design; see references/operations.md.
#
# 24h TTL by default — chosen so a daily cron-driven sweep gets at most one
# cache miss per day on a quiet board, and an interactive operator running
# `jared sweep` repeatedly in one session doesn't re-pay the full closed pull.


_CLOSED_DEFAULT_TTL_SECONDS = 24 * 60 * 60


def _closed_cache_path(project_number: int, cache_dir: Path | None) -> Path:
    base = cache_dir if cache_dir is not None else _default_cache_dir()
    return base / f"{project_number}-closed.json"


def set_closed_items(
    project_number: int,
    *,
    items: list[dict[str, Any]],
    cache_dir: Path | None = None,
) -> None:
    """Atomically write the closed-items snapshot for this project."""
    path = _closed_cache_path(project_number, cache_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"fetched_at": time.time(), "items": items}
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload))
    os.replace(tmp, path)


def invalidate_closed_items(
    project_number: int,
    *,
    cache_dir: Path | None = None,
) -> None:
    """Remove the closed-items cache file. No-op if absent."""
    path = _closed_cache_path(project_number, cache_dir)
    with contextlib.suppress(FileNotFoundError):
        path.unlink()


def get_closed_items(
    project_number: int,
    *,
    ttl_seconds: int = _CLOSED_DEFAULT_TTL_SECONDS,
    cache_dir: Path | None = None,
) -> list[dict[str, Any]] | None:
    """Return cached closed-items if the file exists and is within TTL, else None."""
    path = _closed_cache_path(project_number, cache_dir)
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


def _etag_cache_path(
    repo: str,
    number: int,
    cache_dir: Path | None = None,
) -> Path:
    base = cache_dir if cache_dir is not None else _default_cache_dir()
    return base / "etags" / repo / f"{number}.json"


def get_issue_etag(
    repo: str,
    number: int,
    *,
    cache_dir: Path | None = None,
) -> tuple[str, dict[str, Any]] | None:
    """Return (etag, body) for a cached REST issue response, or None.

    Companion to `fetch_issue_state_rest`'s conditional-GET layer (#147).
    Stores etag and body together in one JSON file so a reader can never
    observe a stale-etag/fresh-body pair — `os.replace` is the single
    atomicity boundary, matching `set_item_list`'s pattern. Returns None
    when the file is missing, malformed, or the body isn't a dict.
    """
    path = _etag_cache_path(repo, number, cache_dir)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    etag = payload.get("etag")
    body = payload.get("body")
    if not isinstance(etag, str) or not etag or not isinstance(body, dict):
        return None
    return etag, body


def set_issue_etag(
    repo: str,
    number: int,
    *,
    etag: str,
    body: dict[str, Any],
    cache_dir: Path | None = None,
) -> None:
    """Atomically write the (ETag, JSON body) pair for a REST issue response."""
    path = _etag_cache_path(repo, number, cache_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"etag": etag, "body": body}
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload))
    os.replace(tmp, path)
