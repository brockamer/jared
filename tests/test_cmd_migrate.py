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


@pytest.fixture(autouse=True)
def _isolate_cwd(monkeypatch: pytest.MonkeyPatch, tmp_path: object) -> None:
    """Every migrate test runs from a fresh tmp dir. `--apply` writes a run
    artifact to a default tmp/ path (Phase 3.4); without this, apply tests that
    omit --out would litter the worktree's tmp/ on each pytest run. Module-local:
    only migrate tests exercise the artifact write."""
    monkeypatch.chdir(str(tmp_path))


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
        comments: dict[int, list[_Comment]] | None = None,
    ) -> None:
        self._items = items
        self._edges = edges
        self._caps = caps
        self._milestones = milestones or []
        self._validate_raises = validate_raises
        self._comments = comments or {}
        self.created: list[BoardItem] = []
        self.file_calls: list[dict[str, object]] = []
        self.set_field_calls: list[tuple[int, str, str]] = []
        self.set_milestone_calls: list[tuple[int, str]] = []
        self.move_calls: list[tuple[int, str]] = []
        self.add_blocked_by_calls: list[tuple[int, int]] = []
        self.set_body_calls: list[tuple[int, str]] = []
        self.comment_calls: list[tuple[int, str]] = []

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
        return list(self._comments.get(ref, []))

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
        self.add_blocked_by_calls.append((ref, blocker))

    def set_body(self, ref: int, text: str) -> None:
        self.set_body_calls.append((ref, text))

    def comment(self, ref: int, body: str) -> str:
        self.comment_calls.append((ref, body))
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


# ---------------------------------------------------------------------------
# Task 3.2 — second-pass blocked-by edges
# ---------------------------------------------------------------------------


def test_apply_translates_edges_through_number_map(monkeypatch: pytest.MonkeyPatch) -> None:
    """After item creation, source edges are re-keyed through the ledger's number
    map and replayed via add_blocked_by. A KF->GitHub renumber case is used so the
    assertion actually pins translate_edges: GitHub auto-assigns (stub: 100, 101),
    so the source edge (dependent=8, blocker=7) must surface as (101, 100) — an
    identity GH->KF map could not distinguish translation from raw passthrough."""
    src = _StubProvider(
        items=[
            BoardItem(number=7, title="a", status="Backlog", priority="High", body=""),
            BoardItem(number=8, title="b", status="Backlog", priority="Low", body=""),
        ],
        edges=[Edge(dependent=8, blocker=7)],
        caps=_all_capabilities(),
    )
    tgt = _StubProvider(items=[], edges=[], caps=_all_capabilities())
    cli = _patch_boards(monkeypatch, src, tgt, source_backend="kanbanflow", target_backend="github")
    rc = cli.main(["migrate", "--to", "github", "--target-doc", "t.md", "--apply", "--yes"])
    assert rc == 0
    # Stub assigns 100 to #7 and 101 to #8; the edge re-keys to (101, 100).
    assert [i.number for i in tgt.created] == [100, 101]
    assert tgt.add_blocked_by_calls == [(101, 100)]


# ---------------------------------------------------------------------------
# Task 3.3 — body cross-ref rewrite + comment portage with attribution
# ---------------------------------------------------------------------------


def test_apply_rewrites_body_cross_refs_kf_to_github(monkeypatch: pytest.MonkeyPatch) -> None:
    """The second pass rewrites '#<old>' -> '#<new>' in each migrated body via
    rewrite_cross_refs(get_body(old), nm) and writes it with set_body(new, ...).
    A KF->GitHub renumber is used so the map is non-identity (source #1 -> stub's
    100): the body 'see #1' must surface as set_body(100, 'see #100'). An identity
    GH->KF map could not distinguish a real rewrite from a raw echo."""
    src = _StubProvider(
        items=[BoardItem(number=1, title="a", status="Backlog", priority="High", body="see #1")],
        edges=[],
        caps=_all_capabilities(),
    )
    tgt = _StubProvider(items=[], edges=[], caps=_all_capabilities())
    cli = _patch_boards(monkeypatch, src, tgt, source_backend="kanbanflow", target_backend="github")
    rc = cli.main(["migrate", "--to", "github", "--target-doc", "t.md", "--apply", "--yes"])
    assert rc == 0
    # Source #1 maps to the stub's 100; the self-ref '#1' re-keys to '#100'.
    assert tgt.set_body_calls == [(100, "see #100")]


