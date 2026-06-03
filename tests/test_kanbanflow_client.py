from __future__ import annotations

import json
from typing import cast

import pytest

from skills.jared.scripts.lib.kanbanflow_client import (
    KanbanFlowAuthError,
    KanbanFlowClient,
    KanbanFlowError,
    KanbanFlowForbiddenError,
    KanbanFlowNotFoundError,
    KanbanFlowServerError,
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
