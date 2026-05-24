"""Shared helper for jared scripts: parse docs/project-board.md, wrap gh calls."""

from __future__ import annotations

import contextlib
import datetime as dt
import json
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar, Literal

from . import cache

if TYPE_CHECKING:
    from .ties import OpenIssueForTies


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
    # Search order for autodiscovery when --board / --config is not supplied.
    # First entry is the canonical primary location; the rest are graceful
    # fallbacks for projects that follow common conventions (docs/maintainers/
    # for OSS contributor docs, root or .github/ for repo-level metadata).
    DEFAULT_CONFIG_PATHS: ClassVar[tuple[str, ...]] = (
        "docs/project-board.md",
        "docs/maintainers/project-board.md",
        "PROJECT_BOARD.md",
        ".github/project-board.md",
    )

    project_number: int
    project_id: str
    owner: str
    repo: str
    project_url: str
    _field_ids: dict[str, str] = field(default_factory=dict)
    _field_options: dict[str, dict[str, str]] = field(default_factory=dict)
    session_handoff_prompt: str = "ask"
    session_start_checks: list[str] = field(default_factory=list)
    # Optional "current-state operator docs" config — populated from the
    # `### Current-state operator docs` block in docs/project-board.md.
    # Both lists empty = check disabled (no block, or block lacks `Docs:`).
    # If `Docs:` is present but `Code surface:` is absent, code_surface
    # defaults to ['src/**']. See sweep.check_doc_sync_gate (#163).
    operator_docs: list[str] = field(default_factory=list)
    code_surface: list[str] = field(default_factory=list)
    # Cached `gh project item-list` result, populated on first board_items()
    # call and reused for the lifetime of this instance. None means uncached.
    _items: list[dict[str, Any]] | None = field(default=None, repr=False)
    # Verbatim text of docs/project-board.md, stored for post-parse lookups
    # (e.g. tie_stop_words). Set by from_path / _parse; empty string if not
    # constructed via those entry points (e.g. direct dataclass construction
    # in tests that don't need this feature).
    _raw_doc: str = field(default="", repr=False)

    @classmethod
    def find_default_path(cls, project_root: Path | None = None) -> Path | None:
        """Return the first existing path from DEFAULT_CONFIG_PATHS, or None.

        Searched relative to `project_root` (defaults to the nearest .git/
        ancestor of cwd, or cwd if no git root is found). Lets CLI subcommands
        find the convention doc when it has been relocated to one of the
        accepted alternative locations (e.g. docs/maintainers/).
        """
        root = project_root if project_root is not None else _find_project_root(Path.cwd())
        for candidate in cls.DEFAULT_CONFIG_PATHS:
            p = root / candidate
            if p.exists():
                return p
        return None

    @classmethod
    def from_default(cls, project_root: Path | None = None) -> Board:
        """Like `from_path`, but autodiscovers the convention doc.

        Raises BoardConfigError listing every attempted path when none is
        found, so the operator can see exactly where jared looked.
        """
        path = cls.find_default_path(project_root)
        if path is not None:
            return cls.from_path(path)
        root = project_root if project_root is not None else _find_project_root(Path.cwd())
        attempted = "\n".join(f"  - {root / p}" for p in cls.DEFAULT_CONFIG_PATHS)
        raise BoardConfigError(
            "No project-board.md found. Tried:\n"
            f"{attempted}\n"
            "Run /jared-init to bootstrap the project, or pass --board <path>."
        )

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
        operator_docs, code_surface = cls._parse_operator_docs(text)

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
            operator_docs=operator_docs,
            code_surface=code_surface,
            _raw_doc=text,
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
        bullet form is skipped. Section ends at the next `##` or `###`
        heading or end-of-file — stopping at `###` is what keeps a
        following `### Status` field block (whose option bullets like
        `- Backlog: <id>` would otherwise look like config bullets) from
        leaking into the config dict. Returns an empty dict if the
        section is absent.
        """
        m = re.search(
            r"^## Jared config\s*\n(.*?)(?=^#{2,3}\s|\Z)",
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
        by newlines if the block has multiple lines. Section ends at the
        next `##` or `###` heading or end-of-file. Returns [] if section
        is absent.
        """
        m = re.search(
            r"^## Session start checks\s*\n(.*?)(?=^#{2,3}\s|\Z)",
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

    @staticmethod
    def _parse_operator_docs(text: str) -> tuple[list[str], list[str]]:
        """Parse the optional `### Current-state operator docs` block.

        Two bullets supported:
            - Docs: comma-separated list of doc paths/globs
            - Code surface: comma-separated list of code-path globs

        Returns (operator_docs, code_surface). When the section is absent OR
        present-but-missing-`Docs:`, both lists are empty (check disabled).
        When `Docs:` is present and `Code surface:` is absent, code_surface
        defaults to ['src/**'].

        Section ends at next ### or ## heading or end-of-file — same idiom as
        the other optional-section parsers.
        """
        section_re = re.compile(
            r"^###\s+Current-state operator docs\s*$(?P<body>.*?)(?=^#{2,3}\s|\Z)",
            re.MULTILINE | re.DOTALL,
        )
        match = section_re.search(text)
        if not match:
            return [], []

        body = match.group("body")

        docs_re = re.compile(r"^\s*-\s*Docs:\s*(?P<list>.+?)\s*$", re.MULTILINE)
        docs_match = docs_re.search(body)
        if not docs_match:
            # Section present but Docs: bullet missing — treat as disabled.
            return [], []
        docs = [d.strip() for d in docs_match.group("list").split(",")]
        docs = [d for d in docs if d]

        surface_re = re.compile(r"^\s*-\s*Code surface:\s*(?P<list>.+?)\s*$", re.MULTILINE)
        surface_match = surface_re.search(body)
        if surface_match:
            surface = [s.strip() for s in surface_match.group("list").split(",")]
            surface = [s for s in surface if s]
        else:
            surface = ["src/**"]

        return docs, surface

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

    def tie_stop_words(self) -> frozenset[str]:
        """Project-specific label stop-words for ties analysis.

        Reads `### Tie Analysis` section from project-board.md if present:

            ### Tie Analysis
            - Label stop-words: foo, bar, baz

        Falls back to ties.DEFAULT_LABEL_STOP_WORDS otherwise. Override is
        total — defaults are NOT merged with project-specific words.
        """
        from .ties import DEFAULT_LABEL_STOP_WORDS

        text = self._raw_doc  # the verbatim project-board.md content
        section_re = re.compile(
            r"^###\s+Tie Analysis\s*$(?P<body>.*?)(?=^###\s|\Z)",
            re.MULTILINE | re.DOTALL,
        )
        match = section_re.search(text)
        if not match:
            return DEFAULT_LABEL_STOP_WORDS
        bullet_re = re.compile(r"^\s*-\s*Label stop-words:\s*(?P<words>.+?)\s*$", re.MULTILINE)
        bullet_match = bullet_re.search(match.group("body"))
        if not bullet_match:
            return DEFAULT_LABEL_STOP_WORDS
        words = [w.strip() for w in bullet_match.group("words").split(",")]
        return frozenset(w for w in words if w)

    def run_gh(self, args: list[str], *, cache: str | None = None) -> Any:
        return run_gh(args, cache=cache)

    def run_gh_raw(self, args: list[str], *, cache: str | None = None) -> str:
        return run_gh_raw(args, cache=cache)

    def board_items(self) -> list[dict[str, Any]]:
        """Cached `gh project item-list` result, shared across processes.

        Three layers (#52):
          1. In-process: `self._items`, lifetime of this Board instance.
          2. On-disk: JSON at `${JARED_CACHE_DIR:-${TMPDIR}/jared-cache}/<N>.json`,
             shared across all jared processes within `JARED_CACHE_TTL_SECONDS`.
          3. Fresh fetch via `gh project item-list` — GraphQL-billed.

        Callers that mutate the board within the same process must call
        `invalidate_items()` before reading again, or stale entries leak.
        Mutating-CLI subcommands invalidate the disk cache too so other
        processes refetch on their next read.

        Opt-out: `JARED_NO_CACHE=1` skips both cache layers.
        """
        if self._items is not None:
            return self._items
        no_cache = os.environ.get("JARED_NO_CACHE") == "1"
        if not no_cache:
            ttl = int(os.environ.get("JARED_CACHE_TTL_SECONDS", "60"))
            cached = cache.get_item_list(self.project_number, ttl_seconds=ttl)
            if cached is not None:
                self._items = cached
                return self._items
        limit = 2000
        data = self.run_gh(
            [
                "project",
                "item-list",
                str(self.project_number),
                "--owner",
                self.owner,
                "--limit",
                str(limit),
                "--format",
                "json",
            ]
        )
        self._items = data.get("items", [])
        if len(self._items) == limit:
            raise GhInvocationError(
                f"gh project item-list returned exactly {limit} items — "
                f"likely truncated. Raise the --limit or paginate; do not "
                f"trust this snapshot."
            )
        if not no_cache:
            cache.set_item_list(self.project_number, items=self._items)
        return self._items

    def invalidate_items(self) -> None:
        """Drop both in-process and on-disk snapshot caches."""
        self._items = None
        cache.invalidate_item_list(self.project_number)

    def invalidate_closed_items(self) -> None:
        """Drop the on-disk closed-items snapshot (#186).

        Called from `_cmd_set` when field_name=='Status' — Status mutations
        are the only first-party path that can move an item into or out of
        the closed set, so the invalidation is gated on field, not on every
        mutation. Non-Status writes (Priority, Work Stream) leave the cache
        intact to avoid a wasted full-board refetch on next sweep.
        """
        cache.invalidate_closed_items(self.project_number)

    _OPEN_ITEMS_QUERY = """
    query($owner: String!, $repo: String!) {
      repository(owner: $owner, name: $repo) {
        issues(states: OPEN, first: 100, orderBy: {field: CREATED_AT, direction: DESC}) {
          pageInfo { hasNextPage }
          nodes {
            number
            title
            state
            labels(first: 20) { nodes { name } }
            projectItems(first: 10) {
              nodes {
                id
                project { number }
                fieldValues(first: 20) {
                  nodes {
                    ... on ProjectV2ItemFieldSingleSelectValue {
                      name
                      field { ... on ProjectV2SingleSelectField { name } }
                    }
                  }
                }
              }
            }
          }
        }
      }
    }
    """

    def open_items(self) -> list[dict[str, Any]]:
        """Fetch open issues + their project field values in one GraphQL call.

        Hot-path callers (summary, next-session-prompt) only need open items;
        `board_items()` pulls Done too, so its cost scales with total board
        size on mature boards (#185). The single `repository.issues(states:
        OPEN)` query returns every open issue with its projectItems node
        embedded, so cost scales with open-issue count regardless of how
        much Done has accumulated.

        Returns dicts shaped like `board_items()` entries for open items:
        `{"content": {"number", "title", "state"}, "status", "priority"}`.
        Open issues not on the project board are excluded.

        Raises GhInvocationError if there are >100 open issues — pagination
        is not implemented and a silent truncation would mis-report status.
        """
        owner, repo_name = self.repo.split("/", 1)
        data = self.run_graphql(
            self._OPEN_ITEMS_QUERY,
            owner=owner,
            repo=repo_name,
        )
        issues_node = (data.get("data") or {}).get("repository", {}).get("issues") or {}
        if (issues_node.get("pageInfo") or {}).get("hasNextPage"):
            raise GhInvocationError(
                "open_items() query returned hasNextPage=true; >100 open issues "
                "on this repo. Pagination not implemented — bump the first: cap "
                "or add cursor-based pagination."
            )
        items: list[dict[str, Any]] = []
        for issue in issues_node.get("nodes", []) or []:
            if not isinstance(issue, dict):
                continue
            number = issue.get("number")
            if not isinstance(number, int):
                continue
            flat = _flatten_project_item_for_project(issue.get("projectItems"), self.project_number)
            if flat is None:
                continue
            labels_node = issue.get("labels") or {}
            label_names = tuple(
                n["name"] for n in (labels_node.get("nodes") or []) if "name" in n
            )
            items.append(
                {
                    "content": {
                        "number": number,
                        "title": issue.get("title", ""),
                        "state": issue.get("state", "OPEN"),
                    },
                    "status": flat.get("status"),
                    "priority": flat.get("priority"),
                    "labels": label_names,
                }
            )
        return items

    _ISSUE_PROJECT_ITEM_QUERY = """
    query($owner: String!, $repo: String!, $number: Int!) {
      repository(owner: $owner, name: $repo) {
        issue(number: $number) {
          projectItems(first: 10) {
            nodes {
              id
              project { number }
              fieldValues(first: 20) {
                nodes {
                  ... on ProjectV2ItemFieldSingleSelectValue {
                    name
                    field { ... on ProjectV2SingleSelectField { name } }
                  }
                }
              }
            }
          }
        }
      }
    }
    """

    def fetch_item_for_issue(self, issue_number: int) -> dict[str, Any] | None:
        """Fetch this issue's project item via a scoped projectItems query.

        Costs ~1-3 GraphQL points vs ~200-300 for a full item-list scan.
        Returns a dict with at least 'id' plus any single-select fields
        lowercased (e.g. 'status', 'priority'), or None if the issue is
        not on this board. Fix for #109.

        For batched lookups across many issues, prefer the module-level
        `fetch_project_items_batch` (one gh call instead of N).
        """
        owner, repo_name = self.repo.split("/", 1)
        data = self.run_graphql(
            self._ISSUE_PROJECT_ITEM_QUERY,
            owner=owner,
            repo=repo_name,
            number=issue_number,
        )
        issue = (data.get("data") or {}).get("repository", {}).get("issue") or {}
        return _flatten_project_item_for_project(issue.get("projectItems"), self.project_number)

    def find_item_id(self, issue_number: int) -> str:
        """Look up the ProjectV2Item id for a given issue number on this board.

        Uses a scoped per-issue projectItems query (~1-3 GraphQL points)
        instead of a full item-list scan (~200-300 points). Fix for #109.
        """
        item = self.fetch_item_for_issue(issue_number)
        if item and item.get("id"):
            return str(item["id"])
        raise ItemNotFound(
            f"No project item for issue #{issue_number} in project "
            f"{self.project_number}. Is the issue added to the board?"
        )

    def _add_to_board(self, issue_number: int) -> str:
        """Call `gh project item-add` for `issue_number` and return the new item-id.

        Invalidates the cached item-list snapshot so subsequent `find_item_id`
        calls in the same process see the addition.

        Empirically idempotent (jared#71, 2026-05-01): calling item-add on an
        already-on-board issue exits 0 and returns the existing item-id, so
        the `assume_new=True` short-circuit in `add_existing_to_board` and
        the recovery flow from #64 are safe to re-run.
        """
        url = f"https://github.com/{self.repo}/issues/{issue_number}"
        data = self.run_gh(
            [
                "project",
                "item-add",
                str(self.project_number),
                "--owner",
                self.owner,
                "--url",
                url,
                "--format",
                "json",
            ]
        )
        self.invalidate_items()
        item_id = data.get("id") or ""
        if not item_id:
            # gh project item-add occasionally returns a body with no `id` on
            # the first call but succeeds immediately on retry (jared#112).
            data = self.run_gh(
                [
                    "project",
                    "item-add",
                    str(self.project_number),
                    "--owner",
                    self.owner,
                    "--url",
                    url,
                    "--format",
                    "json",
                ]
            )
            item_id = str(data.get("id") or "")
        if not item_id:
            raise GhInvocationError(f"item-add returned no id for issue {issue_number} after retry")
        return item_id

    def add_existing_to_board(
        self,
        issue_number: int,
        *,
        priority: str,
        status: str,
        labels: list[str] | None = None,
        fields: list[tuple[str, str]] | None = None,
        assume_new: bool = False,
    ) -> str:
        """Add an issue to the board (if needed), apply labels, set Priority/Status/extras.

        Idempotent: re-running on a fully-configured item is a no-op at the
        GitHub API level — `gh project item-edit` exits 0 when the field
        already holds the requested option, and `gh issue edit --add-label`
        is a no-op for labels already present.

        `assume_new=True` skips the `find_item_id` membership check and goes
        straight to `gh project item-add`. Used by `_cmd_file` after a fresh
        `gh issue create` to preserve the perf fix from #4 (no `item-list`
        scan in the filing hot path). Recovery callers leave it False so a
        re-run on an already-added item finds the existing item-id.

        Returns the item_id. Pre-resolves all field/option IDs before any
        GitHub call so misconfiguration raises before side effects. On any
        gh failure raises GhInvocationError; the caller may catch and
        synthesize a paste-and-run recovery command.
        """
        # Pre-resolve everything up front. FieldNotFound / OptionNotFound
        # raise here, before we touch GitHub.
        prio_field_id = self.field_id("Priority")
        prio_option_id = self.option_id("Priority", priority)
        status_field_id = self.field_id("Status")
        status_option_id = self.option_id("Status", status)
        extras: list[tuple[str, str]] = []
        for name, value in fields or []:
            extras.append((self.field_id(name), self.option_id(name, value)))

        # Resolve item-id. assume_new short-circuits the membership scan.
        item_id: str
        if assume_new:
            item_id = self._add_to_board(issue_number)
        else:
            try:
                item_id = self.find_item_id(issue_number)
            except ItemNotFound:
                item_id = self._add_to_board(issue_number)

        # Labels are issue-scoped, not item-scoped; gh issue edit handles it.
        if labels:
            label_args = ["issue", "edit", str(issue_number), "--repo", self.repo]
            for label in labels:
                label_args.extend(["--add-label", label])
            self.run_gh(label_args)

        # Build a single aliased mutation that sets Priority, Status, and any
        # extras in one GraphQL round-trip. IDs are opaque internal values
        # resolved above from project-board.md — interpolating them directly
        # is safe. cache=None is required (mutations must never be cached).
        all_fields = [
            ("setPriority", prio_field_id, prio_option_id),
            ("setStatus", status_field_id, status_option_id),
            *[(f"setExtra{i}", fid, oid) for i, (fid, oid) in enumerate(extras)],
        ]
        mutation_parts = "\n  ".join(
            f"{alias}: updateProjectV2ItemFieldValue("
            f'input: {{projectId: "{self.project_id}", itemId: "{item_id}", '
            f'fieldId: "{fid}", value: {{singleSelectOptionId: "{oid}"}}}}'
            f") {{ projectV2Item {{ id }} }}"
            for alias, fid, oid in all_fields
        )
        mutation = f"mutation {{\n  {mutation_parts}\n}}"
        self.run_graphql(mutation, cache=None)

        return item_id

    def fetch_open_issues_for_ties(self, *, include_bodies: bool = True) -> list[OpenIssueForTies]:
        """Single batched GraphQL fetch for ties analysis.

        Returns OPEN issues only; excludes Done. When include_bodies=False, the
        body field is omitted from the query (saves response size + bandwidth)
        and OpenIssueForTies.body is "" on every record.

        Cached 5 minutes via run_graphql(cache="5m"). Two cache keys via the
        distinct query strings (with vs without body).

        NOTE: projectItems(first: 5) takes [0] — assumes one board per repo.
        If an issue is on multiple boards, the first item's Status/Priority are
        used (typically the relevant one for jared-governed repos).
        """
        from .ties import OpenIssueForTies

        body_field = "body" if include_bodies else ""
        # Board.repo is stored as "owner/name" (see _parse and _infer_repo_from_git).
        owner, name = self.repo.split("/", 1)
        query = f"""
        query OpenIssuesForTies($owner: String!, $name: String!, $cursor: String) {{
          repository(owner: $owner, name: $name) {{
            issues(states: OPEN, first: 100, after: $cursor) {{
              nodes {{
                number
                title
                {body_field}
                labels(first: 20) {{ nodes {{ name }} }}
                milestone {{ title }}
                projectItems(first: 5) {{
                  nodes {{
                    fieldValueByName(name: "Status") {{
                      ... on ProjectV2ItemFieldSingleSelectValue {{ name }}
                    }}
                    priority: fieldValueByName(name: "Priority") {{
                      ... on ProjectV2ItemFieldSingleSelectValue {{ name }}
                    }}
                  }}
                }}
                blockedBy(first: 20) {{ nodes {{ number }} }}
              }}
              pageInfo {{ hasNextPage endCursor }}
            }}
          }}
        }}
        """
        cursor: str | None = None
        all_records: list[OpenIssueForTies] = []
        while True:
            # Only pass cursor when non-None — passing cursor=None becomes the
            # literal string "None" in gh args, not GraphQL null. Follows the
            # same pattern as fetch_blocked_by_edges.
            kwargs: dict[str, str | int | bool] = {"owner": owner, "name": name}
            if cursor is not None:
                kwargs["cursor"] = cursor
            data = self.run_graphql(query, cache="5m", **kwargs)
            page = data["data"]["repository"]["issues"]
            for node in page["nodes"]:
                project_items = node.get("projectItems", {}).get("nodes") or []
                project_item = project_items[0] if project_items else {}
                status_field = project_item.get("fieldValueByName") or {}
                priority_field = project_item.get("priority") or {}
                milestone_obj = node.get("milestone") or {}
                blocked_by_nodes = node.get("blockedBy", {}).get("nodes") or []
                all_records.append(
                    OpenIssueForTies(
                        number=int(node["number"]),
                        title=str(node["title"]),
                        body=str(node.get("body") or ""),
                        labels=tuple(
                            n["name"] for n in (node.get("labels", {}).get("nodes") or [])
                        ),
                        milestone=milestone_obj.get("title"),
                        status=str(status_field.get("name") or "Backlog"),
                        priority=priority_field.get("name"),
                        blocked_by=tuple(int(t["number"]) for t in blocked_by_nodes),
                    )
                )
            if not page["pageInfo"]["hasNextPage"]:
                break
            cursor = page["pageInfo"]["endCursor"]
        # Filter Done if any leaked in (defensive — `states: OPEN` should already exclude).
        return [r for r in all_records if r.status != "Done"]

    def get_issue(self, number: int) -> OpenIssueForTies | None:
        """Return one issue's tie-relevant record, or None if it's not open
        on this repo. Used by _cmd_ties to confirm target is pullable."""
        matching = [
            i for i in self.fetch_open_issues_for_ties(include_bodies=True) if i.number == number
        ]
        return matching[0] if matching else None

    def run_graphql(
        self, query: str, *, cache: str | None = None, **variables: str | int | bool
    ) -> Any:
        return run_graphql(query, cache=cache, **variables)

    def graphql_budget(self) -> tuple[int, int, int]:
        return graphql_budget()


def run_gh(args: list[str], *, cache: str | None = None) -> Any:
    """Run a `gh` subcommand and parse its stdout as JSON (empty → {})."""
    stdout = run_gh_raw(args, cache=cache)
    if not stdout:
        return {}
    try:
        return json.loads(stdout)
    except json.JSONDecodeError as e:
        raise GhInvocationError(f"gh returned non-JSON output: {stdout[:200]}") from e


_HTTP_STATUS_RE = re.compile(r"HTTP/[\d.]+\s+(\d+)")
_ETAG_HEADER_RE = re.compile(r"^Etag:\s*(.+?)\s*$", re.IGNORECASE | re.MULTILINE)


def _parse_issue_state_payload(data: dict[str, Any]) -> tuple[str, str | None]:
    """Extract (state, closed_at) from a REST /repos/.../issues/<n> JSON body.

    State is mapped to GraphQL's `IssueState`/`PullRequestState` enum so
    existing consumers continue to work unchanged:

      - "MERGED" when the issue is a PR with a non-null `merged_at`
        (REST otherwise reports state="closed" for merged PRs, losing
        the merged-vs-closed-unmerged distinction archive-plan needs).
      - "CLOSED" / "OPEN" mapped from REST's lowercase `state`.
      - "UNKNOWN" on a payload missing or with a non-string `state`.
    """
    state = data.get("state")
    if not isinstance(state, str):
        return "UNKNOWN", None
    closed_at = data.get("closed_at")
    if closed_at is not None and not isinstance(closed_at, str):
        closed_at = None
    pr = data.get("pull_request")
    if isinstance(pr, dict) and pr.get("merged_at"):
        return "MERGED", closed_at
    return state.upper(), closed_at


def _fetch_issue_rest_with_etag(repo: str, number: int) -> dict[str, Any] | None:
    """Fetch the REST issue body with ETag/conditional GET (#147).

    With a cached ETag the call sends `If-None-Match`; a 304 resolves to the
    cached body without consuming REST `core` (GitHub doesn't count 304s
    against the primary bucket). Misses and first calls go through `-i` so
    the response ETag can be captured for the next call.

    Cannot use `run_gh*` here: `gh api -i` exits non-zero on 304 even on
    success, and stripping stdout would mangle the headers/body separator.
    Calls `subprocess.run` directly and parses the HTTP status line itself.
    Returns the parsed JSON body on success, or None on any failure mode.
    """
    cached = cache.get_issue_etag(repo, number)
    args = ["gh", "api", "-i", f"repos/{repo}/issues/{number}"]
    if cached is not None:
        cached_etag, _cached_body = cached
        args.extend(["-H", f"If-None-Match: {cached_etag}"])

    result = subprocess.run(
        args,
        capture_output=True,
        text=True,
        check=False,
        env=_child_env(),
    )

    status = _extract_http_status(result.stdout, result.stderr)
    if status is None:
        return None

    if status == 304:
        if cached is None:
            return None
        _cached_etag, cached_body = cached
        return cached_body

    if status != 200:
        return None

    body = _parse_etag_response_body(result.stdout)
    if body is None:
        return None
    new_etag = _extract_etag_header(result.stdout)
    if new_etag:
        with contextlib.suppress(OSError):
            cache.set_issue_etag(repo, number, etag=new_etag, body=body)
    return body


def _extract_http_status(stdout: str, stderr: str) -> int | None:
    """Find the first `HTTP/<v> <code>` status line in stdout (then stderr)."""
    for blob in (stdout, stderr):
        for line in blob.splitlines():
            m = _HTTP_STATUS_RE.match(line)
            if m:
                return int(m.group(1))
    return None


def _extract_etag_header(stdout: str) -> str | None:
    m = _ETAG_HEADER_RE.search(stdout)
    return m.group(1).strip() if m else None


def _parse_etag_response_body(stdout: str) -> dict[str, Any] | None:
    """Split `gh api -i` stdout on the headers/body boundary and parse JSON.

    Accepts both `\\r\\n\\r\\n` and `\\n\\n` separators since `gh api -i`
    can emit either depending on how the output stream is buffered.
    """
    separator = "\r\n\r\n" if "\r\n\r\n" in stdout else "\n\n"
    parts = stdout.split(separator, 1)
    if len(parts) < 2:
        return None
    try:
        body = json.loads(parts[1])
    except json.JSONDecodeError:
        return None
    if not isinstance(body, dict):
        return None
    return body


def fetch_issue_state_rest(repo: str, number: int) -> tuple[str, str | None]:
    """Return (state, closed_at) for an issue via the REST API (#54).

    Uses `gh api repos/<repo>/issues/<n>` so the call hits the REST `core`
    rate-limit bucket (5000/hr) instead of the `graphql` bucket. For batch
    state checks (archive-plan.py scanning many plans, dependency-graph.py
    open-state filters), this removes the calls from GraphQL pressure
    entirely.

    Adds ETag/conditional GET on top (#147): when caching is enabled the
    first call captures the response ETag, and subsequent calls send
    `If-None-Match` so a 304 short-circuits to the cached body without
    consuming REST `core`. `JARED_NO_CACHE=1` bypasses the ETag layer and
    falls back to the unconditional `gh api` flow.
    """
    if os.environ.get("JARED_NO_CACHE") == "1":
        try:
            data = run_gh(["api", f"repos/{repo}/issues/{number}"])
        except GhInvocationError:
            return "UNKNOWN", None
        return _parse_issue_state_payload(data)

    data = _fetch_issue_rest_with_etag(repo, number)
    if data is None:
        return "UNKNOWN", None
    return _parse_issue_state_payload(data)


def _child_env() -> dict[str, str]:
    """Env for `gh` subprocess calls, with GH_TOKEN/GITHUB_TOKEN removed.

    When either var is set, gh prefers it over the OAuth session from
    `gh auth login`, so a fine-grained PAT without `project` scope shadows
    an OAuth token that has it — and `gh auth status` doesn't surface the
    override. Scrubbing here forces project mutations (and every other gh
    call) onto the OAuth session jared expects to be authoritative.
    """
    env = os.environ.copy()
    env.pop("GH_TOKEN", None)
    env.pop("GITHUB_TOKEN", None)
    return env


_TOKEN_SCOPE_ERROR_SIGNATURE = "Resource not accessible by personal access token"


def _looks_like_project_mutation(args: list[str]) -> bool:
    """True when args correspond to a project v2 mutation that needs `project` scope.

    Two shapes hit this codepath: `gh project item-add/item-edit/item-archive ...`
    and `gh api graphql -f query=mutation { ... addProjectV2... | updateProjectV2... }`.
    """
    if not args:
        return False
    if (
        args[0] == "project"
        and len(args) > 1
        and args[1]
        in {
            "item-add",
            "item-edit",
            "item-archive",
            "item-delete",
            "create",
            "field-create",
        }
    ):
        return True
    if args[:2] == ["api", "graphql"]:
        for chunk in args:
            if "addProjectV2" in chunk or "updateProjectV2" in chunk or "deleteProjectV2" in chunk:
                return True
    return False


def _format_token_scope_diagnostic() -> str:
    """Diagnostic block for `Resource not accessible by personal access token`
    failures from project mutations. Best-effort — silently skips parts that can't be
    determined.

    Post-#65, jared scrubs GH_TOKEN/GITHUB_TOKEN before invoking gh, so the call
    that just failed ran on `gh auth login`'s OAuth session. The realistic remaining
    trigger for this error class is OAuth without `project` scope. Mention the #65
    scrub explicitly so an operator with GH_TOKEN set isn't misled.

    Always appends an MCP note (#210). The GitHub MCP server uses a separate token
    surface (Claude Code MCP server config), distinct from `gh auth login` and
    GH_TOKEN. This function is only ever reached from `run_gh_raw`'s failure path —
    MCP-routed mutations fail inside Claude Code's tool layer and never hit this
    code. The line is therefore not a detection signal but a UX hint: when the
    operator is troubleshooting and may also be using MCP, remind them the two
    auth surfaces are independent so `gh auth refresh -s project` isn't assumed
    to fix the MCP side. Always-mention is the only viable shape here, since
    conditional-on-MCP-failure can't be detected from a gh subprocess path.
    """
    lines: list[str] = ["", "Token-scope diagnostic:"]

    has_gh_token = bool(os.environ.get("GH_TOKEN"))
    has_gh_token_var = "GITHUB_TOKEN" if os.environ.get("GITHUB_TOKEN") else None
    if has_gh_token or has_gh_token_var:
        lines.append(
            "  Token source used: gh auth login OAuth session "
            "(jared scrubs GH_TOKEN/GITHUB_TOKEN before invoking gh — see #65)."
        )
    else:
        lines.append("  Token source used: gh auth login OAuth session.")

    scopes = _probe_oauth_scopes()
    if scopes is not None:
        lines.append(f"  Scopes present: {scopes or '(none reported)'}")

    lines.append("  Scopes needed: project (write) for project v2 mutations.")
    lines.append("  Suggested fix: gh auth refresh -s project")
    lines.append(
        "  MCP note: the GitHub MCP server uses a separate token (Claude Code MCP "
        "config); its scope requirements are independent of the gh OAuth session "
        "above, and `gh auth refresh` does not affect it."
    )
    return "\n".join(lines)


def _probe_oauth_scopes() -> str | None:
    """Best-effort scopes lookup via `gh auth status`. Returns the scopes line,
    or None if the probe fails."""
    try:
        result = subprocess.run(
            ["gh", "auth", "status"],
            capture_output=True,
            text=True,
            check=False,
            env=_child_env(),
            timeout=5,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    blob = (result.stdout or "") + (result.stderr or "")
    m = re.search(r"Token scopes:\s*(.+)", blob)
    return m.group(1).strip() if m else None


def run_gh_raw(args: list[str], *, cache: str | None = None) -> str:
    """Run a `gh` subcommand and return its stdout (stripped) without JSON parsing.

    Some gh commands return plain text (e.g. `gh issue create` prints a URL).
    Callers that need the raw string use this; JSON responses use run_gh.

    `cache` is passed to gh as `--cache <duration>`. Only meaningful for
    `gh api ...` calls (including `gh api graphql`); other subcommands
    will reject the flag. Caller's responsibility to use it appropriately.
    """
    full_args = ["gh", *args]
    if cache is not None:
        full_args.extend(["--cache", cache])
    result = subprocess.run(
        full_args,
        capture_output=True,
        text=True,
        check=False,
        env=_child_env(),
    )
    if result.returncode != 0:
        message = f"gh {' '.join(args)} exited {result.returncode}: {result.stderr.strip()}"
        if _TOKEN_SCOPE_ERROR_SIGNATURE in result.stderr and _looks_like_project_mutation(args):
            message += "\n" + _format_token_scope_diagnostic()
        raise GhInvocationError(message)
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


def fetch_blocked_by_edges(
    repo: str,
    *,
    cache: str | None = None,
) -> dict[int, list[dict[str, Any]]]:
    """One paginated GraphQL call → `{issue_number: [{number, state}]}` for all
    open issues in `repo`. Replaces the per-issue N+1 pattern that
    `dependency-graph.py` used to use.

    `cache` is forwarded to gh as `--cache <duration>` — pass "60s" for
    advisory uses (sweep, dependency-graph) so re-runs within a minute
    skip the network and the GraphQL points entirely.
    """
    owner, name = repo.split("/", 1)
    q = (
        "query($o:String!,$r:String!,$c:String){repository(owner:$o,name:$r){"
        "issues(first:100,after:$c,states:OPEN){pageInfo{hasNextPage endCursor}"
        "nodes{number blockedBy(first:20){nodes{number state}}}}}}"
    )
    result: dict[int, list[dict[str, Any]]] = {}
    cursor: str | None = None
    while True:
        kwargs: dict[str, str] = {"o": owner, "r": name}
        if cursor:
            kwargs["c"] = cursor
        data = run_graphql(q, cache=cache, **kwargs)["data"]["repository"]["issues"]
        for node in data["nodes"]:
            result[node["number"]] = node["blockedBy"]["nodes"]
        if not data["pageInfo"]["hasNextPage"]:
            break
        cursor = data["pageInfo"]["endCursor"]
    return result


# ---------- Plan/spec issue-ref parsing ----------
#
# Shared between archive-plan.py and sweep.py so the two scripts can't
# disagree on what counts as a referenced issue (#86, #87, #88).

_PLAN_BOLD_ISSUE_LOOKAHEAD = 15
_PLAN_BOLD_ISSUE_LINE_RE = re.compile(
    r"^\*\*(?:Tracking\s+)?Issues?:\*\*\s+(.+?)\s*$",
    re.IGNORECASE | re.MULTILINE,
)
_PLAN_ISSUE_REF_RE = re.compile(
    r"(?:https?://github\.com/[^/\s]+/[^/\s]+/(?:issues|pull)/(\d+)"
    r"|(?:[\w.-]+/[\w.-]+)?#(\d+))"
)
# A line in the ## Issue / ## Shipped section "counts" as a ref-bearing line
# only if it's either:
#   1. a bare line-start ref (`#229 — Metric Layer C.0`, no list marker), or
#   2. a list item (`- ...`/`* ...`) whose first content is a ref, optionally
#      preceded by a `PR ` / `Issue ` label (e.g. `- PR #415`) and/or wrapped
#      in bold around the ref token (e.g. `- **#622** — short desc`).
#
# Mid-line refs in narrative prose are deliberately ignored — they are the
# source of #86/#87 false positives. The label is gated behind a list marker
# so a bare prose line like `Issue #99 supersedes this work.` cannot match.
_PLAN_LINE_REF_RE = re.compile(
    r"^[\s]*"
    r"(?:[-*]\s+(?:(?:PR|Issue)\s+)?)?"  # optional list marker + optional PR/Issue label
    r"(?:\*\*)?"  # optional bold-open around the ref token (`- **#N**` form)
    r"(?:\[)?"  # optional opening of a markdown link `[#N](...)`
    r"(?:https?://github\.com/[^/\s]+/[^/\s]+/(?:issues|pull)/(\d+)"
    r"|(?:[\w.-]+/[\w.-]+)?#(\d+))",
    re.IGNORECASE,
)


def _parse_plan_section(plan_text: str, heading_pattern: str) -> list[int] | None:
    """Find a heading-bounded section and return line-start refs from its body.

    Returns None if the heading is absent — distinguishes "section missing"
    from "section present but empty" so callers can fall back to alternate
    parsers (e.g. the `**Issue:**` bold-line fallback).
    """
    section_match = re.search(
        rf"^{heading_pattern}\s*$([\s\S]+?)(?=^#{{1,3}}\s|\Z)",
        plan_text,
        re.MULTILINE,
    )
    if not section_match:
        return None
    refs: list[int] = []
    for line in section_match.group(1).splitlines():
        m = _PLAN_LINE_REF_RE.match(line)
        if not m:
            continue
        for g in m.groups():
            if g:
                refs.append(int(g))
                break
    return refs


def parse_referenced_issues(plan_text: str) -> list[int]:
    """Extract issue numbers from a plan/spec.

    Primary source: a `## Issue` / `## Issues` / `## Issue(s)` section. Inside
    that section, only lines whose meaningful content STARTS with a ref count
    — list-item form (`- #42`, `* https://github.com/.../issues/42`) and
    bare line-start form (`#229 — Metric Layer C.0`) both qualify.
    Mid-line refs in prose, blockquotes, or bold lines are skipped.

    Fallback (when no `## Issue` heading is present): a `**Issue:**` /
    `**Issues:**` / `**Tracking issue:**` bold line near the top of the file
    (within the first `_PLAN_BOLD_ISSUE_LOOKAHEAD` lines). The fallback path
    accepts inline ref lists since the bold line itself is the ref carrier
    — there's no risk of swallowing prose paragraphs.

    Refs in `#N`, `owner/repo#N`, and full GitHub issue/pull URL forms.
    Heading wins when both forms are present.
    """
    refs = _parse_plan_section(plan_text, r"#{1,3}\s+Issue[s()]*")
    if refs is not None:
        return refs

    head = "\n".join(plan_text.splitlines()[:_PLAN_BOLD_ISSUE_LOOKAHEAD])
    bold = _PLAN_BOLD_ISSUE_LINE_RE.search(head)
    if not bold:
        return []
    return [int(n) for ref in _PLAN_ISSUE_REF_RE.findall(bold.group(1)) for n in ref if n]


def parse_shipped_section(plan_text: str) -> list[int]:
    """Extract PR numbers from a `## Shipped` section.

    Same line-start rules as `parse_referenced_issues`. Used by archive-plan
    to support recycled-issue plans (#89): a plan that shipped via a merged
    PR but whose originally-tracked issue was rewritten to track follow-on
    work can still be archived by declaring shipping evidence explicitly.

    Returns an empty list if no `## Shipped` section is present.
    """
    refs = _parse_plan_section(plan_text, r"#{1,3}\s+Shipped")
    return refs if refs is not None else []


def check_closed_not_done(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Closed issues should auto-move to Done. If they don't, return them.

    Detection-only. Each entry is `{number, title, current_status}` —
    callers decide the rendering (sweep adds a `Propose: jared set <N>
    Status Done` remediation suffix; the CLI's `summary` command renders
    them under a separate `Stuck closed (N):` heading and excludes them
    from the `In Progress` count). Keeping format out of the detector
    means each call site can pick its own affordance.

    The drift usually comes from projects whose built-in "Item closed →
    Done" workflow is disabled — paths like `gh issue close` and PR-merge
    auto-close rely on it entirely (only `jared close` has its own
    explicit-Status fallback).
    """
    stuck = []
    for i in items:
        content = i.get("content") or {}
        if content.get("state") != "CLOSED":
            continue
        status = i.get("status") or ""
        if status == "Done":
            continue
        stuck.append(
            {
                "number": content.get("number"),
                "title": (content.get("title") or i.get("title") or "")[:60],
                "current_status": status or "no Status",
            }
        )
    return stuck


def _flatten_project_item_for_project(
    project_items_node: Any, project_number: int
) -> dict[str, Any] | None:
    """Pick the projectItems entry matching `project_number` and flatten it.

    GraphQL's projectItems edge returns a list of items (one per project
    the issue belongs to). Callers want a single flat dict for THIS
    project: `{"id": ..., "status": ..., "priority": ..., ...}` with
    single-select field names lowercased.

    Returns None when the issue has no item on this project (off-board
    ghost; see `fetch_item_for_issue`'s contract for the upstream usage).
    Module-level so `Board.fetch_item_for_issue`, `Board.open_items`,
    and `fetch_project_items_batch` share one flattener.
    """
    if not isinstance(project_items_node, dict):
        return None
    for node in project_items_node.get("nodes", []) or []:
        if not isinstance(node, dict):
            continue
        if (node.get("project") or {}).get("number") != project_number:
            continue
        flat: dict[str, Any] = {"id": node.get("id")}
        for fv in (node.get("fieldValues") or {}).get("nodes", []) or []:
            field_name = (fv.get("field") or {}).get("name")
            if field_name:
                flat[field_name.lower()] = fv.get("name")
        return flat
    return None


def fetch_project_items_batch(
    repo: str,
    issue_numbers: list[int],
    *,
    project_number: int,
    cache: str | None = None,
) -> dict[int, dict[str, Any] | None]:
    """One aliased GraphQL call → `{issue_number: flat_project_item or None}`.

    Replaces the N+1 in callers that need projectItems for many issues
    (e.g., `_detect_stuck_closed_recent` post-#185): per-issue
    `fetch_item_for_issue` calls each pay gh-cli startup overhead, which
    dominates wall-clock on mature boards. One aliased query keeps it a
    single round trip — same idiom as `fetch_recent_comments_batch`.

    Each value is the flat `{"id", "status", "priority", ...}` shape
    `fetch_item_for_issue` returns, or None for issues not on the named
    project (off-board ghost). Empty input → empty dict, no gh call.
    """
    if not issue_numbers:
        return {}
    owner, name = repo.split("/", 1)
    aliases = "\n".join(
        f"  i{n}: issue(number: {n}) {{ projectItems(first: 10) {{ "
        f"nodes {{ id project {{ number }} fieldValues(first: 20) {{ "
        f"nodes {{ ... on ProjectV2ItemFieldSingleSelectValue {{ "
        f"name field {{ ... on ProjectV2SingleSelectField {{ name }} }} "
        f"}} }} }} }} }} }}"
        for n in issue_numbers
    )
    query = (
        f"query($o:String!,$r:String!) {{\n  repository(owner:$o, name:$r) {{\n{aliases}\n  }}\n}}"
    )
    data = run_graphql(query, cache=cache, o=owner, r=name)
    repo_data = (data.get("data") or {}).get("repository") or {}
    result: dict[int, dict[str, Any] | None] = {}
    for n in issue_numbers:
        issue_data = repo_data.get(f"i{n}")
        if not isinstance(issue_data, dict):
            result[n] = None
            continue
        result[n] = _flatten_project_item_for_project(
            issue_data.get("projectItems"), project_number
        )
    return result


def fetch_recent_comments_batch(
    repo: str,
    issue_numbers: list[int],
    *,
    limit: int = 10,
    cache: str | None = None,
) -> dict[int, list[dict[str, Any]]]:
    """One aliased GraphQL call → `{issue_number: [{body, createdAt}, ...]}`
    for the given numbers. Returns the most recent `limit` comments per
    issue, in chronological order (oldest → newest), matching what gh's
    REST `/comments` endpoint and `gh issue view --json comments` both
    return.

    Replaces the per-issue N+1 in `sweep.py:fetch_recent_comments` and
    the per-issue `gh issue view --json comments` in
    `jared:_latest_session_note_oneliner`. Aliased query — one alias per
    requested number — keeps it a single round trip; cap callers at a
    reasonable N (≤10 typical, the WIP cap is the natural ceiling).

    Empty input → empty dict, no gh call.
    """
    if not issue_numbers:
        return {}
    owner, name = repo.split("/", 1)
    aliases = "\n".join(
        f"  i{n}: issue(number: {n}) {{ comments(last: {limit}) {{ nodes {{ body createdAt }} }} }}"
        for n in issue_numbers
    )
    query = (
        f"query($o:String!,$r:String!) {{\n  repository(owner:$o, name:$r) {{\n{aliases}\n  }}\n}}"
    )
    data = run_graphql(query, cache=cache, o=owner, r=name)["data"]["repository"]
    result: dict[int, list[dict[str, Any]]] = {}
    for n in issue_numbers:
        issue_data = data.get(f"i{n}")
        if not issue_data:
            result[n] = []
            continue
        nodes = issue_data.get("comments", {}).get("nodes", []) or []
        result[n] = nodes
    return result


def fetch_recent_closed_prs_with_files(repo: str, days: int = 7) -> list[dict[str, Any]]:
    """Return closed PRs from the last `days` days, each with its changed
    file list. Used by sweep.check_doc_sync_gate (#163).

    Two-stage: `gh pr list` enumerates by closedAt window, then
    `gh pr view N --json files` per PR. The list endpoint doesn't expose
    `files` reliably across gh versions; per-PR view is the robust path
    and matches check_plan_spec_drift's idiom.

    N+1 in PR count — each PR triggers a per-PR `gh pr view`. Acceptable at
    typical project weekly cadence; busier projects may want a graphql rewrite.
    """
    cutoff = (dt.datetime.now(dt.UTC) - dt.timedelta(days=days)).strftime("%Y-%m-%d")
    list_args = [
        "pr",
        "list",
        "--repo",
        repo,
        "--state",
        "closed",
        "--search",
        f"closed:>={cutoff}",
        "--limit",
        "100",
        "--json",
        "number,closedAt",
    ]
    prs = run_gh(list_args)
    if not isinstance(prs, list):
        return []

    result: list[dict[str, Any]] = []
    for pr in prs:
        number = pr.get("number")
        closed_at = pr.get("closedAt")
        if not isinstance(number, int):
            continue
        view_args = ["pr", "view", str(number), "--repo", repo, "--json", "files"]
        try:
            data = run_gh(view_args)
        except GhInvocationError:
            continue
        files_raw = (data or {}).get("files", []) if isinstance(data, dict) else []
        files = [f["path"] for f in files_raw if isinstance(f, dict) and "path" in f]
        result.append({"number": number, "closedAt": closed_at, "files": files})

    return result


def graphql_budget() -> tuple[int, int, int]:
    """Return `(remaining, limit, reset_unix)` from `gh api rate_limit`.

    Polls a REST endpoint that does NOT draw from the GraphQL bucket,
    so it remains usable even when the GraphQL budget is exhausted.
    Used as a pre-flight probe by heavy GraphQL-bound scripts so they
    can soft-fail with a useful message instead of crashing mid-run.
    """
    data = run_gh(["api", "rate_limit"])
    gql = data.get("resources", {}).get("graphql", {})
    return (
        int(gql.get("remaining", 0)),
        int(gql.get("limit", 5000)),
        int(gql.get("reset", 0)),
    )


def check_graphql_budget(
    budget: tuple[int, int, int],
    *,
    min_required: int = 200,
    force: bool = False,
) -> str | None:
    """Return a warning string if budget is too low to proceed; else None.

    `budget` is the `(remaining, limit, reset_unix)` tuple from
    `graphql_budget()`. Heavy scripts call this before doing real work:

        warning = check_graphql_budget(graphql_budget(), min_required=200)
        if warning:
            print(warning, file=sys.stderr)
            return 0

    `force=True` suppresses the gate (returns None even if budget is low),
    for users who explicitly want to spend the remaining points. The
    message includes both the absolute reset clock and minutes-from-now
    so it reads cleanly in interactive output.
    """
    remaining, limit, reset = budget
    if force or remaining >= min_required:
        return None
    reset_dt = dt.datetime.fromtimestamp(reset, tz=dt.UTC)
    minutes = max(0, int((reset - time.time()) / 60))
    return (
        f"GraphQL budget low: {remaining}/{limit} remaining; "
        f"resets at {reset_dt:%H:%M UTC} (~{minutes} min). "
        f"Run with --force to override."
    )


def run_graphql(query: str, *, cache: str | None = None, **variables: str | int | bool) -> Any:
    """Run a GraphQL query via `gh api graphql` with named variables.

    Uses gh's `-F` for bool/int (so gh casts to the right type) and `-f`
    for strings. Results come back parsed from JSON.

    `cache` enables gh's HTTP-level response cache (`gh api --cache <dur>`).
    Use only on read-only queries; mutation callers must leave it None.
    """
    args = ["api", "graphql", "-f", f"query={query}"]
    for name, value in variables.items():
        flag = "-F" if isinstance(value, bool | int) and not isinstance(value, str) else "-f"
        args.extend([flag, f"{name}={value}"])
    return run_gh(args, cache=cache)


def resolve_body(body: str | None, body_file: str | None) -> str:
    """Resolve issue/comment body from inline text, a file path, or stdin.

    Exactly one of `body` / `body_file` is set (the CLI's argparse mutex
    group enforces this). `body_file == "-"` reads stdin; other values are
    filesystem paths.

    Single seam point — both `jared file` and `jared comment` route through
    here. #97's PII pre-flight redactor will hook this function so inline
    --body, --body-file paths, and stdin all get scanned for gitignored
    claude-shaped local content identically before any GitHub write.
    """
    if body is not None:
        return body
    assert body_file is not None  # argparse mutex group makes this unreachable
    if body_file == "-":
        return sys.stdin.read()
    return Path(body_file).read_text()


# ---------- PII pre-flight redactor (#102) ----------


@dataclass
class RedactionMatch:
    """One body line that matched a phrase from a gitignored claude-shaped file."""

    line_no: int
    line_text: str
    matched_phrase: str
    source_file: Path


@dataclass
class RedactionReport:
    """Result of pre_flight_check. Pure data; caller decides how to react."""

    matches: list[RedactionMatch]
    scanned_files: list[Path]

    @property
    def clean(self) -> bool:
        return not self.matches


# Lines shorter than this (post-strip) are too generic to be useful private content.
_MIN_PHRASE_CHARS = 20
# Phrases with fewer words than this match too eagerly (any common word in a
# local file would flag the body).
_MIN_PHRASE_WORDS = 3
# Markdown-leader characters stripped from line starts before length checks.
_MARKDOWN_LEADER_RE = re.compile(r"^[\s\-\*\>#\|`]+")


def _extract_phrases(file_path: Path) -> list[str]:
    """Extract candidate phrases from one gitignored claude-shaped file.

    A phrase is a line of the file that — after stripping markdown leaders
    (`-`, `*`, `>`, `#`, `|`, backticks, leading whitespace) — has at least
    `_MIN_PHRASE_WORDS` whitespace-separated words AND at least
    `_MIN_PHRASE_CHARS` characters. Returns the cleaned phrases in file order.

    Missing file → empty list, not an exception (the caller has already
    decided this file is in scope; we don't want to second-guess).
    """
    try:
        text = file_path.read_text(encoding="utf-8")
    except (FileNotFoundError, UnicodeDecodeError):
        return []
    out = []
    for raw in text.splitlines():
        cleaned = _MARKDOWN_LEADER_RE.sub("", raw).rstrip()
        if len(cleaned) < _MIN_PHRASE_CHARS:
            continue
        if len(cleaned.split()) < _MIN_PHRASE_WORDS:
            continue
        out.append(cleaned)
    return out


# Standard locations for gitignored claude-shaped local content.
_CLAUDE_SHAPED_PATTERNS = (
    "CLAUDE.local.md",
    ".claude/CLAUDE.local.md",
    ".claude/local/*.md",
)


def _find_claude_shaped_files(project_root: Path) -> list[Path]:
    """Locate gitignored claude-shaped files under `project_root`.

    Checks the standard patterns: `CLAUDE.local.md`, `.claude/CLAUDE.local.md`,
    `.claude/local/*.md`. Returns absolute paths in deterministic order.

    If `project_root` isn't a git repo (no `.git/` directory), returns an
    empty list — the redactor's allowlist semantics depend on git, so without
    git there's no meaningful scan to do.
    """
    if not (project_root / ".git").exists():
        return []
    found = []
    for pattern in _CLAUDE_SHAPED_PATTERNS:
        if "*" in pattern:
            # glob the pattern's directory
            base = project_root / pattern.rsplit("/", 1)[0]
            glob_pat = pattern.rsplit("/", 1)[1]
            if base.is_dir():
                found.extend(sorted(base.glob(glob_pat)))
        else:
            p = project_root / pattern
            if p.is_file():
                found.append(p)
    return found


def _find_project_root(start: Path) -> Path:
    """Walk up from `start` to the nearest ancestor containing a `.git/` entry.

    Returns the discovered project root if found, else `start.resolve()` so
    the redactor's no-git short-circuit applies cleanly. Used by the CLI to
    fix #102's subdir blind spot — `Path.cwd()` alone doesn't find the root
    when the operator invokes `jared` from a feature subdirectory.
    """
    p = start.resolve()
    for candidate in (p, *p.parents):
        if (candidate / ".git").exists():
            return candidate
    return p


def _read_tracked_content(project_root: Path) -> str:
    """Concatenate every tracked file's content into one searchable blob.

    `git ls-files` enumerates tracked paths. We read each and join into
    one string so the allowlist check is a single `phrase in tracked` per
    candidate phrase. Decoding errors on binary files are swallowed —
    binary files can't contain text phrases anyway.
    """
    if not (project_root / ".git").exists():
        return ""
    try:
        out = subprocess.run(
            ["git", "ls-files"],
            cwd=project_root,
            capture_output=True,
            text=True,
            check=True,
        ).stdout
    except (subprocess.CalledProcessError, FileNotFoundError):
        return ""
    chunks = []
    for relpath in out.splitlines():
        f = project_root / relpath
        try:
            chunks.append(f.read_text(encoding="utf-8"))
        except (FileNotFoundError, UnicodeDecodeError, IsADirectoryError):
            continue
    return "\n".join(chunks)


# Process-local cache for pre_flight_check scan inputs (phrases + tracked
# content). Keyed on the resolved absolute project_root path. Survives only
# within one `jared` invocation; that's the intended scope per the spec.
_PRE_FLIGHT_CACHE: dict[Path, tuple[dict[str, Path], list[Path]]] = {}


def _clear_pre_flight_cache() -> None:
    """Test seam — drops the in-process cache."""
    _PRE_FLIGHT_CACHE.clear()


def pre_flight_check(body: str, project_root: Path) -> RedactionReport:
    """Scan body against gitignored claude-shaped files; return a structured report."""
    root = project_root.resolve()
    cached = _PRE_FLIGHT_CACHE.get(root)
    if cached is None:
        files = _find_claude_shaped_files(root)
        if not files:
            _PRE_FLIGHT_CACHE[root] = ({}, [])
            return RedactionReport(matches=[], scanned_files=[])
        tracked = _read_tracked_content(root)
        phrase_to_source: dict[str, Path] = {}
        for f in files:
            for phrase in _extract_phrases(f):
                if tracked and phrase in tracked:
                    continue
                phrase_to_source.setdefault(phrase, f)
        _PRE_FLIGHT_CACHE[root] = (phrase_to_source, files)
        cached = _PRE_FLIGHT_CACHE[root]

    phrase_to_source, scanned_files = cached
    if not phrase_to_source:
        return RedactionReport(matches=[], scanned_files=scanned_files)

    matches: list[RedactionMatch] = []
    body_lines = body.splitlines()
    for phrase, source in phrase_to_source.items():
        if phrase in body:
            for i, line in enumerate(body_lines, start=1):
                if phrase in line:
                    matches.append(
                        RedactionMatch(
                            line_no=i,
                            line_text=line,
                            matched_phrase=phrase,
                            source_file=source,
                        )
                    )
                    break
    return RedactionReport(matches=matches, scanned_files=scanned_files)


def print_redaction_diff(report: RedactionReport, *, file: Any = None) -> None:
    """Format a non-clean RedactionReport for stderr.

    Caller is responsible for the exit code; this only writes the diagnostic.
    No-op when the report is clean — it's a guard against future callers that
    invoke us without checking. Today's callers always gate with `if not
    report.clean:`, but the guard prevents the "0 matches across 0 files"
    nonsense output if that contract ever drifts.
    """
    if report.clean:
        return
    f = file if file is not None else sys.stderr
    print(
        "error: pre-flight redaction check failed — body references content from",
        file=f,
    )
    print(
        "gitignored claude-shaped local files. Refusing to post.",
        file=f,
    )
    print("", file=f)
    n = len(report.matches)
    distinct_files = sorted({m.source_file for m in report.matches})
    nf = len(distinct_files)
    match_word = "match" if n == 1 else "matches"
    file_word = "file" if nf == 1 else "files"
    print(f"  {n} {match_word} across {nf} {file_word}:", file=f)
    for m in report.matches:
        print(f'    line {m.line_no}: "{m.line_text}"', file=f)
        print(f"      ↳ matches {m.source_file}", file=f)
    print("", file=f)
    print("  next steps:", file=f)
    print("    1. Re-issue the call with private content removed.", file=f)
    print(
        "    2. OR add the matched phrase to a tracked file if it's intentionally public.",
        file=f,
    )


def compute_velocity(
    repo: str,
    *,
    days: int = 14,
    cache: str | None = None,
) -> dict[str, Any]:
    """Recent shipping cadence — count + median age-at-close + median PR duration.

    `days` is the lookback window (default 14). Returns:
      - window_days (int): the lookback window the caller asked for
      - closures_in_window (int): count of issues closed in window
      - median_age_at_close (float, days): created→closed for those issues
      - median_pr_duration_days (float): created→merged for PRs in the same
        window. Proxy for "time to ship" — used as the anchor for proposed
        milestone due dates in /jared-audit. PR duration is a tighter signal
        than issue creation→close (which folds in backlog dwell time).
    """
    from statistics import median

    cutoff = (dt.datetime.now(dt.UTC) - dt.timedelta(days=days)).strftime("%Y-%m-%d")
    issues_args = [
        "issue",
        "list",
        "--repo",
        repo,
        "--state",
        "closed",
        "--search",
        f"closed:>={cutoff}",
        "--json",
        "number,createdAt,closedAt",
        "--limit",
        "100",
    ]
    closed = run_gh(issues_args, cache=cache) or []

    prs_args = [
        "pr",
        "list",
        "--repo",
        repo,
        "--state",
        "merged",
        "--search",
        f"merged:>={cutoff}",
        "--json",
        "number,createdAt,mergedAt",
        "--limit",
        "100",
    ]
    merged = run_gh(prs_args, cache=cache) or []

    def _days_between(start: str, end: str) -> float:
        s = dt.datetime.fromisoformat(start.replace("Z", "+00:00"))
        e = dt.datetime.fromisoformat(end.replace("Z", "+00:00"))
        return (e - s).total_seconds() / 86400.0

    ages = [_days_between(i["createdAt"], i["closedAt"]) for i in closed]
    durations = [_days_between(p["createdAt"], p["mergedAt"]) for p in merged]

    return {
        "window_days": days,
        "closures_in_window": len(closed),
        "median_age_at_close": float(median(ages)) if ages else 0.0,
        "median_pr_duration_days": float(median(durations)) if durations else 0.0,
    }


def fetch_audit_window(
    board: Board,
    *,
    count: int | None = None,
    age_days: int | None = None,
    issues: list[int] | None = None,
    entity_type: Literal["issues", "milestones", "both"] = "issues",
    cache: str | None = None,
) -> dict[str, Any]:
    """Fetch the audit working set + velocity block.

    Exactly one of {count, age_days, issues} must be set when entity_type
    includes issues. entity_type is "issues", "milestones", or "both".
    Items are returned oldest-first. The top-level "velocity" key carries
    the output of compute_velocity (used by the slash-command doctrine for
    the date anchor formula and by callers omitting --age-days for the
    default staleness threshold).
    """
    velocity = compute_velocity(board.repo, cache=cache)
    items: list[dict[str, Any]] = []
    milestones: list[dict[str, Any]] = []

    if entity_type in ("issues", "both"):
        raw = (
            run_gh(
                [
                    "issue",
                    "list",
                    "--repo",
                    board.repo,
                    "--state",
                    "open",
                    "--limit",
                    "500",
                    "--json",
                    "number,title,body,createdAt,labels,milestone",
                ],
                cache=cache,
            )
            or []
        )
        raw_sorted = sorted(raw, key=lambda i: i["createdAt"])
        if issues is not None:
            wanted = set(issues)
            items = [i for i in raw_sorted if i["number"] in wanted]
        elif count is not None:
            items = raw_sorted[:count]
        else:
            # age_days mode (explicit) OR default-staleness mode (omitted).
            if age_days is None:
                # Default: 2 * median_age_at_close, clamped to [14, 60].
                threshold = max(14.0, min(60.0, 2.0 * velocity["median_age_at_close"]))
            else:
                threshold = float(age_days)
            now = dt.datetime.now(dt.UTC)
            kept = []
            for i in raw_sorted:
                created = dt.datetime.fromisoformat(i["createdAt"].replace("Z", "+00:00"))
                age = (now - created).total_seconds() / 86400.0
                if age >= threshold:
                    kept.append(i)
            items = kept

    if entity_type in ("milestones", "both"):
        owner, name = board.repo.split("/", 1)
        milestones = (
            run_gh(
                [
                    "api",
                    f"/repos/{owner}/{name}/milestones",
                    "--paginate",
                    "-X",
                    "GET",
                    "-f",
                    "state=open",
                    "-f",
                    "sort=due_on",
                    "-f",
                    "direction=asc",
                ],
                cache=cache,
            )
            or []
        )

    if items:
        # Invert repo-wide blockedBy edges: who depends on each candidate?
        edges = fetch_blocked_by_edges(board.repo, cache=cache)
        dependents: dict[int, list[int]] = {}
        for dependent_num, blocked_by in edges.items():
            for blocker in blocked_by:
                if blocker.get("state") == "OPEN":
                    dependents.setdefault(blocker["number"], []).append(dependent_num)
        for item in items:
            item["open_dependents"] = sorted(dependents.get(item["number"], []))

    return {
        "items": items,
        "milestones": milestones,
        "velocity": velocity,
    }
