"""Tests for bootstrap-project.py's GraphQL field-creation path (#267).

#267: when the bootstrap script creates a single-select field, the options
must reach the GraphQL runtime as a typed
`[ProjectV2SingleSelectFieldOptionInput!]!` list — not as a `-F options=<json>`
string flag, which `gh` passes through as a string literal and the variable's
type check rejects (`Variable $options ... was provided invalid value`).

The fix pipes the whole `{query, variables}` envelope via `gh api graphql
--input -` (stdin), so variable typing is explicit rather than left to gh's
per-flag type guessing.
"""

import json
from typing import Any

import pytest

from tests.conftest import import_bootstrap


def test_create_single_select_field_sends_options_as_typed_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mod = import_bootstrap()

    calls: list[tuple[list[str], str | None]] = []

    def fake_run_gh(args: list[str], *, input_text: str | None = None, **kw: Any) -> dict[str, Any]:
        calls.append((args, input_text))
        return {
            "data": {
                "createProjectV2Field": {
                    "projectV2Field": {
                        "id": "FIELD_STATUS",
                        "name": "Status",
                        "options": [
                            {"id": "o1", "name": "Backlog"},
                            {"id": "o2", "name": "Up Next"},
                        ],
                    }
                }
            }
        }

    monkeypatch.setattr(mod, "board_run_gh", fake_run_gh)

    field = mod.create_single_select_field("PVT_x", "Status", ["Backlog", "Up Next"])

    assert len(calls) == 1
    args, input_text = calls[0]

    # The #267 bug: options smuggled as a `-F options=<jsonstring>` flag.
    assert not any(isinstance(a, str) and a.startswith("options=") for a in args), (
        "options passed as a -F string literal — regression of #267"
    )

    # Fixed shape: the payload is piped via stdin as a {query, variables} envelope.
    assert "--input" in args
    assert input_text is not None, "payload must be piped via stdin (input_text)"

    payload = json.loads(input_text)
    assert payload["variables"]["projectId"] == "PVT_x"
    assert payload["variables"]["name"] == "Status"
    assert payload["variables"]["options"] == [
        {"name": "Backlog", "color": "GRAY", "description": ""},
        {"name": "Up Next", "color": "GRAY", "description": ""},
    ]

    # The parsed field still comes back to the caller unchanged.
    assert field["id"] == "FIELD_STATUS"


def test_create_single_select_field_rejects_empty_options(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Guard predates #267 and must survive the rewrite."""
    mod = import_bootstrap()
    monkeypatch.setattr(mod, "board_run_gh", lambda *a, **k: {})
    try:
        mod.create_single_select_field("PVT_x", "Status", [])
    except RuntimeError as e:
        assert "zero options" in str(e)
    else:
        raise AssertionError("expected RuntimeError on empty options")
