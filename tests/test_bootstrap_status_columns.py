"""Tests for bootstrap-project.py's Status-column normalization (#269).

#269: GitHub seeds a new project's Status field with its own defaults
(Todo / In Progress / Done). The bootstrap script detected missing Priority /
Work Stream fields but never checked whether the *existing* Status field
carried the canonical Jared columns (Backlog / Up Next / In Progress /
Blocked / Done). The fix inspects the Status options and offers to replace
them with the canonical set when they don't match.
"""

import json
from typing import Any

import pytest

from tests.conftest import import_bootstrap

CANONICAL = ["Backlog", "Up Next", "In Progress", "Blocked", "Done"]


def _status_field(option_names: list[str]) -> dict[str, Any]:
    return {
        "id": "PVTSSF_status",
        "name": "Status",
        "options": [{"id": f"opt_{i}", "name": n} for i, n in enumerate(option_names)],
    }


def test_status_options_match_canonical_true_for_jared_set() -> None:
    mod = import_bootstrap()
    assert mod.status_options_match_canonical(_status_field(CANONICAL)) is True


def test_status_options_no_match_for_github_defaults() -> None:
    mod = import_bootstrap()
    github_defaults = _status_field(["Todo", "In Progress", "Done"])
    assert mod.status_options_match_canonical(github_defaults) is False


def test_status_options_order_sensitive() -> None:
    """Column order is board semantics — a reorder is not a match."""
    mod = import_bootstrap()
    reordered = ["Up Next", "Backlog", "In Progress", "Blocked", "Done"]
    assert mod.status_options_match_canonical(_status_field(reordered)) is False


def test_replace_single_select_options_sends_typed_list_via_stdin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mod = import_bootstrap()

    calls: list[tuple[list[str], str | None]] = []

    def fake_run_gh(args: list[str], *, input_text: str | None = None, **kw: Any) -> dict[str, Any]:
        calls.append((args, input_text))
        return {
            "data": {
                "updateProjectV2Field": {
                    "projectV2Field": {
                        "id": "PVTSSF_status",
                        "name": "Status",
                        "options": [{"id": f"o{i}", "name": n} for i, n in enumerate(CANONICAL)],
                    }
                }
            }
        }

    monkeypatch.setattr(mod, "board_run_gh", fake_run_gh)

    field = mod.replace_single_select_options("PVTSSF_status", CANONICAL)

    assert len(calls) == 1
    args, input_text = calls[0]
    # Same #267 discipline: typed list via stdin, never a -F options= string.
    assert not any(isinstance(a, str) and a.startswith("options=") for a in args)
    assert "--input" in args
    assert input_text is not None
    payload = json.loads(input_text)
    assert payload["variables"]["fieldId"] == "PVTSSF_status"
    assert payload["variables"]["options"] == [
        {"name": n, "color": "GRAY", "description": ""} for n in CANONICAL
    ]
    assert field["options"][0]["name"] == "Backlog"
