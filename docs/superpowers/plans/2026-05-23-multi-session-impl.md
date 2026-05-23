# Multi-Session Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the opt-in worktree-based isolation for parallel Claude sessions on a jared-stewarded repo, with unconditional session-presence locking that makes the B-leg refusal real. Closes #231 (worktree-by-default) + #236 (`/jared-start --session` flag) in one PR.

**Architecture:** Two new Python lib modules — `session_lock.py` (lock file lifecycle, PID-liveness, detection-action resolution) and `worktree.py` (collision-aware `git worktree add` + listing). Slash-command stub edits to `/jared-start` (flag parsing, sibling-detection wiring, refusal rendering, worktree creation call) and `/jared-wrap` (lock-clearing on session end). CLAUDE.md surface update for discoverability. Memory cross-references or new memories. Three test files: unit tests for `session_lock.py`, integration test for `worktree.py` (real `git worktree` in tmpdir), scenario tests for the B-leg resolve flow.

**Tech Stack:** Python 3.11+ (stdlib only — `json`, `os`, `pathlib`, `subprocess`, `dataclasses`, `signal`). pytest with `tmp_path` fixtures. Git CLI for worktree operations. Markdown for slash-command stubs.

**Reference:** Full design at `docs/superpowers/specs/2026-05-23-multi-session-impl-design.md` (decisions D1–D5, behavior shape, detection action table, known limitations).

---

## File Structure

| File | Responsibility |
|---|---|
| `skills/jared/scripts/lib/session_lock.py` (new) | Lock file lifecycle: write/read, PID-liveness, list-active-with-stale-cleanup, clear, `resolve_action` |
| `skills/jared/scripts/lib/worktree.py` (new) | `git worktree add` with collision detection; `list_worktrees` parsing |
| `tests/test_session_lock.py` (new) | Unit tests for `session_lock` — round-trips, stale handling, six-row `resolve_action` table |
| `tests/test_worktree.py` (new) | Integration tests for `worktree.py` — real `git init` + `git worktree add` in tmpdir, isolation assertions |
| `tests/test_session_lock_scenarios.py` (new) | End-to-end scenario tests for the B-leg refusal paths — combines lock state + flags + expected `resolve_action` outcome |
| `commands/jared-start.md` (modify) | Add `--session N` + `--no-worktree` flag handling, sibling-detection step, refusal rendering, worktree creation call |
| `commands/jared-wrap.md` (modify) | Add lock-clearing step at end of flow |
| `.gitignore` (modify) | Add `.jared/` entry |
| `CLAUDE.md` (modify) | Add a §multi-session section describing the flag + lock discipline |
| User memory (verify + file/update) | Confirm whether `feedback_parallel_session_worktree.md` and `feedback_session_label_ownership.md` exist; cross-link if they do, file new if they don't |

---

## Phase 1 — `lib/session_lock.py` + tests + `.gitignore`

### Task 1: Lock dataclass + write/read round-trip

**Files:**
- Create: `skills/jared/scripts/lib/session_lock.py`
- Test: `tests/test_session_lock.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_session_lock.py`:

```python
"""Unit tests for lib/session_lock.py — session-presence locks (#231)."""

from __future__ import annotations

from pathlib import Path

from skills.jared.scripts.lib import session_lock


def test_lock_round_trips_through_disk(tmp_path: Path) -> None:
    lock = session_lock.Lock(
        pid=12847,
        started="2026-05-23T14:22:00Z",
        session=1,
        worktree_path="/home/u/Code/jared-231",
        issue=231,
    )
    path = session_lock.write_lock(repo_root=tmp_path, lock=lock)
    assert path == tmp_path / ".jared" / "session-12847.lock"
    assert path.exists()

    loaded = session_lock.read_lock(path)
    assert loaded == lock


def test_read_lock_returns_none_when_file_absent(tmp_path: Path) -> None:
    path = tmp_path / ".jared" / "session-99999.lock"
    assert session_lock.read_lock(path) is None


def test_read_lock_returns_none_when_json_corrupted(tmp_path: Path) -> None:
    lockdir = tmp_path / ".jared"
    lockdir.mkdir()
    path = lockdir / "session-12847.lock"
    path.write_text("{not json")
    assert session_lock.read_lock(path) is None


def test_write_lock_with_solo_session(tmp_path: Path) -> None:
    lock = session_lock.Lock(
        pid=12847,
        started="2026-05-23T14:22:00Z",
        session=None,
        worktree_path=None,
        issue=231,
    )
    path = session_lock.write_lock(repo_root=tmp_path, lock=lock)
    loaded = session_lock.read_lock(path)
    assert loaded is not None
    assert loaded.session is None
    assert loaded.worktree_path is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_session_lock.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'skills.jared.scripts.lib.session_lock'`

- [ ] **Step 3: Write minimal implementation**

Create `skills/jared/scripts/lib/session_lock.py`:

```python
"""Session-presence locking for parallel jared sessions (#231, #236).

Every active `/jared-start` writes a JSON lock file at `<repo>/.jared/session-<pid>.lock`
recording the session's PID, start time, and (if multi-session) the `--session N` value
plus worktree path. This makes the B-leg refusal real: a later `/jared-start` reads
existing locks, checks PID-liveness, and refuses-with-guidance when a sibling is
detected and the operator hasn't opted into multi-session.

See docs/superpowers/specs/2026-05-23-multi-session-impl-design.md for design.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True)
class Lock:
    """A session-presence record on disk."""

    pid: int
    started: str
    session: int | None
    worktree_path: str | None
    issue: int


def _lock_dir(repo_root: Path) -> Path:
    return repo_root / ".jared"


def _lock_path(repo_root: Path, pid: int) -> Path:
    return _lock_dir(repo_root) / f"session-{pid}.lock"


def write_lock(repo_root: Path, lock: Lock) -> Path:
    """Atomically write a lock file for this session. Returns the path."""
    lockdir = _lock_dir(repo_root)
    lockdir.mkdir(parents=True, exist_ok=True)
    path = _lock_path(repo_root, lock.pid)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(asdict(lock)))
    os.replace(tmp, path)
    return path


def read_lock(path: Path) -> Lock | None:
    """Read and parse a lock file. Returns None if absent or malformed."""
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    try:
        return Lock(
            pid=int(payload["pid"]),
            started=str(payload["started"]),
            session=payload["session"] if payload.get("session") is None else int(payload["session"]),
            worktree_path=payload["worktree_path"] if payload.get("worktree_path") is None else str(payload["worktree_path"]),
            issue=int(payload["issue"]),
        )
    except (KeyError, TypeError, ValueError):
        return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_session_lock.py -v`
Expected: PASS — 4 tests pass.

- [ ] **Step 5: Commit**

```bash
git add skills/jared/scripts/lib/session_lock.py tests/test_session_lock.py
git commit -m "feat(session-lock): Lock dataclass + write/read round-trip (Phase 1.1)

Establishes the on-disk representation for session-presence locks per
the multi-session impl spec D3. Lock files at <repo>/.jared/session-<pid>.lock,
JSON-encoded, atomically written via os.replace. read_lock returns None on
absent or malformed files — never raises.

Refs #231, #236."
```

---

### Task 2: `list_active_locks` with stale cleanup

**Files:**
- Modify: `skills/jared/scripts/lib/session_lock.py`
- Modify: `tests/test_session_lock.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_session_lock.py`:

