"""Tests for bootstrap-project.py's legacy-doc patch helpers.

The patch path is what kicks in when `/jared-init` is run against a project
whose `docs/project-board.md` predates the machine-readable bullet block
(e.g. findajob's doc — URL in a markdown link, ID in a code fence). The
goal is to insert the five bullets near the top of the file and leave the
rest verbatim, rather than rewriting the whole doc and destroying prose.
"""

from textwrap import dedent

from tests.conftest import import_bootstrap

CANONICAL_DOC = dedent("""\
    # Project Board — How It Works

    - Project URL: https://github.com/users/brockamer/projects/1
    - Project number: 1
    - Project ID: PVT_kwHOAgGulc4BUtxZ
    - Owner: brockamer
    - Repo: brockamer/findajob

    Some narrative below.
""")


LEGACY_FINDAJOB_DOC = dedent("""\
    # Project Board — How It Works

    The GitHub Projects v2 board at [findajob Pipeline](https://github.com/users/brockamer/projects/1)
    is the **single source of truth for execution state**.

    This document describes the conventions.

    ## Columns (Status field)

    Five columns, left to right.

    ## Fields quick reference

    ```
    Project ID:          PVT_kwHOAgGulc4BUtxZ
    Status field ID:     PVTSSF_status
      Backlog:           opt_backlog
    ```
""")


def test_detect_missing_header_bullets_canonical_returns_empty() -> None:
    mod = import_bootstrap()
    assert mod.detect_missing_header_bullets(CANONICAL_DOC) == []


def test_detect_missing_header_bullets_legacy_returns_all_five() -> None:
    mod = import_bootstrap()
    # Findajob-shape: URL in a markdown link, ID in a code fence, no bullet
    # form of any of the five fields. Every header bullet should register
    # as missing, in HEADER_BULLETS order.
    assert mod.detect_missing_header_bullets(LEGACY_FINDAJOB_DOC) == [
        "Project URL",
        "Project number",
        "Project ID",
        "Owner",
        "Repo",
    ]


def test_detect_missing_header_bullets_partial() -> None:
    mod = import_bootstrap()
    partial = dedent("""\
        # Project board

        - Project URL: https://github.com/users/brockamer/projects/1
        - Project number: 1
        Some prose where Owner, Repo, and Project ID never appear as bullets.
    """)
    assert mod.detect_missing_header_bullets(partial) == [
        "Project ID",
        "Owner",
        "Repo",
    ]


def test_render_header_block_exact_bytes() -> None:
    mod = import_bootstrap()
    out = mod.render_header_block(
        project_url="https://github.com/users/brockamer/projects/1",
        project_number=1,
        project_id="PVT_kwHOAgGulc4BUtxZ",
        owner="brockamer",
        repo="brockamer/findajob",
    )
    assert out == (
        "- Project URL: https://github.com/users/brockamer/projects/1\n"
        "- Project number: 1\n"
        "- Project ID: PVT_kwHOAgGulc4BUtxZ\n"
        "- Owner: brockamer\n"
        "- Repo: brockamer/findajob\n"
    )


def test_find_header_insertion_point_after_h1_and_blank_line() -> None:
    mod = import_bootstrap()
    text = "# Title\n\nBody paragraph.\n"
    pos = mod.find_header_insertion_point(text)
    # Insertion lands between the blank line and "Body paragraph."
    assert text[:pos] == "# Title\n\n"


def test_find_header_insertion_point_h1_without_blank_line() -> None:
    mod = import_bootstrap()
    text = "# Title\nBody paragraph with no blank.\n"
    pos = mod.find_header_insertion_point(text)
    # Just past the H1 line, even without a trailing blank.
    assert text[:pos] == "# Title\n"


def test_find_header_insertion_point_no_h1() -> None:
    mod = import_bootstrap()
    text = "No heading, just prose.\n"
    assert mod.find_header_insertion_point(text) == 0


def test_patch_legacy_doc_preserves_prose_verbatim() -> None:
    mod = import_bootstrap()
    header = mod.render_header_block(
        project_url="https://github.com/users/brockamer/projects/1",
        project_number=1,
        project_id="PVT_kwHOAgGulc4BUtxZ",
        owner="brockamer",
        repo="brockamer/findajob",
    )
    patched = mod.patch_legacy_doc(LEGACY_FINDAJOB_DOC, header)

    # Every line of the original prose must still be present, in order.
    for line in LEGACY_FINDAJOB_DOC.splitlines():
        assert line in patched, f"lost line during patch: {line!r}"

    # The five bullets are now present in canonical form.
    assert "- Project URL: https://github.com/users/brockamer/projects/1" in patched
    assert "- Project number: 1" in patched
    assert "- Project ID: PVT_kwHOAgGulc4BUtxZ" in patched
    assert "- Owner: brockamer" in patched
    assert "- Repo: brockamer/findajob" in patched

    # And they land after the H1, not before it.
    h1_pos = patched.find("# Project Board")
    url_bullet_pos = patched.find("- Project URL:")
    assert h1_pos < url_bullet_pos, "bullets must not precede the H1"


def test_patched_legacy_doc_parses_via_lib_board() -> None:
    """End-to-end: after patching, the lib/board.py parser reads all five fields
    from the bullet block (the canonical path), not via the legacy fallbacks.
    This is the key user-visible win — the doc is now canonical.
    """
    mod = import_bootstrap()
    from skills.jared.scripts.lib.board import Board

    header = mod.render_header_block(
        project_url="https://github.com/users/brockamer/projects/1",
        project_number=1,
        project_id="PVT_kwHOAgGulc4BUtxZ",
        owner="brockamer",
        repo="brockamer/findajob",
    )
    patched = mod.patch_legacy_doc(LEGACY_FINDAJOB_DOC, header)

    # No repo_fallback passed — the patched doc must carry all five fields
    # in bullet form, so parsing succeeds without reaching the git-remote
    # fallback code path.
    board = Board._parse(patched, source="<patched>")
    assert board.project_url == "https://github.com/users/brockamer/projects/1"
    assert board.project_number == 1
    assert board.project_id == "PVT_kwHOAgGulc4BUtxZ"
    assert board.owner == "brockamer"
    assert board.repo == "brockamer/findajob"


def test_detect_and_patch_is_idempotent() -> None:
    """Patching twice doesn't duplicate the bullet block — once the first
    patch lands, the five bullets are present, so detect_missing returns []
    and the second invocation would no-op at the script level."""
    mod = import_bootstrap()
    header = mod.render_header_block(
        project_url="https://github.com/users/brockamer/projects/1",
        project_number=1,
        project_id="PVT_xyz",
        owner="brockamer",
        repo="brockamer/findajob",
    )
    once = mod.patch_legacy_doc(LEGACY_FINDAJOB_DOC, header)
    # After the first patch, detection returns [] — no further insert needed.
    assert mod.detect_missing_header_bullets(once) == []
