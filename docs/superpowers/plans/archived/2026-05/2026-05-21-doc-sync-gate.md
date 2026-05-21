---
**Shipped in #163 on 2026-05-21. Final decisions captured in issue body.**
---

# Doc-Sync Gate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

## Issue

- #163

**Goal:** Add a project-configurable doc-sync advisory to `jared groom` / `sweep.py`: when a closed PR touched a project's configured code surface (e.g. `src/**`) but didn't also touch one of its configured operator docs (e.g. `CLAUDE.md`, `docs/PRD.md`), emit a soft advisory line. Config lives in `docs/project-board.md` as a new optional `### Current-state operator docs` block; absent block = check disabled.

**Architecture:** New optional `### Current-state operator docs` block on the convention doc, parsed by `lib/board.py` at init (mirroring `_parse_session_start_checks`) into two dataclass fields: `operator_docs: list[str]` and `code_surface: list[str]`. New module-level helper `fetch_recent_closed_prs_with_files(repo, days)` in `lib/board.py` queries closed PRs in the last 7 days (default) and their changed-file paths. New `check_doc_sync_gate(prs, operator_docs, code_surface) -> list[str]` in `sweep.py` runs the comparison; called from `main()` only when the project has the block configured. Trailscribe adoption is a sibling task post-merge (option (a) — keep #163 scoped to the jared side per advisor pass).

**Tech Stack:** Python 3.11+, pytest, ruff, mypy --strict, gh CLI via `lib/board.py` (`run_gh` / `run_gh_raw`). Pattern matching via `fnmatch.fnmatchcase` over `**`-expanded globs (re-uses the same idiom used elsewhere for project pathspecs).

---

## File Structure

**Created:**
- *(none — all new code lives in existing files)*

**Modified:**
- `skills/jared/scripts/lib/board.py` — add `operator_docs` + `code_surface` dataclass fields, `_parse_operator_docs` staticmethod, `fetch_recent_closed_prs_with_files` module-level helper (~80 lines added)
- `skills/jared/scripts/sweep.py` — add `check_doc_sync_gate`, `--doc-sync-days` arg, wire into `main()` with optional `Board.from_default()` lift (~50 lines added)
- `skills/jared/assets/project-board.md.template` — document the new optional block (~15 lines added)
- `skills/jared/SKILL.md` — one-paragraph cross-reference under existing groom guidance (~6 lines)
- `skills/jared/references/board-sweep.md` — full description of the check (~15 lines)
- `tests/test_board.py` — parser tests + helper tests (~120 lines)
- `tests/test_sweep_checks.py` — `check_doc_sync_gate` tests (~80 lines)
- `tests/test_asset_project_board_template.py` — assert the new block is documented in the template (~10 lines)

**Versioning:** Release as v0.20.0 (minor bump — additive feature, no breaking changes).

**Branch:** `feature/163-doc-sync-gate` (per `feedback_jared_git_workflow`).

---

## Phase 1: Setup

### Task 1.1: Create the feature branch

**Files:**
- *(none)*

- [ ] **Step 1: Create and switch to feature branch**

Run:
```bash
git checkout main && git pull --ff-only origin main
git checkout -b feature/163-doc-sync-gate
```

Expected: clean working tree on `feature/163-doc-sync-gate`.

---

## Phase 2: Parser — `### Current-state operator docs` block on `Board`

### Task 2.1: Failing test — full block parses to both lists

**Files:**
- Modify: `tests/test_board.py` (append a new test near the existing `test_board_parses_jared_config_section`)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_board.py`:

```python
def test_board_parses_operator_docs_section(tmp_path: Path) -> None:
    """A `### Current-state operator docs` block with both bullets populates
    `operator_docs` and `code_surface` on the Board dataclass."""
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

        ### Current-state operator docs

        - Docs: CLAUDE.md, docs/PRD.md, docs/architecture.md
        - Code surface: src/**, lib/**
        """)
    )
    board = Board.from_path(board_md)
    assert board.operator_docs == ["CLAUDE.md", "docs/PRD.md", "docs/architecture.md"]
    assert board.code_surface == ["src/**", "lib/**"]
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/test_board.py::test_board_parses_operator_docs_section -v`
Expected: FAIL with `AttributeError: 'Board' object has no attribute 'operator_docs'`.

### Task 2.2: Failing test — section present, Code surface bullet absent, defaults to `["src/**"]`

**Files:**
- Modify: `tests/test_board.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_board.py`:

```python
def test_board_operator_docs_defaults_code_surface_when_bullet_missing(tmp_path: Path) -> None:
    """`Docs:` bullet present but `Code surface:` bullet absent — default
    code_surface to ['src/**']. Lets projects opt into the check minimally."""
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

        ### Current-state operator docs

        - Docs: CLAUDE.md
        """)
    )
    board = Board.from_path(board_md)
    assert board.operator_docs == ["CLAUDE.md"]
    assert board.code_surface == ["src/**"]
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/test_board.py::test_board_operator_docs_defaults_code_surface_when_bullet_missing -v`
Expected: FAIL with `AttributeError: 'Board' object has no attribute 'operator_docs'`.

### Task 2.3: Failing test — section absent, both fields default to `[]`

**Files:**
- Modify: `tests/test_board.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_board.py`:

```python
def test_board_operator_docs_defaults_empty_when_section_absent(tmp_path: Path) -> None:
    """No `### Current-state operator docs` block at all → both fields empty,
    which the consumer treats as 'check disabled'."""
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
        """)
    )
    board = Board.from_path(board_md)
    assert board.operator_docs == []
    assert board.code_surface == []
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/test_board.py::test_board_operator_docs_defaults_empty_when_section_absent -v`
Expected: FAIL with `AttributeError: 'Board' object has no attribute 'operator_docs'`.

### Task 2.4: Failing test — section present but `Docs:` bullet missing → both empty (robust to partial config)

**Files:**
- Modify: `tests/test_board.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_board.py`:

```python
def test_board_operator_docs_section_without_docs_bullet_is_disabled(tmp_path: Path) -> None:
    """Section present but `Docs:` bullet absent → both fields empty (check
    disabled). Robust to partial config — no exception, no surprise default."""
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

        ### Current-state operator docs

        - Code surface: src/**
        """)
    )
    board = Board.from_path(board_md)
    assert board.operator_docs == []
    assert board.code_surface == []
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/test_board.py::test_board_operator_docs_section_without_docs_bullet_is_disabled -v`
Expected: FAIL with `AttributeError`.

### Task 2.5: Implement parser + dataclass fields

**Files:**
- Modify: `skills/jared/scripts/lib/board.py`

- [ ] **Step 1: Add the two new dataclass fields**

Edit `lib/board.py` — find the existing dataclass field block around line 60-72 (after `_field_options` and before `_items`). Add the two new fields immediately after `session_start_checks: list[str] = field(default_factory=list)` (around line 64):

```python
    # Optional "current-state operator docs" config — populated from the
    # `### Current-state operator docs` block in docs/project-board.md.
    # Both lists empty = check disabled (no block, or block lacks `Docs:`).
    # If `Docs:` is present but `Code surface:` is absent, code_surface
    # defaults to ['src/**']. See sweep.check_doc_sync_gate (#163).
    operator_docs: list[str] = field(default_factory=list)
    code_surface: list[str] = field(default_factory=list)
```

- [ ] **Step 2: Add the `_parse_operator_docs` staticmethod**

Edit `lib/board.py` — add this staticmethod after `_parse_session_start_checks` (around line 283):

```python
    @staticmethod
    def _parse_operator_docs(text: str) -> tuple[list[str], list[str]]:
        """Parse the optional `### Current-state operator docs` block.

        Two bullets supported:
            - Docs: comma-separated list of doc paths/globs
            - Code surface: comma-separated list of code-path globs

        Returns (operator_docs, code_surface). When the section is absent OR
        present-but-missing-`Docs:`, both lists are empty (check disabled).
        When `Docs:` is present and `Code surface:` is absent, code_surface
        defaults to ['src/**'].

        Section ends at next ### or ## heading or end-of-file — same idiom as
        the other optional-section parsers.
        """
        section_re = re.compile(
            r"^###\s+Current-state operator docs\s*$(?P<body>.*?)(?=^#{2,3}\s|\Z)",
            re.MULTILINE | re.DOTALL,
        )
        match = section_re.search(text)
        if not match:
            return [], []

        body = match.group("body")

        docs_re = re.compile(r"^\s*-\s*Docs:\s*(?P<list>.+?)\s*$", re.MULTILINE)
        docs_match = docs_re.search(body)
        if not docs_match:
            # Section present but Docs: bullet missing — treat as disabled.
            return [], []
        docs = [d.strip() for d in docs_match.group("list").split(",")]
        docs = [d for d in docs if d]

        surface_re = re.compile(r"^\s*-\s*Code surface:\s*(?P<list>.+?)\s*$", re.MULTILINE)
        surface_match = surface_re.search(body)
        if surface_match:
            surface = [s.strip() for s in surface_match.group("list").split(",")]
            surface = [s for s in surface if s]
        else:
            surface = ["src/**"]

        return docs, surface
```

- [ ] **Step 3: Wire parser into `_parse`**

Edit `lib/board.py` — find the `_parse` classmethod (line 117), specifically the block where other parsers are called around line 179-181:

```python
        field_ids, field_options = cls._parse_field_blocks(text)
        session_handoff_prompt = cls._parse_jared_config(text).get("session-handoff-prompt", "ask")
        session_start_checks = cls._parse_session_start_checks(text)
```

Add immediately below:

```python
        operator_docs, code_surface = cls._parse_operator_docs(text)
```

Then in the `return cls(...)` call (around line 183-194), add the two new kwargs after `session_start_checks=session_start_checks,`:

```python
            session_start_checks=session_start_checks,
            operator_docs=operator_docs,
            code_surface=code_surface,
            _raw_doc=text,
```

- [ ] **Step 4: Run all four tests to verify they pass**

Run: `pytest tests/test_board.py -k "operator_docs" -v`
Expected: 4 passed.

- [ ] **Step 5: Run the full board test file to verify no regressions**

Run: `pytest tests/test_board.py -v`
Expected: all green.

- [ ] **Step 6: Type-check + lint**

Run:
```bash
ruff check skills/jared/scripts/lib/board.py
mypy skills/jared/scripts/lib/board.py
```

Expected: clean exit on both.

- [ ] **Step 7: Commit**

```bash
git add tests/test_board.py skills/jared/scripts/lib/board.py
git commit -m "$(cat <<'EOF'
feat(board): parse ### Current-state operator docs block (#163)

Adds two optional Board fields: operator_docs and code_surface. Parsed
at init from a `### Current-state operator docs` block in
docs/project-board.md. Section absent OR missing Docs: bullet → both
empty, signaling check disabled to consumers. Docs: present + Code
surface: absent → code_surface defaults to ['src/**'].

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Phase 3: Helper — `fetch_recent_closed_prs_with_files`

### Task 3.1: Failing test — helper returns shape `[{number, closedAt, files}, ...]`

**Files:**
- Modify: `tests/test_board.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_board.py`:

```python
def test_fetch_recent_closed_prs_with_files_returns_expected_shape(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Helper fetches closed PRs from the last N days via gh and pairs each
    with its changed-file list. PRs older than N days are excluded.

    The helper is a thin orchestrator: it uses `gh pr list` to enumerate
    closed PRs and `gh pr view N --json files` per-PR to get changed paths.
    Tests assert the orchestration, not the gh wire format."""
    from skills.jared.scripts.lib import board as board_mod

    list_payload = [
        {"number": 100, "closedAt": "2026-05-20T10:00:00Z"},
        {"number": 99, "closedAt": "2026-05-18T10:00:00Z"},
    ]
    files_by_pr = {
        100: [{"path": "src/foo.py"}, {"path": "CLAUDE.md"}],
        99: [{"path": "src/bar.py"}],
    }

    def fake_run_gh(args: list[str], *, cache: str | None = None) -> object:
        if args[0:2] == ["pr", "list"]:
            return list_payload
        if args[0:2] == ["pr", "view"]:
            n = int(args[2])
            return {"files": files_by_pr[n]}
        raise AssertionError(f"unexpected gh args: {args}")

    monkeypatch.setattr(board_mod, "run_gh", fake_run_gh)

    result = board_mod.fetch_recent_closed_prs_with_files(
        "brockamer/jared", days=7
    )
    assert result == [
        {"number": 100, "closedAt": "2026-05-20T10:00:00Z", "files": ["src/foo.py", "CLAUDE.md"]},
        {"number": 99, "closedAt": "2026-05-18T10:00:00Z", "files": ["src/bar.py"]},
    ]
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/test_board.py::test_fetch_recent_closed_prs_with_files_returns_expected_shape -v`
Expected: FAIL with `AttributeError: module 'lib.board' has no attribute 'fetch_recent_closed_prs_with_files'`.

### Task 3.2: Implement `fetch_recent_closed_prs_with_files`

**Files:**
- Modify: `skills/jared/scripts/lib/board.py`

- [ ] **Step 1: Add the helper near the other module-level helpers**

Edit `lib/board.py` — add this function near the other module-level fetchers, ideally just above or just below `fetch_recent_comments_batch` (around line 1145):

```python
def fetch_recent_closed_prs_with_files(
    repo: str, days: int = 7, *, cache: str | None = None
) -> list[dict[str, Any]]:
    """Return closed PRs from the last `days` days, each with its changed
    file list. Used by sweep.check_doc_sync_gate (#163).

    Two-stage: `gh pr list` enumerates by closedAt window, then
    `gh pr view N --json files` per PR. The list endpoint doesn't expose
    `files` reliably across gh versions; per-PR view is the robust path
    and matches check_plan_spec_drift's idiom.

    `cache` flows through to run_gh, opting into the on-disk snapshot cache.
    """
    cutoff = (dt.datetime.now(dt.UTC) - dt.timedelta(days=days)).strftime("%Y-%m-%d")
    list_args = [
        "pr", "list",
        "--repo", repo,
        "--state", "closed",
        "--search", f"closed:>={cutoff}",
        "--limit", "100",
        "--json", "number,closedAt",
    ]
    prs = run_gh(list_args, cache=cache)
    if not isinstance(prs, list):
        return []

    result: list[dict[str, Any]] = []
    for pr in prs:
        number = pr.get("number")
        closed_at = pr.get("closedAt")
        if not isinstance(number, int):
            continue
        view_args = ["pr", "view", str(number), "--repo", repo, "--json", "files"]
        try:
            data = run_gh(view_args, cache=cache)
        except GhInvocationError:
            continue
        files_raw = (data or {}).get("files", []) if isinstance(data, dict) else []
        files = [f["path"] for f in files_raw if isinstance(f, dict) and "path" in f]
        result.append({"number": number, "closedAt": closed_at, "files": files})

    return result
```

- [ ] **Step 2: Verify `dt` is already imported**

Run: `grep -n "^import datetime\|^from datetime" skills/jared/scripts/lib/board.py`
Expected: `import datetime as dt` (or equivalent) appears. If absent, add `import datetime as dt` to the imports block.

- [ ] **Step 3: Run the test to verify it passes**

Run: `pytest tests/test_board.py::test_fetch_recent_closed_prs_with_files_returns_expected_shape -v`
Expected: PASS.

- [ ] **Step 4: Add one more test — gh failure on per-PR view is swallowed**

Append to `tests/test_board.py`:

```python
def test_fetch_recent_closed_prs_swallows_per_pr_view_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If `gh pr view N` fails for one PR, the helper skips that PR and
    continues with the rest — advisory-tier resilience."""
    from skills.jared.scripts.lib import board as board_mod
    from skills.jared.scripts.lib.board import GhInvocationError

    list_payload = [
        {"number": 100, "closedAt": "2026-05-20T10:00:00Z"},
        {"number": 99, "closedAt": "2026-05-18T10:00:00Z"},
    ]

    def fake_run_gh(args: list[str], *, cache: str | None = None) -> object:
        if args[0:2] == ["pr", "list"]:
            return list_payload
        if args[0:2] == ["pr", "view"]:
            n = int(args[2])
            if n == 100:
                raise GhInvocationError("simulated network error")
            return {"files": [{"path": "src/bar.py"}]}
        raise AssertionError(f"unexpected gh args: {args}")

    monkeypatch.setattr(board_mod, "run_gh", fake_run_gh)

    result = board_mod.fetch_recent_closed_prs_with_files("brockamer/jared", days=7)
    assert result == [{"number": 99, "closedAt": "2026-05-18T10:00:00Z", "files": ["src/bar.py"]}]
```

- [ ] **Step 5: Run both helper tests**

Run: `pytest tests/test_board.py -k "fetch_recent_closed_prs" -v`
Expected: 2 passed.

- [ ] **Step 6: Type-check + lint**

Run:
```bash
ruff check skills/jared/scripts/lib/board.py tests/test_board.py
mypy skills/jared/scripts/lib/board.py
```

Expected: clean.

- [ ] **Step 7: Commit**

```bash
git add tests/test_board.py skills/jared/scripts/lib/board.py
git commit -m "$(cat <<'EOF'
feat(board): add fetch_recent_closed_prs_with_files helper (#163)

Two-stage fetch — `gh pr list` for closed-PR enumeration windowed by
--search closed:>=<cutoff>, then `gh pr view N --json files` per PR for
changed-file paths. Mirrors check_plan_spec_drift's per-issue idiom.
Per-PR failures are swallowed (advisory-tier resilience).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Phase 4: Check — `check_doc_sync_gate` in `sweep.py`

### Task 4.1: Failing test — PR touched code only → advisory emitted

**Files:**
- Modify: `tests/test_sweep_checks.py`

- [ ] **Step 1: Read existing sweep-check tests for pattern**

Run: `grep -n "^def test_\|import_sweep\|sweep_mod" tests/test_sweep_checks.py | head -20`
Look at one of the existing tests (e.g., `test_check_session_note_freshness`) to mirror its import pattern.

- [ ] **Step 2: Write the failing test**

Append to `tests/test_sweep_checks.py`:

```python
def test_check_doc_sync_gate_flags_code_only_pr() -> None:
    """A closed PR that touched the project's code surface (src/**) without
    touching any operator doc emits an advisory line naming the PR + the
    untouched doc list."""
    from tests.conftest import import_sweep

    sweep = import_sweep()

    prs = [
        {
            "number": 100,
            "closedAt": "2026-05-20T10:00:00Z",
            "files": ["src/foo.py", "tests/test_foo.py"],
        },
    ]
    operator_docs = ["CLAUDE.md", "docs/PRD.md"]
    code_surface = ["src/**"]

    findings = sweep.check_doc_sync_gate(prs, operator_docs, code_surface)
    assert len(findings) == 1
    assert "#100" in findings[0]
    assert "CLAUDE.md" in findings[0] or "docs/PRD.md" in findings[0]
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `pytest tests/test_sweep_checks.py::test_check_doc_sync_gate_flags_code_only_pr -v`
Expected: FAIL with `AttributeError: module 'sweep' has no attribute 'check_doc_sync_gate'`.

### Task 4.2: Failing test — PR touched code + doc → no finding

**Files:**
- Modify: `tests/test_sweep_checks.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_sweep_checks.py`:

```python
def test_check_doc_sync_gate_no_finding_when_both_touched() -> None:
    """A closed PR that touched both code surface and an operator doc is
    correctly synced — no advisory."""
    from tests.conftest import import_sweep

    sweep = import_sweep()

    prs = [
        {
            "number": 101,
            "closedAt": "2026-05-20T10:00:00Z",
            "files": ["src/foo.py", "CLAUDE.md"],
        },
    ]
    operator_docs = ["CLAUDE.md", "docs/PRD.md"]
    code_surface = ["src/**"]

    findings = sweep.check_doc_sync_gate(prs, operator_docs, code_surface)
    assert findings == []
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/test_sweep_checks.py::test_check_doc_sync_gate_no_finding_when_both_touched -v`
Expected: FAIL with `AttributeError`.

### Task 4.3: Failing test — PR touched doc only → no finding

**Files:**
- Modify: `tests/test_sweep_checks.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_sweep_checks.py`:

```python
def test_check_doc_sync_gate_no_finding_when_only_doc_touched() -> None:
    """A docs-only PR (no code-surface paths) is not flagged. The gate fires
    only when code was touched without a corresponding doc update."""
    from tests.conftest import import_sweep

    sweep = import_sweep()

    prs = [
        {
            "number": 102,
            "closedAt": "2026-05-20T10:00:00Z",
            "files": ["docs/PRD.md", "README.md"],
        },
    ]
    operator_docs = ["CLAUDE.md", "docs/PRD.md"]
    code_surface = ["src/**"]

    findings = sweep.check_doc_sync_gate(prs, operator_docs, code_surface)
    assert findings == []
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/test_sweep_checks.py::test_check_doc_sync_gate_no_finding_when_only_doc_touched -v`
Expected: FAIL with `AttributeError`.

### Task 4.4: Failing test — empty `operator_docs` → check skipped (returns `[]` without iterating)

**Files:**
- Modify: `tests/test_sweep_checks.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_sweep_checks.py`:

```python
def test_check_doc_sync_gate_skips_when_operator_docs_empty() -> None:
    """Empty operator_docs (block absent on this project's convention doc)
    short-circuits the check — never iterates PRs."""
    from tests.conftest import import_sweep

    sweep = import_sweep()

    prs = [
        {"number": 103, "closedAt": "2026-05-20T10:00:00Z", "files": ["src/foo.py"]},
    ]
    findings = sweep.check_doc_sync_gate(prs, operator_docs=[], code_surface=[])
    assert findings == []
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/test_sweep_checks.py::test_check_doc_sync_gate_skips_when_operator_docs_empty -v`
Expected: FAIL with `AttributeError`.

### Task 4.5: Failing test — globs in code surface and operator docs are honored

**Files:**
- Modify: `tests/test_sweep_checks.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_sweep_checks.py`:

```python
def test_check_doc_sync_gate_honors_glob_patterns() -> None:
    """Globs in both lists are matched via fnmatch. `lib/**` matches `lib/foo.py`
    and `lib/sub/bar.py`; `docs/architecture/**` matches files under that dir."""
    from tests.conftest import import_sweep

    sweep = import_sweep()

    prs = [
        {
            "number": 104,
            "closedAt": "2026-05-20T10:00:00Z",
            "files": ["lib/sub/bar.py"],
        },
        {
            "number": 105,
            "closedAt": "2026-05-20T10:00:00Z",
            "files": ["lib/sub/baz.py", "docs/architecture/diagrams/x.md"],
        },
    ]
    operator_docs = ["docs/architecture/**", "CLAUDE.md"]
    code_surface = ["lib/**"]

    findings = sweep.check_doc_sync_gate(prs, operator_docs, code_surface)
    assert len(findings) == 1
    assert "#104" in findings[0]
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/test_sweep_checks.py::test_check_doc_sync_gate_honors_glob_patterns -v`
Expected: FAIL with `AttributeError`.

### Task 4.6: Implement `check_doc_sync_gate`

**Files:**
- Modify: `skills/jared/scripts/sweep.py`

- [ ] **Step 1: Add the function near `check_session_note_freshness`**

Edit `sweep.py` — add this function just below `check_session_note_freshness` (around line 517):

```python
def check_doc_sync_gate(
    prs: list[dict[str, Any]],
    operator_docs: list[str],
    code_surface: list[str],
) -> list[str]:
    """Flag closed PRs that touched code surface without touching any operator doc.

    Each PR is a dict of {number, closedAt, files} from
    fetch_recent_closed_prs_with_files. Glob matching uses fnmatchcase over
    `**`-expanded patterns: `src/**` matches `src/foo.py` and `src/a/b.py`.

    Returns one finding line per flagged PR. Empty operator_docs short-
    circuits — no operator-docs config means the check is disabled.
    """
    if not operator_docs:
        return []

    findings: list[str] = []
    for pr in prs:
        files = pr.get("files") or []
        if not files:
            continue
        touched_code = any(_matches_any(f, code_surface) for f in files)
        if not touched_code:
            continue
        touched_doc = any(_matches_any(f, operator_docs) for f in files)
        if touched_doc:
            continue
        number = pr.get("number")
        closed_at = (pr.get("closedAt") or "").split("T")[0]
        docs_list = ", ".join(operator_docs)
        findings.append(
            f"PR #{number} closed {closed_at} touched code surface without an operator doc — "
            f"review whether {docs_list} need an update"
        )
    return findings


def _matches_any(path: str, patterns: list[str]) -> bool:
    """fnmatchcase against patterns, with `**` treated as recursive wildcard.

    fnmatch's `*` doesn't cross `/`. We rewrite `**` → `*` and additionally
    match against the basename-collapsed form to handle `src/**` ⇒ src/x.py
    AND src/a/b.py uniformly. Cheap and adequate for advisory gating.
    """
    from fnmatch import fnmatchcase

    for raw in patterns:
        # Treat ** as recursive — collapse to a single * for fnmatch.
        pat = raw.replace("**", "*")
        if fnmatchcase(path, pat):
            return True
        # Also match if the leading directory of the pattern is a prefix of path.
        # Handles `src/**` matching `src/a/b/c.py` without rewriting to globstar.
        if "/" in raw:
            prefix = raw.split("**", 1)[0].rstrip("/")
            if prefix and (path == prefix or path.startswith(prefix + "/")):
                return True
    return False
```

- [ ] **Step 2: Verify `Any` and `cast` are already imported**

Run: `grep -n "^from typing" skills/jared/scripts/sweep.py`
Expected: `Any` is in the typing import line (it is — line 49 imports `from typing import Any, cast`).

- [ ] **Step 3: Run all 5 check tests to verify they pass**

Run: `pytest tests/test_sweep_checks.py -k "check_doc_sync_gate" -v`
Expected: 5 passed.

- [ ] **Step 4: Run the full sweep test file**

Run: `pytest tests/test_sweep_checks.py -v`
Expected: all green.

- [ ] **Step 5: Type-check + lint**

Run:
```bash
ruff check skills/jared/scripts/sweep.py tests/test_sweep_checks.py
mypy skills/jared/scripts/sweep.py
```

Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add tests/test_sweep_checks.py skills/jared/scripts/sweep.py
git commit -m "$(cat <<'EOF'
feat(sweep): add check_doc_sync_gate (#163)

Pure-function check over a pre-fetched closed-PR list. Flags PRs that
touched the project's configured code surface (default src/**) without
touching any operator doc. Empty operator_docs short-circuits — no
config, no check.

Glob matching via fnmatchcase with ** treated as recursive (also matches
on directory prefix). Adequate for advisory gating; not a security
filter.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Phase 5: Wire `check_doc_sync_gate` into `sweep.py` `main()`

### Task 5.1: Read main() to confirm insertion point

**Files:**
- Read: `skills/jared/scripts/sweep.py`

- [ ] **Step 1: Re-read the section-printing block in main()**

Run: `sed -n '685,720p' skills/jared/scripts/sweep.py`
Confirm the doc-sync block will sit between `== Plan/spec drift ==` and `== Closed items not on Done ==` (cross-resource checks grouped together).

### Task 5.2: Add `--doc-sync-days` arg + the new check block

**Files:**
- Modify: `skills/jared/scripts/sweep.py`

- [ ] **Step 1: Add the CLI arg**

Edit `sweep.py` — find the argument-parsing block in `main()` around line 533-551. Add a new argument after `--blocked-aging-days`:

```python
    parser.add_argument(
        "--doc-sync-days",
        type=int,
        default=7,
        help="Window (in days) of closed PRs to scan for operator-doc sync (default: 7). "
        "Matches the next-session-prompt 'recently closed' window.",
    )
```

- [ ] **Step 2: Import the new helper at the top of `sweep.py`**

Edit `sweep.py` — find the existing `from lib.board import (...)` block (lines 56-81). Add a new import line in the appropriate alphabetically-ordered position:

```python
from lib.board import (
    fetch_recent_closed_prs_with_files as board_fetch_recent_closed_prs_with_files,
)
```

- [ ] **Step 3: Add the check invocation in main()**

Edit `sweep.py` — after the `== Plan/spec drift ==` block (ends around line 695, before the `== Closed items not on Done ==` block at line 697), insert:

```python
    print("== Doc-sync gate (operator docs not updated alongside code) ==")
    if not repo:
        print("  (skipped — repo not determined)")
    else:
        # The doc-sync config lives on the Board dataclass. find_config()
        # already located the convention doc above; load Board lazily here
        # so older boards without the section parse fine (they yield
        # operator_docs=[], which short-circuits the check).
        try:
            board = Board.from_default()
            operator_docs = board.operator_docs
            code_surface = board.code_surface
        except Exception as e:  # noqa: BLE001 — advisory path, never fail the sweep
            print(f"  (skipped — board load failed: {e})")
            operator_docs = []
            code_surface = []
        if not operator_docs:
            print("  (skipped — no ### Current-state operator docs block on this board)")
        else:
            try:
                prs = board_fetch_recent_closed_prs_with_files(repo, days=args.doc_sync_days)
                findings = check_doc_sync_gate(prs, operator_docs, code_surface)
                for line in findings or ["None"]:
                    print(f"  {line}")
            except (RuntimeError, GhInvocationError) as e:
                print(f"  (skipped — {e})")
    print()
```

- [ ] **Step 4: Run integration-style sanity test by invoking sweep against jared itself**

Run:
```bash
cd /home/brockamer/Code/jared && /home/brockamer/Code/jared/skills/jared/scripts/sweep.py 2>&1 | grep -A 3 "Doc-sync"
```

Expected: section heading prints; since jared's own `docs/project-board.md` does NOT yet have the new block, output should be `(skipped — no ### Current-state operator docs block on this board)`.

- [ ] **Step 5: Type-check + lint**

Run:
```bash
ruff check skills/jared/scripts/sweep.py
mypy skills/jared/scripts/sweep.py
```

Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add skills/jared/scripts/sweep.py
git commit -m "$(cat <<'EOF'
feat(sweep): wire check_doc_sync_gate into main() with --doc-sync-days (#163)

New section between Plan/spec drift and Closed-items-not-on-Done. Loads
Board.from_default() lazily so boards without the new block degrade
gracefully (skipped, not errored). Default window 7 days, mirroring
next-session-prompt's "recently closed" surface.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Phase 6: Template + docs

### Task 6.1: Add the optional block to the project-board template

**Files:**
- Modify: `skills/jared/assets/project-board.md.template`

- [ ] **Step 1: Read the template to find the right insertion point**

Run: `cat skills/jared/assets/project-board.md.template`
Look for a natural home — likely after the existing `## Jared config` and `## Session start checks` sections, or alongside `### Tie Analysis` if present (since both are `### `-style optional config blocks).

- [ ] **Step 2: Add the new section to the template**

Append to (or insert into the right spot of) `skills/jared/assets/project-board.md.template`:

```markdown
### Current-state operator docs

*Optional. If present, `jared groom` / `sweep.py` will emit an advisory
when a recently-closed PR touched the project's code surface (default
`src/**`) without touching any of the listed docs. Soft — never blocks.
Remove the section to disable the check.*

- Docs: CLAUDE.md, docs/PRD.md, docs/architecture.md
- Code surface: src/**
```

- [ ] **Step 3: Update `tests/test_asset_project_board_template.py`**

First read the existing test file to see what's already asserted:

Run: `cat tests/test_asset_project_board_template.py`

Then append a new test asserting the new section is documented:

```python
def test_template_documents_operator_docs_section() -> None:
    """The project-board template ships the optional `### Current-state
    operator docs` block as a documented opt-in (covers AC for #163)."""
    template_path = (
        Path(__file__).resolve().parent.parent
        / "skills/jared/assets/project-board.md.template"
    )
    text = template_path.read_text()
    assert "### Current-state operator docs" in text
    assert "- Docs:" in text
    assert "- Code surface:" in text
```

- [ ] **Step 4: Run the asset template test**

Run: `pytest tests/test_asset_project_board_template.py -v`
Expected: all green.

- [ ] **Step 5: Commit**

```bash
git add skills/jared/assets/project-board.md.template tests/test_asset_project_board_template.py
git commit -m "$(cat <<'EOF'
docs(template): document optional ### Current-state operator docs section (#163)

Adds the new optional block to the canonical project-board template so
/jared-init carries it forward to bootstrapped projects. The section is
documented inline as opt-in.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

### Task 6.2: Document the check in SKILL and references

**Files:**
- Modify: `skills/jared/SKILL.md`
- Modify: `skills/jared/references/board-sweep.md`

- [ ] **Step 1: Find the right home in SKILL.md**

Run: `grep -n "groom\|sweep" skills/jared/SKILL.md | head -10`
Locate the "Periodically — groom" section (or wherever groom is currently surfaced).

- [ ] **Step 2: Add a cross-reference line to SKILL.md**

Under the existing groom guidance, add a short paragraph describing the new check:

```markdown
**Doc-sync gate.** If a project's `docs/project-board.md` includes a
`### Current-state operator docs` block, `jared groom` / `sweep.py` will
emit an advisory when recent closed PRs touched the configured code
surface (default `src/**`) without touching any listed doc. The check is
opt-in per project and never blocks; see
[references/board-sweep.md](references/board-sweep.md) for the full
contract.
```

- [ ] **Step 3: Add the full description to references/board-sweep.md**

Append to `skills/jared/references/board-sweep.md`:

```markdown
## Doc-sync gate

When a project's `docs/project-board.md` defines a `### Current-state
operator docs` block, the sweep emits an advisory for each closed PR (last
7 days by default; override with `--doc-sync-days`) that touched the
configured code surface without also touching any of the listed docs.

Config shape:

```
### Current-state operator docs

- Docs: CLAUDE.md, docs/PRD.md, docs/architecture.md
- Code surface: src/**
```

`Code surface` defaults to `src/**` when `Docs:` is set but `Code surface:`
is absent. The block can be removed entirely to disable the check.

The advisory line names the PR + closedAt date + the operator-docs list,
so the operator can decide whether the change actually needs a doc
update. The gate is soft — never blocks PR creation or merge.
```

- [ ] **Step 4: Lint**

Run: `ruff format --check skills/jared/SKILL.md skills/jared/references/board-sweep.md` — these are markdown so ruff won't have opinions, but the command should exit clean.

- [ ] **Step 5: Commit**

```bash
git add skills/jared/SKILL.md skills/jared/references/board-sweep.md
git commit -m "$(cat <<'EOF'
docs(skill): document doc-sync gate convention + behavior (#163)

SKILL.md gets a one-paragraph cross-reference under groom guidance.
board-sweep.md gets the full contract — config shape, defaults, window,
soft-vs-hard semantics — for operators learning the new opt-in.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Phase 7: PR + post-merge sibling

### Task 7.1: Open PR to main

**Files:**
- *(none)*

- [ ] **Step 1: Push the branch**

Run: `git push -u origin feature/163-doc-sync-gate`

- [ ] **Step 2: Open the PR with body referencing #163**

Run:
```bash
gh pr create --base main --title "feat(groom): project-configurable doc-sync gate (#163)" --body "$(cat <<'EOF'
## Summary

Adds an opt-in advisory to `jared groom` / `sweep.py`: when a closed PR
(last 7 days, configurable) touched a project's code surface without
touching any of its configured operator docs, emit one finding line per
PR. Soft — never blocks. Config lives in `docs/project-board.md` as a
new `### Current-state operator docs` block; absent block = check disabled.

## Closes

- #163

## Test plan

- [x] `pytest tests/test_board.py -k operator_docs` — 4 parser tests
- [x] `pytest tests/test_board.py -k fetch_recent_closed_prs` — 2 helper tests
- [x] `pytest tests/test_sweep_checks.py -k check_doc_sync_gate` — 5 check tests
- [x] `pytest tests/test_asset_project_board_template.py` — template documents the new section
- [x] `pytest` — full suite green
- [x] `ruff check . && mypy` — clean
- [x] `sweep.py` smoke run against jared's own board prints the new section, correctly skipped (no block configured locally)

## Backward compatibility

Additive. Boards without the new section behave exactly as before; the
new dataclass fields default to empty lists, the new check short-circuits.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

Expected: PR URL printed.

### Task 7.2: After PR merges — file the trailscribe sibling and clean up trailscribe#176

**Files:**
- *(none — this task runs against the trailscribe repo)*

- [ ] **Step 1: File the trailscribe-side adoption issue**

Per option (a) from the start-time advisor: #163's acceptance criterion that names trailscribe adoption is closed by the sibling issue, not by this PR. After this PR merges to main:

Run (from the trailscribe project root):
```bash
${CLAUDE_PLUGIN_ROOT}/skills/jared/scripts/jared file \
  --title "adopt jared doc-sync gate — list CLAUDE.md / docs/PRD.md / docs/architecture.md" \
  --priority Medium \
  --status Backlog \
  --body-file - <<'EOF'
## Context

`jared` shipped the project-configurable doc-sync gate in
`brockamer/jared#163`. Trailscribe is the original requester (this issue
supersedes the carved-out `brockamer/trailscribe#176`).

## Scope

Add a `### Current-state operator docs` block to
`docs/project-board.md` listing the three operator docs:

- Docs: CLAUDE.md, docs/PRD.md, docs/architecture.md
- Code surface: src/**

Run `jared groom` once after the change to confirm the new section
parses and the doc-sync advisory fires correctly.

## Acceptance criteria

<details>
<summary>Expand</summary>

- `docs/project-board.md` updated with the new block.
- `jared groom` run completes and surfaces the new section (either
  "None" or actual findings, depending on recent PR activity).

</details>
EOF
```

- [ ] **Step 2: Comment on trailscribe#176 pointing here, then drop it from the jared board**

This closes out the cross-repo carve-out:

```bash
# Comment on trailscribe#176 explaining the supersession
gh issue comment 176 --repo brockamer/trailscribe \
  --body "Superseded by the jared-side ship of the configurable doc-sync gate (\`brockamer/jared#163\`) plus the trailscribe-side adoption issue filed at <URL of the new issue from step 1>. Closing."

# Close trailscribe#176
gh issue close 176 --repo brockamer/trailscribe --reason "not planned"
```

- [ ] **Step 3: After both above complete, mark this plan archived**

Move the plan into the archive subdirectory:

```bash
mkdir -p docs/superpowers/plans/archived/2026-05
git mv docs/superpowers/plans/2026-05-21-doc-sync-gate.md docs/superpowers/plans/archived/2026-05/
# Add the shipped-banner at the top of the moved file
```

Then prepend a header:

```markdown
---
**Shipped in #<PR number from Task 7.1> on YYYY-MM-DD. Final decisions captured in issue body.**
---
```

Commit on `main`:

```bash
git add docs/superpowers/plans/
git commit -m "$(cat <<'EOF'
docs(plan): archive 2026-05-21-doc-sync-gate.md (#163 shipped)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Self-review pass

**Spec coverage (issue #163 acceptance criteria):**

1. ✅ "New `### Current-state operator docs` field documented in the project-board template as optional." — Task 6.1.
2. ✅ "`lib/board.py` parses the field; absence is fine." — Phase 2, four parser tests pin the behavior.
3. ✅ "`sweep.py` (or `jared groom`) detects the 'code touched without doc touched' pattern across recent closed PRs and surfaces an advisory line." — Phases 3, 4, 5.
4. ✅ "Test coverage on the parser and the check." — 11 new tests across `test_board.py`, `test_sweep_checks.py`, `test_asset_project_board_template.py`.
5. ✅ "Trailscribe's `docs/project-board.md` adopts the new field listing its three docs once the feature lands." — Reframed per advisor pass to option (a): sibling issue filed immediately post-merge (Task 7.2). This is a scope decision; the original criterion as written would cross repos in one issue. The cross-repo issue (`brockamer/trailscribe#176`) gets a supersession comment + close (Task 7.2 step 2).

**Placeholder scan:** None. Every step has exact paths, exact commands, exact code.

**Type consistency:**
- `operator_docs: list[str]`, `code_surface: list[str]` — consistent across `lib/board.py` definition, `_parse_operator_docs` return tuple shape, `check_doc_sync_gate` parameters, all test fixtures.
- Helper return shape `list[dict[str, Any]]` with keys `number`, `closedAt`, `files` — consistent between helper tests, helper impl, and consumer-check impl/tests.
- `_matches_any(path: str, patterns: list[str]) -> bool` — only used internally by `check_doc_sync_gate`; same signature throughout.

**Trailscribe scoping:** the advisor pass surfaced that #163's AC#5 ("trailscribe adopts the field") crosses repos. Plan resolves this with option (a): #163 closes when the jared PR merges (Task 7.1); the trailscribe adoption is filed immediately as a sibling on the trailscribe board (Task 7.2). The plan calls this out explicitly so the discipline isn't deferred — see `feedback_deferred_verification_drift`.

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-05-21-doc-sync-gate.md`. Two execution options:

1. **Subagent-Driven (recommended)** — dispatch a fresh **sonnet** subagent per task (per `feedback_model_selection`), review between tasks, fast iteration.
2. **Inline Execution** — execute tasks in this session using `superpowers:executing-plans`, batched with checkpoints.

Which approach?
