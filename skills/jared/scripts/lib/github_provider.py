"""GitHubProjectsProvider — BoardProvider over GitHub Projects v2 + Issues.

All gh/GraphQL/field-id/option-id logic is private here. Calls flow through
board.py's module-level run_gh/run_gh_raw/run_graphql so conftest's subprocess
patching is preserved.
"""

from __future__ import annotations

from .board_provider import (
    BoardItem,
    Capability,
    Comment,
    Edge,
    IssueRef,
    Milestone,
    TieCandidate,
)


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

    # reads/writes implemented in Tasks 3–4
    def get_item(self, ref: IssueRef) -> BoardItem | None:
        raise NotImplementedError

    def list_open_items(self) -> list[BoardItem]:
        raise NotImplementedError

    def get_body(self, ref: IssueRef) -> str:
        raise NotImplementedError

    def list_comments(self, ref: IssueRef) -> list[Comment]:
        raise NotImplementedError

    def fetch_ties(self, *, include_bodies: bool = True) -> list[TieCandidate]:
        raise NotImplementedError

    def fetch_blocked_by_edges(self) -> list[Edge]:
        raise NotImplementedError

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
