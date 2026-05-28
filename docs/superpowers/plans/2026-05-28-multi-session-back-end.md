# Multi-session back-end Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make multi-session work in Jared low-ceremony: stage proposes session-N partition, start filters by session-N, wrap runs the commit→push→PR→merge back-end with one confirm gate.

**Architecture:** Three-phase arc across the existing `/jared-stage`, `/jared-start`, `/jared-wrap` slash commands. Stage gets a `--sessions N` flag and proposes session-N label deltas via single-signal file-paths overlap. Start's `next-session-prompt --session N` filters Top of Up Next by `session-N` label. Wrap detects state (dirty/ahead/no-PR/checks/mergeable) and acts; idempotent re-run picks up at the current state.

**Tech Stack:** Python 3.13, pytest (with `tests/conftest.py` helpers `import_cli`, `patch_gh_multi`, `write_minimal_board`), `gh` CLI shell-outs via `lib/board.Board.run_gh*`, ruff + mypy --strict.

**Ship order:** Phase 1 is PR 1 (start-side filter, standalone). Phases 2–5 land as PR 2 (stage proposal + wrap back-end + doctrine). Doctrine piggybacks on PR 2.

---

## File structure

**Created:**
- `skills/jared/scripts/lib/partition.py` — `Assignment`, `Proposal` dataclasses; `extract_surface()`, `propose_partition()`. Imports from `lib/ties.py`.
- `skills/jared/scripts/lib/wrap_state.py` — `GitState`, `PrState` dataclasses; `decide_next_step()` pure function returning a `StepName` literal.
- `tests/test_partition.py` — partition algorithm tests.
- `tests/test_wrap_state.py` — state-detection table tests.
- `tests/test_cmd_propose_partition.py` — CLI subcommand tests.
- `tests/test_cmd_wrap_state.py` — CLI subcommand tests.

**Modified:**
- `skills/jared/scripts/lib/ties.py` — promote `_file_paths_in_body`, `_GENERIC_FILES`, `_tokenize_title`, `_FILE_PATH_RE` to public (drop the underscore). Internal callers updated.
- `skills/jared/scripts/jared` — add `--session N` to `next-session-prompt`; add `propose-partition` subcommand; add `wrap-state` subcommand.
- `commands/jared-start.md` — pass `--session $SESSION_FLAG` through to `next-session-prompt`.
- `commands/jared-stage.md` — drive the propose-partition flow.
- `commands/jared-wrap.md` — back-end flow (commit prompt → push → PR create → mergeable check → confirm merge → existing cleanup).
- `skills/jared/references/parallel-sessions.md` — doctrine updates.
- `tests/test_cmd_next_session_prompt.py` — add `--session N` filter tests.

---

## Phase 1 — PR 1: Start-side filter (standalone)

**Branch setup:** The spec already lives on the `docs/multi-session-back-end-spec` branch (one commit on top of `main`, file `docs/superpowers/specs/2026-05-28-multi-session-back-end-design.md`). All Phase 1 commits land on this same branch; PR 1 includes the spec + Phase 1 code.

Run before starting Task 1.1:

```bash
cd /home/brockamer/Code/jared
git checkout docs/multi-session-back-end-spec
git log --oneline main..HEAD  # confirms the spec commit is present
```

### Task 1.1: Add `--session N` flag to `next-session-prompt` argparse

**Files:**
- Modify: `skills/jared/scripts/jared` — `next-session-prompt` subparser definition
- Test: `tests/test_cmd_next_session_prompt.py` — extend with one filter case

- [ ] **Step 1: Inspect the existing subparser to locate the insertion point**

Run: `grep -n "next-session-prompt\|next_session_prompt" /home/brockamer/Code/jared/skills/jared/scripts/jared | head -20`

Expected output includes lines defining `add_parser("next-session-prompt", ...)` and `--include-session-checks`, `--fresh` flag definitions. Note the line numbers.

- [ ] **Step 2: Write the failing test for `--session 1` filter behavior**

Append to `/home/brockamer/Code/jared/tests/test_cmd_next_session_prompt.py`:

```python
def test_next_session_prompt_session_flag_filters_up_next(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """--session N filters Top of Up Next to issues carrying the session-N label."""
    board_md = write_minimal_board(tmp_path)
    patch_gh_multi(
        monkeypatch,
        open_issues=[
            {"number": 100, "title": "Session-1 item A", "state": "OPEN"},
            {"number": 200, "title": "Session-2 item", "state": "OPEN"},
            {"number": 101, "title": "Session-1 item B", "state": "OPEN"},
            {"number": 300, "title": "Unlabeled item", "state": "OPEN"},
        ],
        statuses={
            100: ("Up Next", "High"),
            200: ("Up Next", "High"),
            101: ("Up Next", "Medium"),
            300: ("Up Next", "Medium"),
        },
        labels_by_number={
            100: ["session-1"],
            200: ["session-2"],
            101: ["session-1"],
            300: [],
        },
    )

    mod = import_cli()
    rc = mod.main(["--board", str(board_md), "next-session-prompt", "--session", "1"])
    out = capsys.readouterr().out

    assert rc == 0
    assert "#100" in out
    assert "#101" in out
    assert "#200" not in out
    assert "#300" not in out
```

- [ ] **Step 3: Run the test to confirm it fails**

Run: `cd /home/brockamer/Code/jared && pytest tests/test_cmd_next_session_prompt.py::test_next_session_prompt_session_flag_filters_up_next -v`

Expected: `error: unrecognized arguments: --session 1` (argparse rejects the unknown flag).

- [ ] **Step 4: Add the `--session N` flag to argparse**

In `/home/brockamer/Code/jared/skills/jared/scripts/jared`, find the `next-session-prompt` subparser block (search for `"next-session-prompt"`). Add a `--session` argument alongside `--include-session-checks` and `--fresh`:

```python
parser_nsp.add_argument(
    "--session",
    type=int,
    default=None,
    metavar="N",
    help="Filter Top of Up Next to issues labeled session-N (e.g., --session 1).",
)
```

- [ ] **Step 5: Run the test — still fails, but now for the right reason**

Run: `cd /home/brockamer/Code/jared && pytest tests/test_cmd_next_session_prompt.py::test_next_session_prompt_session_flag_filters_up_next -v`

Expected: test now runs but fails on `assert "#200" not in out` (flag is parsed but ignored).

- [ ] **Step 6: Commit (flag parsing only, filter logic next)**

```bash
cd /home/brockamer/Code/jared
git add tests/test_cmd_next_session_prompt.py skills/jared/scripts/jared
git commit -m "test(next-session-prompt): add failing test for --session N filter"
```

---

### Task 1.2: Implement the session-N filter

**Files:**
- Modify: `skills/jared/scripts/jared` — `_cmd_next_session_prompt` handler (the function the subparser dispatches to)

- [ ] **Step 1: Locate the rendering point for Top of Up Next**

Run: `grep -n "Top of Up Next\|up_next\|_render_up_next" /home/brockamer/Code/jared/skills/jared/scripts/jared | head -20`

Expected: lines showing where Up Next items are iterated and printed. Note the function name (likely `_cmd_next_session_prompt` or a helper it calls).

- [ ] **Step 2: Apply the filter in the handler**

In `/home/brockamer/Code/jared/skills/jared/scripts/jared`, in the function handling `next-session-prompt`, after fetching the Up Next items but before the top-3 cap is applied, filter by `session-N` label when the flag is set. Pattern (adapt to actual variable names in the codebase):

```python
session_filter: int | None = getattr(args, "session", None)
if session_filter is not None:
    label = f"session-{session_filter}"
    up_next_items = [item for item in up_next_items if label in item.labels]
```

The filter applies only to Up Next. In-flight and Recently-closed sections are unfiltered (they reflect actual board state, not a candidate pool).

- [ ] **Step 3: Run the test to confirm it passes**

Run: `cd /home/brockamer/Code/jared && pytest tests/test_cmd_next_session_prompt.py::test_next_session_prompt_session_flag_filters_up_next -v`

Expected: PASS.

- [ ] **Step 4: Run the existing test suite to confirm no regression**

Run: `cd /home/brockamer/Code/jared && pytest tests/test_cmd_next_session_prompt.py -v`

Expected: all tests pass (including the existing 3 in the file).

- [ ] **Step 5: Commit**

```bash
cd /home/brockamer/Code/jared
git add skills/jared/scripts/jared
git commit -m "feat(next-session-prompt): --session N filters Top of Up Next by session-N label"
```

---

### Task 1.3: Empty-result rendering for `--session N` with no matches

