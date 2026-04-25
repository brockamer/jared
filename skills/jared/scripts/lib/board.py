"""Shared helper for jared scripts: parse docs/project-board.md, wrap gh calls."""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


class BoardConfigError(Exception):
    """Raised when docs/project-board.md is missing or malformed."""


class FieldNotFound(Exception):
    """Raised when a field name is not present in docs/project-board.md."""


class OptionNotFound(Exception):
    """Raised when a field's option name is not present in docs/project-board.md."""


class GhInvocationError(Exception):
    """Raised when `gh` exits non-zero or returns unparseable output."""


class ItemNotFound(Exception):
    """Raised when no project item corresponds to the given issue number."""


@dataclass
class Board:
    project_number: int
    project_id: str
    owner: str
    repo: str
    project_url: str
    _field_ids: dict[str, str] = field(default_factory=dict)
    _field_options: dict[str, dict[str, str]] = field(default_factory=dict)
    session_handoff_prompt: str = "ask"
    session_start_checks: list[str] = field(default_factory=list)

    @classmethod
    def from_path(cls, path: Path) -> Board:
        if not path.exists():
            raise BoardConfigError(f"Missing {path}. Run /jared-init to bootstrap the project.")
        text = path.read_text()
        repo_fallback = _infer_repo_from_git(path.parent.parent)
        return cls._parse(text, source=str(path), repo_fallback=repo_fallback)

    @classmethod
    def _parse(cls, text: str, *, source: str, repo_fallback: str | None = None) -> Board:
        # Bootstrapped-with-header docs carry machine-readable bullets for all
        # five fields; older hand-written docs (e.g. pre-bootstrap.py) only
        # carry the Project ID and put everything else in prose. Each field
        # tries its bullet first, then a fallback derived from other content
        # — so canonical docs take the fast path and legacy docs still parse.
        def find_optional(pattern: str) -> str | None:
            m = re.search(pattern, text, re.MULTILINE)
            return m.group(1).strip() if m else None

        # The URL fallback doubles as the source for project_number and owner,
        # so resolve it first. Accepts either the bullet or the first
        # github.com/{users,orgs}/<owner>/projects/<N> link in the doc.
        project_url = find_optional(r"Project URL:\s*(\S+)")
        url_match: re.Match[str] | None = None
        if project_url is None:
            url_match = re.search(
                r"https?://github\.com/(?:users|orgs)/([^/\s]+)/projects/(\d+)",
                text,
            )
            if url_match is not None:
                project_url = url_match.group(0)
        else:
            url_match = re.search(
                r"https?://github\.com/(?:users|orgs)/([^/\s]+)/projects/(\d+)",
                project_url,
            )

        project_id = find_optional(r"Project ID:\s*(\S+)")

        number_raw = find_optional(r"Project number:\s*(\d+)")
        project_number_val: int | None = int(number_raw) if number_raw else None
        if project_number_val is None and url_match is not None:
            project_number_val = int(url_match.group(2))

        owner = find_optional(r"Owner:\s*(\S+)") or (url_match.group(1) if url_match else None)

        repo = find_optional(r"Repo:\s*(\S+)") or repo_fallback

        missing: list[str] = []
        if project_url is None:
            missing.append("Project URL")
        if project_id is None:
            missing.append("Project ID")
        if project_number_val is None:
            missing.append("Project number")
        if owner is None:
            missing.append("Owner")
        if repo is None:
            missing.append("Repo")
        if missing:
            raise BoardConfigError(
                f"{source} missing required field(s): {', '.join(missing)}. "
                "Run /jared-init to bootstrap or patch the file."
            )
        # Narrow Optional types after the missing-fields check for mypy.
        assert project_url is not None
        assert project_id is not None
        assert project_number_val is not None
        assert owner is not None
        assert repo is not None

        field_ids, field_options = cls._parse_field_blocks(text)
        session_handoff_prompt = cls._parse_jared_config(text).get("session-handoff-prompt", "ask")
        session_start_checks = cls._parse_session_start_checks(text)

        return cls(
            project_number=project_number_val,
            project_id=project_id,
            owner=owner,
            repo=repo,
            project_url=project_url,
            _field_ids=field_ids,
            _field_options=field_options,
            session_handoff_prompt=session_handoff_prompt,
            session_start_checks=session_start_checks,
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
                # Stop parsing this block if we hit a new section header —
                # prevents narrative bullets below the field blocks from being
                # mis-interpreted as options.
                if line.startswith("#"):
                    break
                m = re.match(r"^\s*-\s*Field ID:\s*(\S+)\s*$", line)
                if m:
                    field_id = m.group(1)
                    continue
                # Option line: "- <Option Name>: <id>" where <id> is any non-
                # whitespace token. Real gh option IDs are 8-char hex
                # (e.g. "0369b485"); the test-fixture prefix "OPTION_foo" also
                # matches. Narrative bullets like "- Backlog: captured but …"
                # are avoided because a space in the value won't match \S+.
                m = re.match(r"^\s*-\s*(.+?):\s*(\S+)\s*$", line)
                if m:
                    options[m.group(1).strip()] = m.group(2).strip()
            if field_id is None:
                continue
            field_ids[field_name] = field_id
            field_options[field_name] = options

        return field_ids, field_options

    @staticmethod
    def _parse_jared_config(text: str) -> dict[str, str]:
        """Parse the optional `## Jared config` section's bullets.

        Bullets are `- name: value` pairs. Anything that doesn't match the
        bullet form is skipped. Section ends at the next `##` heading or
        end-of-file. Returns an empty dict if the section is absent.
        """
        m = re.search(
            r"^## Jared config\s*\n(.*?)(?=^##\s|\Z)",
            text,
            re.MULTILINE | re.DOTALL,
        )
        if not m:
            return {}
        result: dict[str, str] = {}
        for line in m.group(1).splitlines():
            bullet = re.match(r"^\s*-\s*([\w-]+):\s*(.+?)\s*$", line)
            if bullet:
                result[bullet.group(1)] = bullet.group(2)
        return result

    @staticmethod
    def _parse_session_start_checks(text: str) -> list[str]:
        """Parse the optional `## Session start checks` section's fenced bash blocks.

        Each ```bash ... ``` (or just ``` ... ```) becomes one entry, joined
        by newlines if the block has multiple lines. Section ends at the next
        `##` heading or end-of-file. Returns [] if section is absent.
        """
        m = re.search(
            r"^## Session start checks\s*\n(.*?)(?=^##\s|\Z)",
            text,
            re.MULTILINE | re.DOTALL,
        )
        if not m:
            return []
        section = m.group(1)
        checks: list[str] = []
        for fenced in re.finditer(r"```(?:bash)?\s*\n(.*?)```", section, re.DOTALL):
            body = fenced.group(1).strip()
            if body:
                checks.append(body)
        return checks

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
                f"Option '{option}' not found for field '{field_name}'. Available: {available}"
            )
        return options[option]

    def run_gh(self, args: list[str]) -> Any:
        return run_gh(args)

    def run_gh_raw(self, args: list[str]) -> str:
        return run_gh_raw(args)

    def find_item_id(self, issue_number: int) -> str:
        """Look up the ProjectV2Item id for a given issue number on this board."""
        data = self.run_gh(
            [
                "project",
                "item-list",
                str(self.project_number),
                "--owner",
                self.owner,
                "--limit",
                "500",
                "--format",
                "json",
            ]
        )
        for item in data.get("items", []):
            content = item.get("content") or {}
            if content.get("number") == issue_number:
                return str(item["id"])
        raise ItemNotFound(
            f"No project item for issue #{issue_number} in project "
            f"{self.project_number}. Is the issue added to the board?"
        )

    def run_graphql(self, query: str, **variables: str | int | bool) -> Any:
        return run_graphql(query, **variables)


