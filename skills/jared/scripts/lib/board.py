"""Shared helper for jared scripts: parse docs/project-board.md, wrap gh calls."""

from __future__ import annotations

import datetime as dt
import json
import os
import re
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

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
    project_number: int
    project_id: str
    owner: str
    repo: str
    project_url: str
    _field_ids: dict[str, str] = field(default_factory=dict)
    _field_options: dict[str, dict[str, str]] = field(default_factory=dict)
    session_handoff_prompt: str = "ask"
    session_start_checks: list[str] = field(default_factory=list)
    # Cached `gh project item-list` result, populated on first board_items()
    # call and reused for the lifetime of this instance. None means uncached.
    _items: list[dict[str, Any]] | None = field(default=None, repr=False)
    # Verbatim text of docs/project-board.md, stored for post-parse lookups
    # (e.g. tie_stop_words). Set by from_path / _parse; empty string if not
    # constructed via those entry points (e.g. direct dataclass construction
    # in tests that don't need this feature).
    _raw_doc: str = field(default="", repr=False)

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
        """Cached `gh project item-list` result for this Board instance.

        Refreshes on first call; subsequent calls reuse the in-memory copy
        for the rest of the process. Callers that mutate the board within
        the same process must call `invalidate_items()` before reading
        again, or stale entries will leak through.

        `gh project item-list` is GraphQL-billed, so reusing the snapshot
        is what saves the points — not just the wall-clock time.
        """
        if self._items is None:
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
            self._items = data.get("items", [])
        # Narrow Optional after the populate-if-None branch above.
        assert self._items is not None
        return self._items

    def invalidate_items(self) -> None:
        """Drop the cached snapshot. Next `board_items()` call re-fetches."""
        self._items = None

    def find_item_id(self, issue_number: int) -> str:
        """Look up the ProjectV2Item id for a given issue number on this board."""
        for item in self.board_items():
            content = item.get("content") or {}
            if content.get("number") == issue_number:
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
        return str(data["id"])

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
                trackedInIssues(first: 10) {{ nodes {{ number }} }}
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
                tracked_in = node.get("trackedInIssues", {}).get("nodes") or []
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
                        blocked_by=tuple(int(t["number"]) for t in tracked_in),
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
    """Four-part diagnostic block for `Resource not accessible by personal access token`
    failures from project mutations. Best-effort — silently skips parts that can't be
    determined.

    Post-#65, jared scrubs GH_TOKEN/GITHUB_TOKEN before invoking gh, so the call
    that just failed ran on `gh auth login`'s OAuth session. The realistic remaining
    trigger for this error class is OAuth without `project` scope. Mention the #65
    scrub explicitly so an operator with GH_TOKEN set isn't misled.
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

    Tries the `blockedBy` field first; on a schema error (older repos
    expose `issueDependencies` under a different name) falls back to
    `issueDependencies`. Raises if neither is available.

    `cache` is forwarded to gh as `--cache <duration>` — pass "60s" for
    advisory uses (sweep, dependency-graph) so re-runs within a minute
    skip the network and the GraphQL points entirely.
    """
    owner, name = repo.split("/", 1)
    for field_name in ("blockedBy", "issueDependencies"):
        q = (
            "query($o:String!,$r:String!,$c:String){repository(owner:$o,name:$r){"
            f"issues(first:100,after:$c,states:OPEN){{pageInfo{{hasNextPage endCursor}}"
            f"nodes{{number {field_name}(first:20){{nodes{{number state}}}}}}}}}}}}"
        )
        result: dict[int, list[dict[str, Any]]] = {}
        cursor: str | None = None
        try:
            while True:
                kwargs: dict[str, str] = {"o": owner, "r": name}
                if cursor:
                    kwargs["c"] = cursor
                data = run_graphql(q, cache=cache, **kwargs)["data"]["repository"]["issues"]
                for node in data["nodes"]:
                    result[node["number"]] = node[field_name]["nodes"]
                if not data["pageInfo"]["hasNextPage"]:
                    break
                cursor = data["pageInfo"]["endCursor"]
            return result
        except GhInvocationError as e:
            # Schema may expose `issueDependencies` instead of `blockedBy`.
            # Match the gh error verbiage loosely so future GraphQL phrasing
            # changes don't silently bypass the fallback.
            msg = str(e)
            if "Field" in msg and ("doesn" in msg or "isn't" in msg):
                continue
            raise
    raise RuntimeError("Neither blockedBy nor issueDependencies field is available")


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
#      preceded by a `PR ` / `Issue ` label (e.g. `- PR #415`).
#
# Mid-line refs in narrative prose are deliberately ignored — they are the
# source of #86/#87 false positives. The label is gated behind a list marker
# so a bare prose line like `Issue #99 supersedes this work.` cannot match.
_PLAN_LINE_REF_RE = re.compile(
    r"^[\s]*"
    r"(?:[-*]\s+(?:(?:PR|Issue)\s+)?)?"  # optional list marker + optional PR/Issue label
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
