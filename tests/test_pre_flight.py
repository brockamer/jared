"""Tests for pre_flight_check (the PII pre-flight redactor) in lib/board.py."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from skills.jared.scripts.lib.board import (
    RedactionMatch,
    RedactionReport,
    _extract_phrases,
    _find_claude_shaped_files,
    _find_private_sources,
    _find_project_root,
    pre_flight_check,
)
from tests.conftest import SHORT_PRIVATE_TERMS, write_short_line_private_file


@pytest.fixture(autouse=True)
def _clear_redactor_cache() -> None:
    """Auto-applied — every test starts with a fresh redactor cache."""
    from skills.jared.scripts.lib.board import _clear_pre_flight_cache

    _clear_pre_flight_cache()


def test_pre_flight_check_empty_body_clean(tmp_path: Path) -> None:
    """Empty body produces a clean report when a private file was scanned."""
    (tmp_path / ".git").mkdir()
    (tmp_path / "CLAUDE.local.md").write_text("the deploy host is internal-foo-7.corp.example\n")
    report = pre_flight_check("", project_root=tmp_path)
    assert report.clean
    assert report.matches == []


def test_redaction_report_clean_property() -> None:
    """clean is True iff at least one file was scanned and nothing matched."""
    assert RedactionReport(matches=[], scanned_files=[Path("z")]).clean is True
    assert (
        RedactionReport(
            matches=[
                RedactionMatch(
                    line_no=1,
                    line_text="x",
                    matched_phrase="y",
                    source_file=Path("z"),
                )
            ],
            scanned_files=[Path("z")],
        ).clean
        is False
    )


def test_redaction_report_zero_files_is_vacuous_not_clean() -> None:
    """#443: a scan of zero files proves nothing, so it must not read as clean."""
    report = RedactionReport(matches=[], scanned_files=[])
    assert report.clean is False
    assert report.vacuous is True
    assert RedactionReport(matches=[], scanned_files=[Path("z")]).vacuous is False


def test_redaction_report_with_unscanned_reason_is_vacuous_despite_files() -> None:
    """#526: a file was read but gave nothing to compare. The report is
    vacuous, not clean, although scanned_files is not empty."""
    report = RedactionReport(
        matches=[], scanned_files=[Path("z")], unscanned_reason="no-usable-phrases"
    )
    assert report.vacuous is True
    assert report.clean is False


def test_extract_phrases_returns_lines_with_3_plus_words_and_20_plus_chars(
    tmp_path: Path,
) -> None:
    f = tmp_path / "CLAUDE.local.md"
    f.write_text(
        "the deploy host is internal-foo-7.corp.example\n"
        "two words\n"
        "short\n"
        "short three words here\n"  # 3 words but only 22 chars — included
        "Daniel Brock - daniel@example.com - +1-555-0100\n"
    )
    phrases = _extract_phrases(f)
    # Order preserved; line content as-is (post markdown-strip).
    assert "the deploy host is internal-foo-7.corp.example" in phrases
    assert "short three words here" in phrases
    assert "Daniel Brock - daniel@example.com - +1-555-0100" in phrases
    # Excluded:
    assert "two words" not in phrases  # < 3 words
    assert "short" not in phrases  # < 3 words AND < 20 chars


def test_extract_phrases_strips_markdown_punctuation(tmp_path: Path) -> None:
    f = tmp_path / "CLAUDE.local.md"
    f.write_text(
        "- bullet item with three words and length\n"
        "  > blockquote with three words too\n"
        "# Heading three words long\n"
        "* asterisk three words here\n"
    )
    phrases = _extract_phrases(f)
    # All four lines have ≥3 words after stripping markdown leaders, ≥20 chars.
    assert "bullet item with three words and length" in phrases
    assert "blockquote with three words too" in phrases
    assert "Heading three words long" in phrases
    assert "asterisk three words here" in phrases


def test_extract_phrases_skips_blank_lines(tmp_path: Path) -> None:
    f = tmp_path / "CLAUDE.local.md"
    f.write_text("\n\nfirst real line is long enough\n\n\n")
    phrases = _extract_phrases(f)
    assert phrases == ["first real line is long enough"]


def test_extract_phrases_handles_missing_file(tmp_path: Path) -> None:
    """Missing file returns empty list, not an exception."""
    assert _extract_phrases(tmp_path / "does-not-exist.md") == []


