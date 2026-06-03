"""In-memory test double for KanbanFlowClient (Phase 3, #316).

Mirrors only the public methods KanbanFlowProvider calls. Holds tasks/comments
in dicts. `fail_set_custom_field` forces set_task_custom_field to raise, for
exercising file()'s rollback path.
"""

from __future__ import annotations

from skills.jared.scripts.lib.kanbanflow_client import (
    KanbanFlowNotFoundError,
    KfBoard,
    KfColumn,
    KfComment,
    KfCustomFieldDef,
    KfCustomFieldValue,
    KfLabel,
    KfSwimlane,
    KfTask,
)


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
        self._next_id = 0
        self.fail_set_custom_field = False

    # --- reads ---
    def get_board(self) -> KfBoard:
        return self.board

    def list_custom_field_defs(self) -> list[KfCustomFieldDef]:
        return self.field_defs

    def iter_all_tasks(self) -> list[KfTask]:
        return list(self.tasks.values())

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
