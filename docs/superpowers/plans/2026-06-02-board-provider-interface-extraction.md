# BoardProvider Interface Extraction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extract a backend-neutral `BoardProvider` contract from the GitHub-coupled `board.py`, with `GitHubProjectsProvider` as the sole implementation, as a behavior-preserving refactor proven by the existing test suite.

**Architecture:** Define a `typing.Protocol` plus backend-neutral data types. Relocate all `gh`/GraphQL machinery into `GitHubProjectsProvider` (private), rewrite every `_cmd_*` and batch-script consumer to call only semantic provider methods, and reduce `Board` to a config-parsing facade that instantiates the configured provider (default `github`). No internal IDs (`PVTI_…`, KF `_id`) cross the interface boundary; `IssueRef` is the stable integer `#N` and the provider resolves it internally.

**Tech Stack:** Python 3.12, `typing.Protocol`, `dataclasses`, `argparse` CLI, `pytest` (pythonpath=["."]), `ruff`, `mypy --strict`. `gh` CLI wrapped via module-level `run_gh`/`run_gh_raw`/`run_graphql`.

**Issue:** #314. Parent epic: #313. Spec: `docs/superpowers/specs/2026-06-02-board-provider-abstraction-design.md`.

---

## The test invariant (read before starting any task)

Measured 2026-06-02: **576 test functions across 45 files. 20 files exercise behavior through the CLI (`import_cli` → `main(argv)` → patched `gh`). Only 5 files call `Board` internals directly.**

Two test kinds, treated differently:

- **Contract/behavior tests (SACRED — stay green and UNTOUCHED).** The 20 CLI files: `test_cmd_*.py`, `test_cli.py`, `test_sweep_checks.py`, `test_stage.py`, `test_archive_plan.py`, `test_board_open_items.py`, `test_normalize_priority.py`. They assert observable outcomes via patched `gh`. Because every rewritten `_cmd_*` routes its semantic provider call down to the **same** module-level `run_gh*` with the **same** gh arguments, these pass unchanged. **This is the behavior-preservation proof. If one of these needs editing, STOP and surface it — that is a behavior change in disguise.**
- **Internal-structure tests (update the CALL only — never the outcome assertion).** Exactly 5 files reference `Board` internals: `test_board.py`, `test_board_open_items.py`, `test_board_fetch_for_ties.py`, `test_cache.py`, `test_sweep_checks.py`. When a method is renamed/neutralized, update how these *call* it (method name, return shape). **Never change what they assert happened.** (Note `test_board_open_items.py`/`test_sweep_checks.py` appear in both lists — touch only their internal-call lines, leave their outcome assertions alone.)