def test_find_claude_shaped_files_finds_CLAUDE_local(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    (tmp_path / "CLAUDE.local.md").write_text("hi")
    found = _find_claude_shaped_files(tmp_path)
    assert tmp_path / "CLAUDE.local.md" in found


def test_find_claude_shaped_files_finds_dot_claude_local(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    local_dir = tmp_path / ".claude" / "local"
    local_dir.mkdir(parents=True)
    (local_dir / "ops.md").write_text("hi")
    (local_dir / "secrets.md").write_text("hi")
    found = _find_claude_shaped_files(tmp_path)
    assert local_dir / "ops.md" in found
    assert local_dir / "secrets.md" in found


def test_find_claude_shaped_files_finds_dot_claude_CLAUDE_local(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    dot_claude = tmp_path / ".claude"
    dot_claude.mkdir()
    (dot_claude / "CLAUDE.local.md").write_text("hi")
    found = _find_claude_shaped_files(tmp_path)
    assert dot_claude / "CLAUDE.local.md" in found


def test_find_claude_shaped_files_no_git_repo_returns_empty(tmp_path: Path) -> None:
    """Without a .git/ dir we have no notion of gitignored — return empty."""
    (tmp_path / "CLAUDE.local.md").write_text("hi")
    assert _find_claude_shaped_files(tmp_path) == []


def test_find_claude_shaped_files_ignores_non_claude_files(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    (tmp_path / "README.md").write_text("hi")
    (tmp_path / "notes.md").write_text("hi")
    assert _find_claude_shaped_files(tmp_path) == []


def test_pre_flight_check_match_in_CLAUDE_local_flagged(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    (tmp_path / "CLAUDE.local.md").write_text("the deploy host is internal-foo-7.corp.example\n")
    body = (
        "## Filing a routine bug\n\n"
        "While testing I noticed the deploy host is internal-foo-7.corp.example "
        "stops responding under load.\n"
    )
    report = pre_flight_check(body, project_root=tmp_path)
    assert not report.clean
    assert len(report.matches) == 1
    m = report.matches[0]
    assert m.matched_phrase == "the deploy host is internal-foo-7.corp.example"
    assert m.source_file == tmp_path / "CLAUDE.local.md"
    assert "internal-foo-7" in m.line_text


def test_pre_flight_check_no_match_clean(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    (tmp_path / "CLAUDE.local.md").write_text("the deploy host is internal-foo-7.corp.example\n")
    body = "Wholly unrelated body text about the public weather service.\n"
    report = pre_flight_check(body, project_root=tmp_path)
    assert report.clean


def test_pre_flight_check_match_in_dot_claude_local_md_flagged(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    local = tmp_path / ".claude" / "local"
    local.mkdir(parents=True)
    (local / "ops.md").write_text("credentials live at /opt/secrets/foo.json on the prod host\n")
    body = "Here's the recipe: credentials live at /opt/secrets/foo.json on the prod host.\n"
    report = pre_flight_check(body, project_root=tmp_path)
    assert not report.clean
    assert report.matches[0].source_file == local / "ops.md"


def test_pre_flight_check_no_git_repo_is_vacuous(tmp_path: Path) -> None:
    """No .git/ means no allowlist, so nothing is scanned — and the report
    says so, with a reason distinct from "git repo, no private file"."""
    (tmp_path / "CLAUDE.local.md").write_text("the deploy host is internal-foo-7.corp.example\n")
    body = "the deploy host is internal-foo-7.corp.example\n"
    report = pre_flight_check(body, project_root=tmp_path)
    assert report.matches == []
    assert report.scanned_files == []
    assert not report.clean
    assert report.vacuous
    assert report.unscanned_reason == "no-git"


def test_pre_flight_check_git_repo_without_private_file_is_vacuous(tmp_path: Path) -> None:
    """#443's core defect: a git repo with no private source used to return
    a bare clean. It must come back vacuous, naming why."""
    _git_init_with_tracked(tmp_path, {"README.md": "Public-safe content only.\n"})
    report = pre_flight_check("Any body at all.\n", project_root=tmp_path)
    assert not report.clean
    assert report.vacuous
    assert report.unscanned_reason == "no-private-files"


def test_pre_flight_check_short_lines_only_is_vacuous(tmp_path: Path) -> None:
    """#526: every line of the private file is under the phrase floor, so it
    yields no phrase. The draft repeats both terms; the report must say that
    nothing was compared, not pass as clean."""
    _git_init_with_tracked(tmp_path, {"README.md": "Public-safe content only.\n"})
    private = write_short_line_private_file(tmp_path)
    body = " and ".join(SHORT_PRIVATE_TERMS) + " are both in this draft.\n"
    report = pre_flight_check(body, project_root=tmp_path)
    assert report.matches == []
    assert report.scanned_files == [private]
    assert not report.clean
    assert report.vacuous
    assert report.unscanned_reason == "no-usable-phrases"


def test_pre_flight_check_private_lines_all_tracked_is_vacuous(tmp_path: Path) -> None:
    """#526: a usable private line that a tracked file also holds is public
    and is dropped. A private file of only such lines compares nothing."""
    line = "Our deploy host is internal-foo-7.corp.example."
    _git_init_with_tracked(tmp_path, {"README.md": line + "\n"})
    (tmp_path / "CLAUDE.local.md").write_text(line + "\n")
    report = pre_flight_check("Any body at all.\n", project_root=tmp_path)
    assert not report.clean
    assert report.vacuous
    assert report.unscanned_reason == "no-usable-phrases"


def test_pre_flight_check_scans_gitignored_root_markdown(tmp_path: Path) -> None:
    """#443 regression: a gitignored private file at the repo root whose name
    matches none of the CLAUDE-shaped patterns is still scanned and flags."""
    _git_init_with_tracked(
        tmp_path,
        {".gitignore": "ops-prompt.md\n", "README.md": "Public-safe content only.\n"},
    )
    private = tmp_path / "ops-prompt.md"
    private.write_text("the recovery contact lives at 12 Example Lane\n")
    body = "Context: the recovery contact lives at 12 Example Lane, per notes.\n"
    report = pre_flight_check(body, project_root=tmp_path)
    assert not report.clean
    assert not report.vacuous
    assert report.scanned_files == [private]
    assert report.matches[0].source_file == private


def test_find_private_sources_skips_tracked_and_unignored_root_markdown(
    tmp_path: Path,
) -> None:
    """Only *gitignored* root markdown is private. A tracked README and an
    untracked-but-not-ignored scratch note are not sources."""
    _git_init_with_tracked(
        tmp_path,
        {".gitignore": "ops-prompt.md\n", "README.md": "Public-safe content only.\n"},
    )
    (tmp_path / "ops-prompt.md").write_text("private\n")
    (tmp_path / "handoff.md").write_text("untracked, not ignored\n")
    assert _find_private_sources(tmp_path) == [tmp_path / "ops-prompt.md"]


def test_find_private_sources_keeps_non_ascii_ignored_root_markdown(tmp_path: Path) -> None:
    """git C-quotes non-ASCII paths in its output by default (core.quotePath),
    so a quoted name would never match its candidate and the file would drop
    out of discovery silently — the #443 failure in miniature."""
    _git_init_with_tracked(tmp_path, {".gitignore": "*-notes.md\n"})
    private = tmp_path / "café-notes.md"
    private.write_text("private\n")
    assert _find_private_sources(tmp_path) == [private]


def test_find_private_sources_lists_ignored_claude_local_once(tmp_path: Path) -> None:
    """A gitignored CLAUDE.local.md matches both the pattern and the
    root-markdown rule; it is one source, not two."""
    _git_init_with_tracked(tmp_path, {".gitignore": "CLAUDE.local.md\n"})
    (tmp_path / "CLAUDE.local.md").write_text("private\n")
    assert _find_private_sources(tmp_path) == [tmp_path / "CLAUDE.local.md"]


def test_pre_flight_check_records_line_number(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    (tmp_path / "CLAUDE.local.md").write_text("the deploy host is internal-foo-7.corp.example\n")
    body = "line 1\nline 2\nthe deploy host is internal-foo-7.corp.example\nline 4\n"
    report = pre_flight_check(body, project_root=tmp_path)
    assert report.matches[0].line_no == 3


def _git_init_with_tracked(tmp_path: Path, tracked_files: dict[str, str]) -> None:
    """Initialize a git repo at tmp_path with the given files tracked."""
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=tmp_path,
        check=True,
    )
    subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, check=True)
    for relpath, content in tracked_files.items():
        f = tmp_path / relpath
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(content)
        subprocess.run(["git", "add", relpath], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=tmp_path, check=True)


def test_pre_flight_check_allowlists_phrase_present_in_tracked_README(
    tmp_path: Path,
) -> None:
    """A phrase that lives in CLAUDE.local.md AND in a tracked README is
    already public; the redactor must not flag it. The second, private-only
    line keeps the report clean: without it nothing is left to compare, and
    the report is vacuous (#526)."""
    _git_init_with_tracked(
        tmp_path,
        {"README.md": "Our deploy host is internal-foo-7.corp.example.\n"},
    )
    (tmp_path / "CLAUDE.local.md").write_text(
        "Our deploy host is internal-foo-7.corp.example.\n"
        "the staging box answers on port 8443 only\n"
    )
    body = "Issue: Our deploy host is internal-foo-7.corp.example. is flaky.\n"
    report = pre_flight_check(body, project_root=tmp_path)
    assert report.clean, (
        f"phrase that exists in tracked README is allowlisted; got matches: {report.matches}"
    )


def test_pre_flight_check_flags_phrase_only_in_gitignored_file(
    tmp_path: Path,
) -> None:
    """The same phrase, but only in CLAUDE.local.md (not in any tracked file),
    must be flagged."""
    _git_init_with_tracked(
        tmp_path,
        {"README.md": "Public-safe content only.\n"},
    )
    (tmp_path / "CLAUDE.local.md").write_text("Our deploy host is internal-foo-7.corp.example.\n")
    body = "Issue: Our deploy host is internal-foo-7.corp.example. is flaky.\n"
    report = pre_flight_check(body, project_root=tmp_path)
    assert not report.clean
    assert report.matches[0].matched_phrase.startswith("Our deploy host")


def test_pre_flight_check_caches_per_project_root(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Second call to the same project_root reuses scan results — no second
    `git ls-files` invocation."""
    _git_init_with_tracked(tmp_path, {"README.md": "public.\n"})
    (tmp_path / "CLAUDE.local.md").write_text("the deploy host is internal-foo-7.corp.example\n")

    real_subprocess_run = subprocess.run
    call_count = {"git_ls_files": 0}

    def counting_run(args, **kwargs):  # type: ignore[no-untyped-def]
        if isinstance(args, list) and args[:2] == ["git", "ls-files"]:
            call_count["git_ls_files"] += 1
        return real_subprocess_run(args, **kwargs)

    # Clear the cache before the test (it's process-local).
    from skills.jared.scripts.lib.board import _clear_pre_flight_cache

    _clear_pre_flight_cache()
    monkeypatch.setattr(
        "skills.jared.scripts.lib.board.subprocess.run",
        counting_run,
    )

    pre_flight_check("body 1", project_root=tmp_path)
    pre_flight_check("body 2", project_root=tmp_path)

    assert call_count["git_ls_files"] == 1, (
        f"expected one git ls-files call (cached); got {call_count}"
    )


def test_print_redaction_diff_format(capsys: pytest.CaptureFixture[str]) -> None:
    from skills.jared.scripts.lib.board import print_redaction_diff

    report = RedactionReport(
        matches=[
            RedactionMatch(
                line_no=12,
                line_text="...the deploy host is internal-foo-7...",
                matched_phrase="the deploy host is internal-foo-7",
                source_file=Path("CLAUDE.local.md"),
            ),
            RedactionMatch(
                line_no=18,
                line_text="...credentials at /opt/secrets/...",
                matched_phrase="credentials at /opt/secrets",
                source_file=Path(".claude/local/ops.md"),
            ),
        ],
        scanned_files=[
            Path("CLAUDE.local.md"),
            Path(".claude/local/ops.md"),
        ],
    )
    import sys

    print_redaction_diff(report, file=sys.stderr)
    captured = capsys.readouterr()
    assert "pre-flight redaction check failed" in captured.err
    assert "2 matches" in captured.err
    assert "line 12:" in captured.err
    assert "line 18:" in captured.err
    assert "CLAUDE.local.md" in captured.err
    assert ".claude/local/ops.md" in captured.err
    assert "next steps:" in captured.err
    # Pin the visual format — guards against silent regressions on
    # indentation, the ↳ arrow, line-text quoting, and step ordering.
    assert "↳ matches CLAUDE.local.md" in captured.err
    assert "↳ matches .claude/local/ops.md" in captured.err
    assert "    line 12:" in captured.err  # 4-space indent
    assert "      ↳ " in captured.err  # 6-space indent for arrow line
    assert "    1. Re-issue" in captured.err
    assert "    2. OR add" in captured.err
    # Step 1 must come before step 2 in the output.
    assert captured.err.index("1. Re-issue") < captured.err.index("2. OR add")


def test_print_redaction_diff_no_op_without_matches(capsys: pytest.CaptureFixture[str]) -> None:
    """Guard added during Task 7 review: a report without matches produces no
    output — whether it is clean or vacuous (#443 made those two differ).

    Real callers gate on `report.matches` so this branch is unreachable in
    practice, but the guard prevents misleading "0 matches across 0 files"
    output if a future caller gates on `not report.clean` instead.
    """
    from skills.jared.scripts.lib.board import print_redaction_diff

    print_redaction_diff(RedactionReport(matches=[], scanned_files=[]))
    print_redaction_diff(RedactionReport(matches=[], scanned_files=[Path("z")]))
    captured = capsys.readouterr()
    assert captured.err == ""
    assert captured.out == ""


def test_print_unscanned_notice_names_the_reason(capsys: pytest.CaptureFixture[str]) -> None:
    """The 0-file warning says the body was not checked and tells the two
    reasons apart, so the operator knows what to fix."""
    from skills.jared.scripts.lib.board import print_unscanned_notice

    print_unscanned_notice(
        RedactionReport(matches=[], scanned_files=[], unscanned_reason="no-git"),
        Path("/proj"),
    )
    no_git = capsys.readouterr().err
    print_unscanned_notice(
        RedactionReport(matches=[], scanned_files=[], unscanned_reason="no-private-files"),
        Path("/proj"),
    )
    no_files = capsys.readouterr().err
    for err in (no_git, no_files):
        assert err.startswith("warning: pre-flight scanned 0 private files")
        assert "not checked" in err
    assert ".git" in no_git
    assert "gitignore" in no_files
    assert no_git != no_files


def test_print_unscanned_notice_no_usable_phrases_names_file_and_rule(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """#526: a file was found, so "scanned 0 private files" would be false.
    The notice names the file and states the phrase rule, so the operator
    sees why a list of short terms checked nothing."""
    from skills.jared.scripts.lib.board import print_unscanned_notice

    print_unscanned_notice(
        RedactionReport(
            matches=[],
            scanned_files=[Path("/proj/private-notes.md")],
            unscanned_reason="no-usable-phrases",
        ),
        Path("/proj"),
    )
    err = capsys.readouterr().err
    assert err.startswith("warning: pre-flight")
    assert "not checked" in err
    assert "scanned 0 private files" not in err
    assert "private-notes.md" in err
    assert "20+ characters" in err
    assert "3+ words" in err
    assert "whole line" in err
    assert "tracked file" in err


def test_print_unscanned_notice_no_op_when_files_were_scanned(
    capsys: pytest.CaptureFixture[str],
) -> None:
    from skills.jared.scripts.lib.board import print_unscanned_notice

    print_unscanned_notice(RedactionReport(matches=[], scanned_files=[Path("z")]), Path("/p"))
    assert capsys.readouterr().err == ""


def test_find_project_root_returns_cwd_when_git_at_root(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    assert _find_project_root(tmp_path) == tmp_path.resolve()


def test_find_project_root_walks_up_from_subdirectory(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    sub = tmp_path / "src" / "feature"
    sub.mkdir(parents=True)
    assert _find_project_root(sub) == tmp_path.resolve()


def test_find_project_root_returns_start_when_no_git_found(tmp_path: Path) -> None:
    """No .git/ in tmp_path or any of its parents (under pytest's tmpdir).
    The function falls back to the start path; the redactor's no-git
    short-circuit then applies.
    """
    sub = tmp_path / "deep" / "nested"
    sub.mkdir(parents=True)
    # Result is .resolve()'d
    assert _find_project_root(sub) == sub.resolve()


# ---------- `## Pre-flight terms` (#528) ----------


def _terms_file(root: Path, *terms: str, name: str = "CLAUDE.local.md") -> Path:
    """Write a private file that holds only a `## Pre-flight terms` section."""
    private = root / name
    private.parent.mkdir(parents=True, exist_ok=True)
    private.write_text("## Pre-flight terms\n\n" + "".join(f"- {t}\n" for t in terms))
    return private


def test_extract_terms_reads_bullets_under_the_heading_only(tmp_path: Path) -> None:
    """Bullets under the heading, up to the next heading, are terms. A bullet
    under another heading is not, and a term under 3 characters is dropped."""
    from skills.jared.scripts.lib.board import _extract_terms

    f = tmp_path / "CLAUDE.local.md"
    f.write_text(
        "# Notes\n"
        "- Not a term\n"
        "## Pre-flight terms\n"
        "Names that stay off the board:\n"
        "- Jane Doe\n"
        "* Orchard Lane\n"
        "- Al\n"
        "## Later\n"
        "- Also not a term\n"
    )
    assert _extract_terms(f) == ["Jane Doe", "Orchard Lane"]


def test_extract_phrases_skips_term_bullets(tmp_path: Path) -> None:
    """A long term follows the term rule, not the phrase rule, so it is not
    also a phrase. Other lines in the section still follow the phrase rule."""
    f = tmp_path / "CLAUDE.local.md"
    f.write_text(
        "## Pre-flight terms\n"
        "- Acme Robotics Holdings International\n"
        "These names must stay off the public board.\n"
    )
    assert _extract_phrases(f) == ["These names must stay off the public board."]


def test_pre_flight_check_term_hit_names_the_source(tmp_path: Path) -> None:
    """#528 AC1: a listed term flags a draft that uses it, possessive
    included. The report has a match and is not vacuous."""
    _git_init_with_tracked(tmp_path, {"README.md": "Public-safe content only.\n"})
    private = _terms_file(tmp_path, "Jane Doe")
    report = pre_flight_check("Met Jane Doe's team\n", project_root=tmp_path)
    assert not report.vacuous
    assert len(report.matches) == 1
    assert report.matches[0].matched_phrase == "Jane Doe"
    assert report.matches[0].source_file == private
    assert report.matches[0].line_no == 1


def test_pre_flight_check_term_matches_whole_tokens_only(tmp_path: Path) -> None:
    """#528 AC2: `Janet Doerr` holds `Jane Doe` as a substring, not as a
    whole token, so the draft is clean."""
    _git_init_with_tracked(tmp_path, {"README.md": "Public-safe content only.\n"})
    _terms_file(tmp_path, "Jane Doe")
    report = pre_flight_check("Janet Doerr called\n", project_root=tmp_path)
    assert report.clean


def test_pre_flight_check_term_is_case_sensitive(tmp_path: Path) -> None:
    """A documented false negative: the operator lists each form to catch."""
    _git_init_with_tracked(tmp_path, {"README.md": "Public-safe content only.\n"})
    _terms_file(tmp_path, "Jane Doe")
    report = pre_flight_check("met jane doe today\n", project_root=tmp_path)
    assert report.clean


def test_pre_flight_check_allowlists_term_tracked_as_whole_token(tmp_path: Path) -> None:
    """#528 AC3: a term that a tracked file holds as a whole token is public
    and is dropped. The second term keeps the report from being vacuous."""
    _git_init_with_tracked(tmp_path, {"README.md": "Thanks to Jane Doe for the fix.\n"})
    _terms_file(tmp_path, "Jane Doe", "Zelda Quimby")
    report = pre_flight_check("Met Jane Doe's team\n", project_root=tmp_path)
    assert report.clean, report.matches


def test_pre_flight_check_term_inside_a_tracked_word_is_not_allowlisted(
    tmp_path: Path,
) -> None:
    """The allowlist uses the same boundary rule as the body. A substring
    test would drop `Jane` because the tracked README holds `Janeway`."""
    _git_init_with_tracked(tmp_path, {"README.md": "Named for Captain Janeway.\n"})
    _terms_file(tmp_path, "Jane")
    report = pre_flight_check("Ask Jane about it\n", project_root=tmp_path)
    assert [m.matched_phrase for m in report.matches] == ["Jane"]


def test_pre_flight_check_terms_all_too_short_is_vacuous(tmp_path: Path) -> None:
    """#528 AC4: terms under 3 characters are ignored. With no phrase in the
    file either, nothing was compared."""
    _git_init_with_tracked(tmp_path, {"README.md": "Public-safe content only.\n"})
    _terms_file(tmp_path, "JD", "Q")
    report = pre_flight_check("JD and Q met\n", project_root=tmp_path)
    assert report.vacuous
    assert report.unscanned_reason == "no-usable-phrases"


def test_pre_flight_check_names_a_private_file_that_adds_nothing(tmp_path: Path) -> None:
    """One file has a usable phrase; the other lists short names with no
    terms heading. The report is clean, but it names the second file, so
    the operator sees that its names were never compared."""
    _git_init_with_tracked(tmp_path, {"README.md": "Public-safe content only.\n"})
    (tmp_path / "CLAUDE.local.md").write_text("the deploy host is internal-foo-7.corp.example\n")
    people = tmp_path / ".claude" / "local" / "people.md"
    people.parent.mkdir(parents=True)
    people.write_text("".join(f"- {t}\n" for t in SHORT_PRIVATE_TERMS))
    report = pre_flight_check(f"{SHORT_PRIVATE_TERMS[0]} called.\n", project_root=tmp_path)
    assert report.clean
    assert report.unused_files == [people]


def test_pre_flight_check_every_file_used_lists_none_unused(tmp_path: Path) -> None:
    _git_init_with_tracked(tmp_path, {"README.md": "Public-safe content only.\n"})
    (tmp_path / "CLAUDE.local.md").write_text("the deploy host is internal-foo-7.corp.example\n")
    _terms_file(tmp_path, "Jane Doe", name=".claude/local/people.md")
    report = pre_flight_check("Nothing private.\n", project_root=tmp_path)
    assert report.clean
    assert report.unused_files == []


def test_print_redaction_diff_names_the_matched_term(capsys: pytest.CaptureFixture[str]) -> None:
    """A term can sit anywhere in a long line, so the diff names it."""
    from skills.jared.scripts.lib.board import print_redaction_diff

    report = RedactionReport(
        matches=[
            RedactionMatch(
                line_no=3,
                line_text="We met Jane Doe's team at the offsite last week.",
                matched_phrase="Jane Doe",
                source_file=Path("CLAUDE.local.md"),
                kind="term",
            )
        ],
        scanned_files=[Path("CLAUDE.local.md")],
    )
    print_redaction_diff(report)
    err = capsys.readouterr().err
    assert '↳ matches CLAUDE.local.md (term "Jane Doe")' in err
    assert "claude-shaped" not in err


def test_print_unscanned_notice_no_usable_phrases_names_the_terms_heading(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """#528 AC4: the vacuous warning tells the operator where short names go."""
    from skills.jared.scripts.lib.board import print_unscanned_notice

    print_unscanned_notice(
        RedactionReport(
            matches=[],
            scanned_files=[Path("/proj/CLAUDE.local.md")],
            unscanned_reason="no-usable-phrases",
        ),
        Path("/proj"),
    )
    err = capsys.readouterr().err
    assert "## Pre-flight terms" in err
    assert "3+ characters" in err


def test_print_unused_sources_notice_names_file_and_heading(
    capsys: pytest.CaptureFixture[str],
) -> None:
    from skills.jared.scripts.lib.board import print_unused_sources_notice

    print_unused_sources_notice(
        RedactionReport(
            matches=[],
            scanned_files=[Path("/proj/CLAUDE.local.md"), Path("/proj/.claude/local/people.md")],
            unused_files=[Path("/proj/.claude/local/people.md")],
        ),
        Path("/proj"),
    )
    err = capsys.readouterr().err
    assert err.startswith("warning: pre-flight got nothing to compare from 1 of 2 private files")
    assert ".claude/local/people.md" in err
    assert "/proj/.claude" not in err
    assert "## Pre-flight terms" in err


def test_print_unused_sources_notice_no_op_without_unused_files(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Silent on a clean report with every file used, and on a vacuous one,
    whose own notice already names every file."""
    from skills.jared.scripts.lib.board import print_unused_sources_notice

    print_unused_sources_notice(RedactionReport(matches=[], scanned_files=[Path("z")]), Path("/p"))
    print_unused_sources_notice(
        RedactionReport(
            matches=[],
            scanned_files=[Path("z")],
            unscanned_reason="no-usable-phrases",
            unused_files=[Path("z")],
        ),
        Path("/p"),
    )
    assert capsys.readouterr().err == ""
