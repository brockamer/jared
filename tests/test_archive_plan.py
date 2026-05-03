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
    text = "# Plan\n\n**Issue:** #99\n\n## Issues\n\n- #1\n- #2\n\n## Body\n"
    assert ap.parse_referenced_issues(text) == [1, 2]


def test_parse_referenced_issues_neither_form_returns_empty() -> None:
    text = "# Plan\n\nNo issue references at all.\n\n## Body\n"
    assert ap.parse_referenced_issues(text) == []


def test_parse_referenced_issues_bold_line_only_scanned_near_top() -> None:
    filler = "\n".join(f"line {i}" for i in range(40))
    text = f"# Plan\n\n{filler}\n\n**Issue:** #99\n"
    assert ap.parse_referenced_issues(text) == []


def test_parse_referenced_issues_ignores_inline_refs_in_section_prose() -> None:
    """Regression for #86 — the ## Issue section parser previously captured
    everything between the heading and the next heading, then ran a broad
    `re.findall(r'#(\\d+)', section)` over the whole thing. That harvested
    refs from prose paragraphs (bold lines, blockquotes, narrative) the user
    happened to put after the bullet list but before the next heading. Only
    list-item form (or refs at the start of a line) inside the section
    should count.
    """
    text = (
        "# Plan\n\n"
        "## Issue\n\n"
        "- #408\n"
        "- #310 (closed by this plan)\n\n"
        "> agentic-workers note...\n\n"
        "**Goal:** ...closes #310...\n\n"
        "**Issue:** [#408](...); spawns [#410](...), [#411](...), [#412](...).\n\n"
        "## Pre-flight: branch setup\n"
    )
    assert ap.parse_referenced_issues(text) == [408, 310]


def test_parse_referenced_issues_ignores_inline_prose_hash() -> None:
    """Regression for #87 — bare `#NNN` inside flowing prose (e.g.
    "Adapter #2 validating the framework") must not be matched as an issue
    reference. Refs only count when they appear at the start of a line,
    after an optional list marker."""
    text = (
        "# Plan\n\n"
        "## Issue\n\n"
        "- #408\n"
        "- #310\n\n"
        "Adapter #2 validating the framework — see #88 for follow-up.\n\n"
        "## Body\n"
    )
    assert ap.parse_referenced_issues(text) == [408, 310]


def test_parse_referenced_issues_accepts_url_form_in_list_items() -> None:
    """URLs and `owner/repo#N` forms remain valid inside list items — they're
    unambiguous, no prose-interpretation risk."""
    text = "# Plan\n\n## Issue\n\n- https://github.com/o/r/issues/42\n- owner/repo#15\n\n## Body\n"
    assert ap.parse_referenced_issues(text) == [42, 15]


def test_parse_referenced_issues_ignores_prose_line_starting_with_issue_label() -> None:
    """The PR/Issue label is gated behind a list marker — a bare prose line
    like `Issue #99 supersedes this work.` (no `- ` or `* ` prefix) must not
    match. Otherwise PR 3's relaxation re-opens the #87 false-positive class.
    """
    text = (
        "# Plan\n\n## Issue\n\n- #408\n\n"
        "Issue #99 supersedes this work; see also PR #100 for context.\n\n"
        "## Body\n"
    )
    assert ap.parse_referenced_issues(text) == [408]


def test_parse_referenced_issues_accepts_bare_line_at_column_zero() -> None:
    """The pre-existing #48-style bare-line form (no list marker — the ref
    sits at column zero) must still be accepted. A line whose meaningful
    content starts with `#NNN` counts."""
    text = "# Plan\n\n## Issue(s)\n\n#229 — Metric Layer C.0\n#230 — follow-up\n\n## Approach\n"
    assert ap.parse_referenced_issues(text) == [229, 230]


def test_parse_shipped_section_returns_pr_numbers() -> None:
    """The `## Shipped` section is the same shape as `## Issue` — list-item
    refs whose meaningful content starts with `#NNN` or a URL.
    """
    text = "# Plan\n\n## Shipped\n\n- PR #415 (merged 2026-05-02)\n- PR #416\n\n## Body\n"
    assert ap.parse_shipped_section(text) == [415, 416]


def test_parse_shipped_section_empty_when_absent() -> None:
    text = "# Plan\n\n## Issue\n\n- #408\n\n## Body\n"
    assert ap.parse_shipped_section(text) == []


def test_parse_shipped_section_ignores_inline_prose_refs() -> None:
    """Same line-start rule as parse_referenced_issues — refs in narrative
    prose between bullets and the next heading don't count."""
    text = (
        "# Plan\n\n## Shipped\n\n- PR #415\n\n"
        "Adapter #2 was the first one merged.\n"
        "**Note:** also see #888 follow-up.\n\n## Body\n"
    )
    assert ap.parse_shipped_section(text) == [415]