**Per-task gate (refactor discipline, not TDD ceremony):** this code is already tested. After each slice, the gate is:
```bash
source .venv/bin/activate
pytest -m 'not integration' -q && ruff check . && mypy
ruff format --check $(git diff --name-only main; git diff --name-only --cached) 2>/dev/null   # only files this work touched
```
Expected: all green. Commit only when green. **Note:** `ruff format --check .` over the *whole tree* trips on `tests/test_stage.py`, which is unformatted on `main` itself (pre-existing, out of scope for #314 — do not reformat it). Only assert format-cleanliness on files this phase touches.

**Dual-import gotcha (CLAUDE.md):** `from skills.jared.scripts.lib.board import Board` (tests) and `from lib.board import Board` (CLI) are two module objects. Keep `run_gh`/`run_gh_raw`/`run_graphql` as **module-level** functions in `board.py` (they already are, at lines 830/1120/1554); the provider calls *through* them, so `conftest`'s subprocess patching is unaffected. New files import them as `from .board import run_gh, run_gh_raw, run_graphql`.

---

## File structure

- Create `skills/jared/scripts/lib/board_provider.py` — the neutral contract: `Capability` enum, `IssueRef` alias, dataclasses (`BoardItem`, `Comment`, `Edge`, `Milestone`, `TieCandidate`), `BoardProvider` Protocol. No `gh` imports — pure types.
- Create `skills/jared/scripts/lib/github_provider.py` — `GitHubProjectsProvider` implementing `BoardProvider`. Holds parsed config + private `gh`/GraphQL logic relocated from `board.py`.
- Create `tests/test_github_provider.py` — new unit tests for the provider (new tests are additive, not edits to existing ones).
- Modify `skills/jared/scripts/lib/board.py` — strip relocated gh-methods; keep parsing/config; add `.provider` + backend selector.
- Modify `skills/jared/scripts/jared` — rewrite each `_cmd_*` to call provider methods.
- Modify `skills/jared/scripts/{sweep,dependency-graph,capture-context}.py` — route through provider methods.
- Update (calls only) the 5 internal-structure test files.

---

## Task 1: Scaffold the neutral contract

**Files:**
- Create: `skills/jared/scripts/lib/board_provider.py`

- [ ] **Step 1: Write the contract module**

```python
"""Backend-neutral board contract. No gh/GraphQL imports — pure types.

A BoardProvider stewards one board on one backend. The interface speaks only
the stable integer handle (IssueRef) and these dataclasses; provider-internal
IDs (GitHub node-ids, KanbanFlow _id) never cross this boundary.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Protocol, runtime_checkable

# The stable, human-facing handle. GitHub: issue number. KanbanFlow: task number.value.
IssueRef = int


class Capability(Enum):
    """Backend feature-support flags. Commands branch on these (Phase 6)."""

    MILESTONE_STATE = "milestone_state"          # open/close + due dates
    VELOCITY_TIMESTAMPS = "velocity_timestamps"  # created/closed/transition times
    NATIVE_DEPENDENCIES = "native_dependencies"  # real edge vs label-marker emulation
    MARKDOWN_BODY = "markdown_body"
    CLOSED_STATE = "closed_state"
    MCP_TIER = "mcp_tier"
    SUB_ISSUES = "sub_issues"


@dataclass
class BoardItem:
    number: int
    title: str
    status: str | None
    priority: str | None
    body: str = ""
    labels: list[str] = field(default_factory=list)
    milestone: str | None = None
    blocked_by: list[int] = field(default_factory=list)
    assignee: str | None = None
    fields: dict[str, str] = field(default_factory=dict)  # custom single-selects


@dataclass
class Comment:
    body: str
    author: str
    created_at: str


@dataclass
class Edge:
    dependent: int
    blocker: int


@dataclass
class Milestone:
    name: str
    description: str = ""
    state: str | None = None   # open/closed; None on backends without the concept
    due: str | None = None


@dataclass
class TieCandidate:
    number: int
    title: str
    body: str
    labels: list[str] = field(default_factory=list)
    milestone: str | None = None


@runtime_checkable
class BoardProvider(Protocol):
    # --- reads ---
    def get_item(self, ref: IssueRef) -> BoardItem | None: ...
    def list_open_items(self) -> list[BoardItem]: ...
    def get_body(self, ref: IssueRef) -> str: ...
    def list_comments(self, ref: IssueRef) -> list[Comment]: ...
    def fetch_ties(self, *, include_bodies: bool = True) -> list[TieCandidate]: ...
    def fetch_blocked_by_edges(self) -> list[Edge]: ...

    # --- writes ---
    def file(
        self,
        *,
        title: str,
        body: str,
        priority: str,
        status: str,
        labels: list[str] | None = None,
        milestone: str | None = None,
        fields: list[tuple[str, str]] | None = None,
    ) -> BoardItem: ...
    def add_to_board(
        self,
        ref: IssueRef,
        *,
        priority: str,
        status: str,
        labels: list[str] | None = None,
        fields: list[tuple[str, str]] | None = None,
    ) -> None: ...
    def set_field(self, ref: IssueRef, field_name: str, value: str) -> None: ...
    def move(self, ref: IssueRef, status: str) -> None: ...
    def close(self, ref: IssueRef, *, comment: str | None = None) -> None: ...
    def set_body(self, ref: IssueRef, text: str) -> None: ...
    def comment(self, ref: IssueRef, body: str) -> None: ...
    def add_label(self, ref: IssueRef, name: str) -> None: ...
    def remove_label(self, ref: IssueRef, name: str) -> None: ...
    def add_blocked_by(self, ref: IssueRef, blocker: IssueRef) -> None: ...
    def remove_blocked_by(self, ref: IssueRef, blocker: IssueRef) -> None: ...
    def set_milestone(self, ref: IssueRef, name: str) -> None: ...
    def list_milestones(self) -> list[Milestone]: ...

    # --- introspection ---
    def capabilities(self) -> frozenset[Capability]: ...
```

- [ ] **Step 2: Run the gate**

```bash
source .venv/bin/activate
pytest -m 'not integration' -q && ruff check . && mypy
```
Expected: PASS (new module imports cleanly; no consumer yet, so suite is unchanged).

- [ ] **Step 3: Commit**

```bash
git add skills/jared/scripts/lib/board_provider.py
git commit -m "feat(board): backend-neutral BoardProvider contract (Phase 1.1, #314)"
```

---

## Task 2: GitHubProjectsProvider scaffold + capabilities

**Files:**
- Create: `skills/jared/scripts/lib/github_provider.py`
- Create: `tests/test_github_provider.py`

The provider holds the parsed GitHub config (formerly fields on `Board`) and exposes `capabilities()`. Read/write methods are filled in Tasks 3–4; for now they raise `NotImplementedError` so the class is importable and type-checks.

- [ ] **Step 1: Write the provider skeleton**

```python
"""GitHubProjectsProvider — BoardProvider over GitHub Projects v2 + Issues.

All gh/GraphQL/field-id/option-id logic is private here. Calls flow through
board.py's module-level run_gh/run_gh_raw/run_graphql so conftest's subprocess
patching is preserved.
"""

from __future__ import annotations

from .board_provider import (
    BoardItem,
    Capability,
    Comment,
    Edge,
    IssueRef,
    Milestone,
    TieCandidate,
)


class GitHubProjectsProvider:
    def __init__(
        self,
        *,
        project_number: int,
        project_id: str,
        owner: str,
        repo: str,
        field_ids: dict[str, str],
        field_options: dict[str, dict[str, str]],
    ) -> None:
        self.project_number = project_number
        self.project_id = project_id
        self.owner = owner
        self.repo = repo
        self._field_ids = field_ids
        self._field_options = field_options
        self._items: list[dict[str, object]] | None = None

    _CAPABILITIES = frozenset(Capability)  # GitHub advertises the full set

    def capabilities(self) -> frozenset[Capability]:
        return self._CAPABILITIES

    # reads/writes implemented in Tasks 3–4
    def get_item(self, ref: IssueRef) -> BoardItem | None: raise NotImplementedError
    def list_open_items(self) -> list[BoardItem]: raise NotImplementedError
    def get_body(self, ref: IssueRef) -> str: raise NotImplementedError
    def list_comments(self, ref: IssueRef) -> list[Comment]: raise NotImplementedError
    def fetch_ties(self, *, include_bodies: bool = True) -> list[TieCandidate]: raise NotImplementedError
    def fetch_blocked_by_edges(self) -> list[Edge]: raise NotImplementedError
    def file(self, *, title, body, priority, status, labels=None, milestone=None, fields=None) -> BoardItem: raise NotImplementedError
    def add_to_board(self, ref, *, priority, status, labels=None, fields=None) -> None: raise NotImplementedError
    def set_field(self, ref: IssueRef, field_name: str, value: str) -> None: raise NotImplementedError
    def move(self, ref: IssueRef, status: str) -> None: raise NotImplementedError
    def close(self, ref: IssueRef, *, comment: str | None = None) -> None: raise NotImplementedError
    def set_body(self, ref: IssueRef, text: str) -> None: raise NotImplementedError
    def comment(self, ref: IssueRef, body: str) -> None: raise NotImplementedError
    def add_label(self, ref: IssueRef, name: str) -> None: raise NotImplementedError
    def remove_label(self, ref: IssueRef, name: str) -> None: raise NotImplementedError
    def add_blocked_by(self, ref: IssueRef, blocker: IssueRef) -> None: raise NotImplementedError
    def remove_blocked_by(self, ref: IssueRef, blocker: IssueRef) -> None: raise NotImplementedError
    def set_milestone(self, ref: IssueRef, name: str) -> None: raise NotImplementedError
    def list_milestones(self) -> list[Milestone]: raise NotImplementedError
```

- [ ] **Step 2: Write the structural conformance + capabilities test**

```python
from skills.jared.scripts.lib.board_provider import BoardProvider, Capability
from skills.jared.scripts.lib.github_provider import GitHubProjectsProvider


def _provider() -> GitHubProjectsProvider:
    return GitHubProjectsProvider(
        project_number=4, project_id="PVT_x", owner="o", repo="o/r",
        field_ids={"Status": "F1", "Priority": "F2"},
        field_options={"Status": {"Done": "D"}, "Priority": {"High": "H"}},
    )


def test_github_provider_satisfies_protocol():
    assert isinstance(_provider(), BoardProvider)


def test_github_provider_advertises_full_capability_set():
    assert _provider().capabilities() == frozenset(Capability)
```

- [ ] **Step 3: Run the gate** (command as in Task 1 Step 2). Expected: PASS — the two new tests included.

- [ ] **Step 4: Commit**

```bash
git add skills/jared/scripts/lib/github_provider.py tests/test_github_provider.py
git commit -m "feat(board): GitHubProjectsProvider scaffold + capabilities (Phase 1.2, #314)"
```

---

## Task 3: Relocate read methods into the provider

Move the read logic from `board.py` into `github_provider.py`, adapting return types to the neutral dataclasses. **Relocate, do not rewrite** — preserve the exact gh calls and GraphQL queries.

**Files:**
- Modify: `skills/jared/scripts/lib/github_provider.py`
- Reference (source of relocated logic): `board.py` — `board_items` (395), `open_items` (491), `fetch_item_for_issue` (570), `find_item_id` (591), `fetch_open_issues_for_ties` (729), and module funcs `fetch_blocked_by_edges` (1181), `fetch_recent_comments_batch` (1397), `fetch_issue_body_rest` (981), `_flatten_project_item_for_project` (1319).
- Test: `tests/test_github_provider.py`

Method-by-method relocation map (each keeps its current gh/GraphQL body; only the return is mapped to a dataclass):

| Provider method | Relocate from | Return mapping |
|---|---|---|
| `list_open_items()` | `Board.open_items()` + `_flatten_project_item_for_project` | each dict → `BoardItem` (number, title, status, priority, labels, milestone, blocked_by, fields) |
| `get_item(ref)` | `Board.fetch_item_for_issue()` + flatten | dict → `BoardItem` or `None` |
| `get_body(ref)` | module `fetch_issue_body_rest(self.repo, ref)` | str (unchanged) |
| `list_comments(ref)` | module `fetch_recent_comments_batch([ref])` | each → `Comment(body, author, created_at)` |
| `fetch_ties(include_bodies=)` | `Board.fetch_open_issues_for_ties()` | each `OpenIssueForTies` → `TieCandidate` |
| `fetch_blocked_by_edges()` | module `fetch_blocked_by_edges(self.repo, ...)` | each → `Edge(dependent, blocker)` |

- [ ] **Step 1:** For each row, implement the provider method by calling the same underlying gh/GraphQL helper (import module funcs from `.board`; copy the `Board`-method bodies that used `self._field_*`, now `self._field_*` on the provider), then convert the dict/`OpenIssueForTies` result into the dataclass. Keep `field_id`/`option_id` as private helpers on the provider (copy from `board.py:340-355`).

- [ ] **Step 2: Add provider read tests** — mirror the assertions in `tests/test_board_open_items.py` and `tests/test_board_fetch_for_ties.py` but against the provider and the dataclass shape (route gh via `patch_gh_by_arg`; see `tests/conftest.py`). Assert the same observable data, now on `BoardItem`/`TieCandidate`.

- [ ] **Step 3: Run the gate.** Expected: PASS. (Existing `test_board_*` still pass — `Board` read methods are still present this task; they are removed in Task 8.)

- [ ] **Step 4: Commit** `feat(board): provider read methods (Phase 1.3, #314)`

---

## Task 4: Relocate write methods into the provider

Move write logic; **preserve identical gh arguments and GraphQL mutation text** — this is what keeps the contract tests green later.

**Files:**
- Modify: `skills/jared/scripts/lib/github_provider.py`
- Reference: `board.py` — `add_existing_to_board` (653), `_add_to_board` (605); `jared` CLI — `_cmd_file` (521), `_cmd_set` (863), `_cmd_close` (464), `_cmd_comment` (829), `_cmd_blocked_by` (797); module `_add_to_board`, milestone via `gh api`/`gh issue edit`.

Method relocation map:

| Provider method | Relocate from | Notes |
|---|---|---|
| `add_to_board(ref, ...)` | `Board.add_existing_to_board(assume_new=False)` | drop the returned item_id (interface returns None) |
| `file(...)` | `_cmd_file`'s `gh issue create` + `add_existing_to_board(assume_new=True)` + milestone assignment | returns `BoardItem` for the new issue (number parsed from create URL) |
| `set_field(ref, name, value)` | the single aliased `updateProjectV2ItemFieldValue` in `_cmd_set` | resolves `field_id(name)`/`option_id(name, value)` internally |
| `move(ref, status)` | `set_field(ref, "Status", status)` | one-liner delegate |
| `close(ref, comment=)` | `_cmd_close` (optional comment → `gh issue close` → poll auto-move → fallback `set_field("Status","Done")`) | preserve the verify-and-fallback exactly |
| `set_body(ref, text)` | `capture-context.py`'s `gh api PATCH /repos/{repo}/issues/{ref}` body write | |
| `comment(ref, body)` | `_cmd_comment`'s `gh issue comment` | PII pre-flight stays in the CLI layer, above the provider |
| `add_label`/`remove_label` | `gh issue edit --add-label/--remove-label` | idempotent |
| `add_blocked_by`/`remove_blocked_by` | `_cmd_blocked_by`'s `addBlockedBy`/`removeBlockedBy` GraphQL (resolve node-ids first) | |
| `set_milestone(ref, name)` | `gh issue edit --milestone` (validate against open milestones) | |
| `list_milestones()` | `gh api /repos/{repo}/milestones?state=open` (cached 5m) | each → `Milestone` |

- [ ] **Step 1:** Implement each method per the map. The aliased-mutation builder from `add_existing_to_board` (board.py:708-725) is the template for `set_field` (single alias) and `add_to_board`/`file` (multi alias). Interpolate `self.project_id`/`self._field_*` exactly as today.

- [ ] **Step 2: Add provider write tests** routing gh via `patch_gh_by_arg`; assert the gh argv produced matches today's (e.g. `set_field` emits one `updateProjectV2ItemFieldValue` with the resolved ids). Reuse argv assertions from `tests/test_cmd_set.py`/`test_cmd_file.py` as the oracle.

- [ ] **Step 3: Run the gate.** Expected: PASS.

- [ ] **Step 4: Commit** `feat(board): provider write methods (Phase 1.4, #314)`

---

## Task 5: Board facade + backend selector

**Files:**
- Modify: `skills/jared/scripts/lib/board.py` (add, do not yet remove)
- Test: `tests/test_board.py` (add a new test; do not edit existing assertions)

- [ ] **Step 1:** Add a `backend: str = "github"` field to the `Board` dataclass (default keeps every existing board GitHub). Parse an optional `- backend: kanbanflow` bullet from the `## Jared config` block in `_parse_jared_config` (board.py:247) — absent → `"github"`.

- [ ] **Step 2:** Add a cached `provider` property:

```python
@property
def provider(self) -> GitHubProjectsProvider:
    if self.backend != "github":
        raise BoardConfigError(
            f"backend '{self.backend}' has no provider yet (Phase 3+). "
            "Only 'github' is implemented."
        )
    if self._provider is None:
        from .github_provider import GitHubProjectsProvider
        self._provider = GitHubProjectsProvider(
            project_number=self.project_number, project_id=self.project_id,
            owner=self.owner, repo=self.repo,
            field_ids=self._field_ids, field_options=self._field_options,
        )
    return self._provider
```
Add `_provider: GitHubProjectsProvider | None = field(default=None, repr=False)` to the dataclass.

- [ ] **Step 3:** New test in `tests/test_board.py`: a `Board` built from a github-default doc returns a `GitHubProjectsProvider` whose `capabilities()` is the full set; a doc with `- backend: kanbanflow` raises `BoardConfigError` on `.provider`.

- [ ] **Step 4: Run the gate.** Expected: PASS. **Step 5: Commit** `feat(board): Board facade exposes provider + backend selector (Phase 1.5, #314)`

---

## Task 6: Migrate `_cmd_*` consumers to the provider

**Files:**
- Modify: `skills/jared/scripts/jared`
- Tests: the 20 CLI contract files — **run, do not edit.**

Rewrite each subcommand to call provider methods via `board.provider`, deleting inline `board.run_gh`/`field_id`/`option_id`/`run_graphql` mutation-building. **Invariant: the gh argv/GraphQL text the provider emits must be byte-for-byte what the command emitted before** (that is why the contract tests pass untouched).

Migration map (rewrite → run the named contract test):

| Subcommand | New call | Contract test (must stay green, untouched) |
|---|---|---|
| `_cmd_get_item` | `board.provider.get_item(n)` | `test_cmd_get_item.py` |
| `_cmd_summary` | `board.provider.list_open_items()` | `test_cmd_summary.py` |
| `_cmd_set` | `board.provider.set_field(n, field, value)` | `test_cmd_set.py` |
| `_cmd_move` | `board.provider.move(n, status)` | `test_cmd_move.py` |
| `_cmd_close` | `board.provider.close(n, comment=...)` | `test_cmd_close.py` |
| `_cmd_comment` | `board.provider.comment(n, body)` (keep PII pre-flight above) | `test_cmd_comment.py` |
| `_cmd_file` | `board.provider.file(...)` | `test_cmd_file.py` |
| `_cmd_add_to_board` | `board.provider.add_to_board(n, ...)` | `test_cmd_add_to_board.py` |
| `_cmd_blocked_by` | `board.provider.add_blocked_by/remove_blocked_by` | `test_cmd_blocked_by.py` |
| `_cmd_next_session_prompt` | `list_open_items()` + `list_comments()` | `test_cmd_next_session_prompt.py` |
| `_cmd_ties` | `board.provider.fetch_ties(...)` | `test_cmd_ties.py` |
| `_cmd_audit_fetch` | `list_open_items()` + `list_milestones()` (+ velocity stays a module fn) | `test_cmd_audit.py` |

- [ ] **Step 1:** Migrate one subcommand. **Step 2:** Run its contract test:
```bash
source .venv/bin/activate && pytest tests/test_cmd_<name>.py -q
```
Expected: PASS, with **zero edits** to that test file. If it fails, the provider is emitting different gh args — fix the provider, not the test. If the test *asserts* a different outcome that you believe is now correct, STOP and surface it.
- [ ] **Step 3:** Repeat Steps 1–2 for every row. **Step 4:** Full gate. **Step 5:** Commit `refactor(cli): route _cmd_* through BoardProvider (Phase 1.6, #314)` (or one commit per subcommand for a finer phase trail).

---

## Task 7: Migrate batch-script consumers

**Files:**
- Modify: `skills/jared/scripts/sweep.py`, `dependency-graph.py`, `capture-context.py`
- Tests: `test_sweep_checks.py` (contract assertions untouched; internal-call lines updated if any)

- [ ] **Step 1:** Replace `board.open_items()`→`board.provider.list_open_items()`, `board_run_gh(...)` mutation building → provider methods, `fetch_blocked_by_edges`→`board.provider.fetch_blocked_by_edges()`, capture-context body read-modify-write → `get_body`/`set_body`. Velocity/audit module functions that are pure data-shaping may stay as module functions.
- [ ] **Step 2:** Run the gate. Expected: PASS. **Step 3:** Commit `refactor(scripts): batch scripts use BoardProvider (Phase 1.7, #314)`

---

## Task 8: Remove dead Board gh-methods; update internal-structure tests

**Files:**
- Modify: `skills/jared/scripts/lib/board.py` (delete relocated methods)
- Modify (calls only): `tests/test_board.py`, `tests/test_board_open_items.py`, `tests/test_board_fetch_for_ties.py`, `tests/test_cache.py`, `tests/test_sweep_checks.py`

- [ ] **Step 1:** Delete from `Board` the now-unused gh-operation methods: `board_items`, `open_items`, `invalidate_items`, `invalidate_closed_items`, `fetch_item_for_issue`, `find_item_id`, `_add_to_board`, `add_existing_to_board`, `fetch_open_issues_for_ties`, `get_issue`, `graphql_budget`, and the `Board.run_gh`/`run_gh_raw`/`run_graphql` delegators **iff** no consumer remains (grep first). Keep `field_id`/`option_id` only if still referenced; otherwise delete (they live on the provider now). **Keep** parsing, `from_*`, `tie_stop_words`, config fields, and the module-level `run_gh*` functions.
- [ ] **Step 2:** In the 5 test files, repoint internal calls to the provider (e.g. `board.open_items()` → `board.provider.list_open_items()` and assert on `BoardItem`). **Change only the call and the result-shape read — never the asserted outcome.**
- [ ] **Step 3:** Run the gate. Expected: PASS. **Step 4:** Commit `refactor(board): drop relocated gh-methods; repoint internal tests (Phase 1.8, #314)`

---

## Task 9: Fork-decision gate + final verification

**Files:**
- Reference only; may update `CLAUDE.md` if the dual-import note needs a pointer to the provider.

- [ ] **Step 1: Zero-leakage grep (the fork-decision evidence).**
```bash
grep -nE "\b(run_gh|run_gh_raw|run_graphql|field_id|option_id)\(" skills/jared/scripts/jared
```
Expected: **no matches.** Each match is either a missed migration (fix it) or irreducible GitHub entanglement — if the latter, document the exact line in the issue #314 as fork-signal evidence and discuss before closing the phase.

- [ ] **Step 2: Full verification gate.**
```bash
source .venv/bin/activate
pytest -m 'not integration' -q && ruff check . && ruff format --check . && mypy
```
Expected: all green; 576+ test functions (the added provider tests increase the count; **no contract test was edited**).

- [ ] **Step 3:** Confirm the contract net is intact:
```bash
git diff --stat main -- tests/ | grep -E "test_cmd_|test_cli|test_stage|test_archive"
```
Expected: **empty** — no CLI contract test file appears in the diff. If one does, justify it against the "behavior change in disguise" rule before proceeding.

- [ ] **Step 4: Commit** `chore(board): Phase 1 verification gate — neutral interface, zero leakage (#314)` and open the PR per the repo workflow.

---

## Documentation Impact

- `CLAUDE.md` § "The `Board` helper" and § "three-tier operations model" describe `Board` as the gh-wrapper. After this phase, add one line: board operations go through `board.provider` (a `BoardProvider`); `Board` is the config-parsing facade. (Keep it light — the deeper provider/backends story lands when Phase 3+ ships.)
- No SKILL.md / slash-command changes this phase (no observable behavior change; capability *enforcement* is Phase 6).
- Spec `docs/superpowers/specs/2026-06-02-board-provider-abstraction-design.md` is the design of record; on ship, `archive-plan.py` will prepend the shipped header and archive this plan.

## Verification gate (phase exit)

- `pytest -m 'not integration'` green, **no CLI contract test edited** (Task 9 Step 3 empty).
- `ruff check .`, `ruff format --check .`, `mypy` all clean.
- Zero-leakage grep (Task 9 Step 1) empty, or residue documented on #314 as fork-signal.
- `GitHubProjectsProvider` is the only `BoardProvider`; `Board.provider` returns it by default; `kanbanflow` backend raises a clear not-yet-implemented error.

## Self-review checklist

- [ ] Every spec acceptance criterion maps to a task (Protocol→T1; provider+private gh→T2-4; facade→T5; zero-leakage→T9; tests-green→every gate).
- [ ] No placeholder steps; new-artifact code is complete; migration steps name exact source locations and the contract test that guards each.
- [ ] Method/type names consistent across tasks (`set_field`, `list_open_items`, `BoardItem`, `Capability`, `IssueRef`).
- [ ] The sacred-contract-tests invariant is restated where it bites (Tasks 6, 8, 9).
