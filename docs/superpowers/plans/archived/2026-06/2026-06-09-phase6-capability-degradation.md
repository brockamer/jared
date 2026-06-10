---
**Shipped in #319 on 2026-06-10. Final decisions captured in issue body.**
---

# Phase 6 — Capability Declaration + Graceful Degradation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Issue:** #319

**Goal:** Make every jared surface that assumes a GitHub-only board capability instead check `board.capabilities()` and degrade with a single consistent note (or, on KanbanFlow, omit a misleading value / refuse a whole-scope-absent invocation) — so the core board loop works on both backends and GitHub-only richness degrades gracefully instead of erroring or lying.

**Architecture:** One leaf helper module (`lib/capabilities.py`) is the consistency anchor — a single note phrasing (`degraded: <feature> unavailable on <backend> — <instead>`) and a single per-surface gate (`degraded_or_none`). Python surfaces (CLI subcommands + batch scripts) read the backend's static capability set via `board.capabilities()` (resolved by backend — **no live provider construction**; on KanbanFlow, building the provider makes live API calls) and route degradation through that gate, keyed **per rendered section** (spec Resolved decision 5). Prose surfaces (slash-command stubs, `SKILL.md`, references) do **not** call the helper — they branch on the existing `- backend:` bullet in `docs/project-board.md` § "Jared config" (spec Resolved decision 1, the voice-kill-switch pattern). GitHub advertises the full capability set, so **no GitHub behavior changes** — that is the regression bar.

**Tech Stack:** Python 3.14 stdlib (argparse CLI, no deps), pytest (unit + opt-in integration), ruff, mypy --strict. The settled design lives in [`../specs/2026-06-09-phase6-capability-declaration-design.md`](../specs/2026-06-09-phase6-capability-declaration-design.md); the exhaustive surface list is [`2026-06-09-phase6-capability-inventory.md`](2026-06-09-phase6-capability-inventory.md) (84 surfaces / 24 files / 47 misleading-if-shown).

**Live verification:** A real KanbanFlow board exists — "Jared Test" (`p9vK6cR`), token in `~/.secrets` as `KANBANFLOW_API_TOKEN`, Bearer auth confirmed. Task 11 exercises capability resolution + at least one degraded surface against it (spec Acceptance: live, not fake-only).

---

## File structure

**New files:**
- `skills/jared/scripts/lib/capabilities.py` — the degradation helper + the per-surface gate. Leaf module: imports only `Capability` from `board_provider`. Single responsibility: turn "capability X absent on backend B" into the one canonical note string.
- `tests/test_capabilities.py` — unit tests for the helper + gate.
- `tests/test_phase6_degradation.py` — per-capability degraded-path tests for the Python surfaces (one focused test per representative surface; drives real command/script functions with a capability-restricted provider).
- `tests/test_kanbanflow_live.py` — `@pytest.mark.integration` live verification against board `p9vK6cR`.

**Modified (Python — gated in-process):**
- `skills/jared/scripts/jared` — `_cmd_close`, `_cmd_blocked_by`, `_cmd_comment`, `_cmd_file` (markdown note + the `--milestone` whole-scope-absent refusal), `_detect_stuck_closed_recent`, `_cmd_next_session_prompt`, `_cmd_audit_fetch` (the `--type milestones/both` whole-scope-absent refusal).
- `skills/jared/scripts/lib/board.py` — `compute_velocity`, `fetch_audit_window` (issues/milestones/edges sub-queries), `fetch_open_issues_for_ties`, `_format_token_scope_diagnostic`.
- `skills/jared/scripts/sweep.py` — the four `VELOCITY_TIMESTAMPS` sections + `check_native_dependencies` section.
- `skills/jared/scripts/dependency-graph.py` — `fetch_all_native_dependencies`, `find_orphaned`.
- `skills/jared/scripts/stage.py` — milestone-proximity rank note, backlog-age tiebreaker note, native-edge note.

**Modified (prose — branch on `- backend:`):**
- `commands/*.md` (jared, jared-start, jared-wrap, jared-groom, jared-stage, jared-audit, jared-reshape, jared-file, jared-init), `skills/jared/SKILL.md`, `skills/jared/references/*.md` (operations.md, milestones-and-roadmap.md, human-readable-board.md, board-sweep.md, structural-review.md, dependencies.md, new-board.md, jared-cli.md).

**Modified (docs):**
- `skills/jared/references/operations.md` (capability/degradation section; scope MCP-first tier to `MCP_TIER`), `skills/jared/SKILL.md`, `CLAUDE.md`, `docs/project-board.md` (capabilities-on-this-backend note), `CHANGELOG.md`.

---

## Task 0: Record SUB_ISSUES as a deliberate non-finding (no code)