```python
def test_is_alive_returns_true_for_current_process() -> None:
    assert session_lock.is_alive(os.getpid()) is True


def test_is_alive_returns_false_for_dead_pid(monkeypatch) -> None:
    def fake_kill(pid: int, sig: int) -> None:
        raise ProcessLookupError()
    monkeypatch.setattr(session_lock.os, "kill", fake_kill)
    assert session_lock.is_alive(9999999) is False


def test_is_alive_returns_true_when_permission_denied(monkeypatch) -> None:
    # init (PID 1) typically gives EPERM rather than ESRCH — the process IS alive.
    def fake_kill(pid: int, sig: int) -> None:
        raise PermissionError()
    monkeypatch.setattr(session_lock.os, "kill", fake_kill)
    assert session_lock.is_alive(1) is True


def test_list_active_locks_empty_when_no_lockdir(tmp_path: Path) -> None:
    assert session_lock.list_active_locks(repo_root=tmp_path) == []


def test_list_active_locks_returns_alive_locks(tmp_path: Path) -> None:
    lock = session_lock.Lock(
        pid=os.getpid(),
        started="2026-05-23T14:22:00Z",
        session=1,
        worktree_path=None,
        issue=231,
    )
    session_lock.write_lock(repo_root=tmp_path, lock=lock)
    active = session_lock.list_active_locks(repo_root=tmp_path)
    assert len(active) == 1
    assert active[0] == lock


def test_list_active_locks_clears_stale_locks(tmp_path: Path, capsys) -> None:
    stale = session_lock.Lock(
        pid=9999999,
        started="2026-05-23T10:00:00Z",
        session=None,
        worktree_path=None,
        issue=200,
    )
    session_lock.write_lock(repo_root=tmp_path, lock=stale)
    stale_path = tmp_path / ".jared" / "session-9999999.lock"
    assert stale_path.exists()

    # is_alive(9999999) will almost certainly return False on a normal system,
    # but to make this test deterministic we monkeypatch os.kill below.
    import builtins
    import skills.jared.scripts.lib.session_lock as sl_mod
    original_kill = sl_mod.os.kill
    def fake_kill(pid: int, sig: int) -> None:
        if pid == 9999999:
            raise ProcessLookupError()
        return original_kill(pid, sig)
    sl_mod.os.kill = fake_kill
    try:
        active = session_lock.list_active_locks(repo_root=tmp_path)
    finally:
        sl_mod.os.kill = original_kill

    assert active == []
    assert not stale_path.exists()
    captured = capsys.readouterr()
    assert "stale lock" in captured.err.lower()
    assert "9999999" in captured.err


def test_list_active_locks_skips_malformed_files(tmp_path: Path) -> None:
    lockdir = tmp_path / ".jared"
    lockdir.mkdir()
    (lockdir / "session-12847.lock").write_text("{not json")
    assert session_lock.list_active_locks(repo_root=tmp_path) == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_session_lock.py -v`
Expected: FAIL — `AttributeError: module 'skills.jared.scripts.lib.session_lock' has no attribute 'is_alive'` (and similar for `list_active_locks`).

- [ ] **Step 3: Write the implementation**

Append to `skills/jared/scripts/lib/session_lock.py`:

```python
import sys


def is_alive(pid: int) -> bool:
    """Check whether a process with this PID exists.

    Uses `os.kill(pid, 0)`: ProcessLookupError (ESRCH) means dead;
    PermissionError (EPERM) means alive but not signalable (e.g., init).
    """
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def list_active_locks(repo_root: Path) -> list[Lock]:
    """Enumerate all live session locks for this repo. Clears stale entries.

    Walks `<repo>/.jared/session-*.lock`, reads each, drops any with a dead
    PID (deleting the stale file and emitting a one-line stderr warning).
    Malformed lock files are silently skipped — they may be partial writes
    from a crashed write that didn't reach os.replace.
    """
    lockdir = _lock_dir(repo_root)
    if not lockdir.exists():
        return []
    active: list[Lock] = []
    for path in sorted(lockdir.glob("session-*.lock")):
        lock = read_lock(path)
        if lock is None:
            continue
        if is_alive(lock.pid):
            active.append(lock)
        else:
            try:
                path.unlink()
            except OSError:
                pass
            print(
                f"warning: cleared stale lock for PID {lock.pid} "
                f"(no longer running): {path}",
                file=sys.stderr,
            )
    return active
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_session_lock.py -v`
Expected: PASS — all 11 tests (4 from Task 1 + 7 new).

- [ ] **Step 5: Commit**

```bash
git add skills/jared/scripts/lib/session_lock.py tests/test_session_lock.py
git commit -m "feat(session-lock): is_alive + list_active_locks with stale cleanup (Phase 1.2)

list_active_locks enumerates all lock files in the repo's .jared/ dir, runs
PID-liveness checks via os.kill(pid, 0), and clears stale entries with an
audible stderr warning. Malformed files are silently skipped (partial-write
recovery).

Refs #231."
```

---

### Task 3: `clear_lock` for wrap

**Files:**
- Modify: `skills/jared/scripts/lib/session_lock.py`
- Modify: `tests/test_session_lock.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_session_lock.py`:

```python
def test_clear_lock_removes_matching_file(tmp_path: Path) -> None:
    lock = session_lock.Lock(
        pid=12847,
        started="2026-05-23T14:22:00Z",
        session=1,
        worktree_path=None,
        issue=231,
    )
    path = session_lock.write_lock(repo_root=tmp_path, lock=lock)
    assert path.exists()
    session_lock.clear_lock(repo_root=tmp_path, pid=12847)
    assert not path.exists()


def test_clear_lock_is_noop_when_file_absent(tmp_path: Path) -> None:
    # no lockdir, no file — should not raise
    session_lock.clear_lock(repo_root=tmp_path, pid=12847)


def test_clear_lock_leaves_other_sessions_alone(tmp_path: Path) -> None:
    own = session_lock.Lock(pid=12847, started="2026-05-23T14:00:00Z", session=1, worktree_path=None, issue=231)
    sibling = session_lock.Lock(pid=13201, started="2026-05-23T14:30:00Z", session=2, worktree_path=None, issue=235)
    session_lock.write_lock(repo_root=tmp_path, lock=own)
    session_lock.write_lock(repo_root=tmp_path, lock=sibling)

    session_lock.clear_lock(repo_root=tmp_path, pid=12847)

    own_path = tmp_path / ".jared" / "session-12847.lock"
    sibling_path = tmp_path / ".jared" / "session-13201.lock"
    assert not own_path.exists()
    assert sibling_path.exists()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_session_lock.py -v`
Expected: FAIL — `AttributeError: module 'skills.jared.scripts.lib.session_lock' has no attribute 'clear_lock'`.

- [ ] **Step 3: Write the implementation**

Append to `skills/jared/scripts/lib/session_lock.py`:

```python
import contextlib


def clear_lock(repo_root: Path, pid: int) -> None:
    """Remove the lock file for this PID. No-op if absent."""
    path = _lock_path(repo_root, pid)
    with contextlib.suppress(FileNotFoundError):
        path.unlink()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_session_lock.py -v`
Expected: PASS — all 14 tests.

- [ ] **Step 5: Commit**

```bash
git add skills/jared/scripts/lib/session_lock.py tests/test_session_lock.py
git commit -m "feat(session-lock): clear_lock for /jared-wrap (Phase 1.3)

clear_lock(repo_root, pid) removes the matching session-<pid>.lock file
and is a no-op when the file is absent. Surgical — leaves sibling sessions'
locks untouched.

Refs #231."
```

---

### Task 4: `resolve_action` — the detection action table

**Files:**
- Modify: `skills/jared/scripts/lib/session_lock.py`
- Create: `tests/test_session_lock_scenarios.py`

- [ ] **Step 1: Write the failing scenario tests**

Create `tests/test_session_lock_scenarios.py`:

