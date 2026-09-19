import json
from pathlib import Path

import pytest

from tests.conftest import (
    graphql_item_response,
    import_cli,
    patch_gh,
    patch_gh_by_arg,
    write_minimal_board,
)


def test_get_item_prints_json(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    board_md = write_minimal_board(tmp_path)
    patch_gh(
        monkeypatch,
        stdout=graphql_item_response(
            project_number=7, item_id="PVTI_aaa", status="In Progress", priority="High"
        ),
    )

    mod = import_cli()
    rc = mod.main(["--board", str(board_md), "get-item", "42"])

    captured = capsys.readouterr()
    assert rc == 0, captured.err
    out = json.loads(captured.out)
    assert out["issue_number"] == 42
    assert out["item_id"] == "PVTI_aaa"
    assert out["status"] == "In Progress"
    assert out["priority"] == "High"


def test_get_item_fields_omits_unset_priority(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Status SET but Priority UNSET → fields dict has 'status' key but no 'priority' key."""
    board_md = write_minimal_board(tmp_path)
    patch_gh(
        monkeypatch,
        stdout=graphql_item_response(
            project_number=7, item_id="PVTI_bbb", status="Backlog", priority=None
        ),
    )

    mod = import_cli()
    rc = mod.main(["--board", str(board_md), "get-item", "55"])

    captured = capsys.readouterr()
    assert rc == 0, captured.err
    out = json.loads(captured.out)
    fields = out["fields"]
    assert "status" in fields, "status should be present when set"
    assert "priority" not in fields, "priority key must be omitted when unset"


def test_get_item_issue_not_found_exits_nonzero(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    board_md = write_minimal_board(tmp_path)
    patch_gh(
        monkeypatch,
        stdout='{"data":{"repository":{"issue":{"projectItems":{"nodes":[]}}}}}',
    )

    mod = import_cli()
    rc = mod.main(["--board", str(board_md), "get-item", "999"])

    captured = capsys.readouterr()
    assert rc != 0
    assert "999" in captured.err or "not found" in captured.err.lower()


# --- #410: --body flag exposes BoardProvider.get_body() ------------------


_BODY_MD = """One-sentence summary.

## Current state

- [ ] unchecked item
- [x] checked item

```python
def f() -> int:
    return 1
```

## Acceptance criteria

<details>
<summary>Expand</summary>

- Criterion 1

</details>
"""


def test_get_item_body_flag_includes_body(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """--body adds a 'body' key carrying the issue's markdown."""
    board_md = write_minimal_board(tmp_path)
    patch_gh_by_arg(
        monkeypatch,
        responses={"/issues/42": json.dumps({"body": _BODY_MD})},
        default=graphql_item_response(
            project_number=7, item_id="PVTI_aaa", status="In Progress", priority="High"
        ),
    )

    mod = import_cli()
    rc = mod.main(["--board", str(board_md), "get-item", "42", "--body"])

    captured = capsys.readouterr()
    assert rc == 0, captured.err
    out = json.loads(captured.out)
    assert out["body"] == _BODY_MD


def test_get_item_without_body_flag_omits_body_key(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Default output shape is unchanged — no 'body' key, and no REST call for it."""
    board_md = write_minimal_board(tmp_path)
    calls = patch_gh_by_arg(
        monkeypatch,
        responses={"/issues/42": json.dumps({"body": _BODY_MD})},
        default=graphql_item_response(
            project_number=7, item_id="PVTI_aaa", status="In Progress", priority="High"
        ),
    )

    mod = import_cli()
    rc = mod.main(["--board", str(board_md), "get-item", "42"])

    captured = capsys.readouterr()
    assert rc == 0, captured.err
    out = json.loads(captured.out)
    assert "body" not in out, "body key must be opt-in"
    assert not any("/issues/42" in " ".join(c) for c in calls), (
        "no body fetch should happen without --body"
    )


def test_get_item_body_round_trips_markdown_unchanged(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Headings, checkboxes and fenced blocks survive with no truncation."""
    board_md = write_minimal_board(tmp_path)
    patch_gh_by_arg(
        monkeypatch,
        responses={"/issues/42": json.dumps({"body": _BODY_MD})},
        default=graphql_item_response(
            project_number=7, item_id="PVTI_aaa", status="Backlog", priority="Low"
        ),
    )

    mod = import_cli()
    rc = mod.main(["--board", str(board_md), "get-item", "42", "--body"])

    captured = capsys.readouterr()
    assert rc == 0, captured.err
    body = json.loads(captured.out)["body"]
    assert "## Current state" in body
    assert "- [ ] unchecked item" in body
    assert "- [x] checked item" in body
    assert "```python" in body
    assert "<details>" in body and "</details>" in body
    assert body.endswith("</details>\n")


def test_get_item_body_flag_missing_issue_exits_nonzero(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A nonexistent issue fails with the not-found error, not an empty body."""
    board_md = write_minimal_board(tmp_path)
    patch_gh(
        monkeypatch,
        stdout='{"data":{"repository":{"issue":{"projectItems":{"nodes":[]}}}}}',
    )

    mod = import_cli()
    rc = mod.main(["--board", str(board_md), "get-item", "999", "--body"])

    captured = capsys.readouterr()
    assert rc != 0
    assert "999" in captured.err or "not found" in captured.err.lower()
    assert captured.out.strip() == "", "no JSON should be printed on the not-found path"