**Files:**
- Modify: `skills/jared/scripts/jared` — Up Next rendering
- Test: `tests/test_cmd_next_session_prompt.py`

- [ ] **Step 1: Write the failing test**

Append to `/home/brockamer/Code/jared/tests/test_cmd_next_session_prompt.py`:

```python
def test_next_session_prompt_session_flag_with_no_matches_renders_empty_marker(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """--session N with zero matching items prints an explicit empty marker
    instead of falling through to unlabeled items."""
    board_md = write_minimal_board(tmp_path)
    patch_gh_multi(
        monkeypatch,
        open_issues=[
            {"number": 300, "title": "Unlabeled item", "state": "OPEN"},
        ],
        statuses={300: ("Up Next", "High")},
        labels_by_number={300: []},
    )

    mod = import_cli()
    rc = mod.main(["--board", str(board_md), "next-session-prompt", "--session", "1"])
    out = capsys.readouterr().out

    assert rc == 0
    assert "(none labeled session-1)" in out
    assert "#300" not in out  # no silent fall-through
```

- [ ] **Step 2: Run the test to confirm it fails**

Run: `cd /home/brockamer/Code/jared && pytest tests/test_cmd_next_session_prompt.py::test_next_session_prompt_session_flag_with_no_matches_renders_empty_marker -v`

Expected: FAIL on `assert "(none labeled session-1)" in out`.

- [ ] **Step 3: Implement empty-marker rendering**

In the Up Next rendering block, after filtering, if `session_filter is not None and not up_next_items`, print the empty marker instead of the bulleted list:

```python
if session_filter is not None and not up_next_items:
    print(f"  (none labeled session-{session_filter})")
else:
    for item in up_next_items[:3]:
        print(f"  {_format_up_next_bullet(item)}")
```

(Adapt the for-loop body to the existing rendering pattern.)

- [ ] **Step 4: Run the test to confirm it passes**

Run: `cd /home/brockamer/Code/jared && pytest tests/test_cmd_next_session_prompt.py::test_next_session_prompt_session_flag_with_no_matches_renders_empty_marker -v`

Expected: PASS.

- [ ] **Step 5: Run the full next-session-prompt test file**

Run: `cd /home/brockamer/Code/jared && pytest tests/test_cmd_next_session_prompt.py -v`

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
cd /home/brockamer/Code/jared
git add tests/test_cmd_next_session_prompt.py skills/jared/scripts/jared
git commit -m "feat(next-session-prompt): empty marker for --session N with no matches"
```

---

### Task 1.4: Wire `--session N` through `/jared-start`

**Files:**
- Modify: `commands/jared-start.md` — step 1 invocation

- [ ] **Step 1: Read the current step 1 invocation**

Run: `grep -n "next-session-prompt" /home/brockamer/Code/jared/commands/jared-start.md`

Expected: a line showing the existing invocation `${CLAUDE_PLUGIN_ROOT}/skills/jared/scripts/jared next-session-prompt --include-session-checks`.

- [ ] **Step 2: Update the invocation to pass through `--session`**

In `/home/brockamer/Code/jared/commands/jared-start.md`, locate step 1 of the flow. Update the bash invocation to:

```bash
${CLAUDE_PLUGIN_ROOT}/skills/jared/scripts/jared next-session-prompt --include-session-checks ${SESSION_FLAG:+--session $SESSION_FLAG}
```

Add a sentence under the code block explaining the pass-through:

> When the operator passes `--session N`, the Top of Up Next section is filtered to `session-N`-labeled items. The menu shown for "Which issue would you like to pull?" is the session-N partition; items labeled for other sessions are hidden. If no items are labeled session-N, the section prints `(none labeled session-N)` and the operator must label items via `/jared-stage --sessions N` before pulling.

- [ ] **Step 3: Run all tests as a safety check**

Run: `cd /home/brockamer/Code/jared && pytest`

Expected: full suite passes.

- [ ] **Step 4: Lint and type-check**

Run: `cd /home/brockamer/Code/jared && ruff check . && ruff format --check . && mypy`

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
cd /home/brockamer/Code/jared
git add commands/jared-start.md
git commit -m "doctrine(start): pass --session through to next-session-prompt"
```

---

### Task 1.5: Open PR 1

**Files:** none new; this packages Phase 1 as a PR.

- [ ] **Step 1: File the tracking issue on the board**

Run:

```bash
cd /home/brockamer/Code/jared
./skills/jared/scripts/jared file \
  --title "feat(start): --session N filter on next-session-prompt" \
  --label enhancement \
  --priority Medium \
  --status "Up Next" \
  --no-milestone \
  --body "$(cat <<'EOF'
## Acceptance criteria

- `jared next-session-prompt --session N` filters Top of Up Next to issues labeled `session-N`
- Empty match renders `(none labeled session-N)` — no silent fall-through to unlabeled items
- `/jared-start --session N` (no issue arg) shows the filtered menu
- Existing `next-session-prompt` behavior unchanged when `--session` is absent

## Why

Today the recommendation menu surfaces global top-3 of Up Next regardless of `--session N`. The operator must mentally cross-reference labels. This change makes the partition load-bearing at start time.

## Out of scope

Stage-side proposal of session-N labels; wrap back-end flow. See `docs/superpowers/specs/2026-05-28-multi-session-back-end-design.md`.
EOF
)"
```

Note the issue number that's returned.

- [ ] **Step 2: Push the spec + Phase 1 branch**

The work is all on `docs/multi-session-back-end-spec`. Push it as-is — the branch name doesn't need to follow `feature/<ISSUE>-` since the PR title and body name the closing issue.

```bash
cd /home/brockamer/Code/jared
git push -u origin docs/multi-session-back-end-spec
```

- [ ] **Step 3: Create the PR**

```bash
cd /home/brockamer/Code/jared
gh pr create --title "feat(start): --session N filter on next-session-prompt (#<ISSUE>)" --body "$(cat <<'EOF'
## Summary

- Adds `--session N` flag to `jared next-session-prompt`
- Filters Top of Up Next by `session-N` label; renders `(none labeled session-N)` on no match
- `/jared-start --session N` passes the flag through; the menu shown when no issue is specified is now the session-N partition

Closes #<ISSUE>. Phase 1 of `docs/superpowers/specs/2026-05-28-multi-session-back-end-design.md`.

## Test plan

- [ ] `pytest tests/test_cmd_next_session_prompt.py -v` passes
- [ ] Manual smoke: run `jared next-session-prompt --session 1` against `brockamer/jared`; confirm only session-1 items in Top of Up Next
- [ ] Manual smoke: run `jared next-session-prompt --session 99` (no such label); confirm `(none labeled session-99)` rendered

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

Note the PR URL.

- [ ] **Step 4: Wait for operator review and merge**

Operator merges via `gh pr merge --merge --delete-branch` when ready. After merge, locally:

```bash
cd /home/brockamer/Code/jared
git checkout main
git pull origin main
```

Phase 1 complete. Continue to Phase 2 on a fresh branch.

---

## Phase 2 — ties.py refactor (prep for PR 2)

This phase removes the underscore from four private symbols in `lib/ties.py` so `lib/partition.py` can import them publicly. It's a zero-behavior-change refactor. Lands as the first commit of PR 2.

### Task 2.1: Promote four private symbols to public

**Files:**
- Modify: `skills/jared/scripts/lib/ties.py`

- [ ] **Step 1: Start a fresh branch for PR 2 work**

```bash
cd /home/brockamer/Code/jared
git checkout main
git pull origin main
git checkout -b feature/multi-session-stage-wrap
```

- [ ] **Step 2: Rename the four private symbols and their callers**

Open `/home/brockamer/Code/jared/skills/jared/scripts/lib/ties.py` and apply these renames everywhere they appear in the file:

| Old (private) | New (public) |
|---|---|
| `_file_paths_in_body` | `file_paths_in_body` |
| `_GENERIC_FILES` | `GENERIC_FILES` |
| `_tokenize_title` | `tokenize_title` |
| `_FILE_PATH_RE` | `FILE_PATH_RE` |

There are 4 definitions and approximately 6-7 internal call sites. Use sed for a deterministic mass rename:

```bash
cd /home/brockamer/Code/jared
sed -i \
  -e 's/_file_paths_in_body/file_paths_in_body/g' \
  -e 's/_GENERIC_FILES/GENERIC_FILES/g' \
  -e 's/_tokenize_title/tokenize_title/g' \
  -e 's/_FILE_PATH_RE/FILE_PATH_RE/g' \
  skills/jared/scripts/lib/ties.py