```python
"""Scenario tests for session_lock.resolve_action — the six-row detection action table.

Maps directly to docs/superpowers/specs/2026-05-23-multi-session-impl-design.md § D3.
"""

from __future__ import annotations

from skills.jared.scripts.lib import session_lock
from skills.jared.scripts.lib.session_lock import Action, Flags, Lock


def _solo_sibling() -> Lock:
    return Lock(pid=12847, started="2026-05-23T14:00:00Z", session=None, worktree_path=None, issue=200)


def _multi_sibling(n: int) -> Lock:
    return Lock(
        pid=12847 + n,
        started="2026-05-23T14:00:00Z",
        session=n,
        worktree_path=f"/home/u/Code/jared-{200 + n}",
        issue=200 + n,
    )


def test_no_siblings_solo_flags_proceeds_solo() -> None:
    action = session_lock.resolve_action(siblings=[], flags=Flags(session=None, no_worktree=False))
    assert action == Action.PROCEED_SOLO


def test_no_siblings_multi_flag_proceeds_multi() -> None:
    action = session_lock.resolve_action(siblings=[], flags=Flags(session=1, no_worktree=False))
    assert action == Action.PROCEED_MULTI


def test_conflicting_flags_refused() -> None:
    action = session_lock.resolve_action(
        siblings=[],
        flags=Flags(session=1, no_worktree=True),
    )
    assert action == Action.REFUSE_CONFLICTING_FLAGS


def test_solo_flags_with_any_sibling_refused() -> None:
    action = session_lock.resolve_action(siblings=[_solo_sibling()], flags=Flags(session=None, no_worktree=False))
    assert action == Action.REFUSE_BLEG
    action = session_lock.resolve_action(siblings=[_multi_sibling(2)], flags=Flags(session=None, no_worktree=False))
    assert action == Action.REFUSE_BLEG


def test_multi_flag_with_solo_sibling_refused() -> None:
    # Solo sibling on shared HEAD is exactly the trap shape — must be refused.
    action = session_lock.resolve_action(
        siblings=[_solo_sibling()],
        flags=Flags(session=2, no_worktree=False),
    )
    assert action == Action.REFUSE_BLEG


def test_multi_flag_with_different_n_sibling_proceeds() -> None:
    action = session_lock.resolve_action(
        siblings=[_multi_sibling(1)],
        flags=Flags(session=2, no_worktree=False),
    )
    assert action == Action.PROCEED_MULTI


def test_multi_flag_with_same_n_sibling_refused() -> None:
    action = session_lock.resolve_action(
        siblings=[_multi_sibling(1)],
        flags=Flags(session=1, no_worktree=False),
    )
    assert action == Action.REFUSE_DUP_SESSION_N


def test_no_worktree_ack_with_any_sibling_proceeds() -> None:
    # Operator explicitly accepted the trap risk.
    action = session_lock.resolve_action(
        siblings=[_solo_sibling()],
        flags=Flags(session=None, no_worktree=True),
    )
    assert action == Action.PROCEED_ACK_RISK
    action = session_lock.resolve_action(
        siblings=[_multi_sibling(2)],
        flags=Flags(session=None, no_worktree=True),
    )
    assert action == Action.PROCEED_ACK_RISK
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_session_lock_scenarios.py -v`
Expected: FAIL — `ImportError: cannot import name 'Action' from 'skills.jared.scripts.lib.session_lock'`.

- [ ] **Step 3: Write the implementation**

Append to `skills/jared/scripts/lib/session_lock.py`:

```python
import enum


class Action(enum.Enum):
    """Resolution outcome for a `/jared-start` invocation."""

    PROCEED_SOLO = "proceed_solo"
    PROCEED_MULTI = "proceed_multi"
    PROCEED_ACK_RISK = "proceed_ack_risk"
    REFUSE_BLEG = "refuse_bleg"
    REFUSE_DUP_SESSION_N = "refuse_dup_session_n"
    REFUSE_CONFLICTING_FLAGS = "refuse_conflicting_flags"


@dataclass(frozen=True)
class Flags:
    """Operator-supplied flags to `/jared-start`."""

    session: int | None
    no_worktree: bool


def resolve_action(siblings: list[Lock], flags: Flags) -> Action:
    """Decide what `/jared-start` should do given current sibling locks and flags.

    Maps to the six-row action table in
    docs/superpowers/specs/2026-05-23-multi-session-impl-design.md § D3.
    Pure function — no I/O, no side effects.
    """
    # --session and --no-worktree are mutually exclusive: one says "isolate me",
    # the other says "I'm accepting the shared-HEAD risk".
    if flags.session is not None and flags.no_worktree:
        return Action.REFUSE_CONFLICTING_FLAGS

    if not siblings:
        if flags.session is not None:
            return Action.PROCEED_MULTI
        return Action.PROCEED_SOLO

    # At least one live sibling.
    if flags.no_worktree:
        # Operator acknowledged the trap explicitly.
        return Action.PROCEED_ACK_RISK

    if flags.session is None:
        # Sibling exists, no flag → refuse with guidance.
        return Action.REFUSE_BLEG

    # flags.session is not None — multi-session opt-in.
    for sib in siblings:
        if sib.session is None:
            # Solo sibling on shared HEAD: this session would be safe in its
            # worktree, but the solo sibling is still on shared HEAD and can
            # still hit the trap. Refuse so the operator handles the sibling first.
            return Action.REFUSE_BLEG
        if sib.session == flags.session:
            return Action.REFUSE_DUP_SESSION_N

    return Action.PROCEED_MULTI
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_session_lock.py tests/test_session_lock_scenarios.py -v`
Expected: PASS — all 14 + 8 = 22 tests.

- [ ] **Step 5: Commit**

```bash
git add skills/jared/scripts/lib/session_lock.py tests/test_session_lock_scenarios.py
git commit -m "feat(session-lock): resolve_action — six-row detection table (Phase 1.4)

Pure function takes (siblings, flags) → Action enum. Maps directly to
the action table in the impl spec § D3. Eight scenario tests cover all
six rows including the dual-flag refusal and the solo-sibling-on-shared-HEAD
edge case.

The choice to refuse REFUSE_BLEG when a multi-flag session detects a SOLO
sibling (rather than proceeding-with-warning) is load-bearing: the new
session's worktree isolates IT, but the solo sibling is still on the shared
HEAD and can still hit the trap. Operator must address the sibling first.

Refs #231, #236."
```

---

### Task 5: Type-check and ruff pass on Phase 1

**Files:**
- (no new files — verify Phase 1 modules pass project tooling)

- [ ] **Step 1: Run ruff**

Run: `ruff check skills/jared/scripts/lib/session_lock.py tests/test_session_lock.py tests/test_session_lock_scenarios.py`
Expected: PASS — no issues.

If issues surface (likely: unused imports, line length): fix inline and re-run.

- [ ] **Step 2: Run ruff format check**

Run: `ruff format --check skills/jared/scripts/lib/session_lock.py tests/test_session_lock.py tests/test_session_lock_scenarios.py`
Expected: PASS, or "would reformat N files" — if so, run `ruff format <files>` and re-check.

- [ ] **Step 3: Run mypy**

Run: `mypy skills/jared/scripts/lib/session_lock.py`
Expected: PASS — `Success: no issues found`.

If mypy complains (likely: missing type annotations on test helpers), fix inline.

- [ ] **Step 4: Commit any tooling fixes**

If steps 1–3 required edits:

```bash
git add skills/jared/scripts/lib/session_lock.py tests/test_session_lock.py tests/test_session_lock_scenarios.py
git commit -m "chore(session-lock): ruff + mypy pass on Phase 1 (Phase 1.5)"
```

If no edits were needed, skip this commit.

---

### Task 6: `.gitignore` entry for `.jared/`

**Files:**
- Modify: `.gitignore`

- [ ] **Step 1: Read current `.gitignore`**

Run: `cat .gitignore`

- [ ] **Step 2: Add `.jared/` if not present**

If `.gitignore` does not already contain `.jared/`, append it (preserving existing ordering — append to the bottom under a comment, or in a logical spot like alongside other dev-state directories).

Example addition:

```
# Session-presence locks for parallel jared sessions (#231)
.jared/
```

- [ ] **Step 3: Verify**

