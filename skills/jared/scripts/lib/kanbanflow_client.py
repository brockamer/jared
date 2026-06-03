"""Wire-level KanbanFlow REST client (epic #313, Phase 2 / #315).

Pure transport: auth, quota policy, typed resources, error mapping. No semantic
board mapping — that is the KanbanFlowProvider's job (#316). Stdlib only.

All network I/O flows through the module-level `_raw_http` seam; `_sleep` and
`_now` are the other two seams. Tests monkeypatch these three. See the design
spec's Appendix B for the verified API surface.
"""

from __future__ import annotations

import contextlib
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any

# --------------------------------------------------------------------------- #
# Module-level seams (the only impure functions; monkeypatched in tests)      #
# --------------------------------------------------------------------------- #


def _raw_http(
    method: str, url: str, headers: dict[str, str], data: bytes | None
) -> tuple[int, dict[str, str], bytes]:
    """Perform one HTTP request. Returns (status, response_headers, body_bytes).

    Non-2xx responses (urllib raises HTTPError) are captured and returned like
    any other response, so `_request` maps them uniformly. Connection-level
    failures (URLError that is not HTTPError) propagate to the caller.
    """
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status, dict(resp.headers.items()), resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, dict(exc.headers.items()), exc.read()


def _sleep(seconds: float) -> None:
    time.sleep(seconds)


def _now() -> float:
    return time.time()


# --------------------------------------------------------------------------- #
# Typed exceptions                                                            #
# --------------------------------------------------------------------------- #


class KanbanFlowError(Exception):
    """Base for all client errors (also transport/JSON failures)."""


class KanbanFlowAuthError(KanbanFlowError):
    """401 — missing or invalid token."""


class KanbanFlowForbiddenError(KanbanFlowError):
    """403 — refused; validation failures surface here, not 400/422."""


class KanbanFlowNotFoundError(KanbanFlowError):
    """404 — resource not found."""


class KanbanFlowRateLimitError(KanbanFlowError):
    """429 or local budget exhaustion."""


class KanbanFlowServerError(KanbanFlowError):
    """500 — server error."""


_EXCEPTION_FOR_STATUS: dict[int, type[KanbanFlowError]] = {
    401: KanbanFlowAuthError,
    403: KanbanFlowForbiddenError,
    404: KanbanFlowNotFoundError,
    429: KanbanFlowRateLimitError,
    500: KanbanFlowServerError,
}


def _parse_error(body: bytes) -> str:
    """Extract the human message from {"errors":[{"message":"..."}]}."""
    try:
        payload = json.loads(body)
        errors = payload.get("errors") or []
        if errors and isinstance(errors, list):
            return str(errors[0].get("message", "")) or "unknown error"
    except (ValueError, AttributeError):
        pass
    return body.decode(errors="replace") or "unknown error"


# --------------------------------------------------------------------------- #
# KanbanFlow-internal dataclasses (carry KF _ids; no semantic mapping)        #
# --------------------------------------------------------------------------- #


@dataclass
class KfColumn:
    unique_id: str
    name: str
    description: str = ""


@dataclass
class KfSwimlane:
    unique_id: str
    name: str
    description: str = ""


@dataclass
class KfBoard:
    id: str
    name: str
    columns: list[KfColumn] = field(default_factory=list)
    swimlanes: list[KfSwimlane] = field(default_factory=list)


@dataclass
class KfCustomFieldDef:
    id: str
    name: str
    field_type: str
    dropdown_options: list[str] = field(default_factory=list)
    number_prefix: str | None = None


@dataclass
class KfLabel:
    name: str
    pinned: bool = False


@dataclass
class KfCustomFieldValue:
    custom_field_id: str
    value: str | float


@dataclass
class KfTask:
    id: str
    name: str
    description: str = ""
    color: str | None = None
    column_id: str | None = None
    swimlane_id: str | None = None
    position: int | None = None
    number_value: int | None = None
    number_prefix: str | None = None
    responsible_user_id: str | None = None
    collaborators: list[str] = field(default_factory=list)
    labels: list[KfLabel] = field(default_factory=list)
    custom_fields: list[KfCustomFieldValue] = field(default_factory=list)


@dataclass
class KfComment:
    id: str
    text: str
    created_timestamp: str
    author_user_id: str = ""


@dataclass
class KfRelation:
    relation_type: str
    related_task_id: str
    related_task_name: str = ""
    related_task_board_id: str | None = None


@dataclass
class KfUser:
    id: str
    name: str = ""


