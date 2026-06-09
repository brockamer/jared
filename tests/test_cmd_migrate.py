"""Tests for the `migrate` subcommand (Phase 2.2 + 2.3, #318).

Fakes: _StubProvider is an in-memory BoardProvider; _patch_boards monkeypatches
_load_board and _load_target_board so no filesystem or gh calls occur.
"""

from __future__ import annotations

from types import ModuleType

import pytest

from skills.jared.scripts.lib.board_provider import BoardItem, Capability, Edge, Milestone
from skills.jared.scripts.lib.board_provider import Comment as _Comment  # noqa: F401
from tests.conftest import import_cli as _import_cli


# The CLI inserts scripts/ on sys.path and imports from lib.board_provider; the
# test tree imports from skills.jared.scripts.lib.board_provider — two different
# module objects, two different Capability enum classes.  Build the "all caps"
# frozenset from the CLI-resolved module so enum identity matches what
# compute_loss_axes iterates (mirroring the FieldNotFound pattern in
# test_apply_refuses_on_missing_target_structure).
def _all_capabilities() -> frozenset[Capability]:
    cli = _import_cli()
    CliCap = cli.Capability
    return frozenset(CliCap)


class _StubProvider:
    """Minimal in-memory BoardProvider for migrate CLI tests."""

    def __init__(
        self,
        *,
        items: list[BoardItem],
        edges: list[Edge],
        caps: frozenset[Capability],
        milestones: list[Milestone] | None = None,
        validate_raises: Exception | None = None,
    ) -> None:
        self._items = items
        self._edges = edges
        self._caps = caps
        self._milestones = milestones or []
        self._validate_raises = validate_raises
        self.created: list[BoardItem] = []

    def capabilities(self) -> frozenset[Capability]:
        return self._caps

    def list_open_items(self) -> list[BoardItem]:
        return list(self._items)

    def get_body(self, ref: int) -> str:
        return next(i.body for i in self._items if i.number == ref)

    def fetch_blocked_by_edges(self) -> list[Edge]:
        return list(self._edges)

    def list_milestones(self) -> list[Milestone]:
        return list(self._milestones)

    def list_comments(self, ref: int) -> list[_Comment]:
        return []

    def validate_fields(
        self,
        *,
        priority: str,
        status: str,
        fields: list[tuple[str, str]] | None = None,
    ) -> None:
        if self._validate_raises is not None:
            raise self._validate_raises

    # write side recorded for apply tests (Phase 3)
    def file(self, **kw: object) -> BoardItem:
        item = BoardItem(
            number=100 + len(self.created),
            title=str(kw.get("title", "")),
            status=str(kw.get("status", "")),
            priority=str(kw.get("priority", "")),
            body=str(kw.get("body", "")),
        )
        self.created.append(item)
        return item

    def move(self, ref: int, status: str) -> None:
        return None

    def set_field(self, ref: int, name: str, value: str) -> None:
        return None

    def set_milestone(self, ref: int, name: str) -> None:
        return None

    def add_blocked_by(self, ref: int, blocker: int) -> None:
        return None

    def comment(self, ref: int, body: str) -> str:
        return ""


class _FakeBoard:
    """Minimal Board stand-in — exposes .backend and .provider."""

    def __init__(self, backend: str, provider: _StubProvider) -> None:
        self.backend = backend
        self.provider = provider


def _patch_boards(
    monkeypatch: pytest.MonkeyPatch,
    source: _StubProvider,
    target: _StubProvider,
    source_backend: str = "github",
    target_backend: str = "kanbanflow",
    cli_override: ModuleType | None = None,
) -> ModuleType:
    from tests.conftest import import_cli

    cli = cli_override if cli_override is not None else import_cli()
    monkeypatch.setattr(cli, "_load_board", lambda _arg: _FakeBoard(source_backend, source))
    monkeypatch.setattr(cli, "_load_target_board", lambda _path: _FakeBoard(target_backend, target))
    return cli


# ---------------------------------------------------------------------------
# Task 2.2 — dry-run tests
# ---------------------------------------------------------------------------


def test_dry_run_prints_report_and_writes_nothing(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    src = _StubProvider(
        items=[
            BoardItem(number=1, title="a", status="Up Next", priority="High", body="x"),
            BoardItem(number=2, title="b", status="Backlog", priority="Low", body="see #1"),
        ],
        edges=[Edge(dependent=2, blocker=1)],
        caps=_all_capabilities(),
    )
    tgt = _StubProvider(items=[], edges=[], caps=frozenset())
    cli = _patch_boards(monkeypatch, src, tgt)
    rc = cli.main(["migrate", "--to", "kanbanflow", "--target-doc", "t.md"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "github->kanbanflow" in out
    assert "2 items" in out
    assert "native_dependencies" in out
    assert tgt.created == []  # dry-run: no writes


def test_dry_run_refuses_when_source_equals_target_backend(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    src = _StubProvider(items=[], edges=[], caps=frozenset())
    tgt = _StubProvider(items=[], edges=[], caps=frozenset())
    cli = _patch_boards(
        monkeypatch, src, tgt, source_backend="kanbanflow", target_backend="kanbanflow"
    )
    rc = cli.main(["migrate", "--to", "kanbanflow", "--target-doc", "t.md"])
    assert rc == 2
    err = capsys.readouterr().err
    assert "--to kanbanflow" in err


# ---------------------------------------------------------------------------
# Task 2.3 — target-structure validation tests
# ---------------------------------------------------------------------------


def test_apply_refuses_on_missing_target_structure(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """--apply with a target that raises FieldNotFound on validate_fields must exit
    non-zero and print 'missing target structure:' before any write."""
    from tests.conftest import import_cli

    # Use the CLI module's FieldNotFound so the exception identity matches what
    # _validate_target_structure catches (dual-import-path: lib.board vs
    # skills.jared.scripts.lib.board produce different class objects).
    cli = import_cli()
    FieldNotFound = cli.FieldNotFound

    src = _StubProvider(
        items=[
            BoardItem(number=1, title="a", status="Up Next", priority="High", body=""),
        ],
        edges=[],
        caps=_all_capabilities(),
    )
    tgt = _StubProvider(
        items=[],
        edges=[],
        caps=frozenset(),
        validate_raises=FieldNotFound("Status column 'Up Next' not found"),
    )
    _patch_boards(monkeypatch, src, tgt, cli_override=cli)
    rc = cli.main(["migrate", "--to", "kanbanflow", "--target-doc", "t.md", "--apply", "--yes"])
    assert rc != 0
    out = capsys.readouterr().out
    assert "missing target structure:" in out
    assert tgt.created == []  # no writes performed