Run: `git check-ignore -v .jared/session-12345.lock`
Expected: Output shows the file is ignored by `.gitignore:<line>:.jared/`.

(You may need to `mkdir -p .jared && touch .jared/session-12345.lock` first to give `check-ignore` something to check, then clean up — or just trust the rule and rely on the test in Phase 2.)

- [ ] **Step 4: Commit**

```bash
git add .gitignore
git commit -m "chore(gitignore): ignore .jared/ session-lock dir (Phase 1.6)

The .jared/ directory holds session-presence lock files for parallel
jared sessions (#231). These are per-machine ephemeral state and must
never be committed.

Refs #231."
```

---

## Phase 2 — `lib/worktree.py` + integration tests

### Task 7: `create_worktree` happy path + isolation integration test

**Files:**
- Create: `skills/jared/scripts/lib/worktree.py`
- Create: `tests/test_worktree.py`

- [ ] **Step 1: Write the failing integration test**

Create `tests/test_worktree.py`:

```python
"""Integration tests for lib/worktree.py — real `git worktree` in tmpdir (#231).

These tests prove the structural isolation between main checkout and worktree
is real: independent HEAD refs, independent branch switches, independent commits.

This is the test that maps to issue #231's acceptance criterion
"trap can no longer fire" — it's not enough to verify the detection logic
correctness; we have to verify the git operation itself produces isolation.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from skills.jared.scripts.lib import worktree


def _git(repo: Path, *args: str) -> str:
    """Run a git command in `repo` and return stdout (stripped)."""
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


@pytest.fixture
def main_repo(tmp_path: Path) -> Path:
    """Create a fresh git repo with one commit on `main`."""
    repo = tmp_path / "main-repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "test")
    (repo / "README.md").write_text("initial\n")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-m", "initial")
    return repo


def test_create_worktree_at_sibling_path(main_repo: Path, tmp_path: Path) -> None:
    target = tmp_path / "main-repo-231"
    branch = "feature/231-test"
    result = worktree.create_worktree(repo=main_repo, target=target, branch=branch, base="main")
    assert result == target
    assert target.exists()
    assert (target / "README.md").exists()
    # The worktree's HEAD should be on the new branch.
    head = _git(target, "rev-parse", "--abbrev-ref", "HEAD")
    assert head == branch


def test_worktree_has_independent_head(main_repo: Path, tmp_path: Path) -> None:
    """The acceptance-criterion test: branch switches in main do not propagate to the worktree."""
    target = tmp_path / "main-repo-231"
    worktree.create_worktree(repo=main_repo, target=target, branch="feature/231-test", base="main")

    # Sanity: both checkouts point at independent ref locations.
    main_git_dir = _git(main_repo, "rev-parse", "--absolute-git-dir")
    worktree_git_dir = _git(target, "rev-parse", "--absolute-git-dir")
    assert main_git_dir != worktree_git_dir

    # Create a second branch in the main checkout. The worktree's HEAD should not move.
    _git(main_repo, "checkout", "-b", "feature/other")
    main_head = _git(main_repo, "rev-parse", "--abbrev-ref", "HEAD")
    worktree_head = _git(target, "rev-parse", "--abbrev-ref", "HEAD")
    assert main_head == "feature/other"
    assert worktree_head == "feature/231-test"


def test_commit_in_worktree_lands_on_worktree_branch(main_repo: Path, tmp_path: Path) -> None:
    target = tmp_path / "main-repo-231"
    worktree.create_worktree(repo=main_repo, target=target, branch="feature/231-test", base="main")

    (target / "worktree-only.txt").write_text("from worktree\n")
    _git(target, "add", "worktree-only.txt")
    _git(target, "commit", "-m", "from worktree")

    # The worktree-only commit must NOT be visible on main.
    main_log = _git(main_repo, "log", "main", "--oneline")
    assert "from worktree" not in main_log

    # But IS visible on the worktree's branch (via the shared object database).
    worktree_log = _git(main_repo, "log", "feature/231-test", "--oneline")
    assert "from worktree" in worktree_log
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_worktree.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'skills.jared.scripts.lib.worktree'`.

- [ ] **Step 3: Write the implementation**

Create `skills/jared/scripts/lib/worktree.py`:

```python
"""git-worktree wrapper for jared (#231).

Creates issue-bound worktrees for parallel Claude sessions per the multi-session
impl spec D1 (path shape) and D5 (collision UX). All functions take an explicit
`repo: Path` argument so they're testable against a tmpdir-scoped git repo
rather than the live working tree.

See docs/superpowers/specs/2026-05-23-multi-session-impl-design.md.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path


class WorktreeError(Exception):
    """Raised when git worktree operations fail in an actionable way."""


def create_worktree(repo: Path, target: Path, branch: str, base: str = "main") -> Path:
    """Create a new worktree at `target` checked out on a fresh `branch`.

    Equivalent to `git -C <repo> worktree add <target> -b <branch> <base>`.
    Returns the target path on success; raises WorktreeError on failure.
    """
    cmd = ["git", "-C", str(repo), "worktree", "add", str(target), "-b", branch, base]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise WorktreeError(
            f"git worktree add failed:\n"
            f"  command: {' '.join(cmd)}\n"
            f"  stderr: {result.stderr.strip()}"
        )
    return target
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_worktree.py -v`
Expected: PASS — 3 tests pass.

- [ ] **Step 5: Commit**

```bash
git add skills/jared/scripts/lib/worktree.py tests/test_worktree.py
git commit -m "feat(worktree): create_worktree + isolation integration test (Phase 2.1)

Wraps git worktree add with a typed Python interface. Three integration tests
prove the structural isolation: independent HEAD refs, branch switches in the
main checkout don't propagate, and commits in the worktree land on the
worktree's branch rather than main.

This is the test layer that maps to issue #231's acceptance criterion
\"trap can no longer fire\" — verifying the git operation itself produces
isolation, not just that the detection logic resolves correctly.

Refs #231."
```

---

### Task 8: `list_worktrees` + collision-aware behavior

**Files:**
- Modify: `skills/jared/scripts/lib/worktree.py`
- Modify: `tests/test_worktree.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_worktree.py`:

```python
def test_list_worktrees_includes_main(main_repo: Path) -> None:
    entries = worktree.list_worktrees(repo=main_repo)
    paths = [e.path for e in entries]
    assert main_repo in paths


def test_list_worktrees_includes_added_worktrees(main_repo: Path, tmp_path: Path) -> None:
    target = tmp_path / "main-repo-231"
    worktree.create_worktree(repo=main_repo, target=target, branch="feature/231-test", base="main")
    entries = worktree.list_worktrees(repo=main_repo)
    paths = [e.path for e in entries]
    assert target in paths
    assert main_repo in paths


def test_create_worktree_at_existing_registered_path_returns_existing(
    main_repo: Path, tmp_path: Path
) -> None:
    """Common shape: laptop crashed, ~/Code/jared-231/ still exists and is registered.
    create_worktree returns the existing path rather than failing."""
    target = tmp_path / "main-repo-231"
    worktree.create_worktree(repo=main_repo, target=target, branch="feature/231-test", base="main")

    # Second call — same target, expect to resume.
    result = worktree.create_worktree(
        repo=main_repo,
        target=target,
        branch="feature/231-test",
        base="main",
    )
    assert result == target


def test_create_worktree_at_orphan_path_raises(main_repo: Path, tmp_path: Path) -> None:
    """Path exists but is NOT a registered worktree — error with remediation."""
    target = tmp_path / "main-repo-231"
    target.mkdir()
    (target / "stray.txt").write_text("not a worktree\n")
    with pytest.raises(worktree.WorktreeError) as exc_info:
        worktree.create_worktree(repo=main_repo, target=target, branch="feature/231-test", base="main")
    msg = str(exc_info.value)
    assert "not a registered worktree" in msg.lower() or "exists" in msg.lower()
    assert str(target) in msg
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_worktree.py -v`
Expected: FAIL — `AttributeError: module 'skills.jared.scripts.lib.worktree' has no attribute 'list_worktrees'`.