def _parse_label(raw: dict[str, Any]) -> KfLabel:
    return KfLabel(name=str(raw["name"]), pinned=bool(raw.get("pinned", False)))


def _parse_custom_field_value(raw: dict[str, Any]) -> KfCustomFieldValue:
    value_obj: dict[str, Any] = raw.get("value") or {}
    raw_value = value_obj.get("text", value_obj.get("number"))
    value: str | float = raw_value if raw_value is not None else ""
    return KfCustomFieldValue(custom_field_id=str(raw["customFieldId"]), value=value)


def _parse_task(raw: dict[str, Any]) -> KfTask:
    number: dict[str, Any] = raw.get("number") or {}
    return KfTask(
        id=str(raw["_id"]),
        name=str(raw.get("name", "")),
        description=str(raw.get("description", "")),
        color=str(raw["color"]) if raw.get("color") is not None else None,
        column_id=str(raw["columnId"]) if raw.get("columnId") is not None else None,
        swimlane_id=str(raw["swimlaneId"]) if raw.get("swimlaneId") is not None else None,
        position=int(raw["position"]) if raw.get("position") is not None else None,
        number_value=int(number["value"]) if number.get("value") is not None else None,
        number_prefix=str(number["prefix"]) if number.get("prefix") is not None else None,
        responsible_user_id=(
            str(raw["responsibleUserId"]) if raw.get("responsibleUserId") is not None else None
        ),
        collaborators=[str(c["userId"]) for c in raw.get("collaborators", [])],
        labels=[_parse_label(label) for label in raw.get("labels", [])],
        custom_fields=[_parse_custom_field_value(cf) for cf in raw.get("customFields", [])],
    )


def _parse_board(raw: dict[str, Any]) -> KfBoard:
    return KfBoard(
        id=str(raw["_id"]),
        name=str(raw.get("name", "")),
        columns=[
            KfColumn(
                unique_id=str(c["uniqueId"]),
                name=str(c.get("name", "")),
                description=str(c.get("description", "")),
            )
            for c in raw.get("columns", [])
        ],
        swimlanes=[
            KfSwimlane(
                unique_id=str(s["uniqueId"]),
                name=str(s.get("name", "")),
                description=str(s.get("description", "")),
            )
            for s in raw.get("swimlanes", [])
        ],
    )


def _parse_custom_field_def(raw: dict[str, Any]) -> KfCustomFieldDef:
    ns: dict[str, Any] = raw.get("numberSettings") or {}
    return KfCustomFieldDef(
        id=str(raw["_id"]),
        name=str(raw.get("name", "")),
        field_type=str(raw.get("fieldType", "")),
        dropdown_options=[str(o["text"]) for o in raw.get("dropdownOptions", [])],
        number_prefix=str(ns["prefix"]) if ns.get("prefix") is not None else None,
    )


def _parse_comment(raw: dict[str, Any]) -> KfComment:
    return KfComment(
        id=str(raw["_id"]),
        text=str(raw.get("text", "")),
        created_timestamp=str(raw.get("createdTimestamp", "")),
        author_user_id=str(raw.get("authorUserId", "")),
    )


def _parse_relation(raw: dict[str, Any]) -> KfRelation:
    return KfRelation(
        relation_type=str(raw.get("relationType", "")),
        related_task_id=str(raw.get("relatedTaskId", "")),
        related_task_name=str(raw.get("relatedTaskName", "")),
        related_task_board_id=(
            str(raw["relatedTaskBoardId"]) if raw.get("relatedTaskBoardId") is not None else None
        ),
    )


def _parse_user(raw: dict[str, Any]) -> KfUser:
    return KfUser(id=str(raw["_id"]), name=str(raw.get("name", "")))


