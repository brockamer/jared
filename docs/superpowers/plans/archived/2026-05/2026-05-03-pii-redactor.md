---
**Shipped in #102 on 2026-05-03. Final decisions captured in issue body.**
---

# PII Pre-Flight Redactor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Issue:** brockamer/jared#102

**Goal:** Add a runtime pre-flight in `lib/board.py` that scans body content for matches against gitignored claude-shaped local files, refusing to post when private content would leak into a public GitHub issue or comment.

**Architecture:** Pure module-level function `pre_flight_check(body, project_root) -> RedactionReport` plus a `print_redaction_diff` formatter. Wired into `_cmd_file` and `_cmd_comment` immediately after `resolve_body()`. Allowlist via `git ls-files` content lookup (anything in tracked files is already public, so don't flag). Phrase-based matching (≥3 words / ≥20 chars) keeps signal high vs noise. Process-local cache keyed on `project_root`.

**Tech Stack:** Python 3.11+, dataclasses, pathlib, pytest, git CLI (via existing `Board.run_gh*` patterns or direct `subprocess.run` for `git ls-files`).

---

## File Structure

**New files:**
- `tests/test_pre_flight.py` — unit tests for `pre_flight_check`, `print_redaction_diff`, helpers
- `skills/jared/references/pii-pre-flight.md` — operator reference doc

**Modified files:**
- `skills/jared/scripts/lib/board.py` — add dataclasses + `pre_flight_check` + `print_redaction_diff` + helpers
- `skills/jared/scripts/jared` (CLI) — wire pre-flight into `_cmd_file` and `_cmd_comment`
- `tests/test_cmd_file.py` — integration tests
- `tests/test_cmd_comment.py` — integration tests
- `skills/jared/SKILL.md` — replace future-tense #102 reference with present-tense doctrine
- `skills/jared/references/operations.md` — cross-reference new doc
- `commands/jared-file.md` — short note on pre-flight
- `commands/jared-wrap.md` — short note on pre-flight

---

## Task 1: Dataclasses + skeleton

**Files:**
- Modify: `skills/jared/scripts/lib/board.py` (append at end)
- Test: `tests/test_pre_flight.py` (create)

- [ ] **Step 1: Create test file with failing skeleton test**

Create `tests/test_pre_flight.py`:

```python
"""Tests for pre_flight_check (the PII pre-flight redactor) in lib/board.py."""

from __future__ import annotations

from pathlib import Path

import pytest

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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
source .venv/bin/activate && pytest tests/test_pre_flight.py -v
```

Expected: ImportError or ModuleAttributeError (`RedactionMatch`, `RedactionReport`, `pre_flight_check` don't exist yet).

- [ ] **Step 3: Add dataclasses + skeleton to lib/board.py**

Append to the end of `skills/jared/scripts/lib/board.py`:

```python
# ---------- PII pre-flight redactor (#102) ----------


@dataclass
class RedactionMatch:
    """One body line that matched a phrase from a gitignored claude-shaped file."""

    line_no: int
    line_text: str
    matched_phrase: str
    source_file: Path


@dataclass
class RedactionReport:
    """Result of pre_flight_check. Pure data; caller decides how to react."""

    matches: list[RedactionMatch]
    scanned_files: list[Path]

    @property
    def clean(self) -> bool:
        return not self.matches


def pre_flight_check(body: str, project_root: Path) -> RedactionReport:
    """Scan body against gitignored claude-shaped files; return a structured report.

    Skeleton — returns a clean report unconditionally. Subsequent tasks fill
    in phrase extraction, file discovery, allowlist filtering, and caching.
    """
    return RedactionReport(matches=[], scanned_files=[])
```

- [ ] **Step 4: Run tests, verify they pass**

```bash
pytest tests/test_pre_flight.py -v
```

Expected: PASS for both tests.

- [ ] **Step 5: Lint, type-check, full suite**

```bash
ruff check . && ruff format --check . && mypy && pytest
```

Expected: all clean, 244 passed (242 existing + 2 new).

- [ ] **Step 6: Commit**

```bash
git add tests/test_pre_flight.py skills/jared/scripts/lib/board.py
git commit -m "feat(redactor): RedactionReport dataclasses + skeleton (#102)"
```

---

## Task 2: Phrase extraction from a single file

**Files:**
- Modify: `skills/jared/scripts/lib/board.py` (add `_extract_phrases`)
- Modify: `tests/test_pre_flight.py` (append tests)

- [ ] **Step 1: Add tests for `_extract_phrases`**

Append to `tests/test_pre_flight.py`:

```python
from skills.jared.scripts.lib.board import _extract_phrases


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
```

- [ ] **Step 2: Run, verify they fail**

```bash
pytest tests/test_pre_flight.py -v
```

Expected: 4 new tests fail with `ImportError` or `AttributeError` on `_extract_phrases`.

- [ ] **Step 3: Implement `_extract_phrases`**

In `lib/board.py`, between the dataclasses and `pre_flight_check`:

```python
# Lines shorter than this (post-strip) are too generic to be useful private content.
_MIN_PHRASE_CHARS = 20
# Phrases with fewer words than this match too eagerly (any common word in a
# local file would flag the body).
_MIN_PHRASE_WORDS = 3
# Markdown-leader characters stripped from line starts before length checks.
_MARKDOWN_LEADER_RE = re.compile(r"^[\s\-\*\>#\|`]+")


def _extract_phrases(file_path: Path) -> list[str]:
    """Extract candidate phrases from one gitignored claude-shaped file.

    A phrase is a line of the file that — after stripping markdown leaders
    (`-`, `*`, `>`, `#`, `|`, backticks, leading whitespace) — has at least
    `_MIN_PHRASE_WORDS` whitespace-separated words AND at least
    `_MIN_PHRASE_CHARS` characters. Returns the cleaned phrases in file order.

    Missing file → empty list, not an exception (the caller has already
    decided this file is in scope; we don't want to second-guess).
    """
    try:
        text = file_path.read_text(encoding="utf-8")
    except (FileNotFoundError, UnicodeDecodeError):
        return []
    out = []
    for raw in text.splitlines():
        cleaned = _MARKDOWN_LEADER_RE.sub("", raw).rstrip()
        if len(cleaned) < _MIN_PHRASE_CHARS:
            continue
        if len(cleaned.split()) < _MIN_PHRASE_WORDS:
            continue
        out.append(cleaned)
    return out
```

- [ ] **Step 4: Run, verify pass**

```bash
pytest tests/test_pre_flight.py -v
```

Expected: 6 PASS.

- [ ] **Step 5: Lint, type-check, full suite**

```bash
ruff check . && ruff format --check . && mypy && pytest
```

Expected: all clean.

- [ ] **Step 6: Commit**

```bash
git add tests/test_pre_flight.py skills/jared/scripts/lib/board.py
git commit -m "feat(redactor): extract candidate phrases from claude-shaped files (#102)"
```

---

## Task 3: Discover gitignored claude-shaped files

**Files:**
- Modify: `skills/jared/scripts/lib/board.py` (add `_find_claude_shaped_files`)
- Modify: `tests/test_pre_flight.py` (append tests)

- [ ] **Step 1: Add tests**

Append to `tests/test_pre_flight.py`:

```python
from skills.jared.scripts.lib.board import _find_claude_shaped_files


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
```

- [ ] **Step 2: Run, verify they fail**

```bash
pytest tests/test_pre_flight.py -v
```

Expected: 5 new tests fail on missing `_find_claude_shaped_files`.

- [ ] **Step 3: Implement file discovery**

In `lib/board.py`, after `_extract_phrases`:

```python
# Standard locations for gitignored claude-shaped local content.
_CLAUDE_SHAPED_PATTERNS = (
    "CLAUDE.local.md",
    ".claude/CLAUDE.local.md",
    ".claude/local/*.md",
)


def _find_claude_shaped_files(project_root: Path) -> list[Path]:
    """Locate gitignored claude-shaped files under `project_root`.

    Checks the standard patterns: `CLAUDE.local.md`, `.claude/CLAUDE.local.md`,
    `.claude/local/*.md`. Returns absolute paths in deterministic order.

    If `project_root` isn't a git repo (no `.git/` directory), returns an
    empty list — the redactor's allowlist semantics depend on git, so without
    git there's no meaningful scan to do.
    """
    if not (project_root / ".git").exists():
        return []
    found = []
    for pattern in _CLAUDE_SHAPED_PATTERNS:
        if "*" in pattern:
            # glob the pattern's directory
            base = project_root / pattern.rsplit("/", 1)[0]
            glob_pat = pattern.rsplit("/", 1)[1]
            if base.is_dir():
                found.extend(sorted(base.glob(glob_pat)))
        else:
            p = project_root / pattern
            if p.is_file():
                found.append(p)
    return found
```

- [ ] **Step 4: Run, verify pass**

```bash
pytest tests/test_pre_flight.py -v
```

Expected: 11 PASS.

- [ ] **Step 5: Lint + type-check + full suite**

```bash
ruff check . && ruff format --check . && mypy && pytest
```

Expected: all clean.

- [ ] **Step 6: Commit**

```bash
git add tests/test_pre_flight.py skills/jared/scripts/lib/board.py
git commit -m "feat(redactor): locate gitignored claude-shaped files (#102)"
```

---

## Task 4: End-to-end matching (no allowlist yet)

**Files:**
- Modify: `skills/jared/scripts/lib/board.py` (fill in `pre_flight_check`)
- Modify: `tests/test_pre_flight.py` (append tests)

- [ ] **Step 1: Add tests**

Append to `tests/test_pre_flight.py`:

```python
def test_pre_flight_check_match_in_CLAUDE_local_flagged(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    (tmp_path / "CLAUDE.local.md").write_text(
        "the deploy host is internal-foo-7.corp.example\n"
    )
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
    (tmp_path / "CLAUDE.local.md").write_text(
        "the deploy host is internal-foo-7.corp.example\n"
    )
    body = "Wholly unrelated body text about the public weather service.\n"
    report = pre_flight_check(body, project_root=tmp_path)
    assert report.clean


def test_pre_flight_check_match_in_dot_claude_local_md_flagged(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    local = tmp_path / ".claude" / "local"
    local.mkdir(parents=True)
    (local / "ops.md").write_text(
        "credentials live at /opt/secrets/foo.json on the prod host\n"
    )
    body = "Here's the recipe: credentials live at /opt/secrets/foo.json on the prod host.\n"
    report = pre_flight_check(body, project_root=tmp_path)
    assert not report.clean
    assert report.matches[0].source_file == local / "ops.md"


def test_pre_flight_check_no_git_repo_returns_clean(tmp_path: Path) -> None:
    (tmp_path / "CLAUDE.local.md").write_text(
        "the deploy host is internal-foo-7.corp.example\n"
    )
    body = "the deploy host is internal-foo-7.corp.example\n"
    report = pre_flight_check(body, project_root=tmp_path)
    assert report.clean
    assert report.scanned_files == []


def test_pre_flight_check_records_line_number(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    (tmp_path / "CLAUDE.local.md").write_text(
        "the deploy host is internal-foo-7.corp.example\n"
    )
    body = "line 1\nline 2\nthe deploy host is internal-foo-7.corp.example\nline 4\n"
    report = pre_flight_check(body, project_root=tmp_path)
    assert report.matches[0].line_no == 3
```

- [ ] **Step 2: Run, verify failures**

```bash
pytest tests/test_pre_flight.py -v
```

Expected: 5 new tests fail (`pre_flight_check` still returns clean unconditionally).

- [ ] **Step 3: Fill in `pre_flight_check`**

Replace the `pre_flight_check` skeleton in `lib/board.py` with:

```python
def pre_flight_check(body: str, project_root: Path) -> RedactionReport:
    """Scan body against gitignored claude-shaped files; return a structured report.

    Pure function — no I/O on caller's behalf, no exit, no print. Caller
    decides what to do with a non-clean report.
    """
    files = _find_claude_shaped_files(project_root)
    if not files:
        return RedactionReport(matches=[], scanned_files=[])

    # Index every candidate phrase to its source file for diagnostic output.
    phrase_to_source: dict[str, Path] = {}
    for f in files:
        for phrase in _extract_phrases(f):
            phrase_to_source.setdefault(phrase, f)

    matches: list[RedactionMatch] = []
    body_lines = body.splitlines()
    for phrase, source in phrase_to_source.items():
        if phrase in body:
            for i, line in enumerate(body_lines, start=1):
                if phrase in line:
                    matches.append(
                        RedactionMatch(
                            line_no=i,
                            line_text=line,
                            matched_phrase=phrase,
                            source_file=source,
                        )
                    )
                    break  # first hit per phrase is enough
    return RedactionReport(matches=matches, scanned_files=files)
```

- [ ] **Step 4: Run, verify pass**

```bash
pytest tests/test_pre_flight.py -v
```

Expected: 16 PASS.

- [ ] **Step 5: Lint + type-check + full suite**

```bash
ruff check . && ruff format --check . && mypy && pytest
```

Expected: all clean.

- [ ] **Step 6: Commit**

```bash
git add tests/test_pre_flight.py skills/jared/scripts/lib/board.py
git commit -m "feat(redactor): wire pre_flight_check end-to-end (#102)"
```

---

## Task 5: Allowlist via tracked content

**Files:**
- Modify: `skills/jared/scripts/lib/board.py` (add tracked-content lookup, filter phrases)
- Modify: `tests/test_pre_flight.py` (append tests)

- [ ] **Step 1: Add tests**

Append to `tests/test_pre_flight.py`:

```python
import subprocess


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
    already public; the redactor must not flag it."""
    _git_init_with_tracked(
        tmp_path,
        {"README.md": "Our deploy host is internal-foo-7.corp.example.\n"},
    )
    (tmp_path / "CLAUDE.local.md").write_text(
        "Our deploy host is internal-foo-7.corp.example.\n"
    )
    body = "Issue: Our deploy host is internal-foo-7.corp.example. is flaky.\n"
    report = pre_flight_check(body, project_root=tmp_path)
    assert report.clean, (
        f"phrase that exists in tracked README is allowlisted; got matches: "
        f"{report.matches}"
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
    (tmp_path / "CLAUDE.local.md").write_text(
        "Our deploy host is internal-foo-7.corp.example.\n"
    )
    body = "Issue: Our deploy host is internal-foo-7.corp.example. is flaky.\n"
    report = pre_flight_check(body, project_root=tmp_path)
    assert not report.clean
    assert report.matches[0].matched_phrase.startswith("Our deploy host")
```

- [ ] **Step 2: Run, verify failures**

```bash
pytest tests/test_pre_flight.py::test_pre_flight_check_allowlists_phrase_present_in_tracked_README -v
```

Expected: FAIL — current matcher doesn't filter against tracked content.

- [ ] **Step 3: Add tracked-content lookup**

In `lib/board.py`, after `_find_claude_shaped_files`:

```python
def _read_tracked_content(project_root: Path) -> str:
    """Concatenate every tracked file's content into one searchable blob.

    `git ls-files` enumerates tracked paths. We read each and join into
    one string so the allowlist check is a single `phrase in tracked` per
    candidate phrase. Decoding errors on binary files are swallowed —
    binary files can't contain text phrases anyway.
    """
    if not (project_root / ".git").exists():
        return ""
    try:
        out = subprocess.run(
            ["git", "ls-files"],
            cwd=project_root,
            capture_output=True,
            text=True,
            check=True,
        ).stdout
    except (subprocess.CalledProcessError, FileNotFoundError):
        return ""
    chunks = []
    for relpath in out.splitlines():
        f = project_root / relpath
        try:
            chunks.append(f.read_text(encoding="utf-8"))
        except (FileNotFoundError, UnicodeDecodeError, IsADirectoryError):
            continue
    return "\n".join(chunks)
```

Then update `pre_flight_check` to filter:

```python
def pre_flight_check(body: str, project_root: Path) -> RedactionReport:
    """Scan body against gitignored claude-shaped files; return a structured report."""
    files = _find_claude_shaped_files(project_root)
    if not files:
        return RedactionReport(matches=[], scanned_files=[])

    tracked = _read_tracked_content(project_root)

    phrase_to_source: dict[str, Path] = {}
    for f in files:
        for phrase in _extract_phrases(f):
            # Allowlist: a phrase already in any tracked file is public.
            if tracked and phrase in tracked:
                continue
            phrase_to_source.setdefault(phrase, f)

    matches: list[RedactionMatch] = []
    body_lines = body.splitlines()
    for phrase, source in phrase_to_source.items():
        if phrase in body:
            for i, line in enumerate(body_lines, start=1):
                if phrase in line:
                    matches.append(
                        RedactionMatch(
                            line_no=i,
                            line_text=line,
                            matched_phrase=phrase,
                            source_file=source,
                        )
                    )
                    break
    return RedactionReport(matches=matches, scanned_files=files)
```

- [ ] **Step 4: Run, verify pass**

```bash
pytest tests/test_pre_flight.py -v
```

Expected: 18 PASS.

- [ ] **Step 5: Lint + type-check + full suite**

```bash
ruff check . && ruff format --check . && mypy && pytest
```

Expected: all clean.

- [ ] **Step 6: Commit**

```bash
git add tests/test_pre_flight.py skills/jared/scripts/lib/board.py
git commit -m "feat(redactor): allowlist phrases that live in tracked content (#102)"
```

---

## Task 6: Process-local cache

**Files:**
- Modify: `skills/jared/scripts/lib/board.py` (add cache, instrument scan)
- Modify: `tests/test_pre_flight.py` (append cache test)

- [ ] **Step 1: Add cache test**

Append to `tests/test_pre_flight.py`:

```python
def test_pre_flight_check_caches_per_project_root(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Second call to the same project_root reuses scan results — no second
    `git ls-files` invocation."""
    _git_init_with_tracked(tmp_path, {"README.md": "public.\n"})
    (tmp_path / "CLAUDE.local.md").write_text(
        "the deploy host is internal-foo-7.corp.example\n"
    )

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
```

- [ ] **Step 2: Run, verify it fails**

```bash
pytest tests/test_pre_flight.py::test_pre_flight_check_caches_per_project_root -v
```

Expected: FAIL — `_clear_pre_flight_cache` doesn't exist; or the call count is 2 (no caching).

- [ ] **Step 3: Add cache + helper**

In `lib/board.py`, replace the `pre_flight_check` body with a cached implementation:

```python
# Process-local cache for pre_flight_check scan inputs (phrases + tracked
# content). Keyed on the resolved absolute project_root path. Survives only
# within one `jared` invocation; that's the intended scope per the spec.
_PRE_FLIGHT_CACHE: dict[Path, tuple[dict[str, Path], list[Path]]] = {}


def _clear_pre_flight_cache() -> None:
    """Test seam — drops the in-process cache."""
    _PRE_FLIGHT_CACHE.clear()


def pre_flight_check(body: str, project_root: Path) -> RedactionReport:
    """Scan body against gitignored claude-shaped files; return a structured report."""
    root = project_root.resolve()
    cached = _PRE_FLIGHT_CACHE.get(root)
    if cached is None:
        files = _find_claude_shaped_files(root)
        if not files:
            _PRE_FLIGHT_CACHE[root] = ({}, [])
            return RedactionReport(matches=[], scanned_files=[])
        tracked = _read_tracked_content(root)
        phrase_to_source: dict[str, Path] = {}
        for f in files:
            for phrase in _extract_phrases(f):
                if tracked and phrase in tracked:
                    continue
                phrase_to_source.setdefault(phrase, f)
        _PRE_FLIGHT_CACHE[root] = (phrase_to_source, files)
        cached = _PRE_FLIGHT_CACHE[root]

    phrase_to_source, scanned_files = cached
    if not phrase_to_source:
        return RedactionReport(matches=[], scanned_files=scanned_files)

    matches: list[RedactionMatch] = []
    body_lines = body.splitlines()
    for phrase, source in phrase_to_source.items():
        if phrase in body:
            for i, line in enumerate(body_lines, start=1):
                if phrase in line:
                    matches.append(
                        RedactionMatch(
                            line_no=i,
                            line_text=line,
                            matched_phrase=phrase,
                            source_file=source,
                        )
                    )
                    break
    return RedactionReport(matches=matches, scanned_files=scanned_files)
```

- [ ] **Step 4: Add `_clear_pre_flight_cache` to fixture in tests**

Append a fixture to `tests/test_pre_flight.py` near the top (after imports):

```python
@pytest.fixture(autouse=True)
def _clear_redactor_cache() -> None:
    """Auto-applied — every test starts with a fresh redactor cache."""
    from skills.jared.scripts.lib.board import _clear_pre_flight_cache

    _clear_pre_flight_cache()
```

- [ ] **Step 5: Run, verify pass**

```bash
pytest tests/test_pre_flight.py -v
```

Expected: 19 PASS.

- [ ] **Step 6: Lint + type-check + full suite**

```bash
ruff check . && ruff format --check . && mypy && pytest
```

Expected: all clean.

- [ ] **Step 7: Commit**

```bash
git add tests/test_pre_flight.py skills/jared/scripts/lib/board.py
git commit -m "feat(redactor): process-local cache keyed on project_root (#102)"
```

---

## Task 7: `print_redaction_diff` formatter

**Files:**
- Modify: `skills/jared/scripts/lib/board.py` (add `print_redaction_diff`)
- Modify: `tests/test_pre_flight.py` (append test)

- [ ] **Step 1: Add test**

Append to `tests/test_pre_flight.py`:

```python
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
```

- [ ] **Step 2: Run, verify it fails**

```bash
pytest tests/test_pre_flight.py::test_print_redaction_diff_format -v
```

Expected: FAIL on missing `print_redaction_diff`.

- [ ] **Step 3: Implement `print_redaction_diff`**

In `lib/board.py`, after `pre_flight_check`:

```python
def print_redaction_diff(report: RedactionReport, *, file: Any = None) -> None:
    """Format a non-clean RedactionReport for stderr.

    Caller is responsible for the exit code; this only writes the diagnostic.
    """
    f = file if file is not None else sys.stderr
    print(
        "error: pre-flight redaction check failed — body references content from",
        file=f,
    )
    print(
        "gitignored claude-shaped local files. Refusing to post.",
        file=f,
    )
    print("", file=f)
    n = len(report.matches)
    distinct_files = sorted({m.source_file for m in report.matches})
    print(
        f"  {n} match{'es' if n != 1 else ''} across {len(distinct_files)} file{'s' if len(distinct_files) != 1 else ''}:",
        file=f,
    )
    for m in report.matches:
        print(f'    line {m.line_no}: "{m.line_text}"', file=f)
        print(f"      ↳ matches {m.source_file}", file=f)
    print("", file=f)
    print("  next steps:", file=f)
    print("    1. Re-issue the call with private content removed.", file=f)
    print(
        "    2. OR add the matched phrase to a tracked file if it's intentionally public.",
        file=f,
    )
```

- [ ] **Step 4: Run, verify pass**

```bash
pytest tests/test_pre_flight.py -v
```

Expected: 20 PASS.

- [ ] **Step 5: Lint + type-check + full suite**

```bash
ruff check . && ruff format --check . && mypy && pytest
```

Expected: all clean.

- [ ] **Step 6: Commit**

```bash
git add tests/test_pre_flight.py skills/jared/scripts/lib/board.py
git commit -m "feat(redactor): print_redaction_diff stderr formatter (#102)"
```

---

## Task 8: Wire pre-flight into `_cmd_file`

**Files:**
- Modify: `skills/jared/scripts/jared` (CLI; import + integration in `_cmd_file`)
- Modify: `tests/test_cmd_file.py` (append integration tests)

- [ ] **Step 1: Add integration tests using real fixtures**

The CLI imports `pre_flight_check` via `from lib.board import ...`, which captures the function reference at import time. Monkeypatching `skills.jared.scripts.lib.board.pre_flight_check` would not intercept the CLI's bound reference (the dual-import-path gotcha — see CLAUDE.md and `tests/conftest.py`'s top-of-file docstring). Real fixtures (git init + CLAUDE.local.md in `tmp_path` + `monkeypatch.chdir`) are also the stronger end-to-end test.

Append to `tests/test_cmd_file.py`:

```python
import subprocess as _subprocess


def _git_init_with_claude_local(tmp_path: Path, claude_local_content: str) -> None:
    """Initialize a git repo at tmp_path and drop a CLAUDE.local.md.

    The redactor only scans files when a `.git/` directory exists, so we
    actually `git init` rather than just `mkdir .git/`. Tracked content is
    empty (no README) — every claude-local phrase is therefore on the
    redactor's flag list, not on the allowlist.
    """
    _subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    _subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=tmp_path,
        check=True,
    )
    _subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, check=True)
    (tmp_path / "CLAUDE.local.md").write_text(claude_local_content)


def test_cmd_file_refuses_on_dirty_pre_flight_report(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """If pre_flight_check returns a non-clean report, _cmd_file must refuse
    before any gh call. Operator gets a stderr diff explaining why."""
    board_md = _write_full_board(tmp_path)
    leaky_phrase = "the deploy host is internal-foo-7.corp.example"
    _git_init_with_claude_local(tmp_path, leaky_phrase + "\n")

    # CLI calls pre_flight_check with project_root=Path.cwd(), so chdir to
    # tmp_path is what makes the redactor scan our fixture.
    monkeypatch.chdir(tmp_path)

    from skills.jared.scripts.lib.board import _clear_pre_flight_cache

    _clear_pre_flight_cache()

    calls = _routed_fake(monkeypatch)

    mod = import_cli()
    rc = mod.main(
        [
            "--board",
            str(board_md),
            "file",
            "--title",
            "Test",
            "--body",
            f"While testing I noticed {leaky_phrase} stops responding under load.",
            "--priority",
            "Low",
        ]
    )
    captured = capsys.readouterr()
    assert rc == 2, captured.err
    assert "pre-flight redaction check failed" in captured.err
    # gh issue create must not have been invoked.
    assert not any("issue" in c and "create" in c for c in calls), (
        f"redactor must short-circuit before gh; calls: {calls}"
    )


def test_cmd_file_proceeds_on_clean_pre_flight_report(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A clean body (no overlap with CLAUDE.local.md) lets the existing flow
    continue normally."""
    board_md = _write_full_board(tmp_path)
    _git_init_with_claude_local(
        tmp_path, "the deploy host is internal-foo-7.corp.example\n"
    )

    monkeypatch.chdir(tmp_path)
    from skills.jared.scripts.lib.board import _clear_pre_flight_cache

    _clear_pre_flight_cache()

    calls = _routed_fake(monkeypatch)

    mod = import_cli()
    rc = mod.main(
        [
            "--board",
            str(board_md),
            "file",
            "--title",
            "Test",
            "--body",
            "Wholly unrelated body about the public weather service.",
            "--priority",
            "Low",
        ]
    )
    captured = capsys.readouterr()
    assert rc == 0, captured.err
    # Normal flow: gh issue create did happen.
    assert any("issue" in c and "create" in c for c in calls)


def test_cmd_file_clean_when_no_claude_local(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The redactor must be a no-op when there's no CLAUDE.local.md anywhere
    — this guards every existing test in this file. Without this guarantee,
    the existing 13 tests would all break the moment Task 8 lands."""
    board_md = _write_full_board(tmp_path)
    # No CLAUDE.local.md, no .git/. The existing _routed_fake gives us a
    # clean filing path; pre_flight_check should return empty, gh proceeds.
    calls = _routed_fake(monkeypatch)

    mod = import_cli()
    rc = mod.main(
        [
            "--board",
            str(board_md),
            "file",
            "--title",
            "Test",
            "--body",
            "Some content with no special meaning.",
            "--priority",
            "Low",
        ]
    )
    captured = capsys.readouterr()
    assert rc == 0, captured.err
    assert any("issue" in c and "create" in c for c in calls)
```

- [ ] **Step 2: Run, verify the dirty-report test fails**

```bash
pytest tests/test_cmd_file.py::test_cmd_file_refuses_on_dirty_pre_flight_report -v
```

Expected: FAIL — current `_cmd_file` doesn't call `pre_flight_check`.

- [ ] **Step 3: Wire pre-flight into `_cmd_file`**

In `skills/jared/scripts/jared`, update the imports near the top:

```python
from lib.board import (  # type: ignore[import-not-found]  # noqa: E402
    Board,
    BoardConfigError,
    FieldNotFound,
    GhInvocationError,
    ItemNotFound,
    OptionNotFound,
    check_closed_not_done,
    fetch_recent_comments_batch,
    pre_flight_check,
    print_redaction_diff,
    resolve_body,
)
```

In `_cmd_file`, immediately after the `body = resolve_body(...)` line:

```python
    body = resolve_body(args.body, args.body_file)

    # Pre-flight redaction check (#102): refuse to post when body references
    # content from gitignored claude-shaped local files. Pure stderr-only
    # diagnostic; no temp file is staged when we refuse here.
    report = pre_flight_check(body, project_root=Path.cwd())
    if not report.clean:
        print_redaction_diff(report, file=sys.stderr)
        return 2

    with tempfile.NamedTemporaryFile(
```

- [ ] **Step 4: Run, verify pass**

```bash
pytest tests/test_cmd_file.py -v
```

Expected: all green (existing 11 + 3 new = 14).

- [ ] **Step 5: Full suite**

```bash
ruff check . && ruff format --check . && mypy && pytest
```

Expected: all clean.

- [ ] **Step 6: Commit**

```bash
git add skills/jared/scripts/jared tests/test_cmd_file.py
git commit -m "feat(file): pre-flight redactor in _cmd_file (#102)"
```

---

## Task 9: Wire pre-flight into `_cmd_comment`

**Files:**
- Modify: `skills/jared/scripts/jared` (CLI; integration in `_cmd_comment`)
- Modify: `tests/test_cmd_comment.py` (append integration tests)

- [ ] **Step 1: Add integration tests using real fixtures**

Same shape as Task 8 — use real `git init` + `CLAUDE.local.md` + `monkeypatch.chdir(tmp_path)` rather than monkeypatching `pre_flight_check` (which would fail due to the dual-import-path gotcha).

Append to `tests/test_cmd_comment.py`:

```python
import subprocess as _subprocess


def _git_init_with_claude_local(tmp_path: Path, claude_local_content: str) -> None:
    """Same shape as test_cmd_file.py's helper. Duplicated rather than
    extracted because the two files don't share a private helper module
    today and adding one for two callers is over-engineering."""
    _subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    _subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=tmp_path,
        check=True,
    )
    _subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, check=True)
    (tmp_path / "CLAUDE.local.md").write_text(claude_local_content)


def test_cmd_comment_refuses_on_dirty_pre_flight_report(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    board_md = write_minimal_board(tmp_path)
    leaky_phrase = "credentials live at /opt/secrets/foo.json on prod"
    _git_init_with_claude_local(tmp_path, leaky_phrase + "\n")

    monkeypatch.chdir(tmp_path)
    from skills.jared.scripts.lib.board import _clear_pre_flight_cache

    _clear_pre_flight_cache()

    calls, _bodies = _patch_gh_capturing_body_file(monkeypatch)

    mod = import_cli()
    rc = mod.main(
        [
            "--board",
            str(board_md),
            "comment",
            "42",
            "--body",
            f"Note: {leaky_phrase}.",
        ]
    )
    captured = capsys.readouterr()
    assert rc == 2, captured.err
    assert "pre-flight redaction check failed" in captured.err
    assert not any("issue" in c and "comment" in c for c in calls), (
        f"redactor must short-circuit before gh; calls: {calls}"
    )


def test_cmd_comment_proceeds_on_clean_pre_flight_report(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    board_md = write_minimal_board(tmp_path)
    _git_init_with_claude_local(
        tmp_path, "credentials live at /opt/secrets/foo.json on prod\n"
    )

    monkeypatch.chdir(tmp_path)
    from skills.jared.scripts.lib.board import _clear_pre_flight_cache

    _clear_pre_flight_cache()

    calls, bodies = _patch_gh_capturing_body_file(monkeypatch)

    mod = import_cli()
    rc = mod.main(
        [
            "--board",
            str(board_md),
            "comment",
            "42",
            "--body",
            "perfectly safe note with no overlap",
        ]
    )
    captured = capsys.readouterr()
    assert rc == 0, captured.err
    assert bodies == ["perfectly safe note with no overlap"]


def test_cmd_comment_clean_when_no_claude_local(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Mirror of the test_cmd_file.py guard test: no CLAUDE.local.md → no
    redactor activity → existing tests stay green."""
    board_md = write_minimal_board(tmp_path)
    body_file = tmp_path / "note.md"
    body_file.write_text("ordinary session note.")

    _calls, bodies = _patch_gh_capturing_body_file(monkeypatch)

    mod = import_cli()
    rc = mod.main(
        [
            "--board",
            str(board_md),
            "comment",
            "42",
            "--body-file",
            str(body_file),
        ]
    )
    captured = capsys.readouterr()
    assert rc == 0, captured.err
    assert bodies == ["ordinary session note."]
```

- [ ] **Step 2: Run, verify the dirty-report test fails**

```bash
pytest tests/test_cmd_comment.py::test_cmd_comment_refuses_on_dirty_pre_flight_report -v
```

Expected: FAIL — `_cmd_comment` doesn't call `pre_flight_check`.

- [ ] **Step 3: Wire pre-flight into `_cmd_comment`**

In `skills/jared/scripts/jared`, in `_cmd_comment`, immediately after `body = resolve_body(...)`:

```python
def _cmd_comment(args: argparse.Namespace) -> int:
    board = Board.from_path(Path(args.board))
    body = resolve_body(args.body, args.body_file)

    report = pre_flight_check(body, project_root=Path.cwd())
    if not report.clean:
        print_redaction_diff(report, file=sys.stderr)
        return 2

    # gh issue comment requires a file path, even when we got the body
```

(The rest of `_cmd_comment` stays the same.)

- [ ] **Step 4: Run, verify pass**

```bash
pytest tests/test_cmd_comment.py -v
```

Expected: all green (existing 5 + 3 new = 8).

- [ ] **Step 5: Full suite**

```bash
ruff check . && ruff format --check . && mypy && pytest
```

Expected: all clean.

- [ ] **Step 6: Commit**

```bash
git add skills/jared/scripts/jared tests/test_cmd_comment.py
git commit -m "feat(comment): pre-flight redactor in _cmd_comment (#102)"
```

---

## Task 10: Operator reference doc

**Files:**
- Create: `skills/jared/references/pii-pre-flight.md`
- Modify: `skills/jared/SKILL.md`
- Modify: `skills/jared/references/operations.md`
- Modify: `commands/jared-file.md`
- Modify: `commands/jared-wrap.md`

- [ ] **Step 1: Write `references/pii-pre-flight.md`**

Create `skills/jared/references/pii-pre-flight.md`:

````markdown
# PII Pre-Flight Redactor

A runtime check that scans issue and comment bodies for content matched against gitignored claude-shaped local files. Refuses to post on hits. Closes the gap that jared's `gh` / MCP API calls bypass any local pre-commit hook protecting file-based commits.

## What it scans

The redactor looks under the project root for gitignored claude-shaped files at:

- `CLAUDE.local.md`
- `.claude/CLAUDE.local.md`
- `.claude/local/*.md`

Files are only considered when the project root is a git repo (has a `.git/` directory). Without git, the allowlist semantics break, so the redactor returns clean rather than flagging everything inconsistently.

## What counts as a "phrase"

Each line of each scanned file is a candidate phrase if — after stripping markdown leaders (`-`, `*`, `>`, `#`, `|`, backticks, leading whitespace) — it has:

- at least 3 whitespace-separated words, AND
- at least 20 characters total.

Shorter content (single words, short tokens, generic markdown structure) is ignored. The thresholds catch rich content like `"the deploy host is internal-foo-7.corp.example"` while ignoring `"# Section"`, `"- foo"`, or `"hostname"`.

## Allowlist semantics

A phrase that appears in *any* tracked file is already public — the redactor does not flag it. The check is `phrase in <concatenated tracked file contents>` via one `git ls-files` call per `jared` invocation (cached process-locally).

This means: if you intentionally documented something publicly in `README.md` and the same phrase happens to appear in `CLAUDE.local.md`, the redactor will not flag it. Conversely, content that lives only in the gitignored file is the protected surface.

## What happens on a hit

`jared file` and `jared comment` both run the pre-flight immediately after resolving the body and before any `gh` call. On a non-clean report:

- Exit code: 2
- Stderr: a structured diff naming each match — line number in the body, the matched phrase, and which gitignored file it came from
- No issue is created; no comment is posted

## How to bypass intentionally

Two ways:

1. **Re-issue with private content removed.** Edit the body to drop the phrase. This is the right move when the phrase is genuinely private.
2. **Add the matched phrase to a tracked file.** If the phrase is something you'd publish anyway (a public deploy URL, a documented hostname), commit it to `README.md` (or any tracked file) so the allowlist picks it up. Re-run the call.

## What it does NOT do

- **No silent edits.** The redactor refuses; it never modifies the body. Silent edits are surprising; a paraphrase that survives redaction is still a leak.
- **No on-disk cache.** Cache lives in process memory and dies with the `jared` invocation. Re-scan cost is negligible (a few milliseconds for typical local files).
- **No configurable thresholds (yet).** v1 ships with hardcoded `MIN_WORDS=3, MIN_CHARS=20`. If false positives flood, the thresholds will become configurable via `docs/project-board.md`.
- **Not a replacement for the pre-commit hook.** The pre-commit hook protects file-system commits; the redactor protects API writes. Both are required for full coverage.

## See also

- `references/operations.md` — Cautions section, cross-reference
- `SKILL.md` § "The lane" — the doctrine the redactor enforces in code
- Issue #102 — design and acceptance
````

- [ ] **Step 2: Update SKILL.md to point at the redactor doc**

In `skills/jared/SKILL.md`, replace this paragraph in "The lane" section:

> Jared *reads* memory, `CLAUDE.md`, project settings, and any gitignored claude-shaped local files (`CLAUDE.local.md`, `.claude/local/*.md`) to align style, infer conventions, and (in a future change, see #102) pre-flight redact private content from public board posts. But Jared never writes to those surfaces. When a sibling skill owns a surface, Jared defers rather than competes:

with:

> Jared *reads* memory, `CLAUDE.md`, project settings, and any gitignored claude-shaped local files (`CLAUDE.local.md`, `.claude/local/*.md`) to align style, infer conventions, and pre-flight redact private content from public board posts. The pre-flight scans every issue and comment body before any `gh` call and refuses to post on hits — see `references/pii-pre-flight.md`. But Jared never writes to those surfaces. When a sibling skill owns a surface, Jared defers rather than competes:

- [ ] **Step 3: Cross-reference from `references/operations.md`**

In `skills/jared/references/operations.md`, append to the Cautions section (after the single-select-mutation paragraph):

```markdown
**Pre-flight redaction.** Every `jared file` and `jared comment` runs a pre-flight scan against gitignored claude-shaped local files (`CLAUDE.local.md`, `.claude/local/*.md`). On a hit, the call is refused with a structured diff and exit 2; nothing is posted. Full reference: `references/pii-pre-flight.md`.
```

- [ ] **Step 4: Add note to `commands/jared-file.md`**

In `commands/jared-file.md`, after step 4 (build the body), insert:

```markdown
   **Pre-flight redaction.** `jared file` runs the body through a pre-flight scan against gitignored claude-shaped local files before posting. If any rich phrase from a local-claude file appears in the body, the call refuses with a stderr diff and exit 2. See `references/pii-pre-flight.md`.

```

- [ ] **Step 5: Add note to `commands/jared-wrap.md`**

In `commands/jared-wrap.md`, after step 2 (draft Session note), insert:

```markdown
   **Pre-flight redaction.** Session notes and `## Current state` updates posted via `jared comment` are scanned by the same pre-flight as `jared file`. Drafts referencing private content from `CLAUDE.local.md` will be refused on post — fix the draft, don't fight the redactor. See `references/pii-pre-flight.md`.

```

- [ ] **Step 6: Verify nothing broke**

```bash
pytest && ruff check . && ruff format --check .
```

Expected: all clean.

- [ ] **Step 7: Commit**

```bash
git add skills/jared/references/pii-pre-flight.md skills/jared/SKILL.md skills/jared/references/operations.md commands/jared-file.md commands/jared-wrap.md
git commit -m "doc(redactor): operator reference + cross-references (#102)"
```

---

## Task 11: Live smoke

**Files:** none modified — manual verification.

- [ ] **Step 1: Hand-craft a test fixture in this repo**

Create `CLAUDE.local.md` at the repo root with one rich phrase (then delete it after the smoke):

```bash
cat > CLAUDE.local.md <<'EOF'
This is a redactor smoke test phrase that should never be posted.
EOF
```

The repo's `.gitignore` already covers `CLAUDE.local.md` (verify).

- [ ] **Step 2: Confirm the redactor refuses on a dirty body**

```bash
./skills/jared/scripts/jared file \
  --title "redactor smoke" \
  --body "Some context. This is a redactor smoke test phrase that should never be posted. More context." \
  --priority Low 2>&1
```

Expected: exit code 2, stderr contains `"pre-flight redaction check failed"`, the staged path, and a `next steps:` section. No issue created on GitHub.

- [ ] **Step 3: Confirm the redactor proceeds on a clean body**

```bash
./skills/jared/scripts/jared file \
  --title "redactor smoke (clean)" \
  --body "Public-safe body content with no overlap." \
  --priority Low 2>&1
```

Expected: exit code 0, issue created on GitHub at issue #N. **Immediately close it** with `./skills/jared/scripts/jared close N`.

- [ ] **Step 4: Confirm `jared comment` honors the redactor**

```bash
./skills/jared/scripts/jared comment <some-test-issue> \
  --body "Some context. This is a redactor smoke test phrase that should never be posted. More context."
```

Expected: exit 2, same stderr shape.

- [ ] **Step 5: Clean up the fixture**

```bash
rm CLAUDE.local.md
```

- [ ] **Step 6: Document smoke results in PR body**

Capture the exact phrases used and the observed exit codes / stderr in the PR description's Test plan section so the reviewer can re-run if needed.

---

## Self-review

Run through the checklist before opening the PR:

- [ ] All 11 tasks committed in order with their phase commit messages.
- [ ] Each task's RED-then-GREEN cycle was actually verified (not skipped).
- [ ] `pytest` (full suite) green, `ruff check` clean, `ruff format --check` clean, `mypy` clean.
- [ ] No skill files mention #102 in future tense (the SKILL.md update closes that loop).
- [ ] PR body lists the deferred items: auto-redaction, on-disk cache, configurable thresholds, claude-md-improver sibling rule.
- [ ] Smoke results documented (Task 11 step 6).
- [ ] Branch name: `feature/jared-pii-redactor` (already created).
- [ ] PR target: `main`. Body closes #102.
