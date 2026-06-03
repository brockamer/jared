"""Disk-backed number <-> KanbanFlow _id index (#316, Phase 3).

KanbanFlow has no get-task-by-number endpoint, and create_task requires an
explicit number. So jared owns #N allocation and persists a number -> _id map
for resolution. Because the jared CLI runs as one-shot processes, this map
lives on disk (the same reason cache.py exists). It is rebuildable: a lost or
corrupt file costs one full board scan to reseed, never correctness.

Stored as {"numbers": {"<N>": "<task_id>"}}. Writes use atomic-rename
(os.replace on a .tmp sibling), matching cache.py.

Concurrency: document-and-accept (operator decision 2026-06-03). Two concurrent
`jared file` calls may both pick max+1 and collide (last-writer-wins on the
index); a reseed scan + manual renumber repairs it. No locking.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from . import cache


class KfNumberIndex:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._map: dict[int, str] = self._load()

    @classmethod
    def for_board(cls, board_id: str, *, cache_dir: Path | None = None) -> KfNumberIndex:
        base = cache_dir if cache_dir is not None else cache._default_cache_dir()
        return cls(base / f"kf-index-{board_id}.json")

    def _load(self) -> dict[int, str]:
        if not self._path.exists():
            return {}
        try:
            payload = json.loads(self._path.read_text())
            numbers = payload["numbers"]
            return {int(k): str(v) for k, v in numbers.items()}
        except (OSError, json.JSONDecodeError, KeyError, AttributeError, ValueError, TypeError):
            return {}

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"numbers": {str(k): v for k, v in self._map.items()}}
        tmp = self._path.with_suffix(self._path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload))
        os.replace(tmp, self._path)

    def get(self, number: int) -> str | None:
        return self._map.get(number)

    def put(self, number: int, task_id: str) -> None:
        self._map[number] = task_id
        self._save()

    def replace(self, mapping: dict[int, str]) -> None:
        self._map = dict(mapping)
        self._save()

    def is_empty(self) -> bool:
        return not self._map

    def max_number(self) -> int:
        return max(self._map, default=0)
