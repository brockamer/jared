from pathlib import Path

import pytest

from tests.conftest import FakeGhResult, import_cli, write_minimal_board


def _routed_fake(
    monkeypatch: pytest.MonkeyPatch,
    *,
    node_id_by_number: dict[int, str],
    graphql_stdout: str = '{"data": {"addBlockedBy": {"issue": {"number": 99}}}}',
) -> list[list[str]]:
    """gh issue view --json id → returns {"id": node_id}; api graphql → graphql_stdout."""
    calls: list[list[str]] = []

    def fake_run(args: list[str], **kw: object) -> FakeGhResult:
        calls.append(args)
        joined = " ".join(args)
        if "issue" in args and "view" in args:
            # Find the issue number positional (after "view")
            idx = args.index("view")
            num = int(args[idx + 1])
            return FakeGhResult(stdout=f'{{"id": "{node_id_by_number[num]}"}}')
        if "graphql" in joined:
            return FakeGhResult(stdout=graphql_stdout)
        return FakeGhResult(stdout="{}")

    monkeypatch.setattr(
        "skills.jared.scripts.lib.board.subprocess.run",
        fake_run,
    )
    return calls


def test_blocked_by_add_edge(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    board_md = write_minimal_board(tmp_path)
    calls = _routed_fake(monkeypatch, node_id_by_number={99: "I_blockee", 42: "I_blocker"})

    mod = import_cli()
    rc = mod.main(["--board", str(board_md), "blocked-by", "99", "42"])
    captured = capsys.readouterr()
    assert rc == 0, captured.err

    # Two issue-view calls (one per issue) to resolve node IDs
    view_calls = [c for c in calls if "view" in c]
    assert len(view_calls) == 2

    # One graphql call with addBlockedBy in the query, carrying both node IDs
    gql = next(c for c in calls if "graphql" in c)
    query_arg = next(a for a in gql if a.startswith("query="))
    assert "addBlockedBy" in query_arg
    # Variables passed via -f
    assert any("issueId=I_blockee" in a for a in gql)
    assert any("blockingIssueId=I_blocker" in a for a in gql)

    assert "#99" in captured.out and "#42" in captured.out


def test_blocked_by_remove_edge(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    board_md = write_minimal_board(tmp_path)
    calls = _routed_fake(
        monkeypatch,
        node_id_by_number={99: "I_blockee", 42: "I_blocker"},
        graphql_stdout='{"data": {"removeBlockedBy": {"issue": {"number": 99}}}}',
    )

    mod = import_cli()
    rc = mod.main(["--board", str(board_md), "blocked-by", "99", "42", "--remove"])
    captured = capsys.readouterr()
    assert rc == 0, captured.err

    gql = next(c for c in calls if "graphql" in c)
    query_arg = next(a for a in gql if a.startswith("query="))
    assert "removeBlockedBy" in query_arg
    assert "addBlockedBy" not in query_arg