`SUB_ISSUES` is a phantom capability — zero consumers on either backend (spec Resolved decision 4). Phase 6 builds **no** note, check, or test for it. The spec's problem-table row is already struck and the inventory's two `SUB_ISSUES` rows already read "No degradation needed." Nothing to implement; this task exists so the engineer does not "fix" the absence by adding a guard (that would be dead code per CLAUDE.md § dead-code doctrine).

- [ ] **Step 1:** Confirm no work. Run `grep -rn "SUB_ISSUES" skills/jared/scripts/ commands/` — expect hits only in `board_provider.py` (enum) and `kanbanflow_provider.py` (`_OMITTED_CAPABILITIES`). If any new consumer appears during the phase, stop and surface it (do not gate on it).

---

## Task 1: The degradation helper (the consistency anchor)

**Files:**
- Create: `skills/jared/scripts/lib/capabilities.py`
- Test: `tests/test_capabilities.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_capabilities.py
from skills.jared.scripts.lib.board_provider import Capability
from skills.jared.scripts.lib.capabilities import degraded_note, degraded_or_none


class _Board:
    def __init__(self, backend: str, caps: set[Capability]) -> None:
        self.backend = backend
        self._caps = caps

    def capabilities(self) -> frozenset[Capability]:
        return frozenset(self._caps)


def test_degraded_note_uses_the_canonical_phrasing() -> None:
    assert (
        degraded_note("aging checks", "no creation timestamps", backend="kanbanflow")
        == "degraded: aging checks unavailable on kanbanflow — no creation timestamps"
    )


def test_degraded_or_none_returns_note_when_capability_absent() -> None:
    board = _Board("kanbanflow", set())  # KanbanFlow advertises nothing
    note = degraded_or_none(
        board, Capability.VELOCITY_TIMESTAMPS, "stale High Backlog", "no creation timestamps"
    )
    assert note == "degraded: stale High Backlog unavailable on kanbanflow — no creation timestamps"


def test_degraded_or_none_returns_none_when_capability_present() -> None:
    board = _Board("github", set(Capability))  # GitHub advertises the full set
    assert degraded_or_none(board, Capability.VELOCITY_TIMESTAMPS, "x", "y") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_capabilities.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named '...capabilities'`.

- [ ] **Step 3: Write the minimal implementation**

```python
# skills/jared/scripts/lib/capabilities.py
"""Phase 6 — capability-aware degradation (epic #313).

The single consistency anchor: ONE note phrasing, ONE per-surface gate. CLI
subcommands and batch scripts read `board.capabilities()` (static, by backend)
and route every degradation through `degraded_or_none`, keyed per rendered
section. Prose surfaces (slash-command stubs, SKILL.md, references) do NOT call
this module — they branch on the `- backend:` bullet directly (spec Resolved
decision 1).

Leaf module: imports only `Capability` from board_provider, so it never
participates in the board.py <-> provider import cycle.
"""

from __future__ import annotations

from typing import Protocol

from .board_provider import Capability


class _CapBoard(Protocol):
    """The Board surface this module needs: a backend name + the static
    per-backend capability set. ``Board.capabilities()`` resolves it WITHOUT
    constructing the provider (which, on KanbanFlow, would make live API calls).
    """

    backend: str

    def capabilities(self) -> frozenset[Capability]: ...


def degraded_note(feature: str, instead: str, *, backend: str) -> str:
    """The single Phase-6 degradation phrasing (spec §33):

    ``degraded: <feature> unavailable on <backend> — <instead>``
    """
    return f"degraded: {feature} unavailable on {backend} — {instead}"


def degraded_or_none(
    board: _CapBoard,
    capability: Capability,
    feature: str,
    instead: str,
) -> str | None:
    """Return the degradation note when `capability` is absent, else None.

    The universal per-surface gate: callers print the note (or route it to
    stderr + exit nonzero for whole-scope-absent invocations) when this returns
    a string, and run their normal logic when it returns None.
    """
    if capability in board.capabilities():
        return None
    return degraded_note(feature, instead, backend=board.backend)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_capabilities.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Lint + type-check**

Run: `ruff check skills/jared/scripts/lib/capabilities.py tests/test_capabilities.py && ruff format skills/jared/scripts/lib/capabilities.py tests/test_capabilities.py && mypy`
Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add skills/jared/scripts/lib/capabilities.py tests/test_capabilities.py
git commit -m "feat(jared): add capability degradation helper (Phase 6.1)"
```

---

## Task 1b: static by-backend capability resolution (no live provider)

The gate must work in batch scripts (`sweep.py`, `dependency-graph.py`) that deliberately avoid constructing a live provider. Capabilities are a compile-time constant per backend, so resolve them from the provider **class** without instantiating — constructing the KanbanFlow provider makes live API calls (`board.py` `provider` property: `KanbanFlowClient.from_env()` → `get_board()` …). A public `default_capabilities()` classmethod keeps the access clean (no `ruff` SLF001 private-member access).

