from pathlib import Path
from textwrap import dedent

import pytest


def test_parse_project_board_md(tmp_path: Path) -> None:
    from skills.jared.scripts.lib.board import Board

    board_md = tmp_path / "docs" / "project-board.md"
    board_md.parent.mkdir(parents=True)
    board_md.write_text(
        dedent("""\
        # Project board

        - Project URL: https://github.com/users/brockamer/projects/7
        - Project number: 7
        - Project ID: PVT_kwHO_xyz
        - Owner: brockamer
        - Repo: brockamer/findajob

        ## Fields

        - Status (field ID: PVTSSF_status): Backlog, Up Next, In Progress, Done, Blocked
        - Priority (field ID: PVTSSF_prio): High, Medium, Low
        """)
    )

    board = Board.from_path(board_md)

    assert board.project_number == 7
    assert board.project_id == "PVT_kwHO_xyz"
    assert board.owner == "brockamer"
    assert board.repo == "brockamer/findajob"


def test_missing_file_raises_board_config_error(tmp_path: Path) -> None:
    from skills.jared.scripts.lib.board import Board, BoardConfigError

    with pytest.raises(BoardConfigError) as exc:
        Board.from_path(tmp_path / "missing.md")

    assert "project-board.md" in str(exc.value) or "missing.md" in str(exc.value)


def test_field_and_option_lookup(tmp_path: Path) -> None:
    from skills.jared.scripts.lib.board import Board

    board_md = tmp_path / "docs" / "project-board.md"
    board_md.parent.mkdir(parents=True)
    board_md.write_text(
        dedent("""\
        - Project URL: https://github.com/users/brockamer/projects/7
        - Project number: 7
        - Project ID: PVT_kwHO_xyz
        - Owner: brockamer
        - Repo: brockamer/findajob

        ## Fields

        ### Status
        - Field ID: PVTSSF_status
        - Backlog: OPTION_backlog
        - Up Next: OPTION_up_next
        - In Progress: OPTION_in_progress
        - Done: OPTION_done
        - Blocked: OPTION_blocked

        ### Priority
        - Field ID: PVTSSF_prio
        - High: OPTION_high
        - Medium: OPTION_med
        - Low: OPTION_low
        """)
    )

    board = Board.from_path(board_md)

    assert board.field_id("Status") == "PVTSSF_status"
    assert board.field_id("Priority") == "PVTSSF_prio"
    assert board.option_id("Status", "In Progress") == "OPTION_in_progress"
    assert board.option_id("Priority", "High") == "OPTION_high"


def test_field_and_option_lookup_with_real_hex_ids(tmp_path: Path) -> None:
    """Real GH option IDs are 8-char hex (e.g. '0369b485'), not OPTION_foo.

    Regression test for the parser: bootstrap-project.py writes the IDs that
    `gh project field-list` returns, and those IDs do not carry the fake
    OPTION_ prefix the Phase 2 fixtures use. The parser must accept both.
    """
    from skills.jared.scripts.lib.board import Board

    board_md = tmp_path / "docs" / "project-board.md"
    board_md.parent.mkdir(parents=True)
    board_md.write_text(
        dedent("""\
        - Project URL: https://github.com/users/brockamer/projects/2
        - Project number: 2
        - Project ID: PVT_kwHOAgGulc4BVayY
        - Owner: brockamer
        - Repo: brockamer/jared-testbed

        ### Status
        - Field ID: PVTSSF_lAHOAgGulc4BVayYzhQ2uI0
        - Backlog: 0369b485
        - Up Next: 22683596
        - In Progress: d58e3645
        - Blocked: 423ecf89
        - Done: 727e952b

        ### Priority
        - Field ID: PVTSSF_lAHOAgGulc4BVayYzhQ2uak
        - High: 701eda34
        - Medium: bda6ffa1
        - Low: bf0a61ce

        Narrative follows — bullets like "- Backlog: Captured but not yet
        scheduled." below this point must not pollute the options map.
        """)
    )

    board = Board.from_path(board_md)

    assert board.field_id("Status") == "PVTSSF_lAHOAgGulc4BVayYzhQ2uI0"
    assert board.option_id("Status", "Backlog") == "0369b485"
    assert board.option_id("Status", "Blocked") == "423ecf89"
    assert board.option_id("Priority", "High") == "701eda34"


def test_unknown_field_raises(tmp_path: Path) -> None:
    from skills.jared.scripts.lib.board import Board, FieldNotFound

    board_md = tmp_path / "docs" / "project-board.md"
    board_md.parent.mkdir(parents=True)
    board_md.write_text(
        dedent("""\
        - Project URL: https://github.com/users/brockamer/projects/7
        - Project number: 7
        - Project ID: PVT_kwHO_xyz
        - Owner: brockamer
        - Repo: brockamer/findajob
        """)
    )

    board = Board.from_path(board_md)
    with pytest.raises(FieldNotFound):
        board.field_id("Nonexistent")


