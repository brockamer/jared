"""Cross-process on-disk snapshot cache for `gh project item-list` results (#52).

The `Board.board_items()` Layer-1 in-memory cache only spans one Python process.
This module provides Layer-2: a JSON file at `<cache_dir>/<owner>-<project_number>.json`
that multiple processes can share within a configurable TTL.

Where it lives. `JARED_CACHE_DIR` if set, else `$XDG_CACHE_HOME/jared`, else
`~/.cache/jared`. The cache holds board data, including private-repo issue
bodies, and jared reads it back as trusted input, so the directory is private to
the user: it is created with mode 0700 and its files with 0600. A directory that
already exists is used only if the current user owns it and no other user can
write to it, and a symbolic link is used only if the current user owns the link.
Otherwise jared says why on stderr, once, and runs without the
on-disk cache for that directory, as if `JARED_NO_CACHE=1` were set.

Concurrency: writes use atomic-rename (`os.replace` on a `.tmp` sibling), so a
concurrent reader either sees the old file or the new file — never a partial
write. Multiple concurrent writers race to last-write-wins; both produce valid
snapshots, so the race is safe (each wasted a `gh` call but the file is sane).
"""

from __future__ import annotations

import contextlib
import json
import os
import stat
import sys
import time
from pathlib import Path
from typing import Any
from urllib.parse import quote

_PRIVATE_DIR_MODE = 0o700
_PRIVATE_FILE_MODE = 0o600

# Directories already reported as unusable in this process, so a refusal is
# said once however many cache calls follow.
_warned: set[str] = set()


def _default_cache_dir() -> Path:
    override = os.environ.get("JARED_CACHE_DIR")
    if override:
        return Path(override)
    xdg = os.environ.get("XDG_CACHE_HOME")
    if xdg and os.path.isabs(xdg):  # the XDG spec says to ignore a relative value
        return Path(xdg) / "jared"
    return Path.home() / ".cache" / "jared"


def _root(cache_dir: Path | None) -> Path:
    return cache_dir if cache_dir is not None else _default_cache_dir()


def _current_uid() -> int | None:
    """The user's uid, or None where the platform has no such thing."""
    return os.getuid() if hasattr(os, "getuid") else None


def _lstat(path: Path) -> os.stat_result:
    """`stat` without following a final symlink. A seam, so tests can fake a link's owner."""
    return path.lstat()


def _refusal_reason(root: Path) -> str | None:
    """Why the existing directory `root` must not be used, or None if it is safe."""
    uid = _current_uid()
    try:
        link = _lstat(root)
        st = root.stat()
    except OSError as exc:
        return f"it cannot be inspected ({exc.strerror})"
    # `stat` follows a link, so a link someone else planted in a shared parent
    # would otherwise be judged by its target, which can be the user's own.
    if stat.S_ISLNK(link.st_mode) and uid is not None and link.st_uid != uid:
        return f"it is a symbolic link owned by another user (uid {link.st_uid})"
    if not stat.S_ISDIR(st.st_mode):
        return "it is not a directory"
    if uid is not None and st.st_uid != uid:
        return f"it is not owned by the current user (owner uid {st.st_uid})"
    if st.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
        return f"it is writable by other users (mode {stat.S_IMODE(st.st_mode):04o})"
    return None


def _warn_once(root: Path, reason: str) -> None:
    if str(root) in _warned:
        return
    _warned.add(str(root))
    print(
        f"jared: not using cache directory {root}: {reason}; continuing without the on-disk cache",
        file=sys.stderr,
    )


def _ensure_private_dir(path: Path) -> None:
    """Create `path` with mode 0700 if it is missing. Its parents get default modes."""
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        path.mkdir(mode=_PRIVATE_DIR_MODE)
    except FileExistsError:
        return
    os.chmod(path, _PRIVATE_DIR_MODE)  # exact, whatever the umask removed


def usable_for_read(root: Path) -> bool:
    """True when `root` exists and is safe to read cached data from.

    A missing directory is a plain cache miss: nothing is created and nothing is
    said. An unsafe one is refused, because anyone who can write there could have
    planted the file being read.
    """
    if not root.exists():
        return False
    reason = _refusal_reason(root)
    if reason is not None:
        _warn_once(root, reason)
        return False
    return True


def write_private_json(path: Path, payload: Any) -> None:
    """Write `payload` as JSON to `path` atomically, with mode 0600.

    `mkdir(parents=True, mode=...)` applies its mode to the leaf only, and a
    `.tmp` file left by an earlier run keeps its old mode, so the mode is set on
    the open descriptor, not assumed from the umask.
    """
    tmp = path.with_suffix(path.suffix + ".tmp")
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0)
    with os.fdopen(os.open(tmp, flags, _PRIVATE_FILE_MODE), "w") as fh:
        os.fchmod(fh.fileno(), _PRIVATE_FILE_MODE)
        fh.write(json.dumps(payload))
    os.replace(tmp, path)


