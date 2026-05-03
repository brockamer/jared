"""Tests for pre_flight_check (the PII pre-flight redactor) in lib/board.py."""

from __future__ import annotations

from pathlib import Path

from skills.jared.scripts.lib.board import (
    RedactionMatch,
    RedactionReport,
    _extract_phrases,
    pre_flight_check,
)


def test_pre_flight_check_empty_body_clean(tmp_path: Path) -> None:
    """Empty body produces a clean report."""
    report = pre_flight_check("", project_root=tmp_path)
    assert report.clean
    assert report.matches == []


def test_redaction_report_clean_property() -> None:
    """clean is True iff matches is empty."""
    assert RedactionReport(matches=[], scanned_files=[]).clean is True
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
