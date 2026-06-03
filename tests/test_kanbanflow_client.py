from __future__ import annotations

import json
from typing import cast

import pytest

import skills.jared.scripts.lib.kanbanflow_client as kf
from skills.jared.scripts.lib.kanbanflow_client import (
    KanbanFlowAuthError,
    KanbanFlowClient,
    KanbanFlowError,
    KanbanFlowForbiddenError,
    KanbanFlowNotFoundError,
    KanbanFlowRateLimitError,
    KanbanFlowServerError,
    KfComment,
    KfCustomFieldValue,
    KfLabel,
    KfRelation,
    KfTask,
    _parse_task,
)
from tests.conftest import patch_kf


def _client() -> KanbanFlowClient:
    return KanbanFlowClient(token="tok", base_url="https://kanbanflow.com/api/v1")


def test_request_sends_bearer_header_and_returns_parsed_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = patch_kf(monkeypatch, status=200, body=json.dumps({"_id": "B1", "name": "Board"}))
    result = _client()._request("GET", "/board")
    assert result == {"_id": "B1", "name": "Board"}
    hdrs = cast(dict[str, str], calls[0]["headers"])
    assert hdrs["Authorization"] == "Bearer tok"
    assert calls[0]["url"] == "https://kanbanflow.com/api/v1/board"
    assert calls[0]["method"] == "GET"


@pytest.mark.parametrize(
    "status,exc",
    [
        (401, KanbanFlowAuthError),
        (403, KanbanFlowForbiddenError),
        (404, KanbanFlowNotFoundError),
        (500, KanbanFlowServerError),
    ],
)
def test_request_maps_status_to_typed_exception_with_message(
    monkeypatch: pytest.MonkeyPatch, status: int, exc: type[KanbanFlowError]
) -> None:
    patch_kf(monkeypatch, status=status, body=json.dumps({"errors": [{"message": "boom"}]}))
    with pytest.raises(exc, match="boom"):
        _client()._request("GET", "/board")


def test_from_env_reads_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KANBANFLOW_API_TOKEN", "envtok")
    client = KanbanFlowClient.from_env()
    calls = patch_kf(monkeypatch, body="{}")
    client._request("GET", "/board")
    assert cast(dict[str, str], calls[0]["headers"])["Authorization"] == "Bearer envtok"


def test_from_env_raises_clear_error_when_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("KANBANFLOW_API_TOKEN", raising=False)
    with pytest.raises(KanbanFlowError, match="KANBANFLOW_API_TOKEN"):
        KanbanFlowClient.from_env()