- [ ] **Step 3: Write the implementation**

Modify `skills/jared/scripts/lib/worktree.py`:

```python
@dataclass(frozen=True)
class WorktreeEntry:
    """One worktree as reported by `git worktree list --porcelain`."""

    path: Path
    branch: str | None
    head: str | None


def list_worktrees(repo: Path) -> list[WorktreeEntry]:
    """Parse `git worktree list --porcelain` into structured entries."""
    cmd = ["git", "-C", str(repo), "worktree", "list", "--porcelain"]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise WorktreeError(f"git worktree list failed: {result.stderr.strip()}")

    entries: list[WorktreeEntry] = []
    current: dict[str, str] = {}
    for line in result.stdout.splitlines():
        if not line:
            if current.get("worktree"):
                entries.append(
                    WorktreeEntry(
                        path=Path(current["worktree"]).resolve(),
                        branch=current.get("branch"),
                        head=current.get("HEAD"),
                    )
                )
            current = {}
            continue
        if line.startswith("worktree "):
            current["worktree"] = line[len("worktree "):]
        elif line.startswith("HEAD "):
            current["HEAD"] = line[len("HEAD "):]
        elif line.startswith("branch "):
            current["branch"] = line[len("branch "):]
    if current.get("worktree"):
        entries.append(
            WorktreeEntry(
                path=Path(current["worktree"]).resolve(),
                branch=current.get("branch"),
                head=current.get("HEAD"),
            )
        )
    return entries
```

Modify `create_worktree` to handle the collision cases:

```python
def create_worktree(repo: Path, target: Path, branch: str, base: str = "main") -> Path:
    """Create a new worktree at `target` checked out on a fresh `branch`.

    Handles collisions per spec D5:
    - Path is already a registered worktree → return target (resuming).
    - Path exists but is NOT a registered worktree → raise with remediation.
    - Path does not exist → `git worktree add`.
    """
    target_resolved = target.resolve() if target.exists() else target

    if target.exists():
        registered = {e.path for e in list_worktrees(repo)}
        if target_resolved in registered:
            return target
        raise WorktreeError(
            f"path exists but is not a registered worktree: {target}\n"
            f"  remediation: remove the directory (`rm -rf {target}`) and re-run, "
            f"or run `git -C {repo} worktree remove {target}` if it was once registered."
        )

    cmd = ["git", "-C", str(repo), "worktree", "add", str(target), "-b", branch, base]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise WorktreeError(
            f"git worktree add failed:\n"
            f"  command: {' '.join(cmd)}\n"
            f"  stderr: {result.stderr.strip()}"
        )
    return target
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_worktree.py -v`
Expected: PASS — all 7 tests.

- [ ] **Step 5: Commit**

```bash
git add skills/jared/scripts/lib/worktree.py tests/test_worktree.py
git commit -m "feat(worktree): list_worktrees + collision-aware create (Phase 2.2)

create_worktree now handles the laptop-crashed-yesterday case gracefully:
- Path is a registered worktree → return target (resume the session)
- Path exists but unregistered → raise with remediation instructions
- Path missing → git worktree add as before

list_worktrees parses `git worktree list --porcelain` into a typed
WorktreeEntry list, used by create_worktree's collision check.

Maps to spec D5.

Refs #231."
```

---

### Task 9: Ruff + mypy pass on Phase 2

**Files:**
- (verify only — fix inline)

- [ ] **Step 1: Run tooling**

Run in parallel:
- `ruff check skills/jared/scripts/lib/worktree.py tests/test_worktree.py`
- `ruff format --check skills/jared/scripts/lib/worktree.py tests/test_worktree.py`
- `mypy skills/jared/scripts/lib/worktree.py`

- [ ] **Step 2: Fix any issues inline**

Likely surfaces: line length on the WorktreeError message, missing type annotations on the `_git` test helper if mypy is strict on tests.

- [ ] **Step 3: Run full test suite to confirm no regression in other modules**

Run: `pytest`
Expected: PASS — all tests, including pre-existing.

- [ ] **Step 4: Commit any fixes**

```bash
git add skills/jared/scripts/lib/worktree.py tests/test_worktree.py
git commit -m "chore(worktree): ruff + mypy pass on Phase 2 (Phase 2.3)"
```

Skip if no fixes were needed.

---

## Phase 3 — Slash-command stub edits + docs + PR

### Task 10: `/jared-start` stub — flag parsing + sibling detection + worktree creation

**Files:**
- Modify: `commands/jared-start.md`

This task is markdown editing — the stub IS the specification Claude reads at runtime. No unit test; verification is "the stub reads coherently and prescribes the behavior the spec requires."

The current stub has a numbered flow (steps 1–9). The new behavior inserts between step 1 (posture) and step 2 (WIP check). Specifically:

- After step 1, add a new step 1b (or renumber) for **session-presence resolution**:
  - Parse `--session N` and `--no-worktree` flags from arguments
  - Compute lock-dir via `git rev-parse --git-common-dir` (handles worktrees correctly)
  - Call `lib.session_lock.list_active_locks` + `resolve_action`
  - On REFUSE_BLEG / REFUSE_DUP_SESSION_N / REFUSE_CONFLICTING_FLAGS: render the error and STOP
  - On PROCEED_MULTI: call `lib.worktree.create_worktree` and `cd` into it
  - In all PROCEED cases: write the lock file
- The existing "Wait for confirmation" step (step 9) is unchanged in shape; the user now also implicitly approves the worktree+lock state.

- [ ] **Step 1: Read the current stub**

Run: `cat commands/jared-start.md`

Verify it matches the version captured in this plan — `## Flow:` followed by numbered steps 1–9.

- [ ] **Step 2: Insert the session-presence step**

The cleanest insertion point is between the current step 1 (posture) and step 2 (WIP check), as a new step **1b** (rather than renumbering, which would churn every downstream reference).

Edit `commands/jared-start.md` — after the existing step 1 block ends and before step 2 begins. Insert:

````markdown
1b. **Session-presence resolution.** Before mutating the board, decide whether this is a solo session, a multi-session opt-in, or a B-leg refusal.

   Parse arguments for two new flags (in addition to the issue reference):
   - `--session N` — operator's claim of which parallel session this is (1, 2, ...). Triggers worktree creation.
   - `--no-worktree` — explicit acknowledgment of shared-`.git/HEAD` risk. Mutually exclusive with `--session N`.

   Resolve the repo's lock directory:

   ```bash
   GIT_COMMON_DIR=$(git rev-parse --git-common-dir 2>/dev/null)
   REPO_ROOT=$(dirname "$GIT_COMMON_DIR")  # handles both main checkout and worktrees
   ```

   Walk the active locks and decide the action via the Python lib:

   ```bash
   ${CLAUDE_PLUGIN_ROOT}/skills/jared/scripts/jared session-resolve \
     --repo-root "$REPO_ROOT" \
     ${SESSION_FLAG:+--session $SESSION_FLAG} \
     ${NO_WORKTREE_FLAG:+--no-worktree}
   ```

   (The `jared session-resolve` subcommand wraps `lib.session_lock.list_active_locks` + `resolve_action` and prints a single line: `PROCEED_SOLO`, `PROCEED_MULTI`, `PROCEED_ACK_RISK`, or one of the REFUSE_* outcomes plus the rendered error message.)

   **On REFUSE_BLEG, REFUSE_DUP_SESSION_N, REFUSE_CONFLICTING_FLAGS:** print the CLI's error message verbatim and STOP. Do NOT proceed to the WIP check or move the issue. The board is unchanged.

   **On PROCEED_MULTI:** create the worktree before continuing:

   ```bash
   ${CLAUDE_PLUGIN_ROOT}/skills/jared/scripts/jared worktree-add \
     --repo-root "$REPO_ROOT" \
     --issue <N> \
     --session "$SESSION_FLAG"
   ```

   This calls `lib.worktree.create_worktree` to make `~/Code/<repo>-<N>/` (path shape per spec D1), checks out a fresh `feature/<N>-<slug>` branch from `origin/main`, and emits the target path on stdout. CWD shifts to the worktree for the remainder of the session.

   **In all PROCEED cases:** write the session lock:

   ```bash
   ${CLAUDE_PLUGIN_ROOT}/skills/jared/scripts/jared session-lock-write \
     --repo-root "$REPO_ROOT" \
     --issue <N> \
     ${SESSION_FLAG:+--session $SESSION_FLAG} \
     ${WORKTREE_PATH:+--worktree-path $WORKTREE_PATH}
   ```

   Solo sessions (`--session` absent) still write a lock with `session=null, worktree_path=null`. This is load-bearing: it lets a later sibling session detect the solo one and refuse with guidance, rather than silently sharing `.git/HEAD`.
