"""Tests for pre_flight_check (the PII pre-flight redactor) in lib/board.py."""

from __future__ import annotations

from pathlib import Path

from skills.jared.scripts.lib.board import (
    RedactionMatch,
    RedactionReport,
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
