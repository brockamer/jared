# skills/jared/scripts/lib/kanbanflow_provider.py
"""KanbanFlowProvider — BoardProvider over the KanbanFlow REST client (#316).

All KanbanFlow ids (_id, columnId, swimlaneId, customFieldId) stay private here;
the interface speaks only IssueRef (#N) and the neutral dataclasses. #N is
resolved to the internal task _id via KfNumberIndex (no get-by-number endpoint).

Capability set is reduced: KanbanFlow supports the core board loop plus milestone
assignment (swimlanes). See the design spec for the per-capability rationale.
"""

from __future__ import annotations

import contextlib
import sys
from datetime import UTC, datetime, timedelta
from typing import Protocol

from .board import FieldNotFound, ItemNotFound, OptionNotFound
from .board_provider import BoardItem, Capability, ClosedItem, Comment, Edge, IssueRef, Milestone
from .kanbanflow_client import (
    KanbanFlowNotFoundError,
    KfBoard,
    KfComment,
    KfCustomFieldDef,
    KfEvent,
    KfLabel,
    KfTask,
    KfUser,
)
from .kf_number_index import KfNumberIndex

# NOTE: later tasks add imports as they first use them — KanbanFlowNotFoundError
# (Task 5), Edge + ClosedItem (Task 6), Milestone (Task 12). Each task keeps its
# own ruff/mypy gate green; do not front-load these here (they would be unused
# until their task and trip ruff F401).

_BLOCKED_BY_PREFIX = "blocked-by:"

_CANONICAL_STATUSES = ("Backlog", "Up Next", "In Progress", "Blocked", "Done")

# KanbanFlow advertises the full Capability set MINUS these. The remainder is
# {MILESTONE_ASSIGNMENT}: swimlanes give KF milestone assignment, but nothing
# richer (state, dates, dependencies, etc). See the design spec and #390.
_OMITTED_CAPABILITIES = frozenset(
    {
        Capability.NATIVE_DEPENDENCIES,
        Capability.MILESTONE_STATE,
        Capability.VELOCITY_TIMESTAMPS,
        Capability.MARKDOWN_BODY,
        Capability.CLOSED_STATE,
        Capability.MCP_TIER,
        Capability.SUB_ISSUES,
    }
)


class KanbanFlowClientLike(Protocol):
    """The exact KanbanFlowClient surface KanbanFlowProvider depends on.

    A consumer-owned structural interface (interface segregation): the real
    KanbanFlowClient and the test FakeKanbanFlowClient both satisfy it without a
    nominal base class, so the provider type-checks under `mypy --strict` whether
    constructed with the production client or the in-memory fake. Declares only
    the ~11 methods the provider actually calls.
    """

    def get_board(self) -> KfBoard: ...
    def list_custom_field_defs(self) -> list[KfCustomFieldDef]: ...
    def iter_all_tasks(self) -> list[KfTask]: ...
    def get_board_events(
        self,
        *,
        from_ts: str | None = None,
        to_ts: str | None = None,
        limit: int = 100,
        order: str = "descending",
    ) -> list[KfEvent]: ...
    def get_task(self, task_id: str) -> KfTask: ...
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
    ) -> KfTask: ...
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
    ) -> KfTask: ...
    def delete_task(self, task_id: str) -> None: ...
    def set_task_custom_field(
        self, task_id: str, custom_field_id: str, value: str | float
    ) -> None: ...
    def add_comment(self, task_id: str, text: str) -> str: ...
    def list_users(self) -> list[KfUser]: ...
    def list_comments(self, task_id: str) -> list[KfComment]: ...
    def add_label(self, task_id: str, name: str) -> None: ...
    def remove_label(self, task_id: str, name: str) -> None: ...