```

- [ ] **Step 3: Update the docstrings to reflect public status**

The docstring on `file_paths_in_body` (previously `_file_paths_in_body`) currently says it's a private helper. Open `/home/brockamer/Code/jared/skills/jared/scripts/lib/ties.py`, find the function, and replace its docstring:

```python
def file_paths_in_body(body: str) -> frozenset[str]:
    """Extract path-like tokens from a body. Generic filenames excluded.

    Public: also consumed by `lib/partition.py` to compute surface overlap.
    """
```

Same for `tokenize_title`:

```python
def tokenize_title(title: str) -> frozenset[str]:
    """Tokenize a title into lowercase content words for adjacency scoring.

    Public: also consumed by `lib/partition.py` (future signal, not v1).
    """
```

- [ ] **Step 4: Run the existing ties test suite to confirm zero regression**

Run: `cd /home/brockamer/Code/jared && pytest tests/test_ties_analyzers.py tests/test_ties_combine.py tests/test_ties_dataclasses.py tests/test_ties_format.py tests/test_cmd_ties.py -v`

Expected: all tests pass (the existing tests imported the *public* symbols `analyze_file_paths`, `OpenIssueForTies`, etc., which haven't changed; only internal callers were renamed).

- [ ] **Step 5: Run the full test suite for broader safety**

Run: `cd /home/brockamer/Code/jared && pytest`

Expected: full pass.

- [ ] **Step 6: Lint and type-check**

Run: `cd /home/brockamer/Code/jared && ruff check . && mypy`

Expected: pass.

- [ ] **Step 7: Commit**

```bash
cd /home/brockamer/Code/jared
git add skills/jared/scripts/lib/ties.py
git commit -m "refactor(ties): promote file_paths_in_body, GENERIC_FILES, tokenize_title, FILE_PATH_RE to public

Drops the underscore from four symbols so lib/partition.py can import
them. Internal callers updated. Zero behavior change."
```

---

### Task 2.2: Add public-import regression test

**Files:**
- Test: `tests/test_ties_analyzers.py` — add one assertion

- [ ] **Step 1: Add the import test**

Open `/home/brockamer/Code/jared/tests/test_ties_analyzers.py`. Append at the bottom:

```python
def test_public_extractors_importable() -> None:
    """Regression: lib/partition.py depends on these symbols being public.
    If anyone re-privates them, this test fails loudly."""
    from skills.jared.scripts.lib.ties import (
        FILE_PATH_RE,
        GENERIC_FILES,
        file_paths_in_body,
        tokenize_title,
    )

    assert callable(file_paths_in_body)
    assert callable(tokenize_title)
    assert isinstance(GENERIC_FILES, frozenset)
    assert FILE_PATH_RE.pattern  # has a pattern attribute
```

- [ ] **Step 2: Run the test to confirm it passes**

Run: `cd /home/brockamer/Code/jared && pytest tests/test_ties_analyzers.py::test_public_extractors_importable -v`

Expected: PASS.

- [ ] **Step 3: Commit**

```bash
cd /home/brockamer/Code/jared
git add tests/test_ties_analyzers.py
git commit -m "test(ties): regression test for public extractor symbols"
```

---

## Phase 3 — PR 2 part A: Partition module

### Task 3.1: Create `lib/partition.py` skeleton with dataclasses

**Files:**
- Create: `skills/jared/scripts/lib/partition.py`
- Create: `tests/test_partition.py`

- [ ] **Step 1: Write the failing test for the dataclass shapes**

Create `/home/brockamer/Code/jared/tests/test_partition.py`:

```python
"""Tests for the partition module — anti-overlap session-N assignment."""

from skills.jared.scripts.lib.partition import Assignment, Proposal


def test_assignment_dataclass_shape() -> None:
    a = Assignment(issue=42, session=1, reason="existing label honored")
    assert a.issue == 42
    assert a.session == 1
    assert a.reason == "existing label honored"


def test_assignment_session_none_for_float() -> None:
    a = Assignment(issue=42, session=None, reason="no surface signal in body")
    assert a.session is None


def test_proposal_dataclass_shape() -> None:
    p = Proposal(keep=[], move=[], add=[], floats=[])
    assert p.keep == []
    assert p.move == []
    assert p.add == []
    assert p.floats == []
