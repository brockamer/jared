"""Shared helper for jared scripts: parse docs/project-board.md, wrap gh calls."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path


class BoardConfigError(Exception):
    """Raised when docs/project-board.md is missing or malformed."""


class FieldNotFound(Exception):
    """Raised when a field name is not present in docs/project-board.md."""


class OptionNotFound(Exception):
    """Raised when a field's option name is not present in docs/project-board.md."""


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

        field_ids, field_options = cls._parse_field_blocks(text)

        return cls(
            project_number=project_number,
            project_id=project_id,
            owner=owner,
            repo=repo,
            project_url=project_url,
            _field_ids=field_ids,
            _field_options=field_options,
        )

    @staticmethod
    def _parse_field_blocks(text: str) -> tuple[dict[str, str], dict[str, dict[str, str]]]:
        field_ids: dict[str, str] = {}
        field_options: dict[str, dict[str, str]] = {}

        # Split on "### " at start of line. Each block opens with the field name.
        blocks = re.split(r"^### ", text, flags=re.MULTILINE)[1:]
        for block in blocks:
            lines = block.splitlines()
            if not lines:
                continue
            field_name = lines[0].strip()
            options: dict[str, str] = {}
            field_id: str | None = None
            for line in lines[1:]:
                m = re.match(r"^\s*-\s*Field ID:\s*(\S+)\s*$", line)
                if m:
                    field_id = m.group(1)
                    continue
                m = re.match(r"^\s*-\s*(.+?):\s*(OPTION_\S+)\s*$", line)
                if m:
                    options[m.group(1).strip()] = m.group(2).strip()
            if field_id is None:
                continue
            field_ids[field_name] = field_id
            field_options[field_name] = options

        return field_ids, field_options

    def field_id(self, name: str) -> str:
        if name not in self._field_ids:
            available = ", ".join(sorted(self._field_ids)) or "(none)"
            raise FieldNotFound(
                f"Field '{name}' not found in project-board.md. Available: {available}"
            )
        return self._field_ids[name]

    def option_id(self, field_name: str, option: str) -> str:
        options = self._field_options.get(field_name, {})
        if option not in options:
            available = ", ".join(sorted(options)) or "(none)"
            raise OptionNotFound(
                f"Option '{option}' not found for field '{field_name}'. "
                f"Available: {available}"
            )
        return options[option]