def test_archive_one_archives_via_shipped_section_when_pr_merged(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Regression for #89 — a plan whose tracking issue was recycled (still
    OPEN) but which shipped via a merged PR can archive by declaring the PR
    in a `## Shipped` section. Archive uses the PR merge date."""
    plan = tmp_path / "2026-05-03-recycled-issue.md"
    plan.write_text("# Plan\n\n## Shipped\n\n- PR #415\n\n## Body\n\nDetails.\n")
    patch_gh_by_arg(
        monkeypatch,
        {"issue view 415": '{"state": "MERGED", "closedAt": "2026-05-02T15:30:00Z"}'},
    )

    result = ap.archive_one(plan, "brockamer/findajob", dry_run=True, yes=True)

    captured = capsys.readouterr()
    assert result is not None
    assert "skipping" not in result, f"merged-PR Shipped section must archive; got: {result}"
    assert "archived/2026-05" in result
    assert "2026-05-02" in captured.out


def test_archive_one_skips_shipped_section_with_open_pr(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A `## Shipped` section whose listed PR is not MERGED still refuses to
    archive — the predicate is "evidence of shipping," not just "the section
    exists"."""
    plan = tmp_path / "still-shipping.md"
    plan.write_text("# Plan\n\n## Shipped\n\n- PR #999\n\n## Body\n")
    patch_gh_by_arg(
        monkeypatch,
        {"issue view 999": '{"state": "OPEN", "closedAt": null}'},
    )

    result = ap.archive_one(plan, "brockamer/findajob", dry_run=True, yes=True)

    assert result is not None
    assert "skipping" in result
    assert "[999]" in result


def test_archive_one_shipped_takes_priority_over_issue_section(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """When both `## Issue` (with an open recycled issue) and `## Shipped`
    (with a merged PR) are present, archival uses the Shipped evidence
    and ignores the open issue."""
    plan = tmp_path / "mixed.md"
    plan.write_text("# Plan\n\n## Issue\n\n- #414\n\n## Shipped\n\n- PR #415\n\n## Body\n")
    patch_gh_by_arg(
        monkeypatch,
        {
            "issue view 414": '{"state": "OPEN", "closedAt": null}',
            "issue view 415": '{"state": "MERGED", "closedAt": "2026-05-02T15:30:00Z"}',
        },
    )

    result = ap.archive_one(plan, "brockamer/findajob", dry_run=True, yes=True)

    captured = capsys.readouterr()
    assert result is not None
    assert "skipping" not in result, (
        f"Shipped section must take priority over open Issue refs; got: {result}"
    )
    assert "2026-05-02" in captured.out


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


def test_check_plan_conv_compliance_returns_empty_when_all_present() -> None:
    """All required sections present (case-insensitive heading match,
    'Self-review' or 'Self-review checklist' both count)."""
    text = (
        "# Plan\n\n"
        "## Issue\n\n- #1\n\n"
        "## Documentation Impact\n\n- README.md\n\n"
        "## Self-review checklist\n\n- [x] Tests pass\n"
    )
    assert ap.check_plan_conv_compliance(text) == []


def test_check_plan_conv_compliance_flags_missing_documentation_impact() -> None:
    text = "# Plan\n\n## Issue\n\n- #1\n\n## Self-review\n\n- [x] Tests pass\n"
    missing = ap.check_plan_conv_compliance(text)
    assert "Documentation Impact" in missing
    assert "Self-review" not in missing


def test_check_plan_conv_compliance_flags_missing_self_review() -> None:
    text = "# Plan\n\n## Issue\n\n- #1\n\n## Documentation Impact\n\n- README.md\n"
    missing = ap.check_plan_conv_compliance(text)
    assert "Self-review" in missing
    assert "Documentation Impact" not in missing


def test_check_plan_conv_compliance_flags_both_when_neither_present() -> None:
    text = "# Plan\n\n## Issue\n\n- #1\n\nJust a body, no required sections.\n"
    missing = ap.check_plan_conv_compliance(text)
    assert set(missing) == {"Documentation Impact", "Self-review"}


def test_archive_one_warns_to_stderr_when_plan_lacks_required_sections(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Warn — do NOT refuse — when plan is missing required sections.

    Refusing would compound parser fragility (#86, #87, #88 backlog of bugs)
    and break legitimate edge cases (recycled-issue plans, #89). Warning to
    stderr keeps the operator informed without gating the archival.
    """
    plan = _write_plan(tmp_path, "noncompliant.md", [42])
    # _write_plan creates a plan with `## Issues` and `## Body` only —
    # neither required section is present.
    patch_gh_by_arg(
        monkeypatch,
        {"issue view 42": '{"state": "CLOSED", "closedAt": "2026-05-01T00:00:00Z"}'},
    )

    result = ap.archive_one(plan, "brockamer/jared", dry_run=True, yes=True)

    captured = capsys.readouterr()
    # Archival proceeds (dry-run returns the would-be path, not None).
    assert result is not None
    # Warning lives on stderr, not stdout — the archival output is on stdout.
    assert "Documentation Impact" in captured.err
    assert "Self-review" in captured.err
    assert "warning" in captured.err.lower() or "missing" in captured.err.lower()


def test_archive_one_does_not_warn_when_plan_compliant(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """No warning when both required sections are present."""
    plan = tmp_path / "compliant.md"
    plan.write_text(
        "# Plan\n\n"
        "## Issues\n\n- #42\n\n"
        "## Documentation Impact\n\n- README.md\n\n"
        "## Self-review checklist\n\n- [x] Tests pass\n"
    )
    patch_gh_by_arg(
        monkeypatch,
        {"issue view 42": '{"state": "CLOSED", "closedAt": "2026-05-01T00:00:00Z"}'},
    )

    result = ap.archive_one(plan, "brockamer/jared", dry_run=True, yes=True)

    captured = capsys.readouterr()
    assert result is not None
    assert "Documentation Impact" not in captured.err
    assert "Self-review" not in captured.err


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