```

- [ ] **Step 2: Run the test to confirm it fails**

Run: `cd /home/brockamer/Code/jared && pytest tests/test_partition.py -v`

Expected: `ModuleNotFoundError: No module named 'skills.jared.scripts.lib.partition'`.

- [ ] **Step 3: Create the partition module**

Create `/home/brockamer/Code/jared/skills/jared/scripts/lib/partition.py`:

```python
"""Anti-overlap partition: propose session-N label assignments for parallel
Claude sessions sharing one repo.

Single signal (v1): file paths cited in the issue body. Two candidates whose
bodies cite overlapping file paths are presumed to touch overlapping code.

The partition is operator-approved per item. Existing session-N labels are
honored (manual overrides win). A candidate with no surface signal is a
float — no label proposed.

See docs/superpowers/specs/2026-05-28-multi-session-back-end-design.md for
the full design and the cuts that distinguish v1 from a more elaborate
multi-signal version.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from lib.ties import file_paths_in_body

if TYPE_CHECKING:
    from lib.ties import OpenIssueForTies


@dataclass(frozen=True)
class Assignment:
    """Proposed session-N assignment for one issue.

    `session=None` means float — no label proposed for this issue. `reason`
    is a short rationale shown in the proposal output.
    """

    issue: int
    session: int | None
    reason: str


@dataclass(frozen=True)
class Proposal:
    """Full stage proposal across a candidate set.

    `keep` — issue's existing session-N label is honored.
    `move` — existing label, proposing a different session (reserved for a
             future re-balance flag; v1 never populates this list).
    `add`  — no existing label, proposing one.
    `floats` — no surface signal; no label proposed.
    """

    keep: list[Assignment]
    move: list[Assignment]
    add: list[Assignment]
    floats: list[Assignment]
```

- [ ] **Step 4: Run the test to confirm it passes**

Run: `cd /home/brockamer/Code/jared && pytest tests/test_partition.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
cd /home/brockamer/Code/jared
git add skills/jared/scripts/lib/partition.py tests/test_partition.py
git commit -m "feat(partition): create lib/partition.py with Assignment, Proposal dataclasses"
```

---

### Task 3.2: Implement `extract_surface(body)`

**Files:**
- Modify: `skills/jared/scripts/lib/partition.py`
- Modify: `tests/test_partition.py`

- [ ] **Step 1: Write the failing test**

Append to `/home/brockamer/Code/jared/tests/test_partition.py`:

```python
from skills.jared.scripts.lib.partition import extract_surface


def test_extract_surface_returns_file_paths_from_body() -> None:
    body = "Fix bug in `lib/board.py` and update `commands/jared-stage.md`."
    surface = extract_surface(body)
    assert "lib/board.py" in surface
    assert "commands/jared-stage.md" in surface


def test_extract_surface_excludes_generic_files() -> None:
    body = "Touches README.md and lib/board.py."
    surface = extract_surface(body)
    assert "README.md" not in surface
    assert "lib/board.py" in surface


def test_extract_surface_empty_body_returns_empty() -> None:
    assert extract_surface("") == frozenset()


def test_extract_surface_no_paths_returns_empty() -> None:
    assert extract_surface("Prose with no paths anywhere.") == frozenset()
```

- [ ] **Step 2: Run the test to confirm it fails**

Run: `cd /home/brockamer/Code/jared && pytest tests/test_partition.py -v`

Expected: `ImportError: cannot import name 'extract_surface'`.

- [ ] **Step 3: Implement `extract_surface`**

Append to `/home/brockamer/Code/jared/skills/jared/scripts/lib/partition.py`:

```python
def extract_surface(body: str) -> frozenset[str]:
    """Compute the surface fingerprint of an issue body — the set of file
    paths it cites. Single signal for v1.

    Direct alias of `lib.ties.file_paths_in_body`. Lives behind a partition-
    specific name so future signal expansion (title scope, label clusters)
    doesn't churn the partition-side import.
    """
    return file_paths_in_body(body)
```

- [ ] **Step 4: Run the test to confirm it passes**

Run: `cd /home/brockamer/Code/jared && pytest tests/test_partition.py -v`

Expected: all 7 tests pass.

- [ ] **Step 5: Commit**

```bash
cd /home/brockamer/Code/jared
git add skills/jared/scripts/lib/partition.py tests/test_partition.py
git commit -m "feat(partition): extract_surface() returns file paths cited in issue body"
```

---

### Task 3.3: Implement `propose_partition` — disjoint clusters happy path

**Files:**
- Modify: `skills/jared/scripts/lib/partition.py`
- Modify: `tests/test_partition.py`

- [ ] **Step 1: Add a test fixture helper for `OpenIssueForTies`**

Append to `/home/brockamer/Code/jared/tests/test_partition.py`:

```python
from skills.jared.scripts.lib.partition import propose_partition
from skills.jared.scripts.lib.ties import OpenIssueForTies


def _candidate(
    number: int,
    *,
    title: str = "",
    body: str = "",
    labels: tuple[str, ...] = (),
) -> OpenIssueForTies:
    return OpenIssueForTies(
        number=number,
        title=title,
        body=body,
        labels=labels,
        milestone=None,
        status="Up Next",
        priority="Medium",
        blocked_by=(),
    )
```

- [ ] **Step 2: Write the failing test for disjoint-cluster 2-way split**

Append:

```python
def test_propose_partition_disjoint_clusters_split_cleanly() -> None:
    """Two candidate groups citing entirely different file paths land in
    different sessions."""
    candidates = [
        _candidate(1, body="Update `lib/board.py`."),
        _candidate(2, body="Refactor `lib/board.py`."),
        _candidate(3, body="Edit `commands/jared-stage.md`."),
        _candidate(4, body="Edit `commands/jared-wrap.md`."),
    ]
    proposal = propose_partition(candidates, K=2, existing_session_labels={})

    # All four are `add` (no existing labels)
    assert len(proposal.add) == 4
    assert len(proposal.keep) == 0
    assert len(proposal.move) == 0
    assert len(proposal.floats) == 0

    # Issues 1 and 2 share lib/board.py — should be in the same session
    by_issue = {a.issue: a.session for a in proposal.add}
    assert by_issue[1] == by_issue[2]
    # Issues 3 and 4 share commands/ — should be in the same session
    assert by_issue[3] == by_issue[4]
    # The two groups should be in different sessions
    assert by_issue[1] != by_issue[3]
```

- [ ] **Step 3: Run the test to confirm it fails**

Run: `cd /home/brockamer/Code/jared && pytest tests/test_partition.py::test_propose_partition_disjoint_clusters_split_cleanly -v`

Expected: `ImportError: cannot import name 'propose_partition'`.

- [ ] **Step 4: Implement `propose_partition`**

Append to `/home/brockamer/Code/jared/skills/jared/scripts/lib/partition.py`:

```python
def propose_partition(
    candidates: list[OpenIssueForTies],
    K: int,
    existing_session_labels: dict[int, int],
) -> Proposal:
    """Greedy anti-overlap partition.

    Walks `candidates` in their given order (caller is expected to sort by
    priority). For each candidate:

    - If body has no file paths → float (no label proposed, regardless of
      existing label).
    - If an existing session-N label is set and 1 ≤ N ≤ K → keep (honor
      operator's prior decision).
    - Otherwise → pick the session with the smallest cumulative surface
      overlap; tie-break by load (smaller session wins).

    `move` is reserved for a future re-balance flag and is always empty in
    v1 — existing labels are never overridden.
    """
    session_surfaces: dict[int, set[str]] = {n: set() for n in range(1, K + 1)}
    session_loads: dict[int, int] = {n: 0 for n in range(1, K + 1)}

    keep: list[Assignment] = []
    move: list[Assignment] = []
    add: list[Assignment] = []
    floats: list[Assignment] = []

    for candidate in candidates:
        surface = extract_surface(candidate.body)
        if not surface:
            floats.append(
                Assignment(
                    issue=candidate.number,
                    session=None,
                    reason="no surface signal in body",
                )
            )
            continue

        existing = existing_session_labels.get(candidate.number)
        if existing is not None and 1 <= existing <= K:
            keep.append(
                Assignment(
                    issue=candidate.number,
                    session=existing,
                    reason="existing label honored",
                )
            )
            session_surfaces[existing] |= surface
            session_loads[existing] += 1
            continue

        # Pick session with smallest overlap, tie-break by smaller load.
        best = min(
            range(1, K + 1),
            key=lambda n: (len(session_surfaces[n] & surface), session_loads[n]),
        )
        overlap = session_surfaces[best] & surface
        if overlap:
            reason = f"smallest overlap with session-{best} (shares {sorted(overlap)[0]})"
        else:
            reason = f"no overlap with session-{best}"

        add.append(
            Assignment(
                issue=candidate.number,
                session=best,
                reason=reason,
            )
        )
        session_surfaces[best] |= surface
        session_loads[best] += 1

    return Proposal(keep=keep, move=move, add=add, floats=floats)
```

- [ ] **Step 5: Run the test to confirm it passes**

Run: `cd /home/brockamer/Code/jared && pytest tests/test_partition.py::test_propose_partition_disjoint_clusters_split_cleanly -v`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
cd /home/brockamer/Code/jared
git add skills/jared/scripts/lib/partition.py tests/test_partition.py
git commit -m "feat(partition): propose_partition greedy assignment for disjoint clusters"
```

---

### Task 3.4: Test existing-label honoring + float behavior

**Files:**
- Modify: `tests/test_partition.py`

- [ ] **Step 1: Write three more tests**

Append to `/home/brockamer/Code/jared/tests/test_partition.py`:

```python
def test_propose_partition_honors_existing_labels() -> None:
    """Issues with existing session-N labels land in `keep`, not `add`."""
    candidates = [
        _candidate(1, body="Update `lib/board.py`."),
        _candidate(2, body="Refactor `lib/board.py`."),
    ]
    proposal = propose_partition(
        candidates,
        K=2,
        existing_session_labels={1: 1, 2: 2},
    )
    assert len(proposal.keep) == 2
    assert len(proposal.add) == 0
    keep_sessions = {a.issue: a.session for a in proposal.keep}
    assert keep_sessions[1] == 1
    assert keep_sessions[2] == 2


def test_propose_partition_float_candidate_with_no_surface() -> None:
    """A candidate whose body has no file paths is a float — no label
    proposed even if other candidates could absorb it."""
    candidates = [
        _candidate(1, body="Prose-only issue with no paths anywhere."),
    ]
    proposal = propose_partition(candidates, K=2, existing_session_labels={})
    assert len(proposal.floats) == 1
    assert proposal.floats[0].issue == 1
    assert proposal.floats[0].session is None
    assert len(proposal.add) == 0


def test_propose_partition_load_balance_tiebreak_on_zero_overlap() -> None:
    """When no overlap exists with any session, the smaller-load session wins."""
    candidates = [
        _candidate(1, body="Touches `a/a.py`."),
        _candidate(2, body="Touches `b/b.py`."),
        _candidate(3, body="Touches `c/c.py`."),
    ]
    proposal = propose_partition(candidates, K=2, existing_session_labels={})
    # Three disjoint candidates, two sessions: split 2/1.
    counts = {1: 0, 2: 0}
    for a in proposal.add:
        if a.session is not None:
            counts[a.session] += 1
    assert sorted(counts.values()) == [1, 2]
```

- [ ] **Step 2: Run the new tests**

Run: `cd /home/brockamer/Code/jared && pytest tests/test_partition.py -v`

Expected: all tests pass (the implementation from Task 3.3 already covers these cases).

If any fail, fix the implementation in `lib/partition.py` accordingly. The most likely failure is the load-balance test — verify the `min` key is `(overlap_size, load)`.

- [ ] **Step 3: Commit**

```bash
cd /home/brockamer/Code/jared
git add tests/test_partition.py
git commit -m "test(partition): existing-label honoring, float candidates, load-balance tiebreak"
```

---

### Task 3.5: Add `jared propose-partition` CLI subcommand

**Files:**
- Modify: `skills/jared/scripts/jared`
- Create: `tests/test_cmd_propose_partition.py`

- [ ] **Step 1: Write the failing test**

Create `/home/brockamer/Code/jared/tests/test_cmd_propose_partition.py`:

```python
"""Tests for `jared propose-partition`."""

import json
from pathlib import Path

import pytest

from tests.conftest import import_cli, patch_gh_multi, write_minimal_board


def test_propose_partition_human_format_renders_proposal(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    board_md = write_minimal_board(tmp_path)
    patch_gh_multi(
        monkeypatch,
        open_issues=[
            {
                "number": 1,
                "title": "A",
                "state": "OPEN",
                "body": "Edits `lib/board.py`.",
            },
            {
                "number": 2,
                "title": "B",
                "state": "OPEN",
                "body": "Edits `commands/jared-wrap.md`.",
            },
        ],
        statuses={1: ("Up Next", "High"), 2: ("Up Next", "Medium")},
        labels_by_number={1: [], 2: []},
    )

    mod = import_cli()
    rc = mod.main(
        ["--board", str(board_md), "propose-partition", "--sessions", "2"]
    )
    out = capsys.readouterr().out

    assert rc == 0
    assert "session-1" in out
    assert "session-2" in out
    assert "#1" in out and "#2" in out


def test_propose_partition_json_format_returns_structured_proposal(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    board_md = write_minimal_board(tmp_path)
    patch_gh_multi(
        monkeypatch,
        open_issues=[
            {"number": 1, "title": "A", "state": "OPEN", "body": "Edits `x/y.py`."},
        ],
        statuses={1: ("Up Next", "High")},
        labels_by_number={1: []},
    )

    mod = import_cli()
    rc = mod.main(
        [
            "--board",
            str(board_md),
            "propose-partition",
            "--sessions",
            "2",
            "--format",
            "json",
        ]
    )
    out = capsys.readouterr().out

    assert rc == 0
    payload = json.loads(out)
    assert "keep" in payload
    assert "add" in payload
    assert "floats" in payload
    # Issue 1 has file paths and no existing label → should be in `add`.
    assert any(a["issue"] == 1 for a in payload["add"])
```

- [ ] **Step 2: Run the test to confirm it fails**

Run: `cd /home/brockamer/Code/jared && pytest tests/test_cmd_propose_partition.py -v`

Expected: argparse error — subcommand `propose-partition` not registered.

- [ ] **Step 3: Register the subcommand**

In `/home/brockamer/Code/jared/skills/jared/scripts/jared`, find the subparser registration block (search for `add_parser`). Add a new subparser modeled on `next-session-prompt`:

```python
parser_pp = subparsers.add_parser(
    "propose-partition",
    help="Propose session-N label assignments across Up Next + currently-labeled items.",
)
parser_pp.add_argument(
    "--sessions",
    type=int,
    required=True,
    metavar="K",
    help="Number of parallel sessions to partition across (typically 2).",
)
parser_pp.add_argument(
    "--format",
    choices=["human", "json"],
    default="human",
    help="Output format (default: human).",
)
parser_pp.set_defaults(func=_cmd_propose_partition)
```

- [ ] **Step 4: Implement the handler**

Add the handler function `_cmd_propose_partition` in the same file. The handler fetches Up Next + currently-labeled items, calls `propose_partition`, renders.

```python
def _cmd_propose_partition(args: argparse.Namespace, board: Board) -> int:
    from lib.partition import Assignment, Proposal, propose_partition

    K = args.sessions
    if K < 2:
        print("ERROR: --sessions must be at least 2.", file=sys.stderr)
        return 2

    # Fetch candidate set: Up Next items + currently-labeled session-N items
    # (any status — currently-labeled In Progress items inform the surface
    # state, even though their labels are honored).
    open_items = board.fetch_open_items_for_partition(K)

    existing_labels: dict[int, int] = {}
    candidates = []
    for item in open_items:
        for label in item.labels:
            if label.startswith("session-"):
                try:
                    n = int(label.removeprefix("session-"))
                except ValueError:
                    continue
                if 1 <= n <= K:
                    existing_labels[item.number] = n
                    break
        candidates.append(item)

    proposal = propose_partition(candidates, K, existing_labels)

    if args.format == "json":
        import json as _json

        print(
            _json.dumps(
                {
                    "keep": [vars(a) for a in proposal.keep],
                    "move": [vars(a) for a in proposal.move],
                    "add": [vars(a) for a in proposal.add],
                    "floats": [vars(a) for a in proposal.floats],
                }
            )
        )
        return 0

    # Human format
    print(
        f"Looking at {len(candidates)} candidates across "
        f"sessions {', '.join(str(n) for n in range(1, K + 1))}."
    )
    print()
    for n in range(1, K + 1):
        session_assignments = [
            a for a in proposal.keep + proposal.add if a.session == n
        ]
        print(f"session-{n} (proposing {len(session_assignments)} items):")
        for a in session_assignments:
            verb = "keep" if a in proposal.keep else "add"
            print(f"  {verb} #{a.issue} — {a.reason}")
        print()

    if proposal.floats:
        print("floats (no surface signal):")
        for a in proposal.floats:
            print(f"  #{a.issue} — {a.reason}")
        print()

    print("Approve? (y / edit / skip)")
    return 0
```

- [ ] **Step 5: Wire the handler to `Board.fetch_open_issues_for_ties`**

The handler in Step 4 used `board.fetch_open_items_for_partition(K)` as a placeholder. The real method on `Board` is `fetch_open_issues_for_ties(...)` — it returns `list[OpenIssueForTies]` with `labels: tuple[str, ...]` already populated, which is exactly what the partition handler needs.

Verify the signature:

```bash
grep -A 5 "def fetch_open_issues_for_ties" /home/brockamer/Code/jared/skills/jared/scripts/lib/board.py
```

Update the handler line in `/home/brockamer/Code/jared/skills/jared/scripts/jared`:

```python
# Replace the placeholder:
#   open_items = board.fetch_open_items_for_partition(K)
# with the real method:
open_items = board.fetch_open_issues_for_ties()
```

If `fetch_open_issues_for_ties` requires arguments (e.g., a target issue for cross-references), pass `None` or a sentinel — the partition use doesn't need target-specific filtering. Inspect the signature and adapt accordingly. If extension is required to omit the target requirement, add an optional argument with a default that makes the method work standalone.

- [ ] **Step 6: Run the tests to confirm they pass**

Run: `cd /home/brockamer/Code/jared && pytest tests/test_cmd_propose_partition.py -v`

Expected: both tests pass.

- [ ] **Step 7: Run the full test suite for safety**

Run: `cd /home/brockamer/Code/jared && pytest`

Expected: full pass.

- [ ] **Step 8: Commit**

```bash
cd /home/brockamer/Code/jared
git add skills/jared/scripts/jared tests/test_cmd_propose_partition.py
git commit -m "feat(propose-partition): CLI subcommand with human + json output"
```

---

### Task 3.6: Update `commands/jared-stage.md` to drive the proposal flow

**Files:**
- Modify: `commands/jared-stage.md`

- [ ] **Step 1: Read the current stage command to understand its flow**

Run: `head -80 /home/brockamer/Code/jared/commands/jared-stage.md`

Note the existing structure — voice opening, current flow (Backlog → Up Next promotion proposals), where the partition step fits naturally.

- [ ] **Step 2: Add the `--sessions N` partition flow to the slash command**

In `/home/brockamer/Code/jared/commands/jared-stage.md`, add a new section after the existing promotion proposal block (or wherever fits the existing structure). Suggested content:

```markdown
## Session-N partitioning (`--sessions N`)

When the operator runs `/jared-stage --sessions N` (e.g., `--sessions 2`), propose session-N label assignments across the current candidate set.

Flow:

1. Run:

   ```bash
   ${CLAUDE_PLUGIN_ROOT}/skills/jared/scripts/jared propose-partition --sessions N
   ```

2. Capture stdout. The CLI emits a per-session block showing `keep` (existing labels honored) and `add` (no existing label, partition proposes one), plus a `floats` block for candidates with no surface signal.

3. Render the output verbatim under a voice-wrapped intro, e.g.:

   > Looking at the partition for sessions 1 and 2 — here's what I'd propose based on file paths in the issue bodies:
   >
   > [verbatim CLI output]
   >
   > Approve? (y / edit `#N session=N` / skip)

4. On `y`: apply each `add` assignment with:

   ```bash
   gh issue edit <N> --add-label session-K --repo <owner>/<repo>
   ```

5. On `edit #N session=K`: apply the operator's override, then continue.

6. On `skip`: do nothing; the partition is unchanged.

**Honoring existing labels.** The partition algorithm never overrides an existing `session-N` label. To re-balance, the operator removes the label manually and re-runs `/jared-stage --sessions N`.

**Single signal.** v1 uses only file paths cited in issue bodies. Two candidates whose bodies share a path are presumed to touch overlapping code. Issues with no paths in their body float (no label proposed).
```

- [ ] **Step 3: Run all tests as a safety check**

Run: `cd /home/brockamer/Code/jared && pytest`

Expected: full pass.

- [ ] **Step 4: Commit**

```bash
cd /home/brockamer/Code/jared
git add commands/jared-stage.md
git commit -m "doctrine(stage): --sessions N flow drives propose-partition + label application"
```

---

## Phase 4 — PR 2 part B: Wrap back-end

### Task 4.1: Create `lib/wrap_state.py` with `GitState`, `PrState`, `decide_next_step()`

**Files:**
- Create: `skills/jared/scripts/lib/wrap_state.py`
- Create: `tests/test_wrap_state.py`

- [ ] **Step 1: Write the failing test for the state-detection table**

Create `/home/brockamer/Code/jared/tests/test_wrap_state.py`:

```python
"""Tests for the wrap state-detection table.

The pure function `decide_next_step(git_state, pr_state)` is the spine of the
wrap back-end flow's idempotency: each step inspects state and decides whether
to act, so re-running wrap picks up at the same step.
"""

from skills.jared.scripts.lib.wrap_state import (
    GitState,
    PrState,
    decide_next_step,
)


def _git(dirty: bool = False, ahead: bool = False) -> GitState:
    return GitState(dirty=dirty, branch="feature/100-worktree", ahead_of_remote=ahead)


def _pr(
    *,
    exists: bool = False,
    checks: str = "none",
    mergeable: bool | None = None,
    merged: bool = False,
) -> PrState:
    return PrState(
        exists=exists,
        pr_number=42 if exists else None,
        checks_status=checks,
        mergeable=mergeable,
        merged=merged,
    )


def test_decide_dirty_tree_returns_commit() -> None:
    assert decide_next_step(_git(dirty=True), _pr()) == "commit"


def test_decide_ahead_no_pr_returns_push() -> None:
    assert decide_next_step(_git(ahead=True), _pr()) == "push"


def test_decide_clean_no_pr_returns_create_pr() -> None:
    assert decide_next_step(_git(), _pr()) == "create_pr"


def test_decide_pr_checks_pending_returns_wait_checks() -> None:
    assert (
        decide_next_step(_git(), _pr(exists=True, checks="pending"))
        == "wait_checks"
    )


def test_decide_pr_checks_failed_returns_surface_failure() -> None:
    assert (
        decide_next_step(_git(), _pr(exists=True, checks="failed"))
        == "surface_failure"
    )


def test_decide_pr_checks_green_not_mergeable_returns_surface_conflict() -> None:
    assert (
        decide_next_step(
            _git(), _pr(exists=True, checks="passed", mergeable=False)
        )
        == "surface_conflict"
    )


def test_decide_pr_checks_green_mergeable_returns_confirm_merge() -> None:
    assert (
        decide_next_step(
            _git(), _pr(exists=True, checks="passed", mergeable=True)
        )
        == "confirm_merge"
    )


def test_decide_pr_merged_returns_cleanup() -> None:
    assert decide_next_step(_git(), _pr(exists=True, merged=True)) == "cleanup"


def test_decide_dirty_tree_takes_precedence_over_pr_state() -> None:
    """Dirty working tree must be addressed before any PR-side action."""
    assert (
        decide_next_step(
            _git(dirty=True),
            _pr(exists=True, checks="passed", mergeable=True),
        )
        == "commit"
    )
```

- [ ] **Step 2: Run the test to confirm it fails**

Run: `cd /home/brockamer/Code/jared && pytest tests/test_wrap_state.py -v`

Expected: `ModuleNotFoundError: No module named 'skills.jared.scripts.lib.wrap_state'`.

- [ ] **Step 3: Create the module**

Create `/home/brockamer/Code/jared/skills/jared/scripts/lib/wrap_state.py`:

```python
"""Wrap back-end state detection — pure function, no I/O.

The wrap slash command collects git state via `git status` and PR state via
`gh pr view --json ...`, hands them to `decide_next_step`, and acts on the
returned `StepName`. Re-running wrap re-evaluates state and picks up at
whichever step is current — no in-flight lock needed; state IS the lock.

See docs/superpowers/specs/2026-05-28-multi-session-back-end-design.md §
"Phase 3 — Wrap back-end" for the full state table and rationale.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

CheckStatus = Literal["pending", "passed", "failed", "none"]
StepName = Literal[
    "commit",
    "push",
    "create_pr",
    "wait_checks",
    "surface_failure",
    "surface_conflict",
    "confirm_merge",
    "cleanup",
]


@dataclass(frozen=True)
class GitState:
    """Working-tree + branch state at wrap entry."""

    dirty: bool
    branch: str
    ahead_of_remote: bool


@dataclass(frozen=True)
class PrState:
    """Pull request state for the current branch."""

    exists: bool
    pr_number: int | None
    checks_status: CheckStatus
    mergeable: bool | None
    merged: bool


def decide_next_step(git_state: GitState, pr_state: PrState) -> StepName:
    """Pick the next wrap step from current state.

    Precedence (highest first):
      1. Dirty tree → commit (must be addressed before any PR action).
      2. PR merged → cleanup (worktree + branch removal).
      3. Branch ahead of remote → push.
      4. No PR → create_pr.
      5. PR checks pending → wait_checks (exit clean; re-run when green).
      6. PR checks failed → surface_failure (exit clean; operator fixes).
      7. PR checks green, not mergeable → surface_conflict (rebase needed).
      8. PR checks green, mergeable → confirm_merge.
    """
    if git_state.dirty:
        return "commit"
    if pr_state.merged:
        return "cleanup"
    if git_state.ahead_of_remote:
        return "push"
    if not pr_state.exists:
        return "create_pr"
    if pr_state.checks_status == "pending":
        return "wait_checks"
    if pr_state.checks_status == "failed":
        return "surface_failure"
    # checks_status == "passed" (or "none" — treated as passed for now)
    if pr_state.mergeable is False:
        return "surface_conflict"
    return "confirm_merge"
```

- [ ] **Step 4: Run the tests to confirm they pass**

Run: `cd /home/brockamer/Code/jared && pytest tests/test_wrap_state.py -v`

Expected: all 9 tests pass.

- [ ] **Step 5: Lint + type-check**

Run: `cd /home/brockamer/Code/jared && ruff check . && mypy`

Expected: pass.

- [ ] **Step 6: Commit**

```bash
cd /home/brockamer/Code/jared
git add skills/jared/scripts/lib/wrap_state.py tests/test_wrap_state.py
git commit -m "feat(wrap-state): pure state-detection function for wrap back-end flow"
```

---

### Task 4.2: Add `jared wrap-state` CLI subcommand

**Files:**
- Modify: `skills/jared/scripts/jared`
- Create: `tests/test_cmd_wrap_state.py`

- [ ] **Step 1: Write the failing test**

Create `/home/brockamer/Code/jared/tests/test_cmd_wrap_state.py`:

```python
"""Tests for `jared wrap-state` — collects git + PR state, prints next step name."""

from pathlib import Path
from unittest.mock import patch

import pytest

from tests.conftest import import_cli, write_minimal_board


def test_wrap_state_dirty_tree_prints_commit(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    board_md = write_minimal_board(tmp_path)

    with patch("subprocess.run") as mock_run:
        # `git status --porcelain` returns dirty output.
        # `git rev-parse --abbrev-ref HEAD` returns a branch.
        # `git rev-list --count @{u}..HEAD` returns "0".
        # `gh pr view --json ...` returns no PR.
        def _run(cmd, **kwargs):  # type: ignore[no-untyped-def]
            from subprocess import CompletedProcess

            argv = cmd if isinstance(cmd, list) else cmd.split()
            if argv[:2] == ["git", "status"]:
                return CompletedProcess(argv, 0, " M file.py\n", "")
            if argv[:2] == ["git", "rev-parse"]:
                return CompletedProcess(argv, 0, "feature/100-worktree\n", "")
            if argv[:2] == ["git", "rev-list"]:
                return CompletedProcess(argv, 0, "0\n", "")
            if argv[:2] == ["gh", "pr"]:
                return CompletedProcess(argv, 1, "", "no pull requests found")
            return CompletedProcess(argv, 0, "", "")

        mock_run.side_effect = _run

        mod = import_cli()
        rc = mod.main(["--board", str(board_md), "wrap-state"])

    out = capsys.readouterr().out.strip()
    assert rc == 0
    assert out == "commit"
```

- [ ] **Step 2: Run the test to confirm it fails**

Run: `cd /home/brockamer/Code/jared && pytest tests/test_cmd_wrap_state.py -v`

Expected: argparse error — `wrap-state` subcommand not registered.

- [ ] **Step 3: Register and implement the subcommand**

In `/home/brockamer/Code/jared/skills/jared/scripts/jared`, add a subparser:

```python
parser_ws = subparsers.add_parser(
    "wrap-state",
    help="Collect git + PR state and print the next wrap step name.",
)
parser_ws.set_defaults(func=_cmd_wrap_state)
```

Add the handler:

```python
def _cmd_wrap_state(args: argparse.Namespace, board: Board) -> int:
    """Collect git + PR state, hand to decide_next_step, print the step name."""
    from lib.wrap_state import GitState, PrState, decide_next_step

    # Git state
    status_result = subprocess.run(
        ["git", "status", "--porcelain"],
        capture_output=True,
        text=True,
        check=False,
    )
    dirty = bool(status_result.stdout.strip())

    branch_result = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
    )
    branch = branch_result.stdout.strip()

    ahead_result = subprocess.run(
        ["git", "rev-list", "--count", "@{u}..HEAD"],
        capture_output=True,
        text=True,
        check=False,
    )
    # @{u}..HEAD fails when no upstream; treat as ahead=False, will go to
    # `push` only if local commits exist (which `create_pr` also implies).
    try:
        ahead = int(ahead_result.stdout.strip() or "0") > 0
    except ValueError:
        ahead = False

    git_state = GitState(dirty=dirty, branch=branch, ahead_of_remote=ahead)

    # PR state
    pr_result = subprocess.run(
        [
            "gh",
            "pr",
            "view",
            "--json",
            "number,mergeable,mergeStateStatus,state,statusCheckRollup",
            branch,
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    if pr_result.returncode != 0:
        pr_state = PrState(
            exists=False,
            pr_number=None,
            checks_status="none",
            mergeable=None,
            merged=False,
        )
    else:
        import json as _json

        pr_payload = _json.loads(pr_result.stdout)
        # mergeable values: "MERGEABLE", "CONFLICTING", "UNKNOWN"
        mergeable_value = pr_payload.get("mergeable")
        mergeable: bool | None = None
        if mergeable_value == "MERGEABLE":
            mergeable = True
        elif mergeable_value == "CONFLICTING":
            mergeable = False
        # else: UNKNOWN → None

        # Aggregate checks
        rollup = pr_payload.get("statusCheckRollup") or []
        statuses = {c.get("conclusion") or c.get("status") for c in rollup}
        if "FAILURE" in statuses or "CANCELLED" in statuses or "TIMED_OUT" in statuses:
            checks_status = "failed"
        elif "IN_PROGRESS" in statuses or "PENDING" in statuses or "QUEUED" in statuses:
            checks_status = "pending"
        elif rollup:
            checks_status = "passed"
        else:
            checks_status = "none"

        pr_state = PrState(
            exists=True,
            pr_number=pr_payload.get("number"),
            checks_status=checks_status,  # type: ignore[arg-type]
            mergeable=mergeable,
            merged=(pr_payload.get("state") == "MERGED"),
        )

    print(decide_next_step(git_state, pr_state))
    return 0
```

- [ ] **Step 4: Run the test to confirm it passes**

Run: `cd /home/brockamer/Code/jared && pytest tests/test_cmd_wrap_state.py -v`

Expected: PASS.

- [ ] **Step 5: Run the full test suite for safety**

Run: `cd /home/brockamer/Code/jared && pytest`

Expected: full pass.

- [ ] **Step 6: Commit**

```bash
cd /home/brockamer/Code/jared
git add skills/jared/scripts/jared tests/test_cmd_wrap_state.py
git commit -m "feat(wrap-state): CLI subcommand collects git + PR state, prints next step"
```

---

### Task 4.3: Update `commands/jared-wrap.md` with the back-end flow

**Files:**
- Modify: `commands/jared-wrap.md`

- [ ] **Step 1: Read the current wrap command's step 5 (cleanup)**

Run: `awk '/^5\. /,/^6\. /' /home/brockamer/Code/jared/commands/jared-wrap.md | head -60`

Note where the worktree-removal step lives and the structure of the surrounding flow.

- [ ] **Step 2: Insert the back-end flow steps before the existing cleanup**

In `/home/brockamer/Code/jared/commands/jared-wrap.md`, after the Session-note application steps (step 5 currently) and before the worktree-removal block, add a new step block. Exact insertion: between the `## Current state` capture step and the `Clear this session's presence lock` step.

Suggested content:

```markdown
5b. **Run the back-end flow.** After Session notes are posted and reconciliation is applied, run the commit → push → PR create → mergeable check → confirm merge → cleanup sequence. The flow is idempotent — re-running `/jared-wrap` re-evaluates state and picks up at the current step.

   Loop:

   ```bash
   STEP=$(${CLAUDE_PLUGIN_ROOT}/skills/jared/scripts/jared wrap-state)
   ```

   Each iteration of the loop runs the CLI to determine the next step, then executes that step. Loop exits on `cleanup` (which runs the existing worktree-remove + lock-clear block below), or when the operator declines a confirm prompt, or when a non-actionable step (`wait_checks`, `surface_failure`, `surface_conflict`) is returned.

   **Step actions:**

   - **`commit`** (working tree dirty): Show `git status` to the operator. Ask: *"Commit message? (or 'skip' to leave uncommitted and exit)"*. On a message: run `git add -A && git commit -m "$msg"`. On `skip`: exit wrap (the lock is still cleared at the end). Loop continues after a successful commit.

   - **`push`** (local commits ahead of remote): Run `git push -u origin $(git rev-parse --abbrev-ref HEAD)`. On failure, surface the git error and exit. Loop continues on success.

   - **`create_pr`** (no PR for the branch): Auto-generate title from the issue title (the issue moved to In Progress at start). Auto-generate body from the issue's first paragraph + the commit subjects on the branch. Run:

     ```bash
     gh pr create --title "$TITLE" --body "$BODY"
     ```

     On failure, surface the gh error and exit. Loop continues on success.

   - **`wait_checks`** (PR exists, checks pending): Print *"PR #N: checks pending. Re-run `/jared-wrap` when they're green and I'll handle the merge."* Exit the loop (do not poll). The remaining wrap steps (lock-clear) still run.

   - **`surface_failure`** (PR exists, checks failed): Print the failed check names from `gh pr checks $PR --json`. Exit the loop. Lock-clear runs.

   - **`surface_conflict`** (checks green but not mergeable): Print *"PR #N: conflict with main. Rebase in this worktree (`git fetch && git rebase origin/main`), resolve, push, and re-run `/jared-wrap`."* Exit the loop. Lock-clear runs.

   - **`confirm_merge`** (checks green, mergeable): Render the confirm-merge block:

     ```
     PR #<N>: <title>
       branch:     <branch>
       mergeable:  yes
       checks:     <count> passed
       sibling:    <enumerate other session locks if present, with their branches>

     Merge? (y / edit / no)
     ```

     On `y`: run `gh pr merge <N> --merge --delete-branch`. On success, loop continues (next state will be `cleanup`). On failure (e.g., GitHub rejected as not-mergeable since the last check), surface the gh error and exit the loop.

     On `edit`: prompt for new title/body inline; run `gh pr edit <N> --title "$NEW_TITLE" --body "$NEW_BODY"`; re-render the confirm block.

     On `no`: exit the loop. Lock-clear runs.

   - **`cleanup`** (PR merged, branch still local): Run the existing worktree-remove + branch-d block (already present below).

   **Concurrent-merge safety.** Two sessions reaching `confirm_merge` at nearly the same time both run the same `wrap-state` query just before the merge. GitHub's PR-merge API is atomic — the first call serializes ahead of the second. If the first's merge invalidates the second's mergeable state, the second's `gh pr merge` call returns an error from GitHub, which surfaces to the operator. No Jared-side lock is used.
```

- [ ] **Step 3: Run all tests as a safety check**

Run: `cd /home/brockamer/Code/jared && pytest`

Expected: full pass (slash-command docs aren't tested by unit tests, but this confirms no regressions).

- [ ] **Step 4: Commit**

```bash
cd /home/brockamer/Code/jared
git add commands/jared-wrap.md
git commit -m "doctrine(wrap): back-end flow (commit -> push -> PR -> merge -> cleanup) via wrap-state"
```

---

## Phase 5 — Doctrine + finalize PR 2

### Task 5.1: Update `references/parallel-sessions.md`

**Files:**
- Modify: `skills/jared/references/parallel-sessions.md`

- [ ] **Step 1: Read the existing reference**

Run: `cat /home/brockamer/Code/jared/skills/jared/references/parallel-sessions.md`

Note the current sections (mostly operator-vigilance framing for the pre-mechanism era).

- [ ] **Step 2: Replace the "Pre-parallel-session operator ritual" section**

In `/home/brockamer/Code/jared/skills/jared/references/parallel-sessions.md`, find the section titled `## Pre-parallel-session operator ritual` and replace its body. Old content (operator does `gh issue edit` by hand) becomes:

```markdown
## Pre-parallel-session ritual

Before launching two or more Claude sessions against the same repo:

1. Run `/jared-stage --sessions N` (e.g., `--sessions 2` for two sessions). Jared reads current `session-N` labels and the Up Next candidates, then proposes a partition based on file-paths overlap in issue bodies. Operator approves or edits per-item.

2. Start the sessions with `/jared-start <issue> --session N`, or `/jared-start --session N` (no issue) to pull the top of the session-N filtered queue.

The partition is operator-approved per item; Jared never applies a `session-N` label without the operator saying so. To re-balance later, re-run `/jared-stage --sessions N` — existing labels are honored unless the operator removes them manually first.
```

- [ ] **Step 3: Add a new section describing the wrap back-end**

Append to the same file, before the existing `## Triggers for the worktree default` or `## When in doubt` section:

```markdown
## The wrap back-end

`/jared-wrap` runs the full commit → push → PR create → mergeable check → confirm merge → cleanup sequence after Session notes are posted. The operator confirms only the merge (the irreversible step against protected `main`).

Idempotency: each step inspects current state via `jared wrap-state`. Re-running `/jared-wrap` after a failure or interruption picks up at the current state — no in-flight lock, no manual recovery sequencing. The state IS the lock.

Concurrent merge safety: two sessions reaching the merge step around the same time both re-check `mergeable` immediately before calling `gh pr merge`. GitHub's PR-merge API is atomic; the second call rejects with a not-mergeable error if the first's merge created a conflict. No Jared-side serialization is needed.

The back-end flow does not auto-commit. If the working tree is dirty at wrap time, wrap pauses and asks for a commit message — your commit discipline (phase-numbered prefixes, "why not what" bodies) is preserved.
```

- [ ] **Step 4: Run lint check on the markdown (no automated check beyond reading; just confirm structure)**

Run: `cat /home/brockamer/Code/jared/skills/jared/references/parallel-sessions.md | head -100`

Verify the new sections render cleanly (proper heading levels, no broken markdown).

- [ ] **Step 5: Commit**

```bash
cd /home/brockamer/Code/jared
git add skills/jared/references/parallel-sessions.md
git commit -m "doctrine(parallel-sessions): /jared-stage --sessions N + wrap back-end"
```

---

### Task 5.2: File the wrap back-end tracking issue + update #253 scope

**Files:** none.

- [ ] **Step 1: Update #253's scope**

#253 currently says "graduate workstream-1d — propose session-N assignments alongside promotions." Edit its body to reflect the extended v1 scope (propose + maintain via re-run; single-signal file-paths overlap; no cache; no annotate):

```bash
cd /home/brockamer/Code/jared
gh issue edit 253 --body "$(cat <<'EOF'
## Goal

`/jared-stage --sessions N` proposes session-N label assignments across the current candidate set (Up Next + currently-labeled items in any status). Single signal in v1: file paths cited in issue bodies. Operator approves per-item; existing labels honored as manual overrides.

## Acceptance criteria

- `jared propose-partition --sessions N` returns a `Proposal` with `keep`/`add`/`floats` lists
- Existing `session-N` labels are honored (`keep`); v1 never proposes `move`
- Candidates with no file paths in body are surfaced as `floats` (no label proposed)
- `/jared-stage --sessions N` drives the proposal flow and applies approved labels via `gh issue edit ... --add-label session-K`
- Re-running `/jared-stage --sessions N` after the board changes proposes the delta against current state (maintenance, not just initial assignment)

## Out of scope

- Surface cache or `--annotate` issue comment (deferred; profile first)
- Multi-signal weighted scoring (deferred; file-paths-only is the v1 signal)
- Auto-application without operator approval
- Active `/jared-groom` integration to surface stale labels

See `docs/superpowers/specs/2026-05-28-multi-session-back-end-design.md`.
EOF
)"
```

- [ ] **Step 2: File the wrap back-end tracking issue**

```bash
cd /home/brockamer/Code/jared
./skills/jared/scripts/jared file \
  --title "feat(wrap): back-end flow (commit -> push -> PR -> merge -> cleanup)" \
  --label enhancement \
  --priority High \
  --status "Up Next" \
  --no-milestone \
  --body "$(cat <<'EOF'
## Goal

`/jared-wrap` runs the commit → push → PR create → mergeable check → confirm merge → cleanup back-end after Session notes are posted. Auto until merge; operator confirms only the merge.

## Acceptance criteria

- `lib/wrap_state.decide_next_step()` is a pure function mapping `(GitState, PrState)` to a `StepName` literal
- `jared wrap-state` CLI subcommand collects git + PR state and prints the next step name
- `/jared-wrap` runs the back-end loop after Session notes: commit prompt (if dirty) → push → PR create → wait/surface/confirm based on PR state → existing cleanup
- Idempotent: re-running `/jared-wrap` after a failure picks up at the current state with no manual recovery
- Concurrent merge safety: trust GitHub atomicity; re-check mergeable immediately before merge; surface conflicts on rejection

## Out of scope

- Polling wait-for-checks (single check, exit clean, re-run)
- Integration merge smoke test (unit-test the state detector; manual smoke on real PR)
- Hard merge-serialization lock (GitHub atomicity is the safety)

See `docs/superpowers/specs/2026-05-28-multi-session-back-end-design.md`.
EOF
)"
```

Note the issue number.

- [ ] **Step 3: Commit (no file changes; just record the operations in the log)**

No commit needed for board operations. Proceed to PR.

---

### Task 5.3: Open PR 2

**Files:** none new; this packages Phases 2–5 as a PR.

- [ ] **Step 1: Confirm the branch state**

```bash
cd /home/brockamer/Code/jared
git log --oneline main..HEAD
```

Expected: 8–10 commits covering Phases 2–5 (ties refactor, partition module + tests, propose-partition CLI + tests, wrap_state module + tests, wrap-state CLI + tests, slash-command updates, doctrine).

- [ ] **Step 2: Run the full test suite + lint + type-check**

Run:

```bash
cd /home/brockamer/Code/jared
pytest
ruff check .
ruff format --check .
mypy
```

Expected: all pass.

- [ ] **Step 3: Push the branch**

```bash
cd /home/brockamer/Code/jared
git push -u origin feature/multi-session-stage-wrap
```

- [ ] **Step 4: Create the PR**

```bash
cd /home/brockamer/Code/jared
gh pr create --title "feat(multi-session): stage proposal + wrap back-end" --body "$(cat <<'EOF'
## Summary

- **Stage:** `/jared-stage --sessions N` proposes session-N label assignments via single-signal file-paths overlap. Existing labels honored; floats (no signal) surfaced. Closes #253.
- **Wrap:** `/jared-wrap` runs commit (prompt) → push → PR create → mergeable check → confirm merge → cleanup back-end after Session notes. Idempotent re-run via `jared wrap-state`. Closes #<WRAP_ISSUE>.
- **Refactor:** Promote four private symbols in `lib/ties.py` to public (`file_paths_in_body`, `GENERIC_FILES`, `tokenize_title`, `FILE_PATH_RE`) so `lib/partition.py` can reuse them.
- **Doctrine:** `references/parallel-sessions.md` updated for the new flow.

Phases 2–5 of `docs/superpowers/specs/2026-05-28-multi-session-back-end-design.md`. Phase 1 (start-side filter) shipped as PR #<PR_1_NUMBER>.

## Concurrent-merge safety

Trust GitHub's PR-merge API atomicity. `decide_next_step` re-evaluates mergeable just before the merge step. No Jared-side serialization lock.

## Test plan

- [ ] `pytest` — all tests pass (5 new test files: test_partition, test_cmd_propose_partition, test_wrap_state, test_cmd_wrap_state, plus one new test in test_ties_analyzers)
- [ ] `ruff check . && mypy` — pass
- [ ] Manual smoke: run `/jared-stage --sessions 2` against `brockamer/jared`; verify the partition output
- [ ] Manual smoke: run `/jared-wrap` from a feature branch with uncommitted changes; verify the back-end flow walks through commit → push → PR → confirm → merge
- [ ] Manual smoke: re-run `/jared-wrap` after killing it mid-PR-create; verify idempotent pickup

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

Replace `<WRAP_ISSUE>` and `<PR_1_NUMBER>` with the numbers from earlier tasks.

- [ ] **Step 5: Wait for operator review + manual smoke verification + merge**

The operator reviews, runs the manual smokes from the test plan, and merges via `gh pr merge --merge --delete-branch` when satisfied.

After merge, locally:

```bash
cd /home/brockamer/Code/jared
git checkout main
git pull origin main
git worktree list  # check if any worktrees from this work remain
```

Implementation complete.