````

- [ ] **Step 3: Verify the stub still reads coherently**

Re-read the full `commands/jared-start.md` from top to bottom. Check:
- The new step 1b reads as a natural insertion between steps 1 and 2.
- The flag-parsing language matches the impl spec's behavior shape examples.
- No broken cross-references (step numbers still match the spec text).

- [ ] **Step 4: No tests for this step alone (the stub is doctrine)**

The integration tests for the underlying lib modules (`session_lock`, `worktree`) cover the behavior. The stub is what Claude reads at runtime; its correctness is reviewed in step 3.

- [ ] **Step 5: Commit**

```bash
git add commands/jared-start.md
git commit -m "feat(jared-start): wire --session, --no-worktree, and session-lock flow (Phase 3.1)

Adds a new step 1b to the /jared-start flow:
- Parse --session N and --no-worktree flags
- Resolve repo root via git rev-parse --git-common-dir (handles worktrees)
- Call jared session-resolve to walk active locks + decide action
- On REFUSE_*: print error, STOP (board unchanged)
- On PROCEED_MULTI: create worktree at ~/Code/<repo>-<N>/, shift CWD
- In all PROCEED cases: write the session lock

Solo sessions write a lock too (with session=null) so a later sibling can
detect them — the load-bearing fix that makes B-leg refusal real.

Refs #231, #236."
```

---

### Task 11: New CLI subcommands — `session-resolve`, `worktree-add`, `session-lock-write`, `session-lock-clear`

**Files:**
- Modify: `skills/jared/scripts/jared` (the unified CLI entry point)
- Modify: `tests/test_cli.py` (to assert the new subcommands route correctly)

The stub edit in Task 10 calls four new `jared` subcommands. They wrap the lib functions for shell-callable use.

- [ ] **Step 1: Inspect the existing CLI structure**

Run: `head -40 skills/jared/scripts/jared` and `grep -n "_cmd_" skills/jared/scripts/jared | head -20`

This tells you the argparse pattern (subparsers, one `_cmd_<name>` function per subcommand). Note the existing subcommand handlers to match style (likely: each takes parsed argparse args, calls into lib, prints output, returns exit code).

- [ ] **Step 2: Write failing tests in `tests/test_cli.py`**

Append to `tests/test_cli.py`:

```python
def test_session_resolve_proceeds_solo_when_no_siblings(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    cli = conftest.import_cli()
    result = cli.main(["session-resolve", "--repo-root", str(tmp_path)])
    assert result == 0
    captured = capsys.readouterr()
    assert "PROCEED_SOLO" in captured.out


def test_session_resolve_proceeds_multi_with_flag(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    cli = conftest.import_cli()
    result = cli.main(["session-resolve", "--repo-root", str(tmp_path), "--session", "1"])
    assert result == 0
    captured = capsys.readouterr()
    assert "PROCEED_MULTI" in captured.out


def test_session_resolve_refuses_when_sibling_present(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from skills.jared.scripts.lib import session_lock
    # Write a sibling lock with the current PID (alive).
    session_lock.write_lock(
        repo_root=tmp_path,
        lock=session_lock.Lock(
            pid=os.getpid(),
            started="2026-05-23T14:00:00Z",
            session=1,
            worktree_path="/fake",
            issue=200,
        ),
    )
    cli = conftest.import_cli()
    result = cli.main(["session-resolve", "--repo-root", str(tmp_path)])
    assert result == 1
    captured = capsys.readouterr()
    assert "REFUSE_BLEG" in captured.out or "REFUSE_BLEG" in captured.err


def test_session_lock_write_creates_file(tmp_path: Path) -> None:
    cli = conftest.import_cli()
    result = cli.main([
        "session-lock-write",
        "--repo-root", str(tmp_path),
        "--issue", "231",
        "--session", "1",
        "--worktree-path", "/home/u/Code/jared-231",
    ])
    assert result == 0
    pid = os.getpid()
    lock_path = tmp_path / ".jared" / f"session-{pid}.lock"
    assert lock_path.exists()


def test_session_lock_clear_removes_file(tmp_path: Path) -> None:
    from skills.jared.scripts.lib import session_lock
    session_lock.write_lock(
        repo_root=tmp_path,
        lock=session_lock.Lock(
            pid=os.getpid(),
            started="2026-05-23T14:00:00Z",
            session=None,
            worktree_path=None,
            issue=231,
        ),
    )
    cli = conftest.import_cli()
    result = cli.main(["session-lock-clear", "--repo-root", str(tmp_path)])
    assert result == 0
    lock_path = tmp_path / ".jared" / f"session-{os.getpid()}.lock"
    assert not lock_path.exists()
```