class KanbanFlowClient:
    """Typed, quota-aware KanbanFlow REST client."""

    def __init__(
        self,
        token: str,
        base_url: str = "https://kanbanflow.com/api/v1",
        *,
        request_floor: int = 50,
        daily_ceiling: int = 4000,
        max_retries: int = 3,
    ) -> None:
        self._token = token
        self._base_url = base_url.rstrip("/")
        self._request_floor = request_floor
        self._daily_ceiling = daily_ceiling
        self._max_retries = max_retries
        # quota state, updated from response headers
        self._remaining: int | None = None
        self._reset: int | None = None
        self._daily_count = 0
        self._cache: dict[str, object] = {}

    @classmethod
    def from_env(cls, **kwargs: object) -> KanbanFlowClient:
        token = os.environ.get("KANBANFLOW_API_TOKEN")
        if not token:
            raise KanbanFlowError(
                "KANBANFLOW_API_TOKEN is not set. Create an API token in a premium "
                "KanbanFlow board (Settings -> API & Webhooks) and export it as "
                "KANBANFLOW_API_TOKEN."
            )
        return cls(token, **kwargs)  # type: ignore[arg-type]

    def _build_url(self, path: str, params: dict[str, object] | None) -> str:
        url = f"{self._base_url}/{path.lstrip('/')}"
        if params:
            clean = {k: str(v) for k, v in params.items() if v is not None}
            if clean:
                url = f"{url}?{urllib.parse.urlencode(clean)}"
        return url

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, object] | None = None,
        body: dict[str, object] | None = None,
    ) -> object:
        for attempt in range(self._max_retries + 1):
            self._budget_gate()
            url = self._build_url(path, params)
            headers = {"Authorization": f"Bearer {self._token}"}
            data: bytes | None = None
            if body is not None:
                data = json.dumps(body).encode()
                headers["Content-Type"] = "application/json"
            try:
                status, resp_headers, resp_body = _raw_http(method, url, headers, data)
            except urllib.error.URLError as exc:
                if attempt < self._max_retries:
                    _sleep(self._backoff(attempt))
                    continue
                raise KanbanFlowError(f"transport error: {exc}") from exc

            self._record_quota(resp_headers)

            if 200 <= status < 300:
                if not resp_body:
                    return None
                try:
                    return json.loads(resp_body)
                except ValueError as exc:
                    raise KanbanFlowError(f"invalid JSON in response body: {exc}") from exc

            message = _parse_error(resp_body)
            if status == 429 and attempt < self._max_retries:
                _sleep(self._retry_delay(resp_headers))
                continue
            if status >= 500 and attempt < self._max_retries:
                _sleep(self._backoff(attempt))
                continue
            raise _EXCEPTION_FOR_STATUS.get(status, KanbanFlowError)(message)

        raise KanbanFlowRateLimitError("request retries exhausted")

    def _cached_get(self, key: str, path: str) -> object:
        if os.environ.get("JARED_NO_CACHE") != "1" and key in self._cache:
            return self._cache[key]
        raw = self._request("GET", path)
        self._cache[key] = raw
        return raw

    def get_board(self) -> KfBoard:
        return _parse_board(self._cached_get("board", "/board"))  # type: ignore[arg-type]

    def list_custom_field_defs(self) -> list[KfCustomFieldDef]:
        raw = self._cached_get("custom-fields", "/custom-fields")
        return [_parse_custom_field_def(d) for d in raw]  # type: ignore[attr-defined]

    def list_users(self) -> list[KfUser]:
        raw = self._cached_get("users", "/users")
        return [_parse_user(u) for u in raw]  # type: ignore[attr-defined]

    def list_tasks(
        self,
        *,
        column_id: str | None = None,
        column_name: str | None = None,
        swimlane_id: str | None = None,
        limit: int | None = None,
        start_task_id: str | None = None,
        order: str | None = None,
    ) -> list[KfTask]:
        params: dict[str, object] = {
            "columnId": column_id,
            "columnName": column_name,
            "swimlaneId": swimlane_id,
            "limit": limit,
            "order": order,
        }
        tasks: list[KfTask] = []
        cursor = start_task_id
        while True:
            params["startTaskId"] = cursor
            groups: Any = self._request("GET", "/tasks", params=params)
            next_cursor: str | None = None
            for group in groups or []:
                for raw in group.get("tasks", []):
                    tasks.append(_parse_task(raw))
                if group.get("tasksLimited") and group.get("nextTaskId"):
                    next_cursor = group["nextTaskId"]
            if not next_cursor:
                break
            cursor = next_cursor
        return tasks

    def iter_all_tasks(self) -> list[KfTask]:
        board = self.get_board()
        tasks: list[KfTask] = []
        for column in board.columns:
            tasks.extend(self.list_tasks(column_id=column.unique_id))
        return tasks

    def get_task(self, task_id: str) -> KfTask:
        raw = self._request("GET", f"/tasks/{task_id}")
        return _parse_task(raw)  # type: ignore[arg-type]

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
        body: dict[str, object] = {
            "name": name,
            "columnId": column_id,
            "number": {"value": number_value},
        }
        if swimlane_id is not None:
            body["swimlaneId"] = swimlane_id
        if description is not None:
            body["description"] = description
        if color is not None:
            body["color"] = color
        if responsible_user_id is not None:
            body["responsibleUserId"] = responsible_user_id
        if labels:
            body["labels"] = [{"name": label.name, "pinned": label.pinned} for label in labels]
        raw = self._request("POST", "/tasks", body=body)
        return _parse_task(raw)  # type: ignore[arg-type]

    def update_task(
        self,
        task_id: str,
        *,
        name: str | None = None,
        column_id: str | None = None,
        number_value: int | None = None,
        description: str | None = None,
        color: str | None = None,
        responsible_user_id: str | None = None,
    ) -> KfTask:
        body: dict[str, object] = {}
        if name is not None:
            body["name"] = name
        if column_id is not None:
            body["columnId"] = column_id
        if number_value is not None:
            body["number"] = {"value": number_value}
        if description is not None:
            body["description"] = description
        if color is not None:
            body["color"] = color
        if responsible_user_id is not None:
            body["responsibleUserId"] = responsible_user_id
        raw = self._request("POST", f"/tasks/{task_id}", body=body)
        return _parse_task(raw)  # type: ignore[arg-type]

    def delete_task(self, task_id: str) -> None:
        self._request("DELETE", f"/tasks/{task_id}")

    def get_task_custom_fields(self, task_id: str) -> list[KfCustomFieldValue]:
        raw = self._request("GET", f"/tasks/{task_id}/custom-fields")
        return [_parse_custom_field_value(cf) for cf in raw]  # type: ignore[attr-defined]

    def set_task_custom_field(self, task_id: str, custom_field_id: str, value: str | float) -> None:
        key = (
            "number" if isinstance(value, (int, float)) and not isinstance(value, bool) else "text"
        )
        self._request(
            "POST",
            f"/tasks/{task_id}/custom-fields/{custom_field_id}",
            body={"value": {key: value}},
        )

    def list_comments(self, task_id: str) -> list[KfComment]:
        raw = self._request("GET", f"/tasks/{task_id}/comments")
        return [_parse_comment(c) for c in raw]  # type: ignore[attr-defined]

    def add_comment(
        self,
        task_id: str,
        text: str,
        *,
        created_timestamp: str | None = None,
        author_user_id: str | None = None,
    ) -> str:
        body: dict[str, object] = {"text": text}
        if created_timestamp is not None:
            body["createdTimestamp"] = created_timestamp
        if author_user_id is not None:
            body["authorUserId"] = author_user_id
        raw = self._request("POST", f"/tasks/{task_id}/comments", body=body)
        return str(raw.get("taskCommentId", ""))  # type: ignore[attr-defined]

    def list_labels(self, task_id: str) -> list[KfLabel]:
        raw = self._request("GET", f"/tasks/{task_id}/labels")
        return [_parse_label(label) for label in raw]  # type: ignore[attr-defined]

    def add_label(self, task_id: str, name: str, *, pinned: bool = False) -> None:
        self._request("POST", f"/tasks/{task_id}/labels", body={"name": name, "pinned": pinned})

    def remove_label(self, task_id: str, name: str) -> None:
        encoded = urllib.parse.quote(name, safe="")
        self._request("DELETE", f"/tasks/{task_id}/labels/by-name/{encoded}")

    def get_relations(self, task_id: str) -> list[KfRelation]:
        raw = self._request("GET", f"/tasks/{task_id}/relations")
        return [_parse_relation(r) for r in raw]  # type: ignore[attr-defined]

    def _budget_gate(self) -> None:
        if self._daily_count >= self._daily_ceiling:
            raise KanbanFlowRateLimitError(
                f"daily request ceiling ({self._daily_ceiling}) reached; refusing to "
                "risk a KanbanFlow token lock (5000/day)"
            )
        if (
            self._remaining is not None
            and self._remaining <= self._request_floor
            and self._reset is not None
        ):
            wait = self._reset - _now()
            if wait > 0:
                _sleep(wait)
        self._daily_count += 1

    def _record_quota(self, headers: dict[str, str]) -> None:
        rem = headers.get("X-RateLimit-Remaining")
        rst = headers.get("X-RateLimit-Reset")
        if rem is not None:
            with contextlib.suppress(ValueError):
                self._remaining = int(rem)
        if rst is not None:
            with contextlib.suppress(ValueError):
                self._reset = int(rst)

    def _retry_delay(self, headers: dict[str, str]) -> float:
        rst = headers.get("X-RateLimit-Reset")
        if rst is not None:
            try:
                wait = int(rst) - _now()
                return float(min(max(wait, 0.0), 60.0))
            except ValueError:
                pass
        return 1.0

    def _backoff(self, attempt: int) -> float:
        return float(min(2**attempt, 30))
