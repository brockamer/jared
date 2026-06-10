"""GitHubProjectsProvider — BoardProvider over GitHub Projects v2 + Issues.

All gh/GraphQL/field-id/option-id logic is private here. Calls flow through
board.py's module-level run_gh/run_gh_raw/run_graphql so conftest's subprocess
patching is preserved.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

from .board import (
    FieldNotFound,
    GhInvocationError,
    ItemNotFound,
    OptionNotFound,
    _flatten_project_item_for_project,
    fetch_issue_body_rest,
    run_gh,
    run_gh_raw,
    run_graphql,
)
from .board import (
    fetch_blocked_by_edges as _fetch_blocked_by_edges,
)
from .board_provider import (
    BoardItem,
    Capability,
    ClosedItem,
    Comment,
    Edge,
    IssueRef,
    Milestone,
)


class FileRoundTripError(Exception):
    """Staging wrote wrong content — the body cannot be trusted; gh was not called.

    `staged_path` is the temp file path (already unlinked by the time this is
    raised). Carry it so the CLI can include it in the error message.
    """

    def __init__(self, staged_path: str) -> None:
        self.staged_path = staged_path
        super().__init__(f"round-trip mismatch staging body to {staged_path!r}")


class FileCreateError(Exception):
    """gh issue create failed. The staged body temp file is PRESERVED so the
    caller can tell the user to retry with --body-file <staged_path>.
    """

    def __init__(self, staged_path: str, message: str) -> None:
        self.staged_path = staged_path
        super().__init__(message)


class FileBoardSetupError(Exception):
    """Issue created successfully but post-create board setup failed.

    `issue_number` and `issue_url` let the CLI build a recovery command.
    """

    def __init__(self, issue_number: int, issue_url: str, cause: Exception) -> None:
        self.issue_number = issue_number
        self.issue_url = issue_url
        self.cause = cause
        super().__init__(str(cause))


class IssueResolutionError(GhInvocationError):
    """Failed to resolve an issue ref to its GitHub node-id (the `gh issue view
    --json id` step that precedes a blocked-by mutation).

    Subclasses GhInvocationError so any existing `except GhInvocationError`
    still catches it, but lets the CLI distinguish a *resolution* failure from
    a downstream *mutation* failure and restore the specific
    "could not resolve issue node IDs" message (#321 item 5). The message
    carries that GitHub-specific phrasing so the CLI can print it verbatim
    without itself referencing node-ids.
    """


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


class GitHubProjectsProvider:
    def __init__(
        self,
        *,
        project_number: int,
        project_id: str,
        owner: str,
        repo: str,
        field_ids: dict[str, str],
        field_options: dict[str, dict[str, str]],
    ) -> None:
        self.project_number = project_number
        self.project_id = project_id
        self.owner = owner
        self.repo = repo
        self._field_ids = field_ids
        self._field_options = field_options

    _CAPABILITIES = frozenset(Capability)  # GitHub advertises the full set

    @classmethod
    def default_capabilities(cls) -> frozenset[Capability]:
        """The backend's static capability set, resolved without an instance."""
        return cls._CAPABILITIES

    def capabilities(self) -> frozenset[Capability]:
        return self._CAPABILITIES

    # ------------------------------------------------------------------ #
    # Private helpers                                                      #
    # ------------------------------------------------------------------ #

    def _field_id(self, name: str) -> str:
        """Return the project field-ID for `name`, or raise FieldNotFound."""
        if name not in self._field_ids:
            available = ", ".join(sorted(self._field_ids)) or "(none)"
            raise FieldNotFound(
                f"Field '{name}' not found in project-board.md. Available: {available}"
            )
        return self._field_ids[name]

    def _option_id(self, field_name: str, option: str) -> str:
        """Return the single-select option-ID for `option` in `field_name`.

        Raises OptionNotFound when the option is unknown.
        """
        options = self._field_options.get(field_name, {})
        if option not in options:
            available = ", ".join(sorted(options)) or "(none)"
            raise OptionNotFound(
                f"Option '{option}' not found for field '{field_name}'. Available: {available}"
            )
        return options[option]

    def _item_from_flat(
        self,
        number: int,
        title: str,
        flat: dict[str, Any],
        *,
        labels: list[str] | None = None,
        milestone: str | None = None,
        blocked_by: list[int] | None = None,
    ) -> BoardItem:
        """Convert a _flatten_project_item_for_project dict into a BoardItem.

        `flat` contains at minimum 'id', 'status', 'priority' (and any other
        single-select field names lowercased). Fields beyond status/priority go
        into `fields` (str→str, dropping None values).
        """
        status: str | None = flat.get("status")
        priority: str | None = flat.get("priority")
        extra: dict[str, str] = {
            k: str(v)
            for k, v in flat.items()
            if k not in {"id", "status", "priority"} and v is not None
        }
        return BoardItem(
            number=number,
            title=title,
            status=status,
            priority=priority,
            labels=labels or [],
            milestone=milestone,
            blocked_by=blocked_by or [],
            fields=extra,
        )

    # ------------------------------------------------------------------ #
    # READ methods                                                         #
    # ------------------------------------------------------------------ #

    def list_open_items(self) -> list[BoardItem]:
        """Fetch open issues and their project field values in one GraphQL call.

        Routes via a `repository.issues(states: OPEN)` query (same as
        Board.open_items).  Issues not on this project board are excluded.

        Raises GhInvocationError when >100 open issues are present (pagination
        not implemented — same guard as Board.open_items).

        Mapping notes:
        - title, status, priority, labels come from the GraphQL response.
        - milestone and blocked_by are absent from _OPEN_ITEMS_QUERY → None/[].
        - fields: extra single-select field values (beyond status/priority),
          keyed by lowercased field name.
        """
        owner, repo_name = self.repo.split("/", 1)
        data = run_graphql(
            _OPEN_ITEMS_QUERY,
            owner=owner,
            repo=repo_name,
        )
        issues_node = (data.get("data") or {}).get("repository", {}).get("issues") or {}
        if (issues_node.get("pageInfo") or {}).get("hasNextPage"):
            raise GhInvocationError(
                "list_open_items() query returned hasNextPage=true; >100 open issues "
                "on this repo. Pagination not implemented — bump the first: cap "
                "or add cursor-based pagination."
            )
        result: list[BoardItem] = []
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
            label_names = [n["name"] for n in (labels_node.get("nodes") or []) if "name" in n]
            result.append(
                self._item_from_flat(
                    number=number,
                    title=str(issue.get("title", "")),
                    flat=flat,
                    labels=label_names,
                )
            )
        return result

    def get_item(self, ref: IssueRef) -> BoardItem | None:
        """Return the project item for issue `ref`, or None if not on board.

        Uses a scoped per-issue projectItems query (~1-3 GraphQL points).

        Mapping notes:
        - title: absent from _ISSUE_PROJECT_ITEM_QUERY → "" (degraded field).
        - labels, milestone, blocked_by: absent from query → []/None/[].
        - status, priority, and any other single-select fields come from flat.
        """
        owner, repo_name = self.repo.split("/", 1)
        data = run_graphql(
            _ISSUE_PROJECT_ITEM_QUERY,
            owner=owner,
            repo=repo_name,
            number=ref,
        )
        issue = (data.get("data") or {}).get("repository", {}).get("issue") or {}
        flat = _flatten_project_item_for_project(issue.get("projectItems"), self.project_number)
        if flat is None:
            return None
        item = self._item_from_flat(number=ref, title="", flat=flat)
        item.provider_ref = str(flat["id"]) if flat.get("id") else None
        return item

    def get_body(self, ref: IssueRef) -> str:
        """Return the issue's Markdown body via REST (with ETag/conditional GET)."""
        return fetch_issue_body_rest(self.repo, ref)

    def fetch_blocked_by_edges(self) -> list[Edge]:
        """Return all blocked-by edges for open issues in this repo.

        Calls module-level fetch_blocked_by_edges(repo) (one paginated GraphQL
        call). Maps dict[issue→[{number, state}]] to Edge(dependent, blocker);
        `state` is discarded. cache=None (no advisory caching at the provider
        level — callers that want caching pass their own cache kwarg via Board).
        """
        raw = _fetch_blocked_by_edges(self.repo)
        edges: list[Edge] = []
        for dependent_num, blockers in raw.items():
            for blocker_node in blockers:
                edges.append(
                    Edge(
                        dependent=dependent_num,
                        blocker=int(blocker_node["number"]),
                    )
                )
        return edges

    def list_comments(self, ref: IssueRef) -> list[Comment]:
        """Return an issue's comments oldest→newest as neutral Comments.

        Uses `gh issue view <n> --json comments`, which returns each comment's
        author.login, body (markdown), and createdAt. The GitHub-camelCase
        `createdAt` is mapped to Comment.created_at here so it never crosses
        the neutral boundary.
        """
        data = run_gh(["issue", "view", str(ref), "--repo", self.repo, "--json", "comments"])
        raw = data.get("comments", []) if isinstance(data, dict) else []
        return [
            Comment(
                author=str((c.get("author") or {}).get("login") or ""),
                body=str(c.get("body", "")),
                created_at=str(c.get("createdAt") or ""),
            )
            for c in raw
        ]

    # ------------------------------------------------------------------ #
    # Private write helpers                                               #
    # ------------------------------------------------------------------ #

    def _find_item_id(self, issue_number: int) -> str:
        """Look up the ProjectV2Item id for a given issue number.

        Uses the provider's existing scoped-per-issue query (same as
        Board.find_item_id but routed through module-level run_graphql).
        Raises ItemNotFound when the issue is not on this board.
        """
        owner, repo_name = self.repo.split("/", 1)
        data = run_graphql(
            _ISSUE_PROJECT_ITEM_QUERY,
            owner=owner,
            repo=repo_name,
            number=issue_number,
        )
        issue = (data.get("data") or {}).get("repository", {}).get("issue") or {}
        flat = _flatten_project_item_for_project(issue.get("projectItems"), self.project_number)
        if flat and flat.get("id"):
            return str(flat["id"])
        raise ItemNotFound(
            f"No project item for issue #{issue_number} in project "
            f"{self.project_number}. Is the issue added to the board?"
        )

    def _item_add(self, issue_number: int) -> str:
        """Call `gh project item-add` and return the new item-id.

        Mirrors Board._add_to_board exactly, including the no-id retry
        (jared#112). Idempotent (jared#71): re-running on an already-on-board
        issue exits 0 and returns the existing item-id.
        """
        url = f"https://github.com/{self.repo}/issues/{issue_number}"
        data = run_gh(
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
        item_id = data.get("id") or ""
        if not item_id:
            # gh project item-add occasionally returns a body with no `id` on
            # the first call but succeeds immediately on retry (jared#112).
            data = run_gh(
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

    def _add_existing(
        self,
        issue_number: int,
        *,
        priority: str,
        status: str,
        labels: list[str] | None = None,
        fields: list[tuple[str, str]] | None = None,
        assume_new: bool = False,
    ) -> str:
        """Add an issue to the board (if needed), apply labels, set fields.

        Mirrors Board.add_existing_to_board exactly. Pre-resolves all
        field/option IDs before any GitHub call so misconfiguration raises
        before side effects. Returns the item_id.

        `assume_new=True` skips the membership scan (used by `file` after a
        fresh issue create — same perf optimisation as Board).
        """
        # Pre-resolve before any gh call.
        prio_field_id = self._field_id("Priority")
        prio_option_id = self._option_id("Priority", priority)
        status_field_id = self._field_id("Status")
        status_option_id = self._option_id("Status", status)
        extras: list[tuple[str, str]] = []
        for name, value in fields or []:
            extras.append((self._field_id(name), self._option_id(name, value)))

        # Resolve item-id.
        item_id: str
        if assume_new:
            item_id = self._item_add(issue_number)
        else:
            try:
                item_id = self._find_item_id(issue_number)
            except ItemNotFound:
                item_id = self._item_add(issue_number)

        # Labels are issue-scoped; gh issue edit handles them.
        if labels:
            label_args = ["issue", "edit", str(issue_number), "--repo", self.repo]
            for label in labels:
                label_args.extend(["--add-label", label])
            run_gh(label_args)

        # Single aliased mutation sets Priority, Status, and any extras in one
        # GraphQL round-trip.  IDs are opaque internal values resolved above
        # from project-board.md — interpolating them directly is safe.
        # cache=None is required (mutations must never be cached).
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
        run_graphql(mutation, cache=None)

        return item_id

    def _resolve_issue_node_id(self, issue_number: int) -> str:
        """Return the GitHub node-id for `issue_number` (needed for blocked-by).

        Raises IssueResolutionError (not a bare GhInvocationError) on lookup
        failure so the CLI can distinguish this resolution step from the
        downstream addBlockedBy/removeBlockedBy mutation and restore the
        specific "could not resolve issue node IDs" message (#321 item 5).
        """
        try:
            data = run_gh(
                [
                    "issue",
                    "view",
                    str(issue_number),
                    "--repo",
                    self.repo,
                    "--json",
                    "id",
                ]
            )
        except GhInvocationError as e:
            raise IssueResolutionError(f"could not resolve issue node IDs: {e}") from e
        return str(data["id"])

    # ------------------------------------------------------------------ #
    # WRITE methods (implemented in Task 4)                               #
    # ------------------------------------------------------------------ #

    def recently_closed(self, *, days: int) -> list[ClosedItem]:
        """Return issues closed in the last `days` days as neutral ClosedItems.

        Uses `gh issue list --state closed --search "closed:>=DATE"`. The CLI's
        `_fetch_recently_closed` is now a thin delegate to this method. Maps
        gh's camelCase `closedAt` to ClosedItem.closed_at here — the GitHub key
        never crosses the neutral boundary (#321 item 1). Sorted by closed_at
        desc (newest first). Empty list if none.

        Raises GhInvocationError on silent-truncation at the 200-item cap.
        """
        from datetime import UTC, datetime, timedelta

        cutoff = (datetime.now(UTC) - timedelta(days=days)).strftime("%Y-%m-%d")
        limit = 200
        data = run_gh(
            [
                "issue",
                "list",
                "--repo",
                self.repo,
                "--state",
                "closed",
                "--search",
                f"closed:>={cutoff}",
                "--limit",
                str(limit),
                "--json",
                "number,title,closedAt",
            ]
        )
        raw: list[dict[str, Any]] = data if isinstance(data, list) else data.get("issues", [])
        if len(raw) == limit:
            raise GhInvocationError(
                f"gh issue list --state closed returned exactly {limit} items "
                f"in the last {days}d — likely truncated. Narrow the lookback "
                f"window or paginate; do not trust this snapshot."
            )
        items = [
            ClosedItem(
                number=int(entry["number"]),
                title=str(entry.get("title", "")),
                closed_at=str(entry.get("closedAt") or ""),
            )
            for entry in raw
        ]
        items.sort(key=lambda c: c.closed_at, reverse=True)
        return items

    def validate_fields(
        self,
        *,
        priority: str,
        status: str,
        fields: list[tuple[str, str]] | None = None,
    ) -> None:
        """Pre-resolve Priority/Status/extra field+option IDs, raising
        FieldNotFound/OptionNotFound on any miss — and returning nothing.

        Resolved IDs stay private to the provider: the CLI learns only
        pass/raise, never a field_id/option_id (that vocabulary was
        deliberately removed from the CLI at the #314 fork-gate). The CLI calls
        this at the very top of `jared file` so a bad --priority/--status/
        --field fails fast (exit 1 via main()'s handler) BEFORE the read-only
        milestone GET and the body PII scan run — restoring pre-#314 ordering
        and the bad-field-beats-PII-body exit code (#321 item 4). file() also
        calls it as its own fail-before-create fence (the two callers are
        intentional — validating twice is cheap, both are pure dict lookups).
        """
        self._field_id("Priority")
        self._option_id("Priority", priority)
        self._field_id("Status")
        self._option_id("Status", status)
        for name, value in fields or []:
            self._field_id(name)
            self._option_id(name, value)

    def file(
        self,
        *,
        title: str,
        body: str,
        priority: str,
        status: str,
        labels: list[str] | None = None,
        milestone: str | None = None,
        fields: list[tuple[str, str]] | None = None,
        number: int | None = None,
    ) -> BoardItem:
        """Atomic: create issue, add to project, set Priority + Status + extras.

        Implements the #100 staged-body discipline: the body is staged to a temp
        file before any gh call. The round-trip fence verifies staging fidelity;
        on mismatch it unlinks the temp file and raises FileRoundTripError. On
        gh issue create failure the temp file is PRESERVED and FileCreateError is
        raised (with staged_path) so the caller can tell the user to retry with
        --body-file <path>. On post-create board-setup failure FileBoardSetupError
        is raised carrying the issue_number and issue_url.

        CLI-layer concerns (pre-flight redaction, milestone-requirement
        enforcement) stay in the CLI layer before this call.

        Milestone is passed to gh issue create verbatim when given (caller is
        responsible for validation — same as how the CLI validates before calling
        this method).
        """
        # number= is honored only on backends that allow setting it (KanbanFlow);
        # GitHub auto-assigns issue numbers and this kwarg is intentionally ignored.
        effective_status = status or "Backlog"

        # Pre-resolve field/option IDs before ANY gh call so misconfiguration
        # raises before the issue is created (mirrors the original CLI guard and
        # Board.add_existing_to_board's "pre-resolve everything up front"
        # discipline). _add_existing re-resolves the same names — the duplication
        # is intentional: the pre-create check is the fail-before-create fence.
        self.validate_fields(priority=priority, status=effective_status, fields=fields)

        # Stage body in a temp file; gh issue create requires a file path.
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".md", delete=False, encoding="utf-8"
        ) as tf:
            tf.write(body)
            body_tmp_path = tf.name

        # Round-trip fence: verify the staged file matches what we wrote.
        # Catches silent staging corruption (filesystem oddity, future routing
        # surprise) where gh would otherwise succeed with empty/wrong body.
        if Path(body_tmp_path).read_text(encoding="utf-8") != body:
            Path(body_tmp_path).unlink(missing_ok=True)
            raise FileRoundTripError(body_tmp_path)

        create_args = [
            "issue",
            "create",
            "--repo",
            self.repo,
            "--title",
            title,
            "--body-file",
            body_tmp_path,
        ]
        for label in labels or []:
            create_args.extend(["--label", label])
        if milestone is not None:
            create_args.extend(["--milestone", milestone])

        # Preserve the staged temp file on any create-step failure so the user
        # can retry without re-typing the body (#100). Unlink ONLY on success.
        try:
            issue_url = run_gh_raw(create_args)
        except GhInvocationError as e:
            # Staged file preserved (not unlinked) — caller must surface the
            # path and unlink after confirming the user has it.
            raise FileCreateError(body_tmp_path, str(e)) from e

        if not issue_url.startswith("http"):
            # Unexpected output: also a create failure; preserve staged file.
            raise FileCreateError(
                body_tmp_path,
                f"unexpected gh issue create output: {issue_url[:200]}",
            )

        # Past the create step — issue exists, safe to clean up staged body.
        Path(body_tmp_path).unlink(missing_ok=True)

        issue_number = int(issue_url.rsplit("/", 1)[-1])

        try:
            self._add_existing(
                issue_number,
                priority=priority,
                status=effective_status,
                fields=fields,
                assume_new=True,
            )
        except (GhInvocationError, FieldNotFound, OptionNotFound, ItemNotFound) as e:
            raise FileBoardSetupError(issue_number, issue_url, e) from e

        return BoardItem(
            number=issue_number,
            title=title,
            status=effective_status,
            priority=priority,
            labels=list(labels or []),
            milestone=milestone,
            # Carry gh's actual create URL so the CLI can echo it verbatim
            # instead of reconstructing one (diverges on GHE hosts — #321 item 3).
            url=issue_url,
        )

    def add_to_board(
        self,
        ref: IssueRef,
        *,
        priority: str,
        status: str,
        labels: list[str] | None = None,
        fields: list[tuple[str, str]] | None = None,
    ) -> None:
        """Add an existing issue to the board, apply labels and fields.

        Idempotent — safe to re-run. Mirrors _cmd_add_to_board's call to
        Board.add_existing_to_board (assume_new=False).
        """
        self._add_existing(
            ref,
            priority=priority,
            status=status,
            labels=labels,
            fields=fields,
            assume_new=False,
        )

    def set_field(self, ref: IssueRef, field_name: str, value: str) -> None:
        """Set a single-select project field on an issue.

        Mirrors _cmd_set: find item-id via scoped graphql query, then emit
        `gh project item-edit --project-id … --id … --field-id … --single-select-option-id …`.
        Does NOT call the aliased updateProjectV2ItemFieldValue mutation — that
        is only used by add_to_board / file for atomic multi-field sets.
        """
        item_id = self._find_item_id(ref)
        field_id = self._field_id(field_name)
        option_id = self._option_id(field_name, value)

        run_gh(
            [
                "project",
                "item-edit",
                "--project-id",
                self.project_id,
                "--id",
                item_id,
                "--field-id",
                field_id,
                "--single-select-option-id",
                option_id,
            ]
        )

    def move(self, ref: IssueRef, status: str) -> None:
        """Move an issue to a new Status column. Delegates to set_field."""
        self.set_field(ref, "Status", status)

    def close(self, ref: IssueRef, *, comment: str | None = None) -> None:
        """Close an issue and set Status=Done.

        Mirrors _cmd_close: optional comment → gh issue close → set_field
        (always, per #137 defense-in-depth; no poll).

        PII pre-flight for the comment stays in the CLI layer (Task 6).
        """
        if comment is not None:
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".md", delete=False, encoding="utf-8"
            ) as tf:
                tf.write(comment)
                tmp_path = tf.name
            try:
                run_gh_raw(
                    [
                        "issue",
                        "comment",
                        str(ref),
                        "--repo",
                        self.repo,
                        "--body-file",
                        tmp_path,
                    ]
                )
            finally:
                Path(tmp_path).unlink(missing_ok=True)

        run_gh(
            [
                "issue",
                "close",
                str(ref),
                "--repo",
                self.repo,
            ]
        )

        # Defense-in-depth (#137): always set Status=Done explicitly; cheap
        # no-op if the GitHub "Item closed → Done" workflow fired, genuine
        # save if it didn't.
        self.set_field(ref, "Status", "Done")

    def set_body(self, ref: IssueRef, text: str) -> None:
        """Replace the issue body.

        Mirrors capture-context.py's write_body:
        `gh issue edit <n> --repo <repo> --body-file <path>`.
        """
        with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False, encoding="utf-8") as f:
            f.write(text)
            path = f.name
        try:
            run_gh_raw(["issue", "edit", str(ref), "--repo", self.repo, "--body-file", path])
        finally:
            Path(path).unlink(missing_ok=True)

    def comment(self, ref: IssueRef, body: str) -> str:
        """Post a comment on an issue and return the new comment URL.

        Mirrors _cmd_comment: stages body in a temp file, then calls
        `gh issue comment <n> --repo <repo> --body-file <path>`.
        The raw stdout (comment URL) is returned so the CLI can echo it.

        PII pre-flight stays in the CLI layer (Task 6).
        """
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".md", delete=False, encoding="utf-8"
        ) as tf:
            tf.write(body)
            tmp_path = tf.name
        try:
            url = run_gh_raw(
                [
                    "issue",
                    "comment",
                    str(ref),
                    "--repo",
                    self.repo,
                    "--body-file",
                    tmp_path,
                ]
            )
        finally:
            Path(tmp_path).unlink(missing_ok=True)
        return url

    def add_label(self, ref: IssueRef, name: str) -> None:
        """Add a label to an issue. Idempotent."""
        run_gh(["issue", "edit", str(ref), "--repo", self.repo, "--add-label", name])

    def remove_label(self, ref: IssueRef, name: str) -> None:
        """Remove a label from an issue. Idempotent."""
        run_gh(["issue", "edit", str(ref), "--repo", self.repo, "--remove-label", name])

    def _mutate_blocked_by(self, ref: IssueRef, blocker: IssueRef, *, mutation: str) -> None:
        """Resolve both issue node-ids and run an (add|remove)BlockedBy mutation.

        Shared by add_blocked_by / remove_blocked_by — the two differ only in
        the mutation field name (`mutation`). The emitted query is byte-identical
        to _cmd_blocked_by's apart from that one token.
        """
        dep_id = self._resolve_issue_node_id(ref)
        blocker_id = self._resolve_issue_node_id(blocker)
        query = (
            "mutation($issueId: ID!, $blockingIssueId: ID!) { "
            f"  {mutation}("
            "    input: { issueId: $issueId, blockingIssueId: $blockingIssueId }"
            "  ) { issue { number } }"
            "}"
        )
        run_graphql(query, issueId=dep_id, blockingIssueId=blocker_id)

    def add_blocked_by(self, ref: IssueRef, blocker: IssueRef) -> None:
        """Add a native GitHub blocked-by dependency edge.

        Mirrors _cmd_blocked_by (remove=False): resolve both issue node-ids
        via `gh issue view --json id`, then emit the addBlockedBy mutation.
        """
        self._mutate_blocked_by(ref, blocker, mutation="addBlockedBy")

    def remove_blocked_by(self, ref: IssueRef, blocker: IssueRef) -> None:
        """Remove a native GitHub blocked-by dependency edge.

        Mirrors _cmd_blocked_by (remove=True): resolve both issue node-ids
        via `gh issue view --json id`, then emit the removeBlockedBy mutation.
        """
        self._mutate_blocked_by(ref, blocker, mutation="removeBlockedBy")

    def set_milestone(self, ref: IssueRef, name: str) -> None:
        """Assign a milestone to an issue by title.

        Mirrors `gh issue edit <n> --milestone <name>` — gh accepts the title
        string directly, no numeric id resolution required.
        """
        run_gh(["issue", "edit", str(ref), "--repo", self.repo, "--milestone", name])

    def list_milestones(self) -> list[Milestone]:
        """Return open milestones for this repo.

        Mirrors _cmd_file's milestone lookup:
        `gh api repos/{repo}/milestones?state=open&per_page=100`.
        The query string form is intentional — -f filters on /milestones would
        hit the POST-create endpoint (#254).
        """
        raw = run_gh(["api", f"repos/{self.repo}/milestones?state=open&per_page=100"])
        milestones: list[Milestone] = []
        for m in raw if isinstance(raw, list) else []:
            milestones.append(
                Milestone(
                    name=m.get("title", ""),
                    description=m.get("description") or "",
                    state=m.get("state"),
                    due=m.get("due_on"),
                )
            )
        return milestones
