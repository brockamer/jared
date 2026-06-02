"""Backend-neutral board contract. No gh/GraphQL imports — pure types.

A BoardProvider stewards one board on one backend. The interface speaks only
the stable integer handle (IssueRef) and these dataclasses; provider-internal
IDs (GitHub node-ids, KanbanFlow _id) never cross this boundary.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Protocol, runtime_checkable

# The stable, human-facing handle. GitHub: issue number. KanbanFlow: task number.value.
IssueRef = int


class Capability(Enum):
    """Backend feature-support flags. Commands branch on these (Phase 6)."""

    MILESTONE_STATE = "milestone_state"  # open/close + due dates
    VELOCITY_TIMESTAMPS = "velocity_timestamps"  # created/closed/transition times
    NATIVE_DEPENDENCIES = "native_dependencies"  # real edge vs label-marker emulation
    MARKDOWN_BODY = "markdown_body"
    CLOSED_STATE = "closed_state"
    MCP_TIER = "mcp_tier"
    SUB_ISSUES = "sub_issues"


@dataclass
class BoardItem:
    number: int
    title: str
    status: str | None
    priority: str | None
    body: str = ""
    labels: list[str] = field(default_factory=list)
    milestone: str | None = None
    blocked_by: list[int] = field(default_factory=list)
    assignee: str | None = None
    fields: dict[str, str] = field(default_factory=dict)  # custom single-selects
    # Opaque backend addressing token (GitHub project-item node-id, KanbanFlow
    # _id). Populated by get_item; the interface promises nothing about its format.
    provider_ref: str | None = None


@dataclass
class Comment:
    body: str
    author: str
    created_at: str


@dataclass
class Edge:
    dependent: int
    blocker: int


@dataclass
class Milestone:
    name: str
    description: str = ""
    state: str | None = None  # open/closed; None on backends without the concept
    due: str | None = None


@dataclass
class TieCandidate:
    number: int
    title: str
    body: str
    labels: list[str] = field(default_factory=list)
    milestone: str | None = None


@runtime_checkable
class BoardProvider(Protocol):
    # --- reads ---
    def get_item(self, ref: IssueRef) -> BoardItem | None: ...
    def list_open_items(self) -> list[BoardItem]: ...
    def get_body(self, ref: IssueRef) -> str: ...
    def list_comments(self, ref: IssueRef) -> list[Comment]: ...
    def fetch_ties(self, *, include_bodies: bool = True) -> list[TieCandidate]: ...
    def fetch_blocked_by_edges(self) -> list[Edge]: ...

    # --- writes ---
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
    ) -> BoardItem: ...
    def add_to_board(
        self,
        ref: IssueRef,
        *,
        priority: str,
        status: str,
        labels: list[str] | None = None,
        fields: list[tuple[str, str]] | None = None,
    ) -> None: ...
    def set_field(self, ref: IssueRef, field_name: str, value: str) -> None: ...
    def move(self, ref: IssueRef, status: str) -> None: ...
    def close(self, ref: IssueRef, *, comment: str | None = None) -> None: ...
    def set_body(self, ref: IssueRef, text: str) -> None: ...
    def comment(self, ref: IssueRef, body: str) -> str: ...
    def add_label(self, ref: IssueRef, name: str) -> None: ...
    def remove_label(self, ref: IssueRef, name: str) -> None: ...
    def add_blocked_by(self, ref: IssueRef, blocker: IssueRef) -> None: ...
    def remove_blocked_by(self, ref: IssueRef, blocker: IssueRef) -> None: ...
    def set_milestone(self, ref: IssueRef, name: str) -> None: ...
    def list_milestones(self) -> list[Milestone]: ...

    # --- introspection ---
    def capabilities(self) -> frozenset[Capability]: ...
