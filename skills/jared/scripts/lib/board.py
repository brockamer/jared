"""Shared helper for jared scripts: parse docs/project-board.md, wrap gh calls."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path


class BoardConfigError(Exception):
    """Raised when docs/project-board.md is missing or malformed."""


@dataclass
class Board:
    project_number: int
    project_id: str
    owner: str
    repo: str
    project_url: str
    _field_ids: dict[str, str] = field(default_factory=dict)
    _field_options: dict[str, dict[str, str]] = field(default_factory=dict)

    @classmethod
    def from_path(cls, path: Path) -> Board:
        if not path.exists():
            raise BoardConfigError(
                f"Missing {path}. Run /jared-init to bootstrap the project."
            )
        text = path.read_text()
        return cls._parse(text, source=str(path))

    @classmethod
    def _parse(cls, text: str, *, source: str) -> Board:
        def find(pattern: str) -> str:
            m = re.search(pattern, text, re.MULTILINE)
            if not m:
                raise BoardConfigError(
                    f"Could not find required field matching r'{pattern}' in {source}"
                )
            return m.group(1).strip()

        project_url = find(r"Project URL:\s*(\S+)")
        project_number = int(find(r"Project number:\s*(\d+)"))
        project_id = find(r"Project ID:\s*(\S+)")
        owner = find(r"Owner:\s*(\S+)")
        repo = find(r"Repo:\s*(\S+)")

        return cls(
            project_number=project_number,
            project_id=project_id,
            owner=owner,
            repo=repo,
            project_url=project_url,
        )