class KanbanFlowProvider:
    _CAPABILITIES = frozenset(Capability) - _OMITTED_CAPABILITIES  # == {MILESTONE_ASSIGNMENT}

    def __init__(
        self,
        *,
        client: KanbanFlowClientLike,
        board: KfBoard,
        field_defs: list[KfCustomFieldDef],
        index: KfNumberIndex,
        status_column_map: dict[str, str] | None = None,
        expected_board_id: str | None = None,
    ) -> None:
        self._client = client
        self._board = board
        self._index = index
        self._status_column_map = status_column_map or {}
        # Raw board column maps — kept only for the "available columns" error message.
        self._column_id_by_name = {c.name: c.unique_id for c in board.columns}
        # Status-keyed maps — every Status<->column translation goes through these,
        # so a renamed column (e.g. Done<-"Complete") stays correct on read AND write.
        self._column_id_by_status: dict[str, str] = {}
        self._status_by_column_id: dict[str, str] = {}
        for status in _CANONICAL_STATUSES:
            col_name = self._status_column_map.get(status, status)  # identity fallback
            col_id = self._column_id_by_name.get(col_name)
            if col_id is not None:
                self._column_id_by_status[status] = col_id
                self._status_by_column_id[col_id] = status
        self._swimlane_id_by_name = {s.name: s.unique_id for s in board.swimlanes}
        self._swimlane_name_by_id = {s.unique_id: s.name for s in board.swimlanes}
        self._field_def_by_name = {d.name: d for d in field_defs}
        self._field_name_by_id = {d.id: d.name for d in field_defs}
        if expected_board_id is not None and board.id != expected_board_id:
            print(
                f"WARNING: KanbanFlow token points at board '{board.id}' but the doc "
                f"records '{expected_board_id}'. Operating on '{board.id}'.",
                file=sys.stderr,
            )

    # --- introspection ---
    @classmethod
    def default_capabilities(cls) -> frozenset[Capability]:
        """The backend's static capability set, resolved without an instance."""
        return cls._CAPABILITIES

    def capabilities(self) -> frozenset[Capability]:
        return self._CAPABILITIES

    # --- private resolution helpers ---
    def _column_id(self, status: str) -> str:
        if status not in self._column_id_by_status:
            available = ", ".join(sorted(self._column_id_by_name)) or "(none)"
            raise FieldNotFound(
                f"Status column for '{status}' not on the board. Available columns: {available}"
            )
        return self._column_id_by_status[status]

    def _swimlane_id(self, name: str) -> str:
        if name not in self._swimlane_id_by_name:
            available = ", ".join(sorted(self._swimlane_id_by_name)) or "(none)"
            raise FieldNotFound(
                f"Milestone (swimlane) '{name}' not on the board. Available: {available}"
            )
        return self._swimlane_id_by_name[name]

    def _field_def(self, name: str) -> KfCustomFieldDef:
        if name not in self._field_def_by_name:
            available = ", ".join(sorted(self._field_def_by_name)) or "(none)"
            raise FieldNotFound(f"Field '{name}' not on the board. Available: {available}")
        return self._field_def_by_name[name]

    def _check_option(self, field_name: str, value: str) -> KfCustomFieldDef:
        definition = self._field_def(field_name)
        if value not in definition.dropdown_options:
            available = ", ".join(definition.dropdown_options) or "(none)"
            raise OptionNotFound(
                f"Option '{value}' not valid for field '{field_name}'. Available: {available}"
            )
        return definition

    @staticmethod
    def _parse_blocked_by(label_names: list[str]) -> list[int]:
        out: list[int] = []
        for name in label_names:
            if name.startswith(_BLOCKED_BY_PREFIX):
                with contextlib.suppress(ValueError):
                    out.append(int(name[len(_BLOCKED_BY_PREFIX) :]))
        return out

    def _item_from_task(self, task: KfTask) -> BoardItem:
        label_names = [label.name for label in task.labels]
        priority: str | None = None
        fields: dict[str, str] = {}
        for cf in task.custom_fields:
            field_name = self._field_name_by_id.get(cf.custom_field_id)
            if field_name is None:
                continue
            if field_name == "Priority":
                priority = str(cf.value)
            else:
                fields[field_name] = str(cf.value)
        # A task in an unmapped column has no canonical Status -> None (by design:
        # such columns are intentionally invisible to jared; bootstrap warns about them).
        return BoardItem(
            number=task.number_value or 0,
            title=task.name,
            status=self._status_by_column_id.get(task.column_id) if task.column_id else None,
            priority=priority,
            body=task.description,
            labels=[n for n in label_names if not n.startswith(_BLOCKED_BY_PREFIX)],
            milestone=self._swimlane_name_by_id.get(task.swimlane_id) if task.swimlane_id else None,
            blocked_by=sorted(self._parse_blocked_by(label_names)),
            assignee=task.responsible_user_id,
            fields=fields,
            provider_ref=task.id,
        )

    # --- index plumbing ---
    def _reseed_index(self) -> None:
        """Rebuild the number -> task_id map from a full board scan.

        Collisions are surfaced rather than swallowed (F3, #371). This was a
        plain dict comprehension keyed by `number_value`, so when two live
        tasks shared a jared #N one `_id` was silently and permanently
        dropped — which made `kf_number_index.py`'s own recovery claim
        ("a reseed scan + manual renumber repairs it") false: nothing ever
        told the operator there was a collision to renumber.

        The surviving id for a collided number is the lexicographically first
        one, so #N resolves to the same task on every reseed. Iteration order
        previously decided it, so the answer could change run to run.

        `replace()` overwrites the map wholesale, which is safe because
        `iter_all_tasks()` walks every column and `list_tasks` follows the
        `tasksLimited`/`nextTaskId` cursor to exhaustion — the scan is a
        complete superset of the board, so the only entries dropped are ones
        whose task no longer exists.
        """
        by_number: dict[int, list[str]] = {}
        for task in self._client.iter_all_tasks():
            if task.number_value is not None:
                by_number.setdefault(task.number_value, []).append(task.id)

        for number, ids in sorted(by_number.items()):
            if len(ids) > 1:
                ordered = sorted(ids)
                print(
                    f"WARNING: #{number} maps to {len(ordered)} tasks on this "
                    f"KanbanFlow board: {', '.join(ordered)}. jared will resolve "
                    f"#{number} to {ordered[0]}; the rest are unreachable by number "
                    f"until you renumber them in KanbanFlow.",
                    file=sys.stderr,
                )

        self._index.replace({number: sorted(ids)[0] for number, ids in by_number.items()})

    def _resolve_task(self, ref: IssueRef) -> KfTask:
        """Resolve #`ref` to a live task, or raise `ItemNotFound` (#385, F70).

        This is the one seam where a jared #N becomes a KanbanFlow `_id`, so it
        is the one place the on-disk index can be checked against the board.
        Three staleness shapes get the same single reseed-and-retry:

        * **miss** — no entry for `ref` (the original `_resolve_id` behavior),
        * **dangling** — the entry's task was deleted, so the fetch 404s,
        * **stale hit** — the entry's task was renumbered in the KanbanFlow UI,
          so it resolves fine but is no longer #`ref`.

        Only the first was handled before. `_resolve_id` returned the index hit
        without fetching, so a renumbered task silently absorbed every write
        aimed at its old number — `move`, `set_field`, `close`, `comment`,
        `add_blocked_by`, `set_milestone` and the rest of the 13 call sites.
        #371 (F3) fixed the same shape in `get_item` for free, because a read
        already had the task in hand; the write path is the residual it left.

        **Cost.** One `GET /tasks/<id>` per resolution. That is the deliberate
        price of Option 1 in #385: the write path had no fetch to reuse, so
        correctness here is not free. Returning the *task* rather than the id
        keeps the callers that do read it — `get_item`, `get_body` — flat
        instead of doubling them; `_resolve_id` is the thin wrapper for the
        write path, which needs only the id.
        """
        for attempt in (0, 1):
            task_id = self._index.get(ref)
            if task_id is None:
                if attempt == 0:
                    self._reseed_index()
                    continue
                break
            try:
                task = self._client.get_task(task_id)
            except KanbanFlowNotFoundError:
                if attempt == 0:
                    self._reseed_index()
                    continue
                break
            if task.number_value != ref:
                if attempt == 0:
                    self._reseed_index()
                    continue
                break
            return task
        raise ItemNotFound(f"#{ref} not found on the KanbanFlow board")

    def _resolve_id(self, ref: IssueRef) -> str:
        """The write path's view of `_resolve_task` — a validated task `_id`."""
        return self._resolve_task(ref).id

    def _set_custom_field(self, field_name: str, value: str, task_id: str) -> None:
        definition = self._check_option(field_name, value)
        self._client.set_task_custom_field(task_id, definition.id, value)

    # --- reads ---
    def get_item(self, ref: IssueRef) -> BoardItem | None:
        """Read #`ref`, or `None` when it does not resolve.

        The staleness handling lives in `_resolve_task` (F3 #371, F70 #385),
        which every other ref-taking method shares. This method only converts
        that seam's `ItemNotFound` into the `None` the BoardProvider contract
        asks for on a read. The retry loop used to be duplicated here, which is
        how the write path came to be missing it.
        """
        try:
            return self._item_from_task(self._resolve_task(ref))
        except ItemNotFound:
            return None

    def list_open_items(self) -> list[BoardItem]:
        done_id = self._column_id_by_status.get("Done")
        # Skip un-numbered tasks (e.g. created in the KF UI without a jared
        # number): they have no stable #N handle, so they're already invisible
        # to ref-resolution and edge-building (_reseed_index,
        # fetch_blocked_by_edges). Surfacing them here would manufacture a bogus
        # #0 and collapse distinct tasks to the same ref.
        return [
            self._item_from_task(t)
            for t in self._client.iter_all_tasks()
            if t.column_id != done_id and t.number_value is not None
        ]

    def get_body(self, ref: IssueRef) -> str:
        # _resolve_task, not _resolve_id + get_task: the seam already fetched
        # the task to validate it, so reading the body off it costs nothing.
        return self._resolve_task(ref).description

    def fetch_blocked_by_edges(self) -> list[Edge]:
        edges: list[Edge] = []
        for task in self._client.iter_all_tasks():
            if task.number_value is None:
                continue
            for blocker in self._parse_blocked_by([label.name for label in task.labels]):
                edges.append(Edge(dependent=task.number_value, blocker=blocker))
        return edges

    def recently_closed(self, *, days: int) -> list[ClosedItem]:
        """Closed items = tasks whose most recent move INTO the Done column
        falls within the `days` window.

        Scans GET /board/events (descending) for changedProperties columnId
        transitions whose newValue is the Done column (resolved via the Status
        column map). Each task's most-recent move-into-Done maps to a ClosedItem;
        the task's number/title come from the live task set, so a deleted task
        (history outlives the task) is skipped.

        Asymmetry vs GitHub: GitHub's recently_closed reflects CURRENT closed
        state, so a reopened issue drops out. This KanbanFlow version keys off the
        move-into-Done event and does NOT check for a later move back out — a task
        moved to Done then reopened still appears (with its Done timestamp). That
        is acceptable for velocity / recently-closed surfaces, which care about
        the close event, not current state.

        No truncation guard: get_board_events pages up to max_pages*limit events;
        a window exceeding that silently truncates (the GitHub sibling raises at
        its 200-item cap). Acceptable while no caller drives large windows on
        KanbanFlow; revisit if a high-traffic board surfaces.
        """
        done_col_id = self._column_id_by_status.get("Done")
        if done_col_id is None:
            return []
        cutoff = (datetime.now(UTC) - timedelta(days=days)).isoformat().replace("+00:00", "Z")
        events = self._client.get_board_events(from_ts=cutoff, order="descending", limit=100)
        task_by_id = {t.id: t for t in self._client.iter_all_tasks()}
        seen: set[str] = set()
        out: list[ClosedItem] = []
        for ev in events:  # descending → first move-into-Done per task is the most recent
            if ev.timestamp and ev.timestamp < cutoff:
                continue
            for de in ev.detailed_events:
                tid = de.task_id
                if not tid or tid in seen:
                    continue
                moved_to_done = any(
                    cp.property == "columnId" and cp.new_value == done_col_id
                    for cp in de.changed_properties
                )
                if not moved_to_done:
                    continue
                task = task_by_id.get(tid)
                if task is not None and task.number_value is not None:
                    out.append(
                        ClosedItem(
                            number=task.number_value,
                            title=task.name,
                            closed_at=ev.timestamp,
                        )
                    )
                seen.add(tid)
        return out

    def _user_name(self, user_id: str) -> str:
        """Resolve a KF user id to a display name, or "" if unknown.

        The "" fallback is the `Comment.author` contract, not a convenience:
        returning the id itself would put a provider-internal `_id` on the
        neutral side of the seam, which is the one thing it exists to prevent.
        Unknown ids are ordinary — a removed board member still owns comments
        (#414).
        """
        if not hasattr(self, "_user_name_by_id"):
            self._user_name_by_id: dict[str, str] = {
                u.id: u.name for u in self._client.list_users()
            }
        return self._user_name_by_id.get(user_id, "")

    def list_comments(self, ref: IssueRef) -> list[Comment]:
        """Return a task's comments oldest→newest as neutral Comments.

        Wraps the client's list_comments; resolves KF authorUserId to a display
        name (lazily, one /users fetch per provider instance). An id that is
        absent from /users resolves to "", per the Comment.author contract.
        """
        task_id = self._resolve_id(ref)
        return [
            Comment(
                author=self._user_name(c.author_user_id) if c.author_user_id else "",
                body=c.text,
                created_at=c.created_timestamp,
            )
            for c in self._client.list_comments(task_id)
        ]

    def list_comments_batch(self, refs: list[IssueRef]) -> dict[IssueRef, list[Comment]]:
        """Return `{ref: comments}` for many tasks, looping over list_comments.

        KanbanFlow has no aliased-batch endpoint, so this is N calls where the
        GitHub provider makes one. Acceptable: the only caller is
        `next-session-prompt`, whose N is the In Progress column bounded by the
        WIP cap (~4). No `gh` is involved on this path (#395).
        """
        return {ref: self.list_comments(ref) for ref in refs}

    # --- writes ---
    def validate_fields(
        self,
        *,
        priority: str,
        status: str,
        fields: list[tuple[str, str]] | None = None,
    ) -> None:
        """Fail-before-mutate fence: resolve Status column + Priority option +
        extra field options, raising FieldNotFound/OptionNotFound on any miss."""
        self._column_id(status)
        self._check_option("Priority", priority)
        for name, value in fields or []:
            self._check_option(name, value)

    def _next_number(self) -> int:
        """Allocate the next free #N from a live board scan (F3, #371).

        Reseeds unconditionally. The previous `_ensure_seeded()` rebuilt only
        when the index was *empty*, so a non-empty but stale index — a task
        numbered outside jared's knowledge, a concurrent `jared file` — handed
        out a number already in use. Costs one board scan per `file()` call,
        which is the right trade for never issuing a colliding number.
        """
        self._reseed_index()
        return self._index.max_number() + 1

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
        effective_status = status or "Backlog"
        self.validate_fields(priority=priority, status=effective_status, fields=fields)
        column_id = self._column_id(effective_status)
        swimlane_id = self._swimlane_id(milestone) if milestone else None
        number = number if number is not None else self._next_number()
        kf_labels = [KfLabel(name=n) for n in (labels or [])]
        task = self._client.create_task(
            name=title,
            column_id=column_id,
            number_value=number,
            swimlane_id=swimlane_id,
            description=body,
            labels=kf_labels or None,
        )
        try:
            self._set_custom_field("Priority", priority, task.id)
            for name, value in fields or []:
                self._set_custom_field(name, value, task.id)
        except Exception:
            with contextlib.suppress(Exception):
                self._client.delete_task(task.id)
            raise
        self._index.put(number, task.id)
        return self._item_from_task(self._client.get_task(task.id))

    def add_to_board(
        self,
        ref: IssueRef,
        *,
        priority: str,
        status: str,
        labels: list[str] | None = None,
        fields: list[tuple[str, str]] | None = None,
    ) -> None:
        task_id = self._resolve_id(ref)
        self.validate_fields(priority=priority, status=status, fields=fields)
        self._client.update_task(task_id, column_id=self._column_id(status))
        self._set_custom_field("Priority", priority, task_id)
        for name, value in fields or []:
            self._set_custom_field(name, value, task_id)
        for name in labels or []:
            self._client.add_label(task_id, name)

    def set_field(self, ref: IssueRef, field_name: str, value: str) -> None:
        # Status is a structural column on KanbanFlow, not a custom field. The
        # CLI drives Status changes through set_field (`jared move` -> _cmd_set
        # -> set_field, and `jared set N Status`), mirroring the GitHub provider
        # where move() is itself set_field("Status"). Route Status to the column
        # move so both CLI paths work on this backend.
        if field_name == "Status":
            self.move(ref, value)
            return
        self._set_custom_field(field_name, value, self._resolve_id(ref))

    def move(self, ref: IssueRef, status: str) -> None:
        self._client.update_task(self._resolve_id(ref), column_id=self._column_id(status))

    def set_body(self, ref: IssueRef, text: str) -> None:
        self._client.update_task(self._resolve_id(ref), description=text)

    def comment(self, ref: IssueRef, body: str) -> str:
        return self._client.add_comment(self._resolve_id(ref), body)

    def close(self, ref: IssueRef, *, comment: str | None = None) -> None:
        task_id = self._resolve_id(ref)
        if comment:
            self._client.add_comment(task_id, comment)
        self._client.update_task(task_id, column_id=self._column_id("Done"))

    def add_label(self, ref: IssueRef, name: str) -> None:
        self._client.add_label(self._resolve_id(ref), name)

    def remove_label(self, ref: IssueRef, name: str) -> None:
        self._client.remove_label(self._resolve_id(ref), name)

    def add_blocked_by(self, ref: IssueRef, blocker: IssueRef) -> None:
        self._client.add_label(self._resolve_id(ref), f"{_BLOCKED_BY_PREFIX}{blocker}")

    def remove_blocked_by(self, ref: IssueRef, blocker: IssueRef) -> None:
        self._client.remove_label(self._resolve_id(ref), f"{_BLOCKED_BY_PREFIX}{blocker}")

    def set_milestone(self, ref: IssueRef, name: str) -> None:
        self._client.update_task(self._resolve_id(ref), swimlane_id=self._swimlane_id(name))

    def clear_milestone(self, ref: IssueRef) -> None:
        """Refuse: a KanbanFlow task always occupies a swimlane.

        Reachable via `jared set-milestone <N> --none` now that
        MILESTONE_ASSIGNMENT is advertised (#390). Explicit rather than a
        pass-through, because `update_task` treats `swimlane_id=None` as
        *leave unchanged*: delegating would POST an empty body and report
        success having changed nothing (verified against the fake client — it
        did not raise and the swimlane survived). A designated default
        swimlane would give "cleared" a meaning, but the acceptance criteria
        for #390 don't ask for one — that's discovered scope, not this fix.
        """
        raise FieldNotFound(
            f"cannot clear the milestone of #{ref}: a KanbanFlow task always "
            "occupies a swimlane, so there is no cleared state. Assign a "
            "different swimlane instead."
        )

    def list_milestones(self) -> list[Milestone]:
        return [
            Milestone(name=s.name, description=s.description, state=None, due=None)
            for s in self._board.swimlanes
        ]