(Adapt `import os` and `import conftest` references to match `test_cli.py`'s existing imports.)

Add a `test_worktree_add_in_tmpdir` test similar in shape to `test_create_worktree_at_sibling_path` from Phase 2, but invoking the CLI subcommand. Use the `main_repo` fixture pattern from `test_worktree.py`.

- [ ] **Step 3: Run tests to verify they fail**

Run: `pytest tests/test_cli.py -v -k "session_resolve or session_lock or worktree_add"`
Expected: FAIL — `argparse error: invalid choice 'session-resolve'`.

- [ ] **Step 4: Implement the four subcommands**

In `skills/jared/scripts/jared`, add four new `_cmd_*` functions and register them with the argparse subparsers. Each is thin glue over the lib.

```python
def _cmd_session_resolve(args: argparse.Namespace) -> int:
    """Walk active locks, resolve the action for the supplied flags, print result."""
    from lib import session_lock as sl  # CLI-side import path

    repo_root = Path(args.repo_root)
    siblings = sl.list_active_locks(repo_root)
    flags = sl.Flags(session=args.session, no_worktree=args.no_worktree)
    action = sl.resolve_action(siblings=siblings, flags=flags)
    print(action.name)
    if action.name.startswith("REFUSE_"):
        # Render the refusal message tied to the action.
        _render_refusal_message(action, siblings, flags)
        return 1
    return 0


def _render_refusal_message(action, siblings, flags) -> None:
    """Print a human-readable refusal to stderr."""
    import sys
    from lib import session_lock as sl  # noqa
    if action == sl.Action.REFUSE_CONFLICTING_FLAGS:
        print(
            "ERROR: --session and --no-worktree are mutually exclusive.\n"
            "  --session N tells this session it should isolate via worktree.\n"
            "  --no-worktree explicitly acknowledges shared-HEAD risk.\n"
            "  Pick one or neither, not both.",
            file=sys.stderr,
        )
        return
    if action == sl.Action.REFUSE_DUP_SESSION_N:
        print(
            f"ERROR: another active jared session is already using --session {flags.session}.\n"
            f"  session-N values must be unique per repo. Pick a different N.",
            file=sys.stderr,
        )
        return
    if action == sl.Action.REFUSE_BLEG:
        # Build a sibling summary.
        sib = siblings[0]
        mode = f"session-{sib.session}" if sib.session is not None else "solo (on shared .git/HEAD)"
        print(
            f"ERROR: another active jared session detected.\n"
            f"  Sibling: PID {sib.pid}, started {sib.started}, issue #{sib.issue}\n"
            f"  Sibling mode: {mode}\n"
            f"\n"
            f"Choose one:\n"
            f"  - Wrap the sibling session first, then start fresh with --session N\n"
            f"  - /jared-start <N> --session <unique N>  (creates a worktree for THIS session)\n"
            f"  - /jared-start <N> --no-worktree  (acknowledge risk, share .git/HEAD)\n",
            file=sys.stderr,
        )


def _cmd_session_lock_write(args: argparse.Namespace) -> int:
    """Write a lock file for this PID."""
    import datetime
    from lib import session_lock as sl

    repo_root = Path(args.repo_root)
    started = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    lock = sl.Lock(
        pid=os.getpid(),
        started=started,
        session=args.session,
        worktree_path=args.worktree_path,
        issue=args.issue,
    )
    sl.write_lock(repo_root=repo_root, lock=lock)
    return 0


def _cmd_session_lock_clear(args: argparse.Namespace) -> int:
    """Clear this PID's lock file."""
    from lib import session_lock as sl
    sl.clear_lock(repo_root=Path(args.repo_root), pid=os.getpid())
    return 0


def _cmd_worktree_add(args: argparse.Namespace) -> int:
    """Create a worktree at ~/Code/<repo-basename>-<issue>/ on a fresh branch."""
    from lib import worktree as wt

    repo_root = Path(args.repo_root).resolve()
    repo_basename = repo_root.name
    target = repo_root.parent / f"{repo_basename}-{args.issue}"
    branch = f"feature/{args.issue}-worktree"  # slug refined by the operator later
    try:
        created = wt.create_worktree(repo=repo_root, target=target, branch=branch, base="main")
    except wt.WorktreeError as e:
        print(str(e), file=sys.stderr)
        return 1
    print(str(created))
    return 0
```

Register each in the argparse subparser block (follow the pattern existing subcommands use). Each subparser needs:
- `--repo-root` (required) — path to the main checkout
- Subcommand-specific flags (`--issue`, `--session`, `--no-worktree`, `--worktree-path` as appropriate)

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_cli.py -v -k "session_resolve or session_lock or worktree_add"`
Expected: PASS — all new tests.

- [ ] **Step 6: Run full test suite to ensure no regression**

Run: `pytest`
Expected: PASS — all tests including pre-existing.

- [ ] **Step 7: Commit**

```bash
git add skills/jared/scripts/jared tests/test_cli.py
git commit -m "feat(cli): session-resolve / session-lock-write / session-lock-clear / worktree-add (Phase 3.2)

Four new subcommands wrap lib.session_lock and lib.worktree for the slash-
command stubs to invoke. Each is thin glue:
- session-resolve: list_active_locks + resolve_action; exit 1 on REFUSE_*
- session-lock-write: write a lock for the current PID
- session-lock-clear: remove this PID's lock (called by /jared-wrap)
- worktree-add: create worktree at <parent>/<repo>-<issue>/

Refusal messages render the three actionable shapes per spec § Behavior shape.

Refs #231, #236."
```

---

### Task 12: `/jared-wrap` stub — lock-clearing step

**Files:**
- Modify: `commands/jared-wrap.md`

- [ ] **Step 1: Insert the lock-clearing step**

Edit `commands/jared-wrap.md`. The current step 5 ("On approval, apply in order") is where state-mutating side effects happen. Add a new bullet at the END of step 5 (after the existing `capture-context.py` bullet):

```markdown
   - Clear this session's presence lock:
     ```bash
     GIT_COMMON_DIR=$(git rev-parse --git-common-dir 2>/dev/null)
     REPO_ROOT=$(dirname "$GIT_COMMON_DIR")
     ${CLAUDE_PLUGIN_ROOT}/skills/jared/scripts/jared session-lock-clear --repo-root "$REPO_ROOT"
     ```
     Removes `<repo>/.jared/session-<pid>.lock` so the next `/jared-start` doesn't see this session as a live sibling. Sibling sessions' locks are left untouched (the clear is PID-keyed).
```

- [ ] **Step 2: Verify the stub still reads coherently**

Re-read `commands/jared-wrap.md` end to end. Confirm the lock-clear bullet fits the rhythm of step 5's other bullets and references the `jared session-lock-clear` subcommand from Task 11.

- [ ] **Step 3: Commit**

```bash
git add commands/jared-wrap.md
git commit -m "feat(jared-wrap): clear session-presence lock at end of flow (Phase 3.3)

Adds a final bullet to step 5 of /jared-wrap: run jared session-lock-clear
to remove this PID's lock file. PID-keyed clear means sibling sessions are
unaffected.

This completes the lock lifecycle: /jared-start writes it (Phase 3.1),
/jared-wrap clears it. Stale locks (process died without wrap) are caught
by list_active_locks's PID-liveness check at the next /jared-start.

Refs #231."
```

---

### Task 13: CLAUDE.md surface — multi-session discipline section

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Read current CLAUDE.md**

Run: `cat CLAUDE.md`. Identify the existing "Branch + PR workflow" section near the bottom — the new multi-session section logically sits adjacent to or just after it (parallel-sessions is a Git-workflow concern).

- [ ] **Step 2: Insert the multi-session section**

Add a new H2 after "Branch + PR workflow":

```markdown
## Multi-session work — `--session N` opt-in

When running two or more Claude sessions against this repo simultaneously, pass
`--session N` to `/jared-start` to opt into worktree isolation:

- `/jared-start <issue>` (solo, default) — no worktree. CWD unchanged. Writes
  a session-presence lock at `<repo>/.jared/session-<pid>.lock` so a later
  session can detect this one.
- `/jared-start <issue> --session 1` — creates `~/Code/<repo>-<issue>/`, checks
  out a fresh `feature/<issue>-<slug>` branch from `origin/main`, shifts CWD
  into the worktree. The `session=1` claim is the durable per-session identity
  (operator applies the `session-1` GitHub label separately, per the labeling
  discipline).
- `/jared-start <issue> --no-worktree` — explicit acknowledgment of the
  shared-`.git/HEAD` risk when starting alongside another active session.
  Use sparingly.

If `/jared-start` detects an active sibling session and neither flag is passed,
it refuses with guidance. Solo work is the common case; the lock + refusal layer
exists so the moment a second session enters the picture, the discipline kicks
in automatically.

`/jared-wrap` clears the lock at session end. Stale locks (from crashed sessions)
are caught and cleared by the next `/jared-start`'s PID-liveness check.

For background and the recovery-sequence incident that motivated this mechanism,
see issue #231 and `docs/superpowers/specs/2026-05-23-multi-session-impl-design.md`.
```

- [ ] **Step 3: Verify**

Re-read CLAUDE.md from top to bottom. The new section should flow naturally after "Branch + PR workflow" and before "Versioning."

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md
git commit -m "docs(CLAUDE.md): multi-session discipline + --session opt-in (Phase 3.4)

Surfaces the new /jared-start flag semantics, the session-lock mechanism,
and the B-leg refusal behavior. Future sessions discover the workflow
without relying on memory entries firing.

Refs #231."
```

---

### Task 14: User memory verification + cross-link or file new

**Files:**
- Read: `~/.claude/projects/-home-brockamer-Code-jared/memory/MEMORY.md` and individual `feedback_*.md` files
- Modify or create: memory files as appropriate

**Context note:** the issue body and the impl spec refer to two memories — `feedback_parallel_session_worktree.md` and `feedback_session_label_ownership.md` — that may not exist by those names. The parent spec (#232) itself flagged uncertainty about one of them. Verify the actual state and act accordingly.

- [ ] **Step 1: List existing memories**

Run: `ls ~/.claude/projects/-home-brockamer-Code-jared/memory/`

- [ ] **Step 2: Read MEMORY.md and decide**

Read `~/.claude/projects/-home-brockamer-Code-jared/memory/MEMORY.md`.

- If a memory describing the parallel-session / shared-HEAD / worktree discipline exists (under any name): edit it to cross-reference the now-implemented mechanism. Update the body's framing from advisory-only to "the mechanism enforces this — see #231 and CLAUDE.md § Multi-session work."
- If no such memory exists: file a new one. Use the auto-memory format (`---` frontmatter with `name`, `description`, `metadata.type: feedback`).

Suggested new memory if needed (one file, not two — the labeling-discipline and worktree-isolation concerns are tightly coupled now):

`feedback_multi_session_discipline.md`:

```markdown
---
name: multi-session-discipline
description: --session N flag opts into worktree isolation for parallel Claude sessions; solo sessions still write presence locks so siblings can detect them
metadata:
  type: feedback
---

When running parallel Claude sessions against the same repo, opt into isolation with `--session N` on `/jared-start` — creates `~/Code/<repo>-<N>/` worktree, isolates `.git/HEAD`. Solo sessions still write session-presence locks (at `<repo>/.jared/session-<pid>.lock`) so a later session can detect them and refuse with guidance.

**Why:** the 2026-05-23 incident where a sibling session's `git checkout` silently moved shared `.git/HEAD`, causing the next commit to land on the wrong branch (recovery required a six-step `git branch -f` + `git reset --hard` + `git cherry-pick` + `git rebase --onto` sequence). The mechanism makes the trap structurally unreachable when the discipline is followed; the B-leg refusal at `/jared-start` catches the case where it isn't.

**How to apply:** if you're about to spawn a second Claude session in this repo, pass `--session N` (different N for each session). If `/jared-start` refuses citing a sibling, address the sibling first (wrap it, or restart it with `--session 1`).

See #231, CLAUDE.md § Multi-session work, `docs/superpowers/specs/2026-05-23-multi-session-impl-design.md`.
```

If you take this path, also add a one-line entry to `MEMORY.md`:

```markdown
- [Multi-session discipline](feedback_multi_session_discipline.md) — --session N opts into worktree isolation; solo sessions still leave presence locks for sibling detection.
```

- [ ] **Step 3: (No commit — these are user memory files, not part of the repo)**

User memories live outside the repo. No git commit. Verify the file(s) saved correctly by re-reading them.

---

### Task 15: Full test suite + ruff + mypy final pass

**Files:**
- (verify only — no edits unless tooling complains)

- [ ] **Step 1: Run the full test suite**

Run: `pytest`
Expected: PASS — all tests, including all new ones from Phases 1–3 and the pre-existing suite.

- [ ] **Step 2: Run ruff on all touched files**

Run:
```bash
ruff check .
ruff format --check .
```
Expected: PASS — no issues.

- [ ] **Step 3: Run mypy**

Run: `mypy`
Expected: PASS — `Success: no issues found`.

- [ ] **Step 4: Fix any issues inline**

If any tool reports issues, fix in the appropriate file and re-run the relevant suite.

- [ ] **Step 5: Commit any tooling fixes (if needed)**

```bash
git add <touched files>
git commit -m "chore: final ruff/mypy pass on the multi-session impl (Phase 3.5)"
```

Skip if no fixes were needed.

---

### Task 16: Push branch and open the PR

**Files:**
- (git operations only)

- [ ] **Step 1: Verify branch state**

Run in parallel:
- `git status` — expect clean working tree
- `git log --oneline main..HEAD` — review the commit trail; should match the phase numbering
- `git diff main..HEAD --stat` — sanity-check the file footprint

- [ ] **Step 2: Push the branch**

Run: `git push -u origin feature/231-236-multi-session-impl`

- [ ] **Step 3: Open the PR**

Run:

```bash
gh pr create --title "feat(multi-session): opt-in worktree + session-presence locking (#231, #236)" --body "$(cat <<'EOF'
## Summary

- Implements **#231** (worktree-by-default for parallel Claude sessions) and **#236** (`/jared-start --session N` flag + sibling-detection prompt) together — they share `/jared-start` as a surface and the `--session` flag drives both.
- New behavior: `/jared-start <N>` is unchanged for solo work; `/jared-start <N> --session 1` creates `~/Code/<repo>-<N>/` worktree isolation; `/jared-start <N> --no-worktree` is the explicit-risk escape from the B-leg refusal.
- Every `/jared-start` writes a session-presence lock at `<repo>/.jared/session-<pid>.lock` — this is the load-bearing fix that makes B-leg detection real even for solo sessions.

## Design

Full design at `docs/superpowers/specs/2026-05-23-multi-session-impl-design.md`. Five decisions:

- **D1** Worktree path = flat sibling (`~/Code/<repo>-<N>/`)
- **D2** Worktree creation = opt-in via `--session N` flag
- **D3** Session presence = unconditional file-lock per `/jared-start`
- **D4** Detection = file-lock + `os.kill(pid, 0)` liveness check
- **D5** Path-collision UX = distinguish registered worktrees (resume) from orphans (error + remediation)

## Test plan

- [ ] Full pytest suite passes (`pytest`)
- [ ] Ruff and mypy clean (`ruff check . && ruff format --check . && mypy`)
- [ ] Manual smoke: `/jared-start <issue>` solo (no flag) — verify lock file appears, no worktree, CWD unchanged
- [ ] Manual smoke: `/jared-start <issue> --session 1` — verify worktree at `~/Code/<repo>-<issue>/`, CWD shifted, lock has session=1
- [ ] Manual smoke: in a second terminal, `/jared-start <other-issue>` with no flag — verify B-leg refusal fires
- [ ] Manual smoke: `/jared-wrap` clears the lock file

Closes #231.
Closes #236.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

- [ ] **Step 4: Note the PR URL in the output**

The `gh pr create` command returns the PR URL. Surface it to the operator.

---

## Self-Review

After writing this plan, I checked it against the spec:

**Spec coverage:**
- D1 (path shape, flat sibling) → Task 11's `_cmd_worktree_add` constructs the path; Task 7's tests verify isolation works at that shape
- D2 (opt-in via flag) → Task 10's stub edit parses `--session N` and `--no-worktree`; Task 11's `_cmd_session_resolve` enforces it
- D3 (unconditional locking) → Tasks 1–3 build `session_lock` lib; Tasks 10 + 11 wire it into the start flow
- D4 (file-lock + kill liveness) → Task 2's `is_alive` + `list_active_locks` with stale cleanup
- D5 (collision UX) → Task 8's `list_worktrees` + `create_worktree` collision handling
- Six-row action table → Task 4's `resolve_action` + 8 scenario tests
- Lock-clear at wrap → Task 12
- CLAUDE.md surface → Task 13
- Memory cross-ref or file → Task 14 (with verification step for the assumption gap)
- Tests: unit + integration + scenario → Phases 1, 2, 3 (combined coverage)

**Placeholder scan:** No "TBD" / "TODO" / "implement later." Each step has runnable code or a runnable command.

**Type consistency:** Lock dataclass fields used consistently across tasks. `Flags`, `Action`, `WorktreeEntry`, `WorktreeError` defined once and referenced. The four CLI subcommand names (`session-resolve`, `session-lock-write`, `session-lock-clear`, `worktree-add`) used identically in stub edits and tests.

**One known gap:** the issue body's "Receives the running session's identity from the selection mechanism (#236)" criterion is satisfied by Task 11's `_cmd_worktree_add` taking `--session` as input. Documented in the PR description; no separate task.