def run_gh(args: list[str]) -> Any:
    """Run a `gh` subcommand and parse its stdout as JSON (empty → {})."""
    stdout = run_gh_raw(args)
    if not stdout:
        return {}
    try:
        return json.loads(stdout)
    except json.JSONDecodeError as e:
        raise GhInvocationError(f"gh returned non-JSON output: {stdout[:200]}") from e


def run_gh_raw(args: list[str]) -> str:
    """Run a `gh` subcommand and return its stdout (stripped) without JSON parsing.

    Some gh commands return plain text (e.g. `gh issue create` prints a URL).
    Callers that need the raw string use this; JSON responses use run_gh.
    """
    result = subprocess.run(
        ["gh", *args],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise GhInvocationError(
            f"gh {' '.join(args)} exited {result.returncode}: {result.stderr.strip()}"
        )
    return result.stdout.strip()


def _infer_repo_from_git(repo_root: Path) -> str | None:
    """Return "owner/repo" from `git remote get-url origin`, or None.

    Fallback used when docs/project-board.md doesn't specify a `- Repo:`
    bullet — older bootstrap-less docs lean on this. Accepts SSH
    (`git@github.com:owner/repo.git`) and HTTPS
    (`https://github.com/owner/repo[.git]`) remote forms.
    """
    try:
        result = subprocess.run(
            ["git", "-C", str(repo_root), "remote", "get-url", "origin"],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    url = result.stdout.strip()
    m = re.search(r"github\.com[:/]([\w.-]+)/([\w.-]+?)(?:\.git)?/?$", url)
    if not m:
        return None
    return f"{m.group(1)}/{m.group(2)}"


def run_graphql(query: str, **variables: str | int | bool) -> Any:
    """Run a GraphQL query via `gh api graphql` with named variables.

    Uses gh's `-F` for bool/int (so gh casts to the right type) and `-f`
    for strings. Results come back parsed from JSON.
    """
    args = ["api", "graphql", "-f", f"query={query}"]
    for name, value in variables.items():
        flag = "-F" if isinstance(value, bool | int) and not isinstance(value, str) else "-f"
        args.extend([flag, f"{name}={value}"])
    return run_gh(args)