def test_unknown_option_raises(tmp_path: Path) -> None:
    from skills.jared.scripts.lib.board import Board, OptionNotFound

    board_md = tmp_path / "docs" / "project-board.md"
    board_md.parent.mkdir(parents=True)
    board_md.write_text(
        dedent("""\
        - Project URL: https://github.com/users/brockamer/projects/7
        - Project number: 7
        - Project ID: PVT_kwHO_xyz
        - Owner: brockamer
        - Repo: brockamer/findajob

        ### Priority
        - Field ID: PVTSSF_prio
        - High: OPTION_high
        """)
    )

    board = Board.from_path(board_md)
    with pytest.raises(OptionNotFound):
        board.option_id("Priority", "Urgent")


def _minimal_board(tmp_path: Path) -> Path:
    board_md = tmp_path / "docs" / "project-board.md"
    board_md.parent.mkdir(parents=True)
    board_md.write_text(
        dedent("""\
        - Project URL: https://github.com/users/brockamer/projects/7
        - Project number: 7
        - Project ID: PVT_kwHO_xyz
        - Owner: brockamer
        - Repo: brockamer/findajob
    """)
    )
    return board_md


def test_run_gh_parses_json(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from skills.jared.scripts.lib.board import Board

    b = Board.from_path(_minimal_board(tmp_path))

    class FakeResult:
        returncode = 0
        stdout = '{"hello": "world"}'
        stderr = ""

    called_args: list[list[str]] = []

    def fake_run(args: list[str], **kw: object) -> FakeResult:
        called_args.append(args)
        return FakeResult()

    monkeypatch.setattr("skills.jared.scripts.lib.board.subprocess.run", fake_run)

    result = b.run_gh(["api", "user"])
    assert result == {"hello": "world"}
    assert called_args == [["gh", "api", "user"]]


def test_run_gh_non_zero_raises(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from skills.jared.scripts.lib.board import Board, GhInvocationError

    b = Board.from_path(_minimal_board(tmp_path))

    class FakeResult:
        returncode = 1
        stdout = ""
        stderr = "HTTP 401: Bad credentials"

    monkeypatch.setattr(
        "skills.jared.scripts.lib.board.subprocess.run",
        lambda *a, **kw: FakeResult(),
    )

    with pytest.raises(GhInvocationError) as exc:
        b.run_gh(["api", "user"])
    assert "401" in str(exc.value)


def test_find_item_id_finds_match(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from skills.jared.scripts.lib.board import Board, ItemNotFound

    b = Board.from_path(_minimal_board(tmp_path))

    class FakeResult:
        returncode = 0
        stdout = (
            '{"items": ['
            '{"id": "PVTI_aaa", "content": {"number": 42}},'
            '{"id": "PVTI_bbb", "content": {"number": 99}}'
            "]}"
        )
        stderr = ""

    monkeypatch.setattr(
        "skills.jared.scripts.lib.board.subprocess.run",
        lambda *a, **kw: FakeResult(),
    )

    assert b.find_item_id(42) == "PVTI_aaa"
    assert b.find_item_id(99) == "PVTI_bbb"

    with pytest.raises(ItemNotFound):
        b.find_item_id(123456)


def test_run_graphql_passes_query_and_vars(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from skills.jared.scripts.lib.board import Board

    b = Board.from_path(_minimal_board(tmp_path))

    captured: dict[str, list[str]] = {}

    class FakeResult:
        returncode = 0
        stdout = '{"data": {"ok": true}}'
        stderr = ""

    def fake_run(args: list[str], **kw: object) -> FakeResult:
        captured["args"] = args
        return FakeResult()

    monkeypatch.setattr("skills.jared.scripts.lib.board.subprocess.run", fake_run)

    result = b.run_graphql("query { ok }", owner="brockamer", number=7)
    assert result == {"data": {"ok": True}}

    args = captured["args"]
    assert args[:4] == ["gh", "api", "graphql", "-f"]
    assert any(a == "query=query { ok }" for a in args)
    # Strings use -f; ints use -F so gh infers numeric type.
    assert "-f" in args and "owner=brockamer" in args
    assert "-F" in args and "number=7" in args


# Legacy board-doc fallbacks: older docs (pre-bootstrap-project.py) lack
# the machine-readable bullet block, so the parser has to infer the header
# fields from prose + git remote. These tests pin the fallback behavior
# so a canonical doc and a legacy doc pointing at the same project both
# parse to identical Board values.


_LEGACY_FINDAJOB_PROJECT_URL = "https://github.com/users/brockamer/projects/1"
_LEGACY_FINDAJOB_DOC = dedent(f"""\
    # Project Board — How It Works

    The GitHub Projects v2 board at [findajob Pipeline]({_LEGACY_FINDAJOB_PROJECT_URL})
    is the **single source of truth**.

    ## Fields quick reference

    ```
    Project ID:          PVT_kwHOAgGulc4BUtxZ
    Status field ID:     PVTSSF_status
      Backlog:           opt_backlog
    Priority field ID:   PVTSSF_prio
      High:              opt_high
    ```
""")


def test_legacy_doc_parses_via_url_prose_and_repo_fallback() -> None:
    """URL in a markdown link, ID in a code block, no owner/repo/number bullets.

    The real repro: findajob's own docs/project-board.md. All four bullet-only
    fields are absent; everything has to come from fallbacks. Passing
    `repo_fallback` bypasses the git-subprocess call so the test is hermetic.
    """
    from skills.jared.scripts.lib.board import Board

    board = Board._parse(
        _LEGACY_FINDAJOB_DOC,
        source="<test>",
        repo_fallback="brockamer/findajob",
    )

    assert board.project_url == _LEGACY_FINDAJOB_PROJECT_URL
    assert board.project_number == 1
    assert board.project_id == "PVT_kwHOAgGulc4BUtxZ"
    assert board.owner == "brockamer"
    assert board.repo == "brockamer/findajob"


def test_canonical_and_legacy_docs_produce_equivalent_board() -> None:
    """Canonical (bullets) and legacy (prose) shapes must resolve identically."""
    from skills.jared.scripts.lib.board import Board

    canonical_text = dedent("""\
        - Project URL: https://github.com/users/brockamer/projects/1
        - Project number: 1
        - Project ID: PVT_kwHOAgGulc4BUtxZ
        - Owner: brockamer
        - Repo: brockamer/findajob
    """)

    canonical = Board._parse(canonical_text, source="<canonical>")
    legacy = Board._parse(
        _LEGACY_FINDAJOB_DOC,
        source="<legacy>",
        repo_fallback="brockamer/findajob",
    )

    assert canonical.project_url == legacy.project_url
    assert canonical.project_number == legacy.project_number
    assert canonical.project_id == legacy.project_id
    assert canonical.owner == legacy.owner
    assert canonical.repo == legacy.repo


def test_doc_missing_url_entirely_raises_board_config_error() -> None:
    """If neither a bullet nor a projects/<N> URL is anywhere in the text, fail."""
    from skills.jared.scripts.lib.board import Board, BoardConfigError

    text = dedent("""\
        # Project board
        Project ID:  PVT_kwHO_xyz
        (no URL bullet, no markdown link, nothing to infer from)
    """)

    with pytest.raises(BoardConfigError) as exc:
        Board._parse(text, source="docs/project-board.md", repo_fallback="brockamer/jared")

    msg = str(exc.value)
    assert "Project URL" in msg
    assert "Project number" in msg
    assert "Owner" in msg
    # Friendly hint pointing at the fix path.
    assert "/jared-init" in msg


def test_partial_bullet_doc_prefers_bullet_over_fallback() -> None:
    """If the bullet is present, use its value; don't let the URL-regex fallback win."""
    from skills.jared.scripts.lib.board import Board

    text = dedent("""\
        # Header with a link pointing elsewhere:
        See [sibling project](https://github.com/users/brockamer/projects/99)
        for context.

        - Project URL: https://github.com/users/brockamer/projects/7
        - Project number: 7
        - Project ID: PVT_xyz
        - Owner: brockamer
        - Repo: brockamer/jared
    """)

    board = Board._parse(text, source="<test>")

    # Bullet URL wins; the 99 project in prose must not leak through.
    assert board.project_number == 7
    assert board.project_url.endswith("/projects/7")


def test_git_remote_inference_parses_common_forms(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """_infer_repo_from_git extracts owner/repo from SSH and HTTPS remote URLs."""
    from skills.jared.scripts.lib.board import _infer_repo_from_git
    from tests.conftest import FakeGhResult

    cases = [
        ("git@github.com:brockamer/jared.git\n", "brockamer/jared"),
        ("https://github.com/brockamer/jared.git\n", "brockamer/jared"),
        ("https://github.com/brockamer/jared\n", "brockamer/jared"),
        ("ssh://git@github.com/brockamer/jared.git\n", "brockamer/jared"),
        ("git@github.com:owner/repo-with-dashes.git\n", "owner/repo-with-dashes"),
    ]

    for remote_url, expected in cases:
        fake = FakeGhResult(stdout=remote_url, returncode=0)
        monkeypatch.setattr(
            "skills.jared.scripts.lib.board.subprocess.run",
            lambda *a, _r=fake, **kw: _r,
        )
        assert _infer_repo_from_git(tmp_path) == expected, remote_url


def test_git_remote_inference_returns_none_on_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If `git remote get-url origin` fails or git is absent, return None."""
    from skills.jared.scripts.lib.board import _infer_repo_from_git
    from tests.conftest import FakeGhResult

    failed = FakeGhResult(
        stdout="", returncode=128, stderr="fatal: No such remote 'origin'"
    )
    monkeypatch.setattr(
        "skills.jared.scripts.lib.board.subprocess.run",
        lambda *a, **kw: failed,
    )
    assert _infer_repo_from_git(tmp_path) is None

    def _raise_fnf(*a: object, **kw: object) -> None:
        raise FileNotFoundError("git not on PATH")

    monkeypatch.setattr("skills.jared.scripts.lib.board.subprocess.run", _raise_fnf)
    assert _infer_repo_from_git(tmp_path) is None
