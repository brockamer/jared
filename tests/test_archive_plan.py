"""Tests for archive-plan.py — accept MERGED PRs as shipped; surface skip reasons.

Regressions targeted:
- `gh issue view <N>` returns state=MERGED for PRs. A merged PR is a valid
  "shipped" signal; it must not look like an open blocker.
- The --plan single-file path previously discarded archive_one's return
  value, so a skip (e.g. "not all issues closed") produced exit=0 with
  no output — indistinguishable from success.
"""

from __future__ import annotations

import importlib.util
from importlib.machinery import SourceFileLoader
from pathlib import Path
from types import ModuleType

import pytest

from tests.conftest import patch_gh_by_arg

REPO_ROOT = Path(__file__).parents[1]
SCRIPT_PATH = REPO_ROOT / "skills" / "jared" / "scripts" / "archive-plan.py"


def _import_archive_plan() -> ModuleType:
    loader = SourceFileLoader("archive_plan", str(SCRIPT_PATH))
    spec = importlib.util.spec_from_loader("archive_plan", loader)
    assert spec is not None
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


ap = _import_archive_plan()


def _write_plan(tmp_path: Path, filename: str, refs: list[int]) -> Path:
    refs_section = "\n".join(f"- #{n}" for n in refs)
    plan = tmp_path / filename
    plan.write_text(f"# A plan\n\n## Issues\n\n{refs_section}\n\n## Body\n\nStuff.\n")
    return plan


def test_parse_referenced_issues_extracts_refs_regardless_of_ref_type() -> None:
    text = "# Plan\n\n## Issues\n\n- #42 (issue)\n- #98 (PR)\n\n## Body\n"
    assert ap.parse_referenced_issues(text) == [42, 98]


def test_parse_referenced_issues_heading_only() -> None:
    text = "# Plan\n\n## Issue\n\n- #7\n\n## Body\n"
    assert ap.parse_referenced_issues(text) == [7]


def test_parse_referenced_issues_bold_line_issue() -> None:
    text = "# Design\n\n**Issue:** brockamer/jared#35\n**Status:** Spec\n"
    assert ap.parse_referenced_issues(text) == [35]


def test_parse_referenced_issues_bold_line_tracking_issue() -> None:
    text = "# Plan\n\n**Goal:** ship X.\n\n**Tracking issue:** brockamer/jared#35.\n"
    assert ap.parse_referenced_issues(text) == [35]


def test_parse_referenced_issues_bold_line_plural_with_multiple_refs() -> None:
    text = "# Plan\n\n**Issues:** #12, owner/repo#13, https://github.com/o/r/issues/14\n"
    assert ap.parse_referenced_issues(text) == [12, 13, 14]


def test_parse_referenced_issues_heading_wins_over_bold_line() -> None:
    text = (
        "# Plan\n\n**Issue:** #99\n\n## Issues\n\n- #1\n- #2\n\n## Body\n"
    )
    assert ap.parse_referenced_issues(text) == [1, 2]


def test_parse_referenced_issues_neither_form_returns_empty() -> None:
    text = "# Plan\n\nNo issue references at all.\n\n## Body\n"
    assert ap.parse_referenced_issues(text) == []


def test_parse_referenced_issues_bold_line_only_scanned_near_top() -> None:
    filler = "\n".join(f"line {i}" for i in range(40))
    text = f"# Plan\n\n{filler}\n\n**Issue:** #99\n"
    assert ap.parse_referenced_issues(text) == []


def test_archive_one_accepts_merged_pr_as_shipped(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    plan = _write_plan(tmp_path, "2026-04-19-native-deps.md", [98])
    patch_gh_by_arg(
        monkeypatch,
        {"issue view 98": '{"state": "MERGED", "closedAt": "2026-04-20T12:00:00Z"}'},
    )

    result = ap.archive_one(plan, "brockamer/findajob", dry_run=True, yes=True)

    captured = capsys.readouterr()
    assert result is not None
    assert "skipping" not in result, f"merged PR must not be skipped; got: {result}"
    assert "archived/2026-04" in result
    assert "2026-04-20" in captured.out


def test_archive_one_still_skips_open_issue(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    plan = _write_plan(tmp_path, "still-open.md", [10])
    patch_gh_by_arg(
        monkeypatch,
        {"issue view 10": '{"state": "OPEN", "closedAt": null}'},
    )

    result = ap.archive_one(plan, "brockamer/findajob", dry_run=True, yes=True)

    assert result is not None
    assert "skipping" in result
    assert "[10]" in result


def test_main_plan_path_surfaces_skip_reason(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    plan = _write_plan(tmp_path, "plan.md", [11])
    patch_gh_by_arg(
        monkeypatch,
        {"issue view 11": '{"state": "OPEN", "closedAt": null}'},
    )

    rc = ap.main(["--plan", str(plan), "--repo", "brockamer/findajob", "--dry-run", "--yes"])

    captured = capsys.readouterr()
    assert rc == 0
    assert "skipping" in captured.out, (
        f"--plan path must surface skip reasons; stdout was {captured.out!r}"
    )
