"""GitHubProjectsProvider — BoardProvider over GitHub Projects v2 + Issues.

All gh/GraphQL/field-id/option-id logic is private here. Calls flow through
board.py's module-level run_gh/run_gh_raw/run_graphql so conftest's subprocess
patching is preserved.
"""

from __future__ import annotations

from typing import Any

from .board import (
    FieldNotFound,
    GhInvocationError,
    OptionNotFound,
    _flatten_project_item_for_project,
    fetch_issue_body_rest,
    fetch_recent_comments_batch,
    run_graphql,
)
from .board import (
    fetch_blocked_by_edges as _fetch_blocked_by_edges,
)
from .board_provider import (
    BoardItem,
    Capability,
    Comment,
    Edge,
    IssueRef,
    Milestone,
    TieCandidate,
)

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
        self._items: list[dict[str, object]] | None = None

    _CAPABILITIES = frozenset(Capability)  # GitHub advertises the full set

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
        return self._item_from_flat(number=ref, title="", flat=flat)

    def get_body(self, ref: IssueRef) -> str:
        """Return the issue's Markdown body via REST (with ETag/conditional GET)."""
        return fetch_issue_body_rest(self.repo, ref)

    def list_comments(self, ref: IssueRef) -> list[Comment]:
        """Return the most recent comments for issue `ref`.

        Mapping notes:
        - body: node["body"]
        - created_at: node["createdAt"]
        - author: absent from fetch_recent_comments_batch query → "" (degraded field).
          The upstream query is `comments(last: N) { nodes { body createdAt } }` — no
          author node. Editing board.py to add author is out of scope for this task.
        """
        batch = fetch_recent_comments_batch(self.repo, [ref])
        nodes = batch.get(ref, [])
        return [
            Comment(
                body=str(node.get("body", "")),
                author="",
                created_at=str(node.get("createdAt", "")),
            )
            for node in nodes
        ]

    def fetch_ties(self, *, include_bodies: bool = True) -> list[TieCandidate]:
        """Fetch open issues for tie analysis, returning TieCandidate records.

        Uses the same paginated GraphQL query as Board.fetch_open_issues_for_ties
        with cache="5m". Done items are filtered before construction.

        Mapping notes:
        - status drives the Done filter; it is not carried on TieCandidate.
        - the query also selects priority (mirroring board.py's ties query) but
          this method does not read it — priority is not a TieCandidate field.
        - blocked_by is dropped (not in TieCandidate).
        - labels: list built from node["labels"]["nodes"][*]["name"].
        - milestone: from node["milestone"]["title"] or None.
        """
        body_field = "body" if include_bodies else ""
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
        all_records: list[TieCandidate] = []
        while True:
            kwargs: dict[str, str | int | bool] = {"owner": owner, "name": name}
            if cursor is not None:
                kwargs["cursor"] = cursor
            data = run_graphql(query, cache="5m", **kwargs)
            page = data["data"]["repository"]["issues"]
            for node in page["nodes"]:
                project_items = node.get("projectItems", {}).get("nodes") or []
                project_item = project_items[0] if project_items else {}
                status_field = project_item.get("fieldValueByName") or {}
                status = str(status_field.get("name") or "Backlog")
                if status == "Done":
                    continue
                milestone_obj = node.get("milestone") or {}
                all_records.append(
                    TieCandidate(
                        number=int(node["number"]),
                        title=str(node["title"]),
                        body=str(node.get("body") or ""),
                        labels=list(n["name"] for n in (node.get("labels", {}).get("nodes") or [])),
                        milestone=milestone_obj.get("title"),
                    )
                )
            if not page["pageInfo"]["hasNextPage"]:
                break
            cursor = page["pageInfo"]["endCursor"]
        return all_records

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

    # ------------------------------------------------------------------ #
    # WRITE methods (implemented in Task 4)                               #
    # ------------------------------------------------------------------ #

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
    ) -> BoardItem:
        raise NotImplementedError

    def add_to_board(
        self,
        ref: IssueRef,
        *,
        priority: str,
        status: str,
        labels: list[str] | None = None,
        fields: list[tuple[str, str]] | None = None,
    ) -> None:
        raise NotImplementedError

    def set_field(self, ref: IssueRef, field_name: str, value: str) -> None:
        raise NotImplementedError

    def move(self, ref: IssueRef, status: str) -> None:
        raise NotImplementedError

    def close(self, ref: IssueRef, *, comment: str | None = None) -> None:
        raise NotImplementedError

    def set_body(self, ref: IssueRef, text: str) -> None:
        raise NotImplementedError

    def comment(self, ref: IssueRef, body: str) -> None:
        raise NotImplementedError

    def add_label(self, ref: IssueRef, name: str) -> None:
        raise NotImplementedError

    def remove_label(self, ref: IssueRef, name: str) -> None:
        raise NotImplementedError

    def add_blocked_by(self, ref: IssueRef, blocker: IssueRef) -> None:
        raise NotImplementedError

    def remove_blocked_by(self, ref: IssueRef, blocker: IssueRef) -> None:
        raise NotImplementedError

    def set_milestone(self, ref: IssueRef, name: str) -> None:
        raise NotImplementedError

    def list_milestones(self) -> list[Milestone]:
        raise NotImplementedError
