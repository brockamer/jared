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
        self.file_calls: list[dict[str, object]] = []
        self.set_field_calls: list[tuple[int, str, str]] = []
        self.set_milestone_calls: list[tuple[int, str]] = []
        self.move_calls: list[tuple[int, str]] = []

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
        self.file_calls.append(dict(kw))
        # Honor a caller-supplied number (GH->KF #N preservation); otherwise
        # auto-assign like the real backends do when number is None (KF->GH).
        explicit = kw.get("number")
        number = explicit if isinstance(explicit, int) else 100 + len(self.created)
        item = BoardItem(
            number=number,
            title=str(kw.get("title", "")),
            status=str(kw.get("status", "")),
            priority=str(kw.get("priority", "")),
            body=str(kw.get("body", "")),
        )
        self.created.append(item)
        return item

    def move(self, ref: int, status: str) -> None:
        self.move_calls.append((ref, status))

    def set_field(self, ref: int, name: str, value: str) -> None:
        self.set_field_calls.append((ref, name, value))

    def set_milestone(self, ref: int, name: str) -> None:
        self.set_milestone_calls.append((ref, name))

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


def test_apply_refuses_on_missing_target_swimlane(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A source item carrying a milestone whose swimlane does not pre-exist on the
    target must be refused before any write. validate_fields covers Status +
    Priority + extra fields but NOT swimlanes (KanbanFlow's file() resolves the
    swimlane separately), so the milestone dimension is a distinct check:
    every source milestone name must be a known target milestone (swimlane)."""
    from tests.conftest import import_cli

    cli = import_cli()

    src = _StubProvider(
        items=[
            BoardItem(
                number=1, title="a", status="Up Next", priority="High", body="", milestone="M1"
            ),
        ],
        edges=[],
        caps=_all_capabilities(),
    )
    # validate_fields passes (validate_raises=None); the target has no "M1"
    # swimlane (empty milestones), so the milestone gap is the only miss.
    tgt = _StubProvider(items=[], edges=[], caps=frozenset(), milestones=[])
    _patch_boards(monkeypatch, src, tgt, cli_override=cli)
    rc = cli.main(["migrate", "--to", "kanbanflow", "--target-doc", "t.md", "--apply", "--yes"])
    assert rc != 0
    out = capsys.readouterr().out
    assert "missing target structure:" in out
    assert "M1" in out
    assert tgt.created == []  # no writes performed


# ---------------------------------------------------------------------------
# Task 3.1 — confirmation gate + item creation with number map
# ---------------------------------------------------------------------------


def test_apply_creates_items_with_preserved_numbers_gh_to_kf(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """GH->KF --apply --yes creates one target item per source item, threading
    number=item.number so #N is preserved (identity number map)."""
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
    rc = cli.main(["migrate", "--to", "kanbanflow", "--target-doc", "t.md", "--apply", "--yes"])
    assert rc == 0
    # #N preserved exactly: identity map 1->1, 2->2 (not 100, 101).
    assert [i.number for i in tgt.created] == [1, 2]
    # Status + priority ride on file() (no redundant move() write).
    assert tgt.move_calls == []
    assert tgt.file_calls[0]["title"] == "a"
    assert tgt.file_calls[0]["status"] == "Up Next"
    assert tgt.file_calls[0]["priority"] == "High"
    assert tgt.file_calls[0]["number"] == 1
    # Raw body on first creation; cross-ref rewrite is deferred to Task 3.3.
    assert tgt.file_calls[1]["body"] == "see #1"


def test_apply_renumbers_kf_to_github(monkeypatch: pytest.MonkeyPatch) -> None:
    """KF->GitHub passes no number; GitHub auto-assigns, so the map is
    non-identity. The stub's fallback (100 + len) stands in for GitHub's
    assignment, proving number=None was threaded for this direction."""
    src = _StubProvider(
        items=[BoardItem(number=7, title="a", status="Backlog", priority="High", body="")],
        edges=[],
        caps=_all_capabilities(),
    )
    tgt = _StubProvider(items=[], edges=[], caps=_all_capabilities())
    cli = _patch_boards(monkeypatch, src, tgt, source_backend="kanbanflow", target_backend="github")
    rc = cli.main(["migrate", "--to", "github", "--target-doc", "t.md", "--apply", "--yes"])
    assert rc == 0
    # number=None was passed (renumber), so the source #7 maps to the stub's 100.
    assert tgt.file_calls[0]["number"] is None
    assert tgt.created[0].number == 100


def test_apply_applies_fields_and_milestone(monkeypatch: pytest.MonkeyPatch) -> None:
    """Extra custom fields go through set_field; milestone through set_milestone."""
    src = _StubProvider(
        items=[
            BoardItem(
                number=5,
                title="c",
                status="Backlog",
                priority="High",
                body="",
                milestone="M1",
                fields={"Area": "backend"},
            ),
        ],
        edges=[],
        caps=_all_capabilities(),
        milestones=[Milestone(name="M1")],
    )
    tgt = _StubProvider(items=[], edges=[], caps=frozenset(), milestones=[Milestone(name="M1")])
    cli = _patch_boards(monkeypatch, src, tgt)
    rc = cli.main(["migrate", "--to", "kanbanflow", "--target-doc", "t.md", "--apply", "--yes"])
    assert rc == 0
    assert [i.number for i in tgt.created] == [5]
    assert tgt.set_field_calls == [(5, "Area", "backend")]
    assert tgt.set_milestone_calls == [(5, "M1")]


def test_apply_without_yes_aborts_on_no(monkeypatch: pytest.MonkeyPatch) -> None:
    """Without --yes, a non-'y' answer at the confirmation prompt writes nothing."""
    src = _StubProvider(
        items=[BoardItem(number=1, title="a", status="Backlog", priority="High", body="")],
        edges=[],
        caps=_all_capabilities(),
    )
    tgt = _StubProvider(items=[], edges=[], caps=frozenset())
    cli = _patch_boards(monkeypatch, src, tgt)
    monkeypatch.setattr("builtins.input", lambda *_a: "n")
    rc = cli.main(["migrate", "--to", "kanbanflow", "--target-doc", "t.md", "--apply"])
    assert rc == 0
    assert tgt.created == []
    assert tgt.file_calls == []


def test_apply_without_yes_proceeds_on_y(monkeypatch: pytest.MonkeyPatch) -> None:
    """Without --yes, a 'y' answer at the prompt performs the writes."""
    src = _StubProvider(
        items=[BoardItem(number=1, title="a", status="Backlog", priority="High", body="")],
        edges=[],
        caps=_all_capabilities(),
    )
    tgt = _StubProvider(items=[], edges=[], caps=frozenset())
    cli = _patch_boards(monkeypatch, src, tgt)
    monkeypatch.setattr("builtins.input", lambda *_a: "y")
    rc = cli.main(["migrate", "--to", "kanbanflow", "--target-doc", "t.md", "--apply"])
    assert rc == 0
    assert [i.number for i in tgt.created] == [1]