def test_proactive_gate_sleeps_until_reset_when_remaining_low(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sleeps: list[float] = []
    monkeypatch.setattr(kf, "_sleep", lambda s: sleeps.append(s))
    monkeypatch.setattr(kf, "_now", lambda: 1_000_000)
    monkeypatch.setattr(kf, "_raw_http", lambda m, u, h, d: (200, {}, b"{}"))
    client = _client()
    client._remaining = 5  # below the default floor of 50
    client._reset = 1_000_030  # 30s in the future
    client._request("GET", "/board")
    assert sleeps == [30]


def test_daily_ceiling_refuses_before_lock(monkeypatch: pytest.MonkeyPatch) -> None:
    patch_kf(monkeypatch, body="{}")
    client = KanbanFlowClient(token="t", daily_ceiling=2)
    client._request("GET", "/board")
    client._request("GET", "/board")
    with pytest.raises(KanbanFlowRateLimitError, match="daily request ceiling"):
        client._request("GET", "/board")


def test_429_then_success_retries_off_reset(monkeypatch: pytest.MonkeyPatch) -> None:
    seq = [
        (429, {"X-RateLimit-Reset": "1000010"}, b'{"errors":[{"message":"slow down"}]}'),
        (200, {}, b'{"ok": true}'),
    ]
    monkeypatch.setattr(kf, "_now", lambda: 1_000_000)
    sleeps: list[float] = []
    monkeypatch.setattr(kf, "_sleep", lambda s: sleeps.append(s))
    monkeypatch.setattr(kf, "_raw_http", lambda m, u, h, d: seq.pop(0))
    result = _client()._request("GET", "/board")
    assert result == {"ok": True}
    assert sleeps == [10]


def test_parse_task_maps_all_fields() -> None:
    raw = {
        "_id": "T1",
        "name": "Do thing",
        "description": "body",
        "color": "red",
        "columnId": "C1",
        "swimlaneId": "S1",
        "position": 0,
        "number": {"value": 42, "prefix": "BUG-"},
        "responsibleUserId": "U1",
        "collaborators": [{"userId": "U2"}, {"userId": "U3"}],
        "labels": [{"name": "Priority", "pinned": True}],
        "customFields": [{"customFieldId": "F1", "value": {"text": "High"}}],
    }
    task = _parse_task(raw)
    assert isinstance(task, KfTask)
    assert task.id == "T1"
    assert task.number_value == 42
    assert task.number_prefix == "BUG-"
    assert task.column_id == "C1"
    assert task.responsible_user_id == "U1"
    assert task.collaborators == ["U2", "U3"]
    assert task.labels == [KfLabel(name="Priority", pinned=True)]
    assert task.custom_fields == [KfCustomFieldValue(custom_field_id="F1", value="High")]


def test_parse_task_handles_missing_optional_arrays() -> None:
    task = _parse_task({"_id": "T2", "name": "Bare", "columnId": "C1"})
    assert task.number_value is None
    assert task.labels == []
    assert task.collaborators == []
    assert task.custom_fields == []


def test_get_board_parses_structure(monkeypatch: pytest.MonkeyPatch) -> None:
    patch_kf(
        monkeypatch,
        body=json.dumps(
            {
                "_id": "B1",
                "name": "Board",
                "columns": [{"uniqueId": "C1", "name": "To-do"}],
                "swimlanes": [{"uniqueId": "S1", "name": "Team A", "description": "d"}],
            }
        ),
    )
    board = _client().get_board()
    assert board.id == "B1"
    assert board.columns[0].unique_id == "C1"
    assert board.swimlanes[0].description == "d"


def test_get_board_is_cached(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = patch_kf(monkeypatch, body=json.dumps({"_id": "B1", "name": "B"}))
    client = _client()
    client.get_board()
    client.get_board()
    board_calls = [c for c in calls if str(c["url"]).endswith("/board")]
    assert len(board_calls) == 1, "second get_board must hit the per-process cache"


def test_jared_no_cache_bypasses_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JARED_NO_CACHE", "1")
    calls = patch_kf(monkeypatch, body=json.dumps({"_id": "B1", "name": "B"}))
    client = _client()
    client.get_board()
    client.get_board()
    board_calls = [c for c in calls if str(c["url"]).endswith("/board")]
    assert len(board_calls) == 2, "JARED_NO_CACHE=1 must defeat caching"


def test_list_tasks_unwraps_column_groups(monkeypatch: pytest.MonkeyPatch) -> None:
    patch_kf(
        monkeypatch,
        body=json.dumps(
            [
                {
                    "columnId": "C1",
                    "columnName": "To-do",
                    "tasksLimited": False,
                    "tasks": [
                        {"_id": "T1", "name": "a", "columnId": "C1"},
                        {"_id": "T2", "name": "b", "columnId": "C1"},
                    ],
                }
            ]
        ),
    )
    tasks = _client().list_tasks(column_id="C1")
    assert [t.id for t in tasks] == ["T1", "T2"]


def test_list_tasks_follows_date_grouped_cursor(monkeypatch: pytest.MonkeyPatch) -> None:
    page1 = json.dumps(
        [
            {
                "columnId": "C1",
                "tasksLimited": True,
                "nextTaskId": "T2",
                "tasks": [{"_id": "T1", "name": "a", "columnId": "C1"}],
            }
        ]
    )
    page2 = json.dumps(
        [
            {
                "columnId": "C1",
                "tasksLimited": False,
                "tasks": [{"_id": "T2", "name": "b", "columnId": "C1"}],
            }
        ]
    )
    pages = [page1.encode(), page2.encode()]
    monkeypatch.setattr(kf, "_sleep", lambda _s: None)
    monkeypatch.setattr(kf, "_now", lambda: 1_000_000)
    seen: list[str] = []

    def fake(
        method: str, url: str, headers: dict[str, str], data: bytes | None
    ) -> tuple[int, dict[str, str], bytes]:
        seen.append(url)
        return 200, {}, pages.pop(0)

    monkeypatch.setattr(kf, "_raw_http", fake)
    tasks = _client().list_tasks(column_id="C1")
    assert [t.id for t in tasks] == ["T1", "T2"]
    assert any("startTaskId=T2" in u for u in seen), "must page using nextTaskId -> startTaskId"


def test_get_task_returns_single(monkeypatch: pytest.MonkeyPatch) -> None:
    patch_kf(monkeypatch, body=json.dumps({"_id": "T9", "name": "solo", "columnId": "C1"}))
    task = _client().get_task("T9")
    assert task.id == "T9"
    assert task.name == "solo"


def test_create_task_always_sends_explicit_number(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = patch_kf(
        monkeypatch,
        body=json.dumps({"_id": "T1", "name": "n", "columnId": "C1", "number": {"value": 7}}),
    )
    task = _client().create_task(name="n", column_id="C1", number_value=7)
    sent = json.loads(cast(bytes, calls[0]["data"]))
    assert sent["number"] == {"value": 7}, "create_task must always send number.value explicitly"
    assert calls[0]["method"] == "POST"
    assert task.number_value == 7


def test_update_task_uses_post_and_includes_only_given_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = patch_kf(
        monkeypatch,
        body=json.dumps({"_id": "T1", "name": "renamed", "columnId": "C2"}),
    )
    _client().update_task("T1", name="renamed", column_id="C2")
    assert calls[0]["method"] == "POST"
    assert str(calls[0]["url"]).endswith("/tasks/T1")
    sent = json.loads(cast(bytes, calls[0]["data"]))
    assert sent == {"name": "renamed", "columnId": "C2"}


def test_delete_task_issues_delete(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = patch_kf(monkeypatch, body="")
    _client().delete_task("T1")
    assert calls[0]["method"] == "DELETE"
    assert str(calls[0]["url"]).endswith("/tasks/T1")


def test_get_task_custom_fields_parses_values(monkeypatch: pytest.MonkeyPatch) -> None:
    patch_kf(
        monkeypatch,
        body=json.dumps(
            [
                {"customFieldId": "F1", "value": {"text": "High"}},
                {"customFieldId": "F2", "value": {"number": 12.5}},
            ]
        ),
    )
    values = _client().get_task_custom_fields("T1")
    assert values[0] == KfCustomFieldValue(custom_field_id="F1", value="High")
    assert values[1] == KfCustomFieldValue(custom_field_id="F2", value=12.5)


def test_set_task_custom_field_text_posts_to_field_url(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = patch_kf(monkeypatch, body="{}")
    _client().set_task_custom_field("T1", "F1", "High")
    assert calls[0]["method"] == "POST"
    assert str(calls[0]["url"]).endswith("/tasks/T1/custom-fields/F1")
    assert json.loads(cast(bytes, calls[0]["data"])) == {"value": {"text": "High"}}


def test_set_task_custom_field_number_uses_number_key(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = patch_kf(monkeypatch, body="{}")
    _client().set_task_custom_field("T1", "F2", 12.5)
    assert json.loads(cast(bytes, calls[0]["data"])) == {"value": {"number": 12.5}}


def test_list_comments_parses(monkeypatch: pytest.MonkeyPatch) -> None:
    patch_kf(
        monkeypatch,
        body=json.dumps(
            [
                {
                    "_id": "C1",
                    "text": "hi",
                    "createdTimestamp": "2026-01-01T00:00:00Z",
                    "authorUserId": "U1",
                }
            ]
        ),
    )
    comments = _client().list_comments("T1")
    assert comments == [
        KfComment(
            id="C1",
            text="hi",
            created_timestamp="2026-01-01T00:00:00Z",
            author_user_id="U1",
        )
    ]


def test_add_comment_posts_text_and_returns_id(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = patch_kf(monkeypatch, body=json.dumps({"taskCommentId": "C9"}))
    cid = _client().add_comment("T1", "a note")
    assert cid == "C9"
    assert calls[0]["method"] == "POST"
    assert str(calls[0]["url"]).endswith("/tasks/T1/comments")
    assert json.loads(cast(bytes, calls[0]["data"])) == {"text": "a note"}


def test_add_comment_backdates_with_created_timestamp(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = patch_kf(monkeypatch, body=json.dumps({"taskCommentId": "C9"}))
    _client().add_comment(
        "T1",
        "old note",
        created_timestamp="2025-01-01T00:00:00Z",
        author_user_id="U2",
    )
    sent = json.loads(cast(bytes, calls[0]["data"]))
    assert sent["createdTimestamp"] == "2025-01-01T00:00:00Z"
    assert sent["authorUserId"] == "U2"


def test_list_labels_parses(monkeypatch: pytest.MonkeyPatch) -> None:
    patch_kf(
        monkeypatch,
        body=json.dumps([{"name": "Priority", "pinned": True}, {"name": "X"}]),
    )
    labels = _client().list_labels("T1")
    assert labels == [KfLabel(name="Priority", pinned=True), KfLabel(name="X", pinned=False)]


def test_add_label_posts_name_and_pinned(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = patch_kf(monkeypatch, body=json.dumps({"insertIndex": 0}))
    _client().add_label("T1", "blocked-by:42", pinned=False)
    assert calls[0]["method"] == "POST"
    assert str(calls[0]["url"]).endswith("/tasks/T1/labels")
    assert json.loads(cast(bytes, calls[0]["data"])) == {"name": "blocked-by:42", "pinned": False}


def test_remove_label_deletes_by_name(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = patch_kf(monkeypatch, body="{}")
    _client().remove_label("T1", "blocked-by:42")
    assert calls[0]["method"] == "DELETE"
    assert str(calls[0]["url"]).endswith("/tasks/T1/labels/by-name/blocked-by%3A42"), (
        "label name must be URL-encoded in the path"
    )


def test_get_relations_parses(monkeypatch: pytest.MonkeyPatch) -> None:
    patch_kf(
        monkeypatch,
        body=json.dumps(
            [{"relationType": "dependsOn", "relatedTaskId": "T2", "relatedTaskName": "dep"}]
        ),
    )
    rels = _client().get_relations("T1")
    assert rels == [
        KfRelation(
            relation_type="dependsOn",
            related_task_id="T2",
            related_task_name="dep",
            related_task_board_id=None,
        )
    ]