def test_apply_ports_comments_with_attribution_gh_to_kf(monkeypatch: pytest.MonkeyPatch) -> None:
    """GH->KF: each source comment is read via list_comments, its refs rewritten,
    an attribution prefix '(originally @{author}, {created_at})\\n\\n' prepended,
    then written via tgt.comment. The map is identity here (so the attribution
    prefix is the load-bearing assertion); a comment body referencing #1 is left
    as '#1' since the identity map maps 1->1."""
    src = _StubProvider(
        items=[
            BoardItem(number=1, title="a", status="Backlog", priority="High", body=""),
        ],
        edges=[],
        caps=_all_capabilities(),
        comments={1: [_Comment(author="alice", body="see #1 also", created_at="2026-01-02")]},
    )
    tgt = _StubProvider(items=[], edges=[], caps=frozenset())
    cli = _patch_boards(monkeypatch, src, tgt)
    rc = cli.main(["migrate", "--to", "kanbanflow", "--target-doc", "t.md", "--apply", "--yes"])
    assert rc == 0
    assert tgt.comment_calls == [(1, "(originally @alice, 2026-01-02)\n\nsee #1 also")]


def test_apply_ports_comments_without_attribution_kf_to_github(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """KF->GitHub: the attribution prefix is NOT prepended (it is GH->KF-only).
    The refs are still rewritten through the non-identity renumber map (source #1
    -> stub's 100), pinning both the direction guard (no prefix) and that the
    comment body passes through rewrite_cross_refs."""
    src = _StubProvider(
        items=[BoardItem(number=1, title="a", status="Backlog", priority="High", body="")],
        edges=[],
        caps=_all_capabilities(),
        comments={1: [_Comment(author="bob", body="depends on #1", created_at="2026-01-03")]},
    )
    tgt = _StubProvider(items=[], edges=[], caps=_all_capabilities())
    cli = _patch_boards(monkeypatch, src, tgt, source_backend="kanbanflow", target_backend="github")
    rc = cli.main(["migrate", "--to", "github", "--target-doc", "t.md", "--apply", "--yes"])
    assert rc == 0
    # No attribution prefix; '#1' rewritten to '#100' via the renumber map.
    assert tgt.comment_calls == [(100, "depends on #100")]


# ---------------------------------------------------------------------------
# Task 3.4 — emit run artifact / resume ledger
# ---------------------------------------------------------------------------


def test_apply_writes_ledger_to_explicit_out(
    monkeypatch: pytest.MonkeyPatch, tmp_path: object
) -> None:
    """--out <path> writes MigrationLedger.to_json() after the run: a JSON artifact
    recording the direction and the complete old->new number map. GH->KF identity
    map (1->1, 2->2) is asserted by reading the file back."""
    import json as _json
    from pathlib import Path as _Path

    out_path = _Path(str(tmp_path)) / "map.json"
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
    rc = cli.main(
        [
            "migrate",
            "--to",
            "kanbanflow",
            "--target-doc",
            "t.md",
            "--apply",
            "--yes",
            "--out",
            str(out_path),
        ]
    )
    assert rc == 0
    assert out_path.exists()
    data = _json.loads(out_path.read_text())
    assert data["direction"] == "github->kanbanflow"
    assert data["completed"] == {"1": 1, "2": 2}


def test_apply_default_out_is_timestamped_file(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """With no --out, the artifact lands at a default timestamped path under tmp/.
    The resolved path is printed so the user (and this test) can find it; the test
    extracts it from stdout, asserts the file exists, and checks the recorded map."""
    import json as _json
    from pathlib import Path as _Path

    # CWD is already a fresh tmp dir via the autouse _isolate_cwd fixture.
    src = _StubProvider(
        items=[BoardItem(number=1, title="a", status="Backlog", priority="High", body="")],
        edges=[],
        caps=_all_capabilities(),
    )
    tgt = _StubProvider(items=[], edges=[], caps=frozenset())
    cli = _patch_boards(monkeypatch, src, tgt)
    rc = cli.main(["migrate", "--to", "kanbanflow", "--target-doc", "t.md", "--apply", "--yes"])
    assert rc == 0
    out = capsys.readouterr().out
    # The resolved artifact path is announced; parse it back out of stdout.
    marker = "Wrote run artifact to "
    line = next(line for line in out.splitlines() if line.startswith(marker))
    written = line[len(marker) :].strip()
    written_path = _Path(written)
    assert written_path.parts[0] == "tmp"
    assert written_path.name.startswith("migrate-github-to-kanbanflow-")
    assert written_path.suffix == ".json"
    assert written_path.exists()
    data = _json.loads(written_path.read_text())
    assert data["direction"] == "github->kanbanflow"
    assert data["completed"] == {"1": 1}


def test_apply_abort_writes_no_artifact(monkeypatch: pytest.MonkeyPatch, tmp_path: object) -> None:
    """A 'n' answer at the confirmation prompt aborts before any work; no artifact
    is written even though --out is supplied (nothing happened to record)."""
    from pathlib import Path as _Path

    out_path = _Path(str(tmp_path)) / "map.json"
    src = _StubProvider(
        items=[BoardItem(number=1, title="a", status="Backlog", priority="High", body="")],
        edges=[],
        caps=_all_capabilities(),
    )
    tgt = _StubProvider(items=[], edges=[], caps=frozenset())
    cli = _patch_boards(monkeypatch, src, tgt)
    monkeypatch.setattr("builtins.input", lambda *_a: "n")
    rc = cli.main(
        ["migrate", "--to", "kanbanflow", "--target-doc", "t.md", "--apply", "--out", str(out_path)]
    )
    assert rc == 0
    assert not out_path.exists()


def test_include_closed_warns_it_is_inert(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """--include-closed has no closed-items reader on either provider, so it is a
    no-op. It must warn loudly on stderr (rather than silently lie) whenever set,
    in both dry-run and apply modes. This dry-run call (no --apply) proves the
    warning fires regardless of mode."""
    src = _StubProvider(
        items=[BoardItem(number=1, title="a", status="Up Next", priority="High", body="")],
        edges=[],
        caps=_all_capabilities(),
    )
    tgt = _StubProvider(items=[], edges=[], caps=frozenset())
    cli = _patch_boards(monkeypatch, src, tgt)
    rc = cli.main(["migrate", "--to", "kanbanflow", "--target-doc", "t.md", "--include-closed"])
    assert rc == 0
    err = capsys.readouterr().err
    assert "closed-item migration not yet supported" in err
    assert "--include-closed" in err


# ---------------------------------------------------------------------------
# Task 5.1 — flip the source backend selector on success
# ---------------------------------------------------------------------------


def test_apply_flips_source_doc_to_target_backend(
    monkeypatch: pytest.MonkeyPatch, tmp_path: object
) -> None:
    """After a fully-successful --apply, the source project-board.md is overwritten
    with the target-doc's content, so the project now points at the migrated board.

    The target-doc supplied via --target-doc is already a valid jared-init
    convention doc for the target backend; flipping the selector is a byte-copy of
    that doc onto the source doc path (resolved from --board). Asserted by reading
    the source doc back: it must now carry '- backend: kanbanflow' (it started
    '- backend: github')."""
    from pathlib import Path as _Path

    source_doc = _Path(str(tmp_path)) / "source-board.md"
    source_doc.write_text(
        "# Project board\n\n## Jared config\n- backend: github\n\n"
        "Project URL: https://github.com/users/brockamer/projects/4\n"
    )
    target_doc = _Path(str(tmp_path)) / "target-board.md"
    target_doc.write_text(
        "# Project board\n\n## Jared config\n- backend: kanbanflow\n"
        "- Repo: brockamer/jared\n- Board ID: abc123\n\n"
        "### Status column map\n- Backlog: Backlog\n- In Progress: In Progress\n"
    )

    src = _StubProvider(
        items=[BoardItem(number=1, title="a", status="Backlog", priority="High", body="x")],
        edges=[],
        caps=_all_capabilities(),
    )
    tgt = _StubProvider(items=[], edges=[], caps=frozenset())
    cli = _patch_boards(monkeypatch, src, tgt)
    rc = cli.main(
        [
            "--board",
            str(source_doc),
            "migrate",
            "--to",
            "kanbanflow",
            "--target-doc",
            str(target_doc),
            "--apply",
            "--yes",
        ]
    )
    assert rc == 0
    flipped = source_doc.read_text()
    assert "- backend: kanbanflow" in flipped
    assert "- backend: github" not in flipped
    # The flip is a byte-for-byte copy of the target convention doc.
    assert flipped == target_doc.read_text()


def test_apply_does_not_flip_when_no_source_doc_resolves(
    monkeypatch: pytest.MonkeyPatch, tmp_path: object
) -> None:
    """When no source doc can be resolved (no --board and no discoverable
    project-board.md), the flip is skipped silently — the apply still succeeds.

    This is the guard that keeps the flip from raising on every test that patches
    _load_board without a real doc on disk. The autouse _isolate_cwd chdir's to a
    fresh tmp with no project-board.md, so find_default_path() returns None."""
    from pathlib import Path as _Path

    target_doc = _Path(str(tmp_path)) / "target-board.md"
    target_doc.write_text("## Jared config\n- backend: kanbanflow\n")

    src = _StubProvider(
        items=[BoardItem(number=1, title="a", status="Backlog", priority="High", body="x")],
        edges=[],
        caps=_all_capabilities(),
    )
    tgt = _StubProvider(items=[], edges=[], caps=frozenset())
    cli = _patch_boards(monkeypatch, src, tgt)
    # No --board: source_doc_path resolves via find_default_path() -> None -> skip.
    rc = cli.main(
        ["migrate", "--to", "kanbanflow", "--target-doc", str(target_doc), "--apply", "--yes"]
    )
    assert rc == 0


def test_abort_does_not_flip_source_doc(monkeypatch: pytest.MonkeyPatch, tmp_path: object) -> None:
    """A user-aborted apply (answer != 'y') must NOT flip the source doc — the flip
    is reached only after the full apply succeeds, past the abort early-return."""
    from pathlib import Path as _Path

    source_doc = _Path(str(tmp_path)) / "source-board.md"
    source_doc.write_text("## Jared config\n- backend: github\n")
    target_doc = _Path(str(tmp_path)) / "target-board.md"
    target_doc.write_text("## Jared config\n- backend: kanbanflow\n")

    src = _StubProvider(
        items=[BoardItem(number=1, title="a", status="Backlog", priority="High", body="x")],
        edges=[],
        caps=_all_capabilities(),
    )
    tgt = _StubProvider(items=[], edges=[], caps=frozenset())
    cli = _patch_boards(monkeypatch, src, tgt)
    monkeypatch.setattr("builtins.input", lambda *_a: "n")
    rc = cli.main(
        [
            "--board",
            str(source_doc),
            "migrate",
            "--to",
            "kanbanflow",
            "--target-doc",
            str(target_doc),
            "--apply",
        ]
    )
    assert rc == 0
    # Aborted: source doc is untouched, still github.
    assert "- backend: github" in source_doc.read_text()


def test_apply_flip_survives_a_torn_write(
    monkeypatch: pytest.MonkeyPatch, tmp_path: object
) -> None:
    """A torn write while flipping the source doc must never corrupt it.

    docs/project-board.md is parsed by EVERY subsequent jared command, so a
    half-written flip leaves the whole project unusable (BoardConfigError) until
    a manual recopy. The flip must therefore use the atomic helper (stage in a
    `.tmp` sibling, then os.replace) like the four ledger persist sites do.

    Proven the same way as test_apply_ledger_write_survives_a_torn_write: make
    every write whose target IS the source doc land truncated garbage, while the
    `.tmp` sibling (a different path) gets the real content. With atomic-rename
    the source doc is produced only by os.replace from the intact `.tmp`, so the
    byte-for-byte flip lands whole. A bare `write_text(source_doc)` would write
    the garbage straight onto docs/project-board.md."""
    from pathlib import Path as _Path

    source_doc = _Path(str(tmp_path)) / "source-board.md"
    source_doc.write_text(
        "# Project board\n\n## Jared config\n- backend: github\n\n"
        "Project URL: https://github.com/users/brockamer/projects/4\n"
    )
    target_doc = _Path(str(tmp_path)) / "target-board.md"
    target_doc.write_text(
        "# Project board\n\n## Jared config\n- backend: kanbanflow\n"
        "- Repo: brockamer/jared\n- Board ID: abc123\n\n"
        "### Status column map\n- Backlog: Backlog\n- In Progress: In Progress\n"
    )

    src = _StubProvider(
        items=[BoardItem(number=1, title="a", status="Backlog", priority="High", body="x")],
        edges=[],
        caps=_all_capabilities(),
    )
    tgt = _StubProvider(items=[], edges=[], caps=frozenset())

    real_write_text = _Path.write_text

    def _torn_write_text(self: _Path, data: str, *a: object, **k: object) -> int:
        # A direct write to the source doc tears (truncated garbage); the .tmp
        # sibling — a different path — gets the whole content.
        if self == source_doc:
            return real_write_text(self, "- backend: gith", *a, **k)  # type: ignore[arg-type]
        return real_write_text(self, data, *a, **k)  # type: ignore[arg-type]

    monkeypatch.setattr(_Path, "write_text", _torn_write_text)

    cli = _patch_boards(monkeypatch, src, tgt)
    rc = cli.main(
        [
            "--board",
            str(source_doc),
            "migrate",
            "--to",
            "kanbanflow",
            "--target-doc",
            str(target_doc),
            "--apply",
            "--yes",
        ]
    )
    assert rc == 0

    # The source doc survives intact: the flip is the byte-for-byte target doc,
    # not the truncated garbage a direct write_text would have left.
    flipped = source_doc.read_text()
    assert flipped == target_doc.read_text()
    assert "- backend: kanbanflow" in flipped
    # No `.tmp` sibling is left behind after the final os.replace.
    assert not _Path(str(source_doc) + ".tmp").exists()


# ---------------------------------------------------------------------------
# Task 4.1 — resume from an existing ledger
# ---------------------------------------------------------------------------


def test_apply_resumes_from_existing_ledger_skips_done_items(
    monkeypatch: pytest.MonkeyPatch, tmp_path: object
) -> None:
    """When --out already holds a ledger, --apply resumes: items the ledger marks
    done are NOT re-created (their file() is skipped), and the second-pass edges
    still re-key through the FULL map (the pre-seeded entry + the newly-created
    one), not just the items created this run.

    Pre-seed --out with a ledger marking source #1 done (1->1). With source #1+#2
    and edge (dependent=2, blocker=1), GH->KF:
      - #1's file() is skipped (ledger.is_done(1)); only #2 is created.
      - ledger.number_map() == {1: 1, 2: 2}, so the edge survives as
        add_blocked_by(2, 1) — proving the second pass used the full map (the
        pre-seeded #1), not just this run's created items. A broken resume would
        re-create #1 (created == [1, 2]) and is caught by the created-list assert.
    """
    import json as _json
    from pathlib import Path as _Path

    out_path = _Path(str(tmp_path)) / "map.json"
    out_path.write_text(
        _json.dumps({"direction": "github->kanbanflow", "completed": {"1": 1}, "losses": []})
    )

    src = _StubProvider(
        items=[
            # #1 carries no ref-bearing body and no comments, so its second-pass
            # set_body/comment writes are unasserted noise — the test pins resume,
            # not the (already-covered) rewrite path.
            BoardItem(number=1, title="a", status="Up Next", priority="High", body="x"),
            BoardItem(number=2, title="b", status="Backlog", priority="Low", body="y"),
        ],
        edges=[Edge(dependent=2, blocker=1)],
        caps=_all_capabilities(),
    )
    tgt = _StubProvider(items=[], edges=[], caps=frozenset())
    cli = _patch_boards(monkeypatch, src, tgt)
    rc = cli.main(
        [
            "migrate",
            "--to",
            "kanbanflow",
            "--target-doc",
            "t.md",
            "--apply",
            "--yes",
            "--out",
            str(out_path),
        ]
    )
    assert rc == 0
    # #1 was skipped (only its file() call is recorded if re-created); only #2
    # should have been created this run.
    assert [c["number"] for c in tgt.file_calls] == [2]
    assert [i.number for i in tgt.created] == [2]
    # The edge re-keys through the FULL map {1:1, 2:2}, surviving as (2, 1).
    assert tgt.add_blocked_by_calls == [(2, 1)]
    # The ledger persisted back to --out now covers both items.
    data = _json.loads(out_path.read_text())
    assert data["completed"] == {"1": 1, "2": 2}


def test_apply_against_completed_artifact_replays_nothing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: object
) -> None:
    """Pointing --apply at a FULLY-completed artifact is a total no-op: no item is
    re-created and — critically — the second pass does not replay.

    The sharpest duplication case. The pre-seed records both items created AND
    their second-pass work done (ported + edges_applied). Because tgt.comment() is
    not idempotent on a live backend (neither GitHub nor KanbanFlow dedups), a
    second pass that ran here would duplicate every ported comment. Source #1
    carries a comment (the opposite of the skip-done-items test's deliberately
    comment-free item) so a replay is observable: the guard must make
    comment_calls / set_body_calls / add_blocked_by_calls all empty.
    """
    import json as _json
    from pathlib import Path as _Path

    out_path = _Path(str(tmp_path)) / "map.json"
    out_path.write_text(
        _json.dumps(
            {
                "direction": "github->kanbanflow",
                "completed": {"1": 1, "2": 2},
                "losses": [],
                "ported": [1, 2],
                "edges_applied": [[2, 1]],
            }
        )
    )

    src = _StubProvider(
        items=[
            BoardItem(number=1, title="a", status="Up Next", priority="High", body="see #1"),
            BoardItem(number=2, title="b", status="Backlog", priority="Low", body="y"),
        ],
        edges=[Edge(dependent=2, blocker=1)],
        caps=_all_capabilities(),
        comments={1: [_Comment(author="alice", body="a note", created_at="2026-01-02")]},
    )
    tgt = _StubProvider(items=[], edges=[], caps=frozenset())
    cli = _patch_boards(monkeypatch, src, tgt)
    rc = cli.main(
        [
            "migrate",
            "--to",
            "kanbanflow",
            "--target-doc",
            "t.md",
            "--apply",
            "--yes",
            "--out",
            str(out_path),
        ]
    )
    assert rc == 0
    # Nothing re-created; nothing re-ported; no edge replayed.
    assert tgt.file_calls == []
    assert tgt.set_body_calls == []
    assert tgt.comment_calls == []
    assert tgt.add_blocked_by_calls == []


def test_apply_resumes_partial_second_pass_without_duplicating(
    monkeypatch: pytest.MonkeyPatch, tmp_path: object
) -> None:
    """A run that crashed mid-second-pass resumes without re-porting done items.

    This pins the per-item / per-edge persistence the guard relies on: the
    ledger.is_ported / is_edge_applied flags only protect a resume if they were
    written to disk before the crash. Pre-seed both items created and #1 already
    ported (ported=[1]) but the edge NOT yet applied (edges_applied=[]). With #1
    and #2 both comment-bearing and edge (2,1):
      - #1's body+comments are NOT replayed (already ported) — no duplicate.
      - #2's body+comments ARE ported this run (it was the crash point).
      - the edge applies this run (it had not been recorded done).
    A guard that didn't persist per-item would re-port #1 and duplicate its
    comment; a guard that didn't persist per-edge is exercised by the
    completed-artifact test above.
    """
    import json as _json
    from pathlib import Path as _Path

    out_path = _Path(str(tmp_path)) / "map.json"
    out_path.write_text(
        _json.dumps(
            {
                "direction": "github->kanbanflow",
                "completed": {"1": 1, "2": 2},
                "losses": [],
                "ported": [1],
                "edges_applied": [],
            }
        )
    )

    src = _StubProvider(
        items=[
            BoardItem(number=1, title="a", status="Up Next", priority="High", body="b1"),
            BoardItem(number=2, title="b", status="Backlog", priority="Low", body="b2"),
        ],
        edges=[Edge(dependent=2, blocker=1)],
        caps=_all_capabilities(),
        comments={
            1: [_Comment(author="alice", body="note one", created_at="2026-01-01")],
            2: [_Comment(author="bob", body="note two", created_at="2026-01-02")],
        },
    )
    tgt = _StubProvider(items=[], edges=[], caps=frozenset())
    cli = _patch_boards(monkeypatch, src, tgt)
    rc = cli.main(
        [
            "migrate",
            "--to",
            "kanbanflow",
            "--target-doc",
            "t.md",
            "--apply",
            "--yes",
            "--out",
            str(out_path),
        ]
    )
    assert rc == 0
    # Both items already created — nothing re-created.
    assert tgt.file_calls == []
    # #1 (already ported) is NOT re-ported; only #2's body + comment land.
    assert tgt.set_body_calls == [(2, "b2")]
    assert tgt.comment_calls == [(2, "(originally @bob, 2026-01-02)\n\nnote two")]
    # The edge applies this run (it was not recorded as done).
    assert tgt.add_blocked_by_calls == [(2, 1)]
    # The persisted ledger now records both items ported and the edge applied.
    data = _json.loads(out_path.read_text())
    assert data["ported"] == [1, 2]
    assert data["edges_applied"] == [[2, 1]]


def test_apply_persists_second_pass_progress_before_a_crash(
    monkeypatch: pytest.MonkeyPatch, tmp_path: object
) -> None:
    """A crash mid-second-pass leaves the already-ported items recorded on disk.

    This is what makes the resume guard load-bearing rather than cosmetic: the
    is_ported flag only protects a re-run if it was persisted BEFORE the crash.
    Without the per-item write_text inside the loop, a crash after porting #1 but
    before the run's final write would leave `ported` empty on disk, and the
    resume would replay #1's comment (duplicating it).

    Inject a crash on the SECOND item's comment write (#2), then read the artifact
    back: #1 must already be recorded as ported. (Items sort #1 before #2, so #1
    is fully ported and persisted before #2's comment is attempted.)
    """
    import json as _json
    from pathlib import Path as _Path

    out_path = _Path(str(tmp_path)) / "map.json"

    src = _StubProvider(
        items=[
            BoardItem(number=1, title="a", status="Up Next", priority="High", body="b1"),
            BoardItem(number=2, title="b", status="Backlog", priority="Low", body="b2"),
        ],
        edges=[],
        caps=_all_capabilities(),
        comments={
            1: [_Comment(author="alice", body="note one", created_at="2026-01-01")],
            2: [_Comment(author="bob", body="note two", created_at="2026-01-02")],
        },
    )
    tgt = _StubProvider(items=[], edges=[], caps=frozenset())

    # Crash on #2's comment (new number == 2 GH->KF identity), after #1 is fully
    # ported and its progress persisted.
    real_comment = tgt.comment

    def _exploding_comment(ref: int, body: str) -> str:
        if ref == 2:
            raise RuntimeError("simulated crash during #2 comment portage")
        return real_comment(ref, body)

    monkeypatch.setattr(tgt, "comment", _exploding_comment)

    cli = _patch_boards(monkeypatch, src, tgt)
    with pytest.raises(RuntimeError, match="simulated crash"):
        cli.main(
            [
                "migrate",
                "--to",
                "kanbanflow",
                "--target-doc",
                "t.md",
                "--apply",
                "--yes",
                "--out",
                str(out_path),
            ]
        )

    # #1's second-pass progress was persisted BEFORE the crash on #2. A resume
    # reads this and skips #1, so its comment is not duplicated.
    data = _json.loads(out_path.read_text())
    assert data["ported"] == [1]


def test_apply_ledger_write_survives_a_torn_write(
    monkeypatch: pytest.MonkeyPatch, tmp_path: object
) -> None:
    """A ledger write torn mid-flight must never leave the artifact corrupt.

    The persist sites write to a `.tmp` sibling and `os.replace` it onto the
    artifact path, so the artifact is only ever swapped in whole. To prove it,
    simulate a torn write: make every write whose target IS the artifact path
    land truncated garbage, while the `.tmp` sibling receives the real content.
    With atomic-rename, the artifact is produced only by `os.replace` from the
    intact `.tmp`, so it stays parseable. A bare `write_text(out_path)` would
    write the garbage straight to the artifact, and the resume's
    `MigrationLedger.from_json` would raise on the truncated JSON.
    """
    import json as _json
    from pathlib import Path as _Path

    from skills.jared.scripts.lib.migrate import MigrationLedger as _Ledger

    out_path = _Path(str(tmp_path)) / "map.json"

    src = _StubProvider(
        items=[
            BoardItem(number=1, title="a", status="Up Next", priority="High", body="x"),
            BoardItem(number=2, title="b", status="Backlog", priority="Low", body="see #1"),
        ],
        edges=[Edge(dependent=2, blocker=1)],
        caps=_all_capabilities(),
    )
    tgt = _StubProvider(items=[], edges=[], caps=frozenset())

    real_write_text = _Path.write_text

    def _torn_write_text(self: _Path, data: str, *a: object, **k: object) -> int:
        # A direct write to the artifact path tears (truncated JSON); the .tmp
        # sibling — a different path — gets the whole content.
        if self == out_path:
            return real_write_text(self, '{"direction"', *a, **k)  # type: ignore[arg-type]
        return real_write_text(self, data, *a, **k)  # type: ignore[arg-type]

    monkeypatch.setattr(_Path, "write_text", _torn_write_text)

    cli = _patch_boards(monkeypatch, src, tgt)
    rc = cli.main(
        [
            "migrate",
            "--to",
            "kanbanflow",
            "--target-doc",
            "t.md",
            "--apply",
            "--yes",
            "--out",
            str(out_path),
        ]
    )
    assert rc == 0

    # The artifact survives intact: a resume can reload it without a JSONDecodeError.
    ledger = _Ledger.from_json(out_path.read_text())
    assert ledger.number_map().to_new(1) == 1
    assert ledger.number_map().to_new(2) == 2
    # No `.tmp` sibling is left behind after the final os.replace.
    assert not _Path(str(out_path) + ".tmp").exists()
    # Re-reading still parses (no truncation leaked through).
    _json.loads(out_path.read_text())


def test_apply_ledger_mark_happens_after_full_config_not_after_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: object
) -> None:
    """The ledger mark+persist for an item must happen AFTER file()+set_field()+
    set_milestone(), never right after file().

    Scenario: 2-item GH->KF migration. #1 configures fully (file + set_field).
    #2 file() succeeds but set_field raises. On crash, the persisted ledger must
    record #1 as done (is_done(1) True) but NOT #2 (is_done(2) False).

    Discriminating invariant: if a future refactor moves ledger.mark+_atomic_write
    to immediately after file() (before the field loop), #2's mark would be
    persisted before the crash. The ledger would then show is_done(2) True and
    this test would turn RED.
    """
    from pathlib import Path as _Path

    from skills.jared.scripts.lib.migrate import MigrationLedger as _Ledger

    out_path = _Path(str(tmp_path)) / "map.json"

    src = _StubProvider(
        items=[
            BoardItem(
                number=1,
                title="a",
                status="Up Next",
                priority="High",
                body="x",
                fields={"Area": "backend"},
            ),
            BoardItem(
                number=2,
                title="b",
                status="Backlog",
                priority="Low",
                body="y",
                fields={"Area": "frontend"},
            ),
        ],
        edges=[],
        caps=_all_capabilities(),
    )
    tgt = _StubProvider(items=[], edges=[], caps=frozenset())

    # Crash on set_field for #2 only. #1's set_field is allowed through.
    real_set_field = tgt.set_field

    def _exploding_set_field(ref: int, name: str, value: str) -> None:
        if ref == 2:
            raise RuntimeError("simulated crash during #2 set_field")
        real_set_field(ref, name, value)

    monkeypatch.setattr(tgt, "set_field", _exploding_set_field)

    cli = _patch_boards(monkeypatch, src, tgt)
    with pytest.raises(RuntimeError, match="simulated crash during #2 set_field"):
        cli.main(
            [
                "migrate",
                "--to",
                "kanbanflow",
                "--target-doc",
                "t.md",
                "--apply",
                "--yes",
                "--out",
                str(out_path),
            ]
        )

    # #1 was fully configured before the crash: its mark+persist happened AFTER
    # set_field, so is_done(1) must be True on disk.
    # #2's file() succeeded but set_field raised before mark+persist could run,
    # so is_done(2) must be False — the item is half-configured and must be
    # re-created (not skipped) on resume.
    ledger = _Ledger.from_json(out_path.read_text())
    assert ledger.is_done(1) is True
    assert ledger.is_done(2) is False
