"""In-memory test double for KanbanFlowClient (Phase 3, #316).

Mirrors only the public methods KanbanFlowProvider calls. Holds tasks/comments
in dicts. `fail_set_custom_field` forces set_task_custom_field to raise, for
exercising file()'s rollback path.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from skills.jared.scripts.lib.kanbanflow_client import (
    KanbanFlowNotFoundError,
    KfBoard,
    KfColumn,
    KfComment,
    KfCustomFieldDef,
    KfCustomFieldValue,
    KfEvent,
    KfLabel,
    KfSwimlane,
    KfTask,
    KfUser,
)
from skills.jared.scripts.lib.kanbanflow_provider import KanbanFlowProvider
from skills.jared.scripts.lib.kf_number_index import KfNumberIndex


class FakeKanbanFlowClient:
    def __init__(
        self,
        *,
        board: KfBoard | None = None,
        field_defs: list[KfCustomFieldDef] | None = None,
    ) -> None:
        self.board = board or KfBoard(
            id="B1",
            name="Test",
            columns=[
                KfColumn(unique_id="col-backlog", name="Backlog"),
                KfColumn(unique_id="col-upnext", name="Up Next"),
                KfColumn(unique_id="col-inprog", name="In Progress"),
                KfColumn(unique_id="col-blocked", name="Blocked"),
                KfColumn(unique_id="col-done", name="Done"),
            ],
            swimlanes=[
                KfSwimlane(unique_id="sw-default", name="Default", description=""),
                KfSwimlane(unique_id="sw-v1", name="v1.0", description="First release"),
            ],
        )
        self.field_defs = field_defs or [
            KfCustomFieldDef(
                id="cf-priority",
                name="Priority",
                field_type="dropdown",
                dropdown_options=["High", "Medium", "Low"],
            ),
            KfCustomFieldDef(
                id="cf-ws",
                name="Work Stream",
                field_type="dropdown",
                dropdown_options=["alpha", "beta"],
            ),
        ]
        self.tasks: dict[str, KfTask] = {}
        self.comments: dict[str, list[KfComment]] = {}
        self.users: list[KfUser] = []
        self.board_events: list[KfEvent] = []
        self._next_id = 0
        self.fail_set_custom_field = False

    # --- reads ---
    def get_board(self) -> KfBoard:
        return self.board

    def list_users(self) -> list[KfUser]:
        return list(self.users)

    def list_custom_field_defs(self) -> list[KfCustomFieldDef]:
        return self.field_defs

    def iter_all_tasks(self) -> list[KfTask]:
        return list(self.tasks.values())

    def get_board_events(
        self,
        *,
        from_ts: str | None = None,
        to_ts: str | None = None,
        limit: int = 100,
        order: str = "descending",
    ) -> list[KfEvent]:
        return list(self.board_events)

    def get_task(self, task_id: str) -> KfTask:
        if task_id not in self.tasks:
            raise KanbanFlowNotFoundError(f"no task {task_id}")
        return self.tasks[task_id]

    # --- writes ---
    def create_task(
        self,
        *,
        name: str,
        column_id: str,
        number_value: int,
        swimlane_id: str | None = None,
        description: str | None = None,
        color: str | None = None,
        responsible_user_id: str | None = None,
        labels: list[KfLabel] | None = None,
    ) -> KfTask:
        self._next_id += 1
        task_id = f"task-{self._next_id}"
        task = KfTask(
            id=task_id,
            name=name,
            description=description or "",
            column_id=column_id,
            swimlane_id=swimlane_id,
            number_value=number_value,
            responsible_user_id=responsible_user_id,
            labels=list(labels or []),
        )
        self.tasks[task_id] = task
        return task

    def update_task(
        self,
        task_id: str,
        *,
        name: str | None = None,
        column_id: str | None = None,
        swimlane_id: str | None = None,
        number_value: int | None = None,
        description: str | None = None,
        color: str | None = None,
        responsible_user_id: str | None = None,
    ) -> KfTask:
        t = self.get_task(task_id)
        if name is not None:
            t.name = name
        if column_id is not None:
            t.column_id = column_id
        if swimlane_id is not None:
            t.swimlane_id = swimlane_id
        if number_value is not None:
            t.number_value = number_value
        if description is not None:
            t.description = description
        return t

    def delete_task(self, task_id: str) -> None:
        self.tasks.pop(task_id, None)

    def set_task_custom_field(self, task_id: str, custom_field_id: str, value: str | float) -> None:
        if self.fail_set_custom_field:
            raise RuntimeError("forced custom-field failure")
        t = self.get_task(task_id)
        for cf in t.custom_fields:
            if cf.custom_field_id == custom_field_id:
                cf.value = value
                return
        t.custom_fields.append(KfCustomFieldValue(custom_field_id=custom_field_id, value=value))

    def add_comment(self, task_id: str, text: str, **_: object) -> str:
        self.get_task(task_id)
        bucket = self.comments.setdefault(task_id, [])
        cid = f"c-{len(bucket) + 1}"
        bucket.append(KfComment(id=cid, text=text, created_timestamp="t"))
        return cid

    def list_comments(self, task_id: str) -> list[KfComment]:
        return self.comments.get(task_id, [])

    def add_label(self, task_id: str, name: str, *, pinned: bool = False) -> None:
        t = self.get_task(task_id)
        if not any(label.name == name for label in t.labels):
            t.labels.append(KfLabel(name=name, pinned=pinned))

    def remove_label(self, task_id: str, name: str) -> None:
        t = self.get_task(task_id)
        t.labels = [label for label in t.labels if label.name != name]

    def list_labels(self, task_id: str) -> list[KfLabel]:
        return self.get_task(task_id).labels


def make_kf_provider_with_task(
    *,
    users: dict[str, str] | None = None,
    comments: list[dict[str, str]] | None = None,
) -> tuple[KanbanFlowProvider, FakeKanbanFlowClient, int]:
    """Build a (KanbanFlowProvider, FakeKanbanFlowClient, ref) triple.

    Creates one task with number_value=1, seeds `users` (id->name) and
    `comments` (list of dicts with text/createdTimestamp/authorUserId keys)
    directly into the fake client so tests can call provider.list_comments(ref)
    without I/O. Suitable for offline unit tests.

    The KfNumberIndex is backed by a real tmpdir so _resolve_id works after
    the index is seeded from iter_all_tasks() on first access.
    """
    client = FakeKanbanFlowClient()
    # Seed users.
    for uid, name in (users or {}).items():
        client.users.append(KfUser(id=uid, name=name))
    # Create the task so the index can resolve ref=1.
    task = client.create_task(name="test task", column_id="col-backlog", number_value=1)
    # Seed comments directly (bypass add_comment which drops authorUserId).
    for raw in comments or []:
        cmt = KfComment(
            id=f"c-{len(client.comments.get(task.id, [])) + 1}",
            text=raw.get("text", ""),
            created_timestamp=raw.get("createdTimestamp", ""),
            author_user_id=raw.get("authorUserId", ""),
        )
        client.comments.setdefault(task.id, []).append(cmt)
    # Build the provider with a real tmpdir-backed index.
    tmp_dir = Path(tempfile.mkdtemp())
    index = KfNumberIndex(tmp_dir / "kf-index-B1.json")
    provider = KanbanFlowProvider(
        client=client,
        board=client.board,
        field_defs=client.field_defs,
        index=index,
    )
    return provider, client, 1