**Files:**
- Modify: `skills/jared/scripts/lib/github_provider.py`, `skills/jared/scripts/lib/kanbanflow_provider.py` (add the classmethod)
- Modify: `skills/jared/scripts/lib/board.py` (add `Board.capabilities()`; ensure `Capability` is imported)
- Test: `tests/test_board_capabilities.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_board_capabilities.py
from skills.jared.scripts.lib.board import Board
from skills.jared.scripts.lib.board_provider import Capability


def _board(backend: str) -> Board:
    b = Board.__new__(Board)  # bypass __init__; capabilities() only reads .backend
    b.backend = backend
    return b


def test_github_advertises_full_capability_set() -> None:
    assert _board("github").capabilities() == frozenset(Capability)


def test_kanbanflow_advertises_empty_capability_set() -> None:
    # Resolved offline — no KANBANFLOW_API_TOKEN, no network.
    assert _board("kanbanflow").capabilities() == frozenset()
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/test_board_capabilities.py -v`
Expected: FAIL — `AttributeError: 'Board' object has no attribute 'capabilities'`.

- [ ] **Step 3a: Add the classmethod to BOTH providers** (within the class — accessing own `_CAPABILITIES`, no SLF001):

```python
@classmethod
def default_capabilities(cls) -> frozenset[Capability]:
    """The backend's static capability set, resolved without an instance."""
    return cls._CAPABILITIES
```

- [ ] **Step 3b: Add `Board.capabilities()`** (in `board.py`, near the `provider` property; add `from .board_provider import Capability` to the existing board_provider import if absent):

```python
def capabilities(self) -> frozenset[Capability]:
    """The backend's static capability set, resolved WITHOUT constructing the
    provider — constructing the KanbanFlow provider makes live API calls.
    Capabilities are a compile-time constant per backend, so the provider class
    attribute is authoritative and fully offline.
    """
    if self.backend == "kanbanflow":
        from .kanbanflow_provider import KanbanFlowProvider

        return KanbanFlowProvider.default_capabilities()
    if self.backend == "github":
        from .github_provider import GitHubProjectsProvider

        return GitHubProjectsProvider.default_capabilities()
    raise BoardConfigError(
        f"backend '{self.backend}' has no capability set. Supported: 'github', 'kanbanflow'."
    )
```

- [ ] **Step 4: Run** — `pytest tests/test_board_capabilities.py -v` → PASS. The kanbanflow test MUST pass with `KANBANFLOW_API_TOKEN` unset (proves it is offline).
- [ ] **Step 5:** `ruff check . && ruff format . && mypy` → clean.
- [ ] **Step 6: Commit**

```bash
git add skills/jared/scripts/lib/github_provider.py skills/jared/scripts/lib/kanbanflow_provider.py skills/jared/scripts/lib/board.py tests/test_board_capabilities.py
git commit -m "feat(jared): Board.capabilities() static by-backend resolver (Phase 6.1b)"
```

---

## Task 2: Test scaffolding for command/script surfaces

The gate unit-tests (Task 1) use a local stub. Surface tests need to drive **real** command/script functions with a restricted capability set. The cheapest, KF-board-free way: build a normal **GitHub** Board, then monkeypatch the provider's `capabilities()` down to a subset — `board.backend` stays `"github"` (the note label is irrelevant to a unit test asserting "the section was skipped"). The live KanbanFlow path is covered by Task 11.

**Files:**
- Modify: `tests/conftest.py` (add one helper)

- [ ] **Step 1: Add the helper**

```python
# tests/conftest.py — append near the other helpers
def restrict_capabilities(
    monkeypatch: pytest.MonkeyPatch, *, keep: set[object] | None = None
) -> None:
    """Force `Board.capabilities()` to return only `keep` (default: nothing).

    Patches the static by-backend resolver so a normal GitHub-backed Board
    behaves as a capability-restricted backend — letting surface tests exercise
    the degraded path without a live KanbanFlow board.
    """
    from skills.jared.scripts.lib.board import Board

    frozen = frozenset(keep or set())
    monkeypatch.setattr(Board, "capabilities", lambda self: frozen)
```

- [ ] **Step 2: Verify it imports**

Run: `pytest tests/conftest.py --collect-only -q`
Expected: no import error.

- [ ] **Step 3: Commit**

```bash
git add tests/conftest.py
git commit -m "test(jared): add restrict_capabilities helper for Phase 6 (Phase 6.2)"
```

---

## Task 3: VELOCITY_TIMESTAMPS surfaces (the per-section marquee)

