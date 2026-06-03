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
    KfCustomFieldValue,
    KfLabel,
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