def write_under(root: Path, path: Path, payload: Any) -> None:
    """Write `payload` to `path` inside the cache directory `root`.

    Creates `root`, and each directory between it and `path`, with mode 0700.
    Does nothing if `root` is refused or cannot be created: the cache is an
    optimisation, so an unusable directory costs a cache miss, never a failure.
    """
    try:
        _ensure_private_dir(root)
    except OSError as exc:
        _warn_once(root, f"it cannot be created ({exc.strerror})")
        return
    reason = _refusal_reason(root)
    if reason is not None:
        _warn_once(root, reason)
        return
    level = root
    for part in path.parent.relative_to(root).parts:
        level = level / part
        _ensure_private_dir(level)
    write_private_json(path, payload)


def _owner_key(owner: str) -> str:
    """Filename-safe, collision-free form of a project owner.

    Project numbers are unique per owner, not globally, so the owner is part of
    every snapshot key (#449). Percent-encoding is injective, so owners that
    differ only in punctuation still get different files, and no owner can name
    a path outside the cache directory.
    """
    if not owner:
        raise ValueError("owner is required: an empty owner would share one snapshot key")
    return quote(owner, safe="")


def _cache_path(owner: str, project_number: int, cache_dir: Path | None) -> Path:
    return _root(cache_dir) / f"{_owner_key(owner)}-{project_number}.json"


def set_item_list(
    project_number: int,
    *,
    owner: str,
    items: list[dict[str, Any]],
    cache_dir: Path | None = None,
) -> None:
    """Atomically write items to the cache file for this project.

    Uses a `.tmp` sibling + `os.replace` so concurrent readers never see a
    partial write. Creates the cache directory if missing.
    """
    path = _cache_path(owner, project_number, cache_dir)
    write_under(_root(cache_dir), path, {"fetched_at": time.time(), "items": items})


def invalidate_item_list(
    project_number: int,
    *,
    owner: str,
    cache_dir: Path | None = None,
) -> None:
    """Remove the cache file for this project. No-op if absent."""
    path = _cache_path(owner, project_number, cache_dir)
    with contextlib.suppress(FileNotFoundError):
        path.unlink()


def get_item_list(
    project_number: int,
    *,
    owner: str,
    ttl_seconds: int = 60,
    cache_dir: Path | None = None,
) -> list[dict[str, Any]] | None:
    """Return cached items if the cache file exists and is within TTL, else None."""
    path = _cache_path(owner, project_number, cache_dir)
    if not usable_for_read(_root(cache_dir)) or not path.exists():
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
# Separate file namespace (`<owner>-<project>-closed.json`) so the open-items
# snapshot and the closed-items snapshot can be invalidated independently. The
# closed set is mostly monotone — what changes is each record's Status field
# (Done ↔ stuck), which the invalidation hook in `_cmd_set` catches for
# first-party mutations. External mutations (raw `gh`, UI, PR-merge auto-close)
# accept staleness within TTL by design; see references/operations.md.
#
# 24h TTL by default — chosen so a daily cron-driven sweep gets at most one
# cache miss per day on a quiet board, and an interactive operator running
# `jared sweep` repeatedly in one session doesn't re-pay the full closed pull.


_CLOSED_DEFAULT_TTL_SECONDS = 24 * 60 * 60


def _closed_cache_path(owner: str, project_number: int, cache_dir: Path | None) -> Path:
    return _root(cache_dir) / f"{_owner_key(owner)}-{project_number}-closed.json"


def set_closed_items(
    project_number: int,
    *,
    owner: str,
    items: list[dict[str, Any]],
    cache_dir: Path | None = None,
) -> None:
    """Atomically write the closed-items snapshot for this project."""
    path = _closed_cache_path(owner, project_number, cache_dir)
    write_under(_root(cache_dir), path, {"fetched_at": time.time(), "items": items})


def invalidate_closed_items(
    project_number: int,
    *,
    owner: str,
    cache_dir: Path | None = None,
) -> None:
    """Remove the closed-items cache file. No-op if absent."""
    path = _closed_cache_path(owner, project_number, cache_dir)
    with contextlib.suppress(FileNotFoundError):
        path.unlink()


def get_closed_items(
    project_number: int,
    *,
    owner: str,
    ttl_seconds: int = _CLOSED_DEFAULT_TTL_SECONDS,
    cache_dir: Path | None = None,
) -> list[dict[str, Any]] | None:
    """Return cached closed-items if the file exists and is within TTL, else None."""
    path = _closed_cache_path(owner, project_number, cache_dir)
    if not usable_for_read(_root(cache_dir)) or not path.exists():
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
    return _root(cache_dir) / "etags" / repo / f"{number}.json"


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
    if not usable_for_read(_root(cache_dir)) or not path.exists():
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
    write_under(_root(cache_dir), path, {"etag": etag, "body": body})