19 surfaces (15 misleading). The Python set: **sweep.py** four checks, `board.compute_velocity`, `board.fetch_audit_window` (issues sub-query), `_cmd_next_session_prompt` recently-closed, `stage.py` backlog-age tiebreaker. Each is its **own** rendered section → its **own** note (spec Resolved decision 5; matches sweep's existing five `(skipped — no issue data)` lines). The prose surfaces (jared-audit/groom/jared status aging) are Task 9.

### Pattern (study this, then apply per row)

`sweep.py`'s render loop already guards each section. Insert a capability gate **before** the existing data guard, using `degraded_or_none(board, …)`. **But sweep does not hold a `Board` at the render sections** — it works off the `repo` string and only builds a `Board` conditionally (closed-cache ~780, doc-sync ~900). So Task 3 first **hoists an offline Board**: after `find_config()` near the top of `cmd_sweep`, add `board = Board.from_default()` (offline doc parse — do **not** touch `board.provider`, which makes live KanbanFlow API calls) and thread `board` into the render function. `board.capabilities()` then resolves the static set with no network. If `find_config()` finds no board doc, skip the gate and keep today's behavior.

Before (`sweep.py` ~826):
```python
print(f"== Stale High-priority Backlog (>{args.staleness_days}d) ==")
if not issues_by_number:
    print("  (skipped — no issue data)")
else:
    stale = check_stale_high_backlog(items, issues_by_number, args.staleness_days)
    for s in stale or ["None"]:
        print(f"  {s}")
print()
```

After:
```python
print(f"== Stale High-priority Backlog (>{args.staleness_days}d) ==")
note = degraded_or_none(
    board, Capability.VELOCITY_TIMESTAMPS,
    "stale High-priority Backlog", "no creation timestamps on this backend",
)
if note:
    print(f"  {note}")
elif not issues_by_number:
    print("  (skipped — no issue data)")
else:
    stale = check_stale_high_backlog(items, issues_by_number, args.staleness_days)
    for s in stale or ["None"]:
        print(f"  {s}")
print()
```

Import at top of `sweep.py`: `from lib.capabilities import degraded_or_none` and `from lib.board_provider import Capability` (match sweep's existing `from lib...` import style — sweep imports board helpers as `board_*`; verify the exact import prefix sweep already uses and mirror it).

- [ ] **Step 1: Write the failing test** (representative: the stale-High section)

```python
# tests/test_phase6_degradation.py
import pytest
from tests.conftest import import_sweep, restrict_capabilities


def test_sweep_velocity_sections_degrade_when_timestamps_absent(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path
) -> None:
    restrict_capabilities(monkeypatch)  # nothing advertised
    sweep = import_sweep()
    # ... construct the minimal board + items the render path needs (see Step 3
    # for the exact fixture; sweep's render function takes board, items,
    # issues_by_number, args) ...
    # Assert the degraded note is printed and the real check did NOT run:
    out = capsys.readouterr().out
    assert "degraded: stale High-priority Backlog unavailable on" in out
```

- [ ] **Step 2: Run to verify it fails** — `pytest tests/test_phase6_degradation.py -v` → FAIL (note absent).
- [ ] **Step 3: Implement** the four sweep gates with these exact `(feature, instead)` strings, all `Capability.VELOCITY_TIMESTAMPS`:

| Section (sweep.py line) | feature | instead |
|---|---|---|
| Stale High-priority Backlog (~826) | `stale High-priority Backlog` | `no creation timestamps on this backend` |
| Stalled In Progress (~835) | `stalled In Progress` | `no activity timestamps on this backend` |
| Blocked-status hygiene **aging sub-check only** (~844) | `Blocked-status aging` | `no activity timestamps — the \`## Blocked by\` presence check still runs` |
| (the `## Blocked by` presence sub-check at line 416-417 stays unconditional) | — | — |

  For Blocked-status hygiene: keep the section header and the presence check; gate **only** the `updatedAt` aging branch (`check_blocked_status_hygiene` lines 418-423). Simplest: pass a `velocity_ok: bool` flag into `check_blocked_status_hygiene` and skip the aging branch when False, printing the note in the render loop.

- [ ] **Step 4: Run** — `pytest tests/test_phase6_degradation.py -v` → PASS.
- [ ] **Step 5: Implement the remaining VELOCITY_TIMESTAMPS Python surfaces** (same gate, exact strings):

| Surface | File:line | feature | instead |
|---|---|---|---|
| `check_session_note_freshness` section | `sweep.py:542` + its render | `session-note freshness` | `no comment timestamps on this backend` |
| `compute_velocity` | `board.py:~1751` | `velocity computation` | `no closed/merged timestamps — velocity is empty` |
| `fetch_audit_window` issues createdAt sort | `board.py:~1862` | `velocity-calibrated audit window` | `no creation timestamps — window falls back to the 14-day floor, items unsorted` |
| `_cmd_next_session_prompt` recently-closed | `jared:~1086` | `recently-closed (7d)` | `no closed-at timestamps on this backend` |
| `stage.py` backlog-age tiebreaker | `stage.py:98-112` | `Backlog-age tiebreaker` | `no creation timestamps — promotion order may differ` |

  Note: `compute_velocity` and `fetch_audit_window` live in `board.py`, which **cannot** import `capabilities.py` at module top (cycle: board → providers → board_provider; capabilities → board_provider is fine, but board → capabilities → board_provider is also fine since capabilities doesn't import board — verify no cycle, it should be clean). These functions receive a `Board`/`board` argument already; gate with `degraded_or_none(board, …)` and return the empty/sentinel result the callers already tolerate (e.g. `compute_velocity` returns its empty dataclass).

- [ ] **Step 6:** Run the full suite — `pytest -m 'not integration' -q` → all green (GitHub path unchanged). `ruff check . && ruff format . && mypy` → clean.
- [ ] **Step 7: Commit** — `git commit -am "feat(jared): degrade VELOCITY_TIMESTAMPS surfaces on capability-absent backends (Phase 6.3)"`

---

## Task 4: NATIVE_DEPENDENCIES surfaces

18 surfaces (12 misleading). Python set: `dependency-graph.py` (`fetch_all_native_dependencies`, `find_orphaned`), `sweep.check_native_dependencies` section, `_cmd_blocked_by` success message, `board.fetch_open_issues_for_ties`, `board.fetch_audit_window` edges sub-query, `stage.fetch_items_for_stage` native edges. Apply the Task-3 gate pattern.

Key nuance: dependency reads **degrade to the emulated `blocked-by:<N>` label edges**, they do not vanish — the note says the graph is built from emulated markers (so cycle/chain checks may be incomplete), per the inventory `degrade_to`. `_cmd_blocked_by`'s message changes wording (it still works via label emulation), it is not skipped. **Board scope (same as sweep):** `dependency-graph.py` does not hold a `Board` at `find_orphaned`/`fetch_all_native_dependencies`; resolve `board = Board.from_default()` once in `main`/`build_graph` (offline; never touch `board.provider`) and pass it to the gated functions. `_cmd_blocked_by` runs inside the CLI, which already constructs a `Board` — use that directly.

- [ ] **Step 1:** Write the failing test (representative: `_cmd_blocked_by` message). Drive `import_cli().main(["blocked-by", ...])` with `restrict_capabilities(monkeypatch)`; assert the success line reads `... (label emulation — NATIVE_DEPENDENCIES not supported on this backend)`.
- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3: Implement** with these exact strings (all `Capability.NATIVE_DEPENDENCIES`):

| Surface | File:line | Behavior | feature / instead (or message) |
|---|---|---|---|
| `_cmd_blocked_by` success | `jared:~734` | reword (not skip) | append `(label emulation — NATIVE_DEPENDENCIES not supported on this backend)` |
| `check_native_dependencies` section | `sweep.py:855` render | skip-with-note | `native-dependency hygiene` / `native edges unavailable — emulated \`blocked-by:\` labels only` |
| `fetch_all_native_dependencies` | `dependency-graph.py:140-160` | note-then-fallback | emit note then existing body-text fallback (do not silently switch) |
| `find_orphaned` (also CLOSED_STATE — Task 6) | `dependency-graph.py:267-282` | skip-with-note | `orphaned-dependency check` / `no closed-state lookup on this backend` |
| `fetch_open_issues_for_ties` | `board.py:653` | gate | route via `list_open_items()` without native edges + note in `jared ties` diagnostic |
| `fetch_audit_window` edges | `board.py:1926` | skip section | `blocked-by edges` / `native edges unavailable on this backend` |
| `stage.fetch_items_for_stage` edges | `stage.py:441` | note, body-ref path still runs | `native blocked-by edges` / `blocker detection from \`## Blocked by\` body sections only` |

- [ ] **Step 4:** Run → PASS. **Step 5:** full suite + lint + mypy clean. **Step 6:** `git commit -am "feat(jared): degrade NATIVE_DEPENDENCIES surfaces (Phase 6.4)"`

---

## Task 5: MILESTONE_STATE surfaces + the whole-scope-absent refusal

17 surfaces (8 misleading). Python set: `board.fetch_audit_window` milestones sub-query, `_cmd_audit_fetch` `--type milestones/both` (**whole-scope-absent → exit nonzero**, spec Resolved decision 2), `stage.py` milestone-proximity ranking, `_cmd_file` milestone error-recovery message.

### The whole-scope-absent refusal (the one new exit-code behavior)

`jared audit fetch --type milestones` (and `--type both`) on a `MILESTONE_STATE`-absent backend must **exit nonzero** with the note on stderr — not return a hollow exit-0 empty result. Model it on the existing `_cmd_file` `--milestone` refusal (`jared:578-589`, `return 2`).

- [ ] **Step 1: Write the failing test**

```python
def test_audit_fetch_milestones_refuses_when_milestone_state_absent(
    monkeypatch, capsys, ...
) -> None:
    restrict_capabilities(monkeypatch)  # MILESTONE_STATE absent
    cli = import_cli()
    rc = cli.main(["audit", "fetch", "--type", "milestones"])
    err = capsys.readouterr().err
    assert rc == 2
    assert "degraded: milestone" in err and "unavailable on" in err
```

- [ ] **Step 2:** Run → FAIL (currently returns 0 with empty milestones).
- [ ] **Step 3: Implement** in `_cmd_audit_fetch` (`jared:~1243`), before calling `fetch_audit_window`:

```python
entity_type = args.type
note = degraded_or_none(
    board, Capability.MILESTONE_STATE,
    "milestone audit", "this backend has no milestone state or due dates",
)
if note and args.type in ("milestones", "both"):
    if args.type == "milestones":
        print(f"error: {note}", file=sys.stderr)
        return 2
    # --type both: continue issues-only — no helper, just narrow the local var
    print(f"warning: {note}; continuing with issues only", file=sys.stderr)
    entity_type = "issues"
# pass `entity_type` (NOT args.type) to fetch_audit_window below
```

- [ ] **Step 4:** Run → PASS.
- [ ] **Step 5: Implement the remaining MILESTONE_STATE surfaces** (gate pattern):

| Surface | File:line | Behavior | feature / instead |
|---|---|---|---|
| `fetch_audit_window` milestones REST | `board.py:1902` | skip section | `milestone audit window` / `no milestone state/due-dates on this backend` |
| `stage.py` milestone-proximity rank | `stage.py:83-95` | already saturates to `inf`; add header note | `milestone-proximity ranking` / `ranked by Priority and age only` |
| `_cmd_file` milestone error-recovery msg | `jared:571-576` | omit GitHub `gh api …/milestones` line on non-GitHub | (only changes the recovery text shown when no milestone matches) |

- [ ] **Step 6:** full suite + lint + mypy. **Step 7:** `git commit -am "feat(jared): degrade MILESTONE_STATE surfaces + refuse whole-scope-absent milestone fetch (Phase 6.5)"`

---

## Task 6: CLOSED_STATE surfaces + the second whole-scope-absent refusal

13 surfaces (5 misleading). Python set: `_cmd_close` (functionally correct on KF — add a "column-move only" note, no skip), `_detect_stuck_closed_recent` (skip-with-note — the stuck-closed divergence detector is meaningless without two signals), `dependency-graph.find_orphaned` (closed-state lookup → skip-with-note; shared with Task 4).

Also the **`jared file --milestone NAME` whole-scope-absent refusal** belongs here conceptually but is gated on `MILESTONE_STATE` — implement it in Task 5's file surface: when `--milestone NAME` is passed and `MILESTONE_STATE` is absent, `return 2` with the note (mirrors the existing unmatched-milestone refusal at `jared:578`).

- [ ] **Step 1:** Failing test — `_detect_stuck_closed_recent` emits the note + returns no items under `restrict_capabilities`.
- [ ] **Step 2:** Run → FAIL. **Step 3: Implement:**

| Surface | File:line | Behavior | feature / instead |
|---|---|---|---|
| `_detect_stuck_closed_recent` | `jared:~943` | skip-with-note | `stuck-closed check` / `Done column is the sole closed signal on this backend` |
| `_cmd_close` output | `jared:~481` | add note (no skip) | append `(column-move only — no native closed state on this backend)` |
| `find_orphaned` | `dependency-graph.py:267-282` | skip-with-note (if not done in Task 4) | `orphaned-dependency check` / `no closed-state lookup on this backend` |

- [ ] **Step 4:** Run → PASS. **Step 5:** suite + lint + mypy. **Step 6:** `git commit -am "feat(jared): degrade CLOSED_STATE surfaces (Phase 6.6)"`

---

## Task 7: MARKDOWN_BODY + MCP_TIER Python surfaces

`MARKDOWN_BODY` (8 surfaces, **0 misleading** — purely cosmetic): `_cmd_file` body + `_cmd_comment` body store plain text on KF. These do **not** skip — content is preserved; add a one-line note that the body is stored as plain text. `MCP_TIER` (7 surfaces, all "misleading" as doctrine): only one is Python — `_format_token_scope_diagnostic` (`board.py:~986`) appends a GitHub-MCP paragraph to scope errors; omit it when `MCP_TIER` is absent. The other six `MCP_TIER` surfaces are prose (Task 9).

- [ ] **Step 1:** Failing test — `_format_token_scope_diagnostic` output omits the "MCP note:" paragraph under `restrict_capabilities`.
- [ ] **Step 2:** Run → FAIL. **Step 3: Implement:**

| Surface | File:line | Capability | Behavior |
|---|---|---|---|
| `_format_token_scope_diagnostic` MCP paragraph | `board.py:~986` | `MCP_TIER` | omit the MCP paragraph when absent (rest of diagnostic stands) |
| `_cmd_file` body | `jared:~595` | `MARKDOWN_BODY` | add note: `degraded: markdown body rendering unavailable on <backend> — stored as plain text` (no skip) |
| `_cmd_comment` body | `jared:~762` | `MARKDOWN_BODY` | same note (no skip) |

- [ ] **Step 4:** Run → PASS. **Step 5:** suite + lint + mypy. **Step 6:** `git commit -am "feat(jared): degrade MARKDOWN_BODY + MCP_TIER Python surfaces (Phase 6.7)"`

---

## Task 8: Verify the whole-scope-absent refusals end to end

Both nonzero-exit invocations were implemented in Tasks 5/6. This task adds the explicit acceptance tests so they cannot regress.

- [ ] **Step 1:** Tests asserting `rc == 2` + a stderr note for: (a) `jared audit fetch --type milestones`, (b) `jared audit fetch --type both` warns + continues issues-only (rc 0), (c) `jared file --milestone "X" ...` when `MILESTONE_STATE` absent. Use `restrict_capabilities`.
- [ ] **Step 2:** Run → PASS (implementations already exist). **Step 3:** `git commit -am "test(jared): lock whole-scope-absent refusal exit codes (Phase 6.8)"`

---

## Task 9: Prose / doctrine surfaces — branch on `- backend:`

No Python. Each stub/reference gains a conditional instruction: **"If `docs/project-board.md` § Jared config has `- backend: kanbanflow`, degrade `<surface>` with a note: `<text>`"** — the voice-kill-switch pattern (compare `commands/*.md` line 5). The note text for each surface is the inventory's `degrade_to` string.

### Representative (jared-reshape Roadmap/milestone section)

In `commands/jared-reshape.md`, before the Step-3 milestone/Roadmap instruction, add:

```markdown
**Backend gate.** If `docs/project-board.md` § Jared config has `- backend: kanbanflow`,
skip Question 3 (milestone dates + Roadmap) and the milestone bundles (2, 3) with a note:
`degraded: milestone dates unavailable on kanbanflow — Roadmap/milestone section omitted`.
KanbanFlow has no milestone state or due dates (MILESTONE_STATE absent).
```

- [ ] **Step 1: Apply the same conditional to each prose surface** in the inventory (regions `stubs` + `doctrine`). Group by file; each gets a backend-gate note quoting its `degrade_to`. Files: `jared-reshape.md`, `jared-audit.md`, `jared-groom.md`, `jared.md`, `jared-file.md`, `jared-start.md`, `jared-wrap.md` (note: PR-flow 5b is **scoped out** — see spec finding; do NOT gate it), `jared-stage.md`, `jared-init.md`, `SKILL.md`, `references/operations.md`, `milestones-and-roadmap.md`, `human-readable-board.md`, `board-sweep.md`, `structural-review.md`, `dependencies.md`, `new-board.md`, `jared-cli.md`.
- [ ] **Step 2: `operations.md` MCP-tier scoping.** Scope the entire MCP-first three-tier model, the GraphQL-budget rules, and the MCP-equivalents table to GitHub (`MCP_TIER`): add a leading "GitHub backend only" qualifier so a KanbanFlow operator does not try `gh`/MCP/GraphQL-budget management. This covers the six prose `MCP_TIER` surfaces.
- [ ] **Step 3: Verify** no prose surface from the inventory is missed: `grep -rn "backend: kanbanflow" commands/ skills/jared/SKILL.md skills/jared/references/` and cross-check the count of gated sections against the inventory's `stubs`+`doctrine` rows.
- [ ] **Step 4: Commit** — `git commit -am "docs(jared): branch prose surfaces on backend for capability degradation (Phase 6.9)"`

---

## Task 10: GitHub regression bar

The whole point: GitHub advertises the full set, so **nothing degrades** on GitHub.

- [ ] **Step 1:** Run the full unit suite untouched: `pytest -m 'not integration' -q`. Expected: all pre-existing tests pass with **no modification** (a changed assertion on the GitHub path is a regression — investigate, don't edit the test).
- [ ] **Step 2:** Spot-check: run `jared summary`, `sweep.py`, `dependency-graph.py --summary` against the real GitHub board (#4) and confirm byte-identical output to pre-Phase-6 (no `degraded:` lines appear).
- [ ] **Step 3:** `ruff check . && ruff format --check . && mypy` → clean across the whole tree.

---

## Task 11: Live KanbanFlow verification (required, not fake-only)

Exercise capability resolution + ≥1 degraded surface against the real board `p9vK6cR` (spec Acceptance). The fake can mask the live shape — this is the #317/PR #334 lesson.

**Prereq:** `KANBANFLOW_API_TOKEN` is in `~/.secrets` (sourced via `~/.profile`). The current process may not have it — re-source or run the integration test in a fresh shell. The test board's columns are non-canonical (`Maybe Never?`, `Planned One Day`, …), so a KF-backed `docs/project-board.md` with a `### Status column map` is needed for board-level ops; capability resolution itself needs only the token.

- [ ] **Step 1:** Write `tests/test_kanbanflow_live.py` (`@pytest.mark.integration`):
  - Build a `KanbanFlowProvider` from the live client (`KanbanFlowClient.from_env()`, `get_board()`, field defs, `KfNumberIndex`) against `p9vK6cR`.
  - Assert `provider.capabilities() == frozenset()` (live, not the fake's value).
  - Assert `degraded_or_none(board, Capability.VELOCITY_TIMESTAMPS, "x", "y")` returns a note (the live empty-set path).
- [ ] **Step 2:** Seed a minimal KF-backed `docs/project-board.md` for the test board (Repo, Board ID `p9vK6cR`, `### Status column map` mapping canonical → the board's columns) — either as a fixture or documented in `tests/testbed-setup.md`. Run one degraded surface (e.g. `jared summary` stuck-closed section, or a sweep velocity section) against it and confirm the `degraded:` note prints live.
- [ ] **Step 3:** Run `pytest -m integration tests/test_kanbanflow_live.py -v` with the token exported. Expected: PASS. Record the exact command + output in the PR description.
- [ ] **Step 4:** `git commit -am "test(jared): live KanbanFlow capability + degradation verification (Phase 6.11)"`

---

## Task 12: Documentation + CHANGELOG + release

- [ ] **Step 1:** `skills/jared/references/operations.md` — add a "Capabilities & degradation" section (the helper, the per-section note format, the backend-branch doctrine for prose); scope the three-tier MCP guidance to `MCP_TIER`.
- [ ] **Step 2:** `skills/jared/SKILL.md` — note the capability model and where degradation is doctrine (prose, `- backend:`) vs code (`degraded_or_none`).
- [ ] **Step 3:** `CLAUDE.md` — a capability-consumption paragraph alongside the existing board-provider abstraction note (Phase 6 consumes the enum; the helper is the anchor; prose branches on `- backend:`).
- [ ] **Step 4:** `docs/project-board.md` (jared's own, GitHub backend) — a "capabilities on this backend" note (full set; nothing degrades).
- [ ] **Step 5:** `CHANGELOG.md` — entry under **Features** citing #319.
- [ ] **Step 6:** Bump version in `.claude-plugin/plugin.json` + `pyproject.toml`; prepare GitHub Release notes (per CLAUDE.md § Versioning). (Tag/release at merge, operator-confirmed.)
- [ ] **Step 7:** `git commit -am "docs(jared): document capability degradation model (Phase 6.12)"`

---

## Execution coordination (parallel session-2 on #318)

Session-2 is live on #318 (`jared migrate`, Phase 5). Its spec's Documentation Impact lists the **same shared files** Phase 6 edits: `operations.md`, `CLAUDE.md`, `docs/project-board.md`, `CHANGELOG.md`. Both phases also conceptually touch a "capability → human prose" mapping (#318's lossiness report vs. Phase 6's degradation note) — though they share the already-shipped `Capability` enum, not a new module, so the collision is on **docs/changelog ordering**, not core code.

- **Worktree isolation is mandatory** (session-1 runs `feature/319-…` in `~/Code/jared-319/`). Already in the start path; this is why.
- **CHANGELOG ordering:** both PRs add a `## Features` entry. Land them in a deterministic order or expect a trivial CHANGELOG merge conflict — coordinate with session-2 before the second merge.
- **Consider splitting Tasks 9 + 12 (prose/docs) into a separable follow-up PR.** The Python mechanism (Tasks 0–8, 10, 11) is the load-bearing, independently-testable core; the prose/doc edits are the widest merge-collision surface against #318. A two-PR split (mechanism PR, then doctrine PR) shrinks the conflict window and keeps each PR reviewable. Decide at execution time based on whether #318 has merged yet.

## Self-review (run before opening the PR)

1. **Spec coverage:** every Resolved decision (1 prose-branch, 2 soft+nonzero, 3 no-header, 4 SUB_ISSUES non-finding, 5 per-section) maps to a task — 1/9, 5/6/8, (3 = absence of any header task, intentional), 0, 3-7. Every inventory capability cluster has a task: VELOCITY→3, NATIVE→4, MILESTONE→5, CLOSED→6, MARKDOWN+MCP→7, prose→9, SUB_ISSUES→0.
2. **Placeholder scan:** the per-surface tables give exact `(feature, instead)` strings; the appendix carries every `degrade_to`. No "add appropriate handling" — each row names the behavior.
3. **Type consistency:** the gate is `degraded_or_none(board, capability, feature, instead) -> str | None` everywhere; the note format is `degraded_note` only. `Capability` members are the seven in `board_provider.py`.
4. **Regression bar:** Task 10 asserts the GitHub suite passes **unmodified** — the canary for "no GitHub behavior change."
