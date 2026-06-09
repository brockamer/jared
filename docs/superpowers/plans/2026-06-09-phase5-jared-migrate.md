# `jared migrate` Between Backends — Implementation Plan (Phase 5)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

## Issue: #318

**Goal:** Add a one-shot, operator-confirmed `jared migrate` command that copies a project's board from its current backend (GitHub Projects v2 or KanbanFlow) to the other, surfacing every named, accepted loss before the first write.

**Architecture:** A pure translation core (`lib/migrate.py`) computes the lossiness report, the old→new number map, edge/cross-ref translation, and a KanbanFlow call-count estimate from plain `BoardItem`/`Edge`/`Comment` dataclasses plus the two backends' `capabilities()` sets — no provider internals. A thin CLI handler (`_cmd_migrate`) wires a *source* provider (the project's configured backend) and a *target* provider (`Board.from_path(--target-doc).provider`) into a read → report → confirm → write → emit-artifact pipeline. Dry-run is the default; `--apply` performs writes; a resume ledger makes a partial run safe to re-run.

**Tech Stack:** Python 3.14, stdlib only; argparse CLI; existing `BoardProvider` contract; `gh` (GitHub) / KanbanFlow REST client (already shipped). Tests: `pytest` (offline unit), `ruff`, `mypy --strict`. One live round-trip against a real KanbanFlow board for acceptance.

> **Environment (worktree).** This work runs in the session-2 worktree `/home/brockamer/Code/jared-318`, which has **no `.venv`** (it's gitignored and lives only in the main repo). Every command below uses the main repo's venv binaries while keeping CWD in the worktree: `cd /home/brockamer/Code/jared-318 && /home/brockamer/Code/jared/.venv/bin/python -m pytest …`. With CWD in the worktree, pytest's `pythonpath=["."]` puts the worktree root first, so the code under test is the worktree's — which also avoids the main-repo-import pitfall where invoking `skills/jared/scripts/jared` would load the main repo's `lib/`.

---

## Resolved design decisions (operator-ratified 2026-06-09)

These settle the 7 open questions in the spec (`docs/superpowers/specs/2026-06-09-phase5-jared-migrate-design.md`). They are the authority for this plan.

1. **Closed history:** live-board-only by default; `--include-closed` opt-in.
2. **Cross-ref rewrite:** **auto-rewrite** `#N` references in bodies and comments via the number map, guarded so only numbers that are *keys in the map* (i.e. genuinely migrated issues) are rewritten.
3. **Resumability:** **yes** — a durable resume ledger (the `--out` artifact doubles as it); a re-run skips already-created items idempotently. No hard size ceiling.
4. **Backend selector:** **flip `docs/project-board.md` to the target on success** (after a successful `--apply`), reusing the init-time doc writer.
5. **Target identity:** **inline flag** `--target-doc PATH`, a convention doc produced by running `jared init` against the target backend (reuses #317 plumbing). Refuse if the target backend equals the source.
6. **Comment author attribution (GH→KF):** **prepend** `(originally @<author>, <date>)` into the comment text.
7. **Comment portage:** **bundle** the `list_comments()` contract extension here (Phase 0). Additive to `board_provider.py` + both providers. If it bloats the PR, it may split to a follow-up issue — but it is **not** scoped out.

## OPEN design-tension — `#N` preservation on GH→KF (Phase 3 gate; do NOT implement Phase 3.1 until resolved)

`KanbanFlowProvider.file()` hardcodes `number = self._next_number()` and takes **no** `number` argument — it never threads a caller-supplied number to `create_task(number_value=…)` (which the *client* supports). So the headline acceptance criterion "GH→KF preserves every `#N` exactly" is **not** achievable through the current contract. Migrating sparse GitHub numbers (#299, #301, #318…) would silently reassign them 1, 2, 3… and `add_blocked_by` (which writes `blocked-by:<N>` labels) would then point at wrong numbers.

Two ways out — **operator decides before Phase 3.1**:

- **(a) Extend the contract:** add `number: int | None = None` to `BoardProvider.file()`. `KanbanFlowProvider` threads it to `create_task(number_value=number or self._next_number())`; `GitHubProjectsProvider` ignores it (GitHub auto-assigns issue numbers — it *cannot* set them, and KF→GitHub renumbers regardless). Additive, default-None, no existing caller affected. **Seam consequence:** this is a **second** `board_provider.py` edit beyond `list_comments` — still additive and still collision-free with #319 *iff* #319 keeps its degradation helper out of `board_provider.py`, but session-1 must be re-told. **(Recommended** — preserves the headline goal; KF already supports it at the client layer.)
- **(b) Drop `#N`-preservation to a named loss:** GH→KF renumbers too (both directions renumber); cross-refs are rewritten via the number map in both directions. No contract change, smaller PR, but it abandons a stated spec goal and the GH→KF "lossless-number" property.

This blocks **only** Phase 3.1. Phases 0, 1, and 2 are independent of it and can proceed. Surface the decision before starting Phase 3.

## Parallel-session seam (do not violate — #319 runs concurrently in session-1)

#319 (capability-degradation) shares files with this work. The boundary, verified by the pre-pull collision analysis:

- **This plan touches `board_provider.py` additively, once — or twice if the `#N` decision picks option (a):** the `Comment` dataclass + `list_comments()` (Phase 0), plus (conditionally) a `number: int | None = None` kwarg on `file()` (Phase 3 gate). Both are additive (new symbol / new default-None kwarg). It adds **no** degradation helper and **no** note-format constant there. (#319's degradation helper must live in `board.py`/CLI, not `board_provider.py` — that constraint is what keeps these additive edits collision-free.)
- **This plan reads `target.capabilities()` directly** to compute losses. It does **not** import any #319 helper as a build dependency.
- **The translation core takes `frozenset[Capability]` arguments**, so its unit tests need **no** capability-restricted fake provider. Do **not** author a shared capability-restricted fake in `tests/conftest.py` — that artifact belongs to #319.
- **`skills/jared/scripts/jared` is the one co-edited file:** append `"migrate"` to `ALL_SUBCOMMANDS` and add the parser block + `_cmd_migrate` at the *end* of the relevant lists to keep the merge hunk small. At merge, the `ALL_SUBCOMMANDS`/parser region is a mechanical union with #319's additions.
- Append-only edits to `docs/project-board.md`, `CLAUDE.md`, `skills/jared/references/operations.md`, `CHANGELOG.md` (both sessions append distinct sections).

---

## File structure

| File | Create / Modify | Responsibility |
|------|-----------------|----------------|
| `skills/jared/scripts/lib/board_provider.py` | Modify | Add neutral `Comment` dataclass + `list_comments()` to the Protocol (additive only). |
| `skills/jared/scripts/lib/github_provider.py` | Modify | Implement `list_comments()` via `gh issue view --json comments`. |
| `skills/jared/scripts/lib/kanbanflow_provider.py` | Modify | Implement `list_comments()` (wrap the client's existing `list_comments`; resolve KF user-id → name). Add `list_users` to `KanbanFlowClientLike`. |
| `skills/jared/scripts/lib/migrate.py` | **Create** | Pure translation core: loss-axis computation, `NumberMap`, cross-ref rewrite, edge translation, call-count estimate, report rendering, resume-ledger (de)serialization. No I/O, no provider calls. |
| `skills/jared/scripts/jared` | Modify | Register `migrate` subcommand; `_cmd_migrate` orchestrates read → report → confirm → write → emit-artifact, and flips the source doc on success. |
| `tests/test_provider_comments.py` | **Create** | Unit tests for `list_comments()` on both providers. |
| `tests/test_migrate_core.py` | **Create** | Unit tests for every pure function in `lib/migrate.py`. |
| `tests/test_cmd_migrate.py` | **Create** | Dry-run + apply + resume tests through fake providers (FakeKanbanFlowClient + gh-patched GitHubProjectsProvider). |
| `docs/project-board.md`, `CLAUDE.md`, `skills/jared/references/operations.md`, `CHANGELOG.md` | Modify | Docs (Phase 7). |

Phases are independently mergeable in order. Phase 0 can ship on its own PR if the operator prefers (it is the only contract change). Phases 1–7 are the migrate feature proper.

---

## Phase 0 — Contract extension: `list_comments()`

**Why first:** the pipeline's comment-portage step needs a comment-*read* method; the shipped contract has only write-side `comment()`. This is the only `board_provider.py` edit — additive, seam-safe.

### Task 0.1: Neutral `Comment` dataclass + Protocol method

**Files:**
- Modify: `skills/jared/scripts/lib/board_provider.py`

- [ ] **Step 1: Add the dataclass and Protocol method.** After the `ClosedItem` dataclass (around line 80), add:

```python
@dataclass
class Comment:
    """A single comment/session-note, in neutral terms.

    `author` is the GitHub login or the KanbanFlow user's display name ("" if
    unresolved). `created_at` is an opaque timestamp string (ISO 8601 on both
    backends); the interface promises nothing about its format beyond
    lexicographic sortability — callers sort/slice, never parse it (same
    contract as ClosedItem.closed_at).
    """

    author: str
    body: str
    created_at: str
```

In the `BoardProvider` Protocol, under `# --- reads ---`, add after `recently_closed`:

```python
    def list_comments(self, ref: IssueRef) -> list[Comment]: ...
```

- [ ] **Step 2: Verify it imports and type-checks.**

Run: `cd /home/brockamer/Code/jared-318 && /home/brockamer/Code/jared/.venv/bin/python -c "from skills.jared.scripts.lib.board_provider import Comment, BoardProvider; print(Comment(author='a', body='b', created_at='c'))"`
Expected: `Comment(author='a', body='b', created_at='c')`

- [ ] **Step 3: Commit.**

```bash
git add skills/jared/scripts/lib/board_provider.py
git commit -m "feat(318): add neutral Comment + list_comments to BoardProvider contract (Phase 0.1)"
```

### Task 0.2: GitHub `list_comments()` (TDD)

**Files:**
- Modify: `skills/jared/scripts/lib/github_provider.py`
- Test: `tests/test_provider_comments.py`

- [ ] **Step 1: Write the failing test.** Create `tests/test_provider_comments.py`:

```python
from __future__ import annotations

import pytest

from skills.jared.scripts.lib.board_provider import Comment
from skills.jared.scripts.lib.github_provider import GitHubProjectsProvider
from tests.conftest import patch_gh


def _gh_provider() -> GitHubProjectsProvider:
    return GitHubProjectsProvider(
        project_number=7,
        project_id="PVT_x",
        owner="brockamer",
        repo="brockamer/jared",
        field_ids={},
        field_options={},
    )


def test_github_list_comments_maps_author_body_created(monkeypatch: pytest.MonkeyPatch) -> None:
    patch_gh(
        monkeypatch,
        stdout=(
            '{"comments": ['
            '{"author": {"login": "brockamer"}, "body": "first", "createdAt": "2026-06-01T00:00:00Z"},'
            '{"author": {"login": "octocat"}, "body": "second", "createdAt": "2026-06-02T00:00:00Z"}'
            "]}"
        ),
    )
    comments = _gh_provider().list_comments(318)
    assert comments == [
        Comment(author="brockamer", body="first", created_at="2026-06-01T00:00:00Z"),
        Comment(author="octocat", body="second", created_at="2026-06-02T00:00:00Z"),
    ]


def test_github_list_comments_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    patch_gh(monkeypatch, stdout='{"comments": []}')
    assert _gh_provider().list_comments(318) == []
```

- [ ] **Step 2: Run it to confirm it fails.**

Run: `cd /home/brockamer/Code/jared-318 && /home/brockamer/Code/jared/.venv/bin/python -m pytest tests/test_provider_comments.py -q`
Expected: FAIL — `AttributeError: 'GitHubProjectsProvider' object has no attribute 'list_comments'`

- [ ] **Step 3: Implement.** In `github_provider.py`, add `Comment` to the `board_provider` import block, then add this method in the READ section (after `fetch_blocked_by_edges`):

```python
    def list_comments(self, ref: IssueRef) -> list[Comment]:
        """Return an issue's comments oldest→newest as neutral Comments.

        Uses `gh issue view <n> --json comments`, which returns each comment's
        author.login, body (markdown), and createdAt. The GitHub-camelCase
        `createdAt` is mapped to Comment.created_at here so it never crosses
        the neutral boundary.
        """
        data = run_gh(["issue", "view", str(ref), "--repo", self.repo, "--json", "comments"])
        raw = data.get("comments", []) if isinstance(data, dict) else []
        return [
            Comment(
                author=str((c.get("author") or {}).get("login") or ""),
                body=str(c.get("body", "")),
                created_at=str(c.get("createdAt") or ""),
            )
            for c in raw
        ]
```

- [ ] **Step 4: Run the test to confirm it passes.**

Run: `cd /home/brockamer/Code/jared-318 && /home/brockamer/Code/jared/.venv/bin/python -m pytest tests/test_provider_comments.py -q`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit.**

```bash
git add skills/jared/scripts/lib/github_provider.py tests/test_provider_comments.py
git commit -m "feat(318): GitHubProjectsProvider.list_comments via gh issue view (Phase 0.2)"
```

### Task 0.3: KanbanFlow `list_comments()` (TDD)

**Files:**
- Modify: `skills/jared/scripts/lib/kanbanflow_provider.py`
- Test: `tests/test_provider_comments.py` (append)

The KanbanFlow *client* already has `list_comments(task_id) -> list[KfComment]` and `list_users()`. `KfComment.author_user_id` is a KF user id; resolve it to a display name via a lazily-built users map. Add `list_users` to the `KanbanFlowClientLike` Protocol so the fake satisfies it.

- [ ] **Step 1: Write the failing test.** Append to `tests/test_provider_comments.py`:

```python
from tests.fake_kanbanflow import make_kf_provider_with_task  # helper added in Step 3 if absent


def test_kanbanflow_list_comments_resolves_author_name() -> None:
    provider, client, ref = make_kf_provider_with_task(
        users={"u1": "Daniel Brock"},
        comments=[
            {"text": "note one", "createdTimestamp": "2026-06-01T00:00:00Z", "authorUserId": "u1"},
        ],
    )
    comments = provider.list_comments(ref)
    assert comments == [Comment(author="Daniel Brock", body="note one", created_at="2026-06-01T00:00:00Z")]
```

> If `tests/fake_kanbanflow.py` does not already expose a constructor that yields a `(provider, client, ref)` triple with seeded comments/users, add a small `make_kf_provider_with_task(*, users, comments)` helper there in this step (it lives in the existing fake module, **not** in `conftest.py`, to respect the #319 seam). Mirror the construction used by `tests/test_kanbanflow_provider.py`.

- [ ] **Step 2: Run it to confirm it fails.**

Run: `cd /home/brockamer/Code/jared-318 && /home/brockamer/Code/jared/.venv/bin/python -m pytest tests/test_provider_comments.py -k kanbanflow -q`
Expected: FAIL — `AttributeError: 'KanbanFlowProvider' object has no attribute 'list_comments'`

- [ ] **Step 3: Implement.** In `kanbanflow_provider.py`:
  - Add `Comment` to the `board_provider` import.
  - Add `list_users` + `list_comments` to the `KanbanFlowClientLike` Protocol:

```python
    def list_users(self) -> list[KfUser]: ...
    def list_comments(self, task_id: str) -> list[KfComment]: ...
```
  (import `KfComment, KfUser` from `.kanbanflow_client`.)
  - Add a lazily-cached user map and the method on `KanbanFlowProvider`:

```python
    def _user_name(self, user_id: str) -> str:
        if not hasattr(self, "_user_name_by_id"):
            self._user_name_by_id = {u.id: u.name for u in self._client.list_users()}
        return self._user_name_by_id.get(user_id, user_id)

    def list_comments(self, ref: IssueRef) -> list[Comment]:
        """Return a task's comments oldest→newest as neutral Comments.

        Wraps the client's list_comments; resolves KF authorUserId to a display
        name (lazily, one /users fetch per provider instance). Falls back to the
        raw id if the user is unknown.
        """
        task_id = self._resolve_id(ref)
        return [
            Comment(
                author=self._user_name(c.author_user_id) if c.author_user_id else "",
                body=c.text,
                created_at=c.created_timestamp,
            )
            for c in self._client.list_comments(task_id)
        ]
```

- [ ] **Step 4: Run the test to confirm it passes.**

Run: `cd /home/brockamer/Code/jared-318 && /home/brockamer/Code/jared/.venv/bin/python -m pytest tests/test_provider_comments.py -q`
Expected: PASS (3 passed)

- [ ] **Step 5: Gate + commit.**

Run: `cd /home/brockamer/Code/jared-318 && /home/brockamer/Code/jared/.venv/bin/ruff check . && /home/brockamer/Code/jared/.venv/bin/ruff format --check . && /home/brockamer/Code/jared/.venv/bin/mypy && /home/brockamer/Code/jared/.venv/bin/python -m pytest -q`
Expected: all clean, full suite green.

```bash
git add skills/jared/scripts/lib/kanbanflow_provider.py tests/test_provider_comments.py tests/fake_kanbanflow.py
git commit -m "feat(318): KanbanFlowProvider.list_comments with author-name resolution (Phase 0.3)"
```

---

## Phase 1 — Translation core (`lib/migrate.py`, pure)

Every function here is pure: it takes dataclasses + capability sets and returns dataclasses/strings. No provider, no I/O. This is where the lossiness model, number map, cross-ref rewrite, edge translation, call estimate, and resume ledger live and get exhaustively unit-tested.

### Task 1.1: Loss-axis model + `compute_loss_axes` (TDD)

**Files:**
- Create: `skills/jared/scripts/lib/migrate.py`
- Test: `tests/test_migrate_core.py`

The loss axes are frozen in Appendix A of the Phase-1 spec (`docs/superpowers/specs/2026-06-02-board-provider-abstraction-design.md`). They are computed from the *difference* between source and target `capabilities()` plus structural facts of the direction.

- [ ] **Step 1: Write the failing test.** Create `tests/test_migrate_core.py`:

```python
from __future__ import annotations

from skills.jared.scripts.lib.board_provider import Capability
from skills.jared.scripts.lib.migrate import LossAxis, compute_loss_axes

_FULL = frozenset(Capability)
_NONE: frozenset[Capability] = frozenset()


def test_github_to_kanbanflow_loss_axes() -> None:
    axes = compute_loss_axes(source_caps=_FULL, target_caps=_NONE, direction="github->kanbanflow")
    keys = {a.key for a in axes}
    # Capabilities present at source but absent at target each become a loss.
    assert "native_dependencies" in keys  # edges -> blocked-by:<N> label markers
    assert "milestone_state" in keys       # due-date + open/close dropped
    assert "closed_state" in keys
    assert "markdown_body" in keys
    # Renumber is NOT a loss in this direction (GH->KF preserves #N).
    assert "renumber" not in keys
    assert all(isinstance(a, LossAxis) and a.description for a in axes)


def test_kanbanflow_to_github_adds_renumber_axis() -> None:
    axes = compute_loss_axes(source_caps=_NONE, target_caps=_FULL, direction="kanbanflow->github")
    keys = {a.key for a in axes}
    # KF->GitHub renumbers (GitHub auto-assigns), so cross-refs need rewriting.
    assert "renumber" in keys
    # Capabilities the target ADDS are not losses.
    assert "milestone_state" not in keys
```

- [ ] **Step 2: Run it to confirm it fails.**

Run: `cd /home/brockamer/Code/jared-318 && /home/brockamer/Code/jared/.venv/bin/python -m pytest tests/test_migrate_core.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'skills.jared.scripts.lib.migrate'`

- [ ] **Step 3: Implement the core skeleton + `compute_loss_axes`.** Create `skills/jared/scripts/lib/migrate.py`:

```python
"""Pure translation core for `jared migrate` (Phase 5, #318).

No I/O, no provider calls. Functions take neutral dataclasses (BoardItem, Edge,
Comment, Milestone) and the two backends' capability sets, and return
dataclasses/strings the CLI orchestrator (`_cmd_migrate`) applies. The lossiness
model is anchored to Appendix A of the Phase-1 board-provider spec.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .board_provider import Capability, Edge

Direction = str  # "github->kanbanflow" | "kanbanflow->github"

# Capability -> (loss key, human description) when the target LACKS it.
_CAPABILITY_LOSS = {
    Capability.NATIVE_DEPENDENCIES: (
        "native_dependencies",
        "native blocked-by edges become 'blocked-by:<N>' label markers + the Blocked column",
    ),
    Capability.MILESTONE_STATE: (
        "milestone_state",
        "milestone open/close state and due dates are dropped (swimlanes carry name + description only)",
    ),
    Capability.VELOCITY_TIMESTAMPS: (
        "velocity_timestamps",
        "created/closed/transition timestamps are not portable",
    ),
    Capability.MARKDOWN_BODY: (
        "markdown_body",
        "markdown rendering is lost (text round-trips; only rendering, not data)",
    ),
    Capability.CLOSED_STATE: (
        "closed_state",
        "no real closed state on the target (Done column only)",
    ),
    Capability.SUB_ISSUES: ("sub_issues", "sub-issue hierarchy is not portable"),
    Capability.MCP_TIER: ("mcp_tier", "MCP-tier operations are unavailable on the target"),
}


@dataclass
class LossAxis:
    key: str
    description: str
    count: int = 0  # dataset-specific magnitude (e.g. # of edges affected); 0 = N/A


def compute_loss_axes(
    *, source_caps: frozenset[Capability], target_caps: frozenset[Capability], direction: Direction
) -> list[LossAxis]:
    """Itemize every named loss for this direction.

    A capability the SOURCE has but the TARGET lacks is a loss. KF->GitHub
    additionally renumbers (#N is auto-assigned on GitHub), which is a loss axis
    even though it is not a capability difference.
    """
    axes: list[LossAxis] = []
    for cap in Capability:
        if cap in source_caps and cap not in target_caps and cap in _CAPABILITY_LOSS:
            key, desc = _CAPABILITY_LOSS[cap]
            axes.append(LossAxis(key=key, description=desc))
    if direction == "kanbanflow->github":
        axes.append(
            LossAxis(
                key="renumber",
                description="every #N is reassigned by GitHub; cross-references are rewritten via the number map",
            )
        )
    return axes
```

- [ ] **Step 4: Run the test to confirm it passes.**

Run: `cd /home/brockamer/Code/jared-318 && /home/brockamer/Code/jared/.venv/bin/python -m pytest tests/test_migrate_core.py -q`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit.**

```bash
git add skills/jared/scripts/lib/migrate.py tests/test_migrate_core.py
git commit -m "feat(318): migrate core — loss-axis model + compute_loss_axes (Phase 1.1)"
```

### Task 1.2: `NumberMap` + cross-reference rewrite (TDD)

**Files:**
- Modify: `skills/jared/scripts/lib/migrate.py`
- Test: `tests/test_migrate_core.py` (append)

The false-positive guard (Q2): only `#N` whose `N` is a **key** in the number map is rewritten. A `#1234` that wasn't migrated is left untouched.

- [ ] **Step 1: Write the failing test.** Append:

```python
from skills.jared.scripts.lib.migrate import NumberMap, rewrite_cross_refs


def test_number_map_identity_for_gh_to_kf() -> None:
    nm = NumberMap.identity([1, 2, 3])
    assert nm.to_new(2) == 2
    assert nm.keys() == {1, 2, 3}


def test_rewrite_cross_refs_only_touches_mapped_numbers() -> None:
    nm = NumberMap({10: 101, 11: 102})
    text = "Depends on #10 and #11, but #9999 is an external tracker ref."
    out = rewrite_cross_refs(text, nm)
    assert out == "Depends on #101 and #102, but #9999 is an external tracker ref."


def test_rewrite_cross_refs_is_word_boundaried() -> None:
    nm = NumberMap({1: 50})
    # '#10' must NOT be rewritten by the '#1' mapping (no partial-number match).
    assert rewrite_cross_refs("see #1 and #10", nm) == "see #50 and #10"
```

- [ ] **Step 2: Run to confirm failure.**

Run: `cd /home/brockamer/Code/jared-318 && /home/brockamer/Code/jared/.venv/bin/python -m pytest tests/test_migrate_core.py -k "number_map or cross_refs" -q`
Expected: FAIL — `ImportError: cannot import name 'NumberMap'`

- [ ] **Step 3: Implement.** Append to `migrate.py`:

```python
@dataclass
class NumberMap:
    """old #N -> new #N. Identity on GH->KF; load-bearing on KF->GitHub."""

    mapping: dict[int, int] = field(default_factory=dict)

    @classmethod
    def identity(cls, numbers: list[int]) -> NumberMap:
        return cls({n: n for n in numbers})

    def put(self, old: int, new: int) -> None:
        self.mapping[old] = new

    def to_new(self, old: int) -> int | None:
        return self.mapping.get(old)

    def keys(self) -> set[int]:
        return set(self.mapping)


_ISSUE_REF_RE = re.compile(r"#(\d+)\b")


def rewrite_cross_refs(text: str, number_map: NumberMap) -> str:
    """Rewrite '#<old>' -> '#<new>' for every old number that is a key in the map.

    Numbers absent from the map are left untouched — the false-positive guard
    for '#N' tokens that are not migrated issue refs (Q2).
    """

    def _sub(m: re.Match[str]) -> str:
        old = int(m.group(1))
        new = number_map.to_new(old)
        return f"#{new}" if new is not None else m.group(0)

    return _ISSUE_REF_RE.sub(_sub, text)
```

- [ ] **Step 4: Run to confirm pass.**

Run: `cd /home/brockamer/Code/jared-318 && /home/brockamer/Code/jared/.venv/bin/python -m pytest tests/test_migrate_core.py -q`
Expected: PASS

- [ ] **Step 5: Commit.**

```bash
git add skills/jared/scripts/lib/migrate.py tests/test_migrate_core.py
git commit -m "feat(318): migrate core — NumberMap + guarded cross-ref rewrite (Phase 1.2)"
```

### Task 1.3: Edge translation + KanbanFlow call-count estimate (TDD)

**Files:**
- Modify: `skills/jared/scripts/lib/migrate.py`
- Test: `tests/test_migrate_core.py` (append)

- [ ] **Step 1: Write the failing test.** Append:

```python
from skills.jared.scripts.lib.migrate import estimate_kf_calls, translate_edges


def test_translate_edges_through_number_map() -> None:
    nm = NumberMap({1: 101, 2: 102, 3: 103})
    edges = [Edge(dependent=2, blocker=1), Edge(dependent=3, blocker=2)]
    out = translate_edges(edges, nm)
    assert out == [Edge(dependent=102, blocker=101), Edge(dependent=103, blocker=102)]


def test_translate_edges_drops_unmapped() -> None:
    nm = NumberMap({2: 102})  # blocker 1 is unmapped
    assert translate_edges([Edge(dependent=2, blocker=1)], nm) == []


def test_estimate_kf_calls_counts_create_fields_edges_comments() -> None:
    # 2 items, each with 1 extra custom field beyond Priority; 1 edge; 3 comments.
    # create(1) + Priority(1) + extra-field(1) = 3 per item -> 6; +1 edge label; +3 comments = 10.
    n = estimate_kf_calls(item_count=2, extra_fields_per_item=1, edge_count=1, comment_count=3)
    assert n == 10
```

- [ ] **Step 2: Run to confirm failure.**

Run: `cd /home/brockamer/Code/jared-318 && /home/brockamer/Code/jared/.venv/bin/python -m pytest tests/test_migrate_core.py -k "edges or estimate" -q`
Expected: FAIL — import error.

- [ ] **Step 3: Implement.** Append to `migrate.py`:

```python
def translate_edges(edges: list[Edge], number_map: NumberMap) -> list[Edge]:
    """Re-key edges through the number map. Drop any edge whose endpoint is
    unmapped (an item that was not migrated)."""
    out: list[Edge] = []
    for e in edges:
        dep = number_map.to_new(e.dependent)
        blk = number_map.to_new(e.blocker)
        if dep is not None and blk is not None:
            out.append(Edge(dependent=dep, blocker=blk))
    return out


def estimate_kf_calls(
    *, item_count: int, extra_fields_per_item: int, edge_count: int, comment_count: int
) -> int:
    """Upper-bound KanbanFlow write calls for a GH->KF apply run.

    Per item: 1 create + 1 Priority custom-field POST + N extra custom-field
    POSTs. Plus 1 label POST per edge (blocked-by:<N>) and 1 POST per comment.
    Printed in the dry-run so the operator knows whether the run fits KF's
    1,000 req/hr window.
    """
    per_item = 1 + 1 + extra_fields_per_item
    return item_count * per_item + edge_count + comment_count
```

- [ ] **Step 4: Run to confirm pass.** `… pytest tests/test_migrate_core.py -q` → PASS.

- [ ] **Step 5: Commit.**

```bash
git add skills/jared/scripts/lib/migrate.py tests/test_migrate_core.py
git commit -m "feat(318): migrate core — edge translation + KF call estimate (Phase 1.3)"
```

### Task 1.4: Report rendering + resume-ledger (de)serialization (TDD)

**Files:**
- Modify: `skills/jared/scripts/lib/migrate.py`
- Test: `tests/test_migrate_core.py` (append)

The `--out` artifact is JSON: `{direction, completed: {old: new}, losses: [...], report: "..."}`. It doubles as the resume ledger (Q3): on re-run, items whose old number is already a key in `completed` are skipped.

- [ ] **Step 1: Write the failing test.** Append:

```python
from skills.jared.scripts.lib.migrate import (
    MigrationLedger,
    render_report,
)


def test_render_report_lists_every_loss_and_estimate() -> None:
    axes = [LossAxis(key="renumber", description="reassigned", count=5)]
    text = render_report(direction="kanbanflow->github", item_count=5, axes=axes, kf_call_estimate=0)
    assert "kanbanflow->github" in text
    assert "5 items" in text
    assert "reassigned" in text


def test_ledger_round_trips_and_marks_completed() -> None:
    led = MigrationLedger(direction="github->kanbanflow")
    led.mark(old=1, new=1)
    led.mark(old=2, new=2)
    blob = led.to_json()
    back = MigrationLedger.from_json(blob)
    assert back.is_done(1) and back.is_done(2)
    assert not back.is_done(3)
    assert back.number_map().to_new(2) == 2
```

- [ ] **Step 2: Run to confirm failure.** import error.

- [ ] **Step 3: Implement.** Append to `migrate.py` (add `import json` at top):

```python
def render_report(
    *, direction: Direction, item_count: int, axes: list[LossAxis], kf_call_estimate: int
) -> str:
    lines = [
        f"Migration plan: {direction}",
        f"  {item_count} items to copy",
    ]
    if kf_call_estimate:
        lines.append(f"  ~{kf_call_estimate} KanbanFlow write calls (1,000/hr budget)")
    lines.append("  Named losses (Appendix A):")
    if not axes:
        lines.append("    (none — lossless in this direction)")
    for a in axes:
        suffix = f" [{a.count}]" if a.count else ""
        lines.append(f"    - {a.key}: {a.description}{suffix}")
    return "\n".join(lines)


@dataclass
class MigrationLedger:
    """Durable resume ledger + run artifact. completed maps old#->new#."""

    direction: Direction
    completed: dict[int, int] = field(default_factory=dict)
    losses: list[str] = field(default_factory=list)

    def mark(self, *, old: int, new: int) -> None:
        self.completed[old] = new

    def is_done(self, old: int) -> bool:
        return old in self.completed

    def number_map(self) -> NumberMap:
        return NumberMap(dict(self.completed))

    def to_json(self) -> str:
        return json.dumps(
            {"direction": self.direction, "completed": {str(k): v for k, v in self.completed.items()},
             "losses": self.losses},
            indent=2,
        )

    @classmethod
    def from_json(cls, blob: str) -> MigrationLedger:
        data = json.loads(blob)
        return cls(
            direction=str(data["direction"]),
            completed={int(k): int(v) for k, v in (data.get("completed") or {}).items()},
            losses=[str(x) for x in (data.get("losses") or [])],
        )
```

- [ ] **Step 4: Run to confirm pass + full-core gate.**

Run: `cd /home/brockamer/Code/jared-318 && /home/brockamer/Code/jared/.venv/bin/python -m pytest tests/test_migrate_core.py -q && /home/brockamer/Code/jared/.venv/bin/ruff check skills/jared/scripts/lib/migrate.py && /home/brockamer/Code/jared/.venv/bin/mypy`
Expected: PASS + clean.

- [ ] **Step 5: Commit.**

```bash
git add skills/jared/scripts/lib/migrate.py tests/test_migrate_core.py
git commit -m "feat(318): migrate core — report render + resume ledger (Phase 1.4)"
```

---

## Phase 2 — CLI wiring + dry-run pipeline

Register the subcommand and build the **default dry-run**: read source → validate target → compute report → print → stop. No writes.

### Task 2.1: Register the `migrate` subcommand

**Files:**
- Modify: `skills/jared/scripts/jared`

- [ ] **Step 1:** Append `"migrate"` to `ALL_SUBCOMMANDS` (line 65 block) as the **last** entry (keeps the #319 merge hunk minimal).

- [ ] **Step 2:** In `build_parser()`, after the last `sub.add_parser(...)` block (the `propose-partition` / `wrap-state` region near line 416–439), add:

```python
    migrate_p = sub.add_parser(
        "migrate",
        help="Copy this board to the other backend (GitHub <-> KanbanFlow). Dry-run by default.",
        allow_abbrev=False,
    )
    migrate_p.add_argument(
        "--to", required=True, choices=["github", "kanbanflow"],
        help="Target backend. Must differ from the source (current) backend.",
    )
    migrate_p.add_argument(
        "--target-doc", required=True,
        help="Path to the target backend's project-board.md (produced by `jared init` on the target).",
    )
    migrate_p.add_argument("--apply", action="store_true", help="Perform writes (default: dry-run).")
    migrate_p.add_argument("--include-closed", action="store_true", help="Also migrate Done/closed items.")
    migrate_p.add_argument("--out", default=None, help="Path for the run artifact / resume ledger (JSON).")
    migrate_p.add_argument("--yes", action="store_true", help="Skip the interactive confirmation on --apply.")
    migrate_p.set_defaults(func=_cmd_migrate)
```

- [ ] **Step 3:** Confirm the parser builds.

Run: `cd /home/brockamer/Code/jared-318 && /home/brockamer/Code/jared/.venv/bin/python -c "import importlib.util, importlib.machinery; m=importlib.util.module_from_spec(importlib.util.spec_from_loader('j', importlib.machinery.SourceFileLoader('j','skills/jared/scripts/jared'))); importlib.machinery.SourceFileLoader('j','skills/jared/scripts/jared').exec_module(m); m.build_parser().parse_args(['migrate','--to','kanbanflow','--target-doc','x.md']); print('ok')"`
Expected: `ok` (no `_cmd_migrate` NameError because Step in Task 2.2 defines it — if running before 2.2, expect NameError; sequence 2.2 before this check or stub `_cmd_migrate` now).

> Implementation note: define a stub `def _cmd_migrate(args): return 0` immediately so the parser import succeeds; Task 2.2 fills it in via TDD.

- [ ] **Step 4: Commit.**

```bash
git add skills/jared/scripts/jared
git commit -m "feat(318): register migrate subcommand + flags (Phase 2.1)"
```

### Task 2.2: Dry-run `_cmd_migrate` (TDD)

**Files:**
- Modify: `skills/jared/scripts/jared`
- Test: `tests/test_cmd_migrate.py`

- [ ] **Step 1: Write the failing test.** Create `tests/test_cmd_migrate.py`. Use the existing fakes: a gh-patched source `GitHubProjectsProvider` (via a minimal source board doc) and a `FakeKanbanFlowClient`-backed target. The cleanest seam is to monkeypatch `Board.from_path` to return prebuilt `Board` objects whose `.provider` is set. Example dry-run test:

```python
from __future__ import annotations

import pytest

from skills.jared.scripts.lib.board_provider import BoardItem, Edge
from tests.conftest import import_cli


class _StubProvider:
    """Minimal in-memory BoardProvider for migrate CLI tests."""

    def __init__(self, *, items, edges, caps, milestones=None):
        self._items, self._edges, self._caps = items, edges, caps
        self._milestones = milestones or []
        self.created: list[BoardItem] = []

    def capabilities(self): return self._caps
    def list_open_items(self): return list(self._items)
    def get_body(self, ref): return next(i.body for i in self._items if i.number == ref)
    def fetch_blocked_by_edges(self): return list(self._edges)
    def list_milestones(self): return list(self._milestones)
    def list_comments(self, ref): return []
    # write side recorded for apply tests (Phase 3)
    def file(self, **kw): 
        item = BoardItem(number=100 + len(self.created), title=kw["title"], status=kw["status"],
                         priority=kw["priority"], body=kw["body"]); self.created.append(item); return item
    def move(self, ref, status): ...
    def set_field(self, ref, name, value): ...
    def set_milestone(self, ref, name): ...
    def add_blocked_by(self, ref, blocker): ...
    def comment(self, ref, body): return ""


def _patch_boards(monkeypatch, source, target):
    cli = import_cli()
    class _B:
        def __init__(self, backend, provider): self.backend = backend; self.provider = provider
    monkeypatch.setattr(cli, "_load_board", lambda _arg: _B("github", source))
    monkeypatch.setattr(cli, "_load_target_board", lambda _path: _B("kanbanflow", target))
    return cli


def test_dry_run_prints_report_and_writes_nothing(monkeypatch, capsys):
    from skills.jared.scripts.lib.board_provider import Capability
    src = _StubProvider(
        items=[BoardItem(number=1, title="a", status="Up Next", priority="High", body="x"),
               BoardItem(number=2, title="b", status="Backlog", priority="Low", body="see #1")],
        edges=[Edge(dependent=2, blocker=1)],
        caps=frozenset(Capability),
    )
    tgt = _StubProvider(items=[], edges=[], caps=frozenset())
    cli = _patch_boards(monkeypatch, src, tgt)
    rc = cli.main(["migrate", "--to", "kanbanflow", "--target-doc", "t.md"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "github->kanbanflow" in out
    assert "2 items" in out
    assert "native_dependencies" in out
    assert tgt.created == []  # dry-run: no writes
```

- [ ] **Step 2: Run to confirm failure.**

Run: `cd /home/brockamer/Code/jared-318 && /home/brockamer/Code/jared/.venv/bin/python -m pytest tests/test_cmd_migrate.py -q`
Expected: FAIL (stub returns 0, no output / no `_load_target_board`).

- [ ] **Step 3: Implement the dry-run.** Replace the stub `_cmd_migrate` and add helpers in `skills/jared/scripts/jared`:

```python
def _load_target_board(target_doc: str) -> Board:
    return Board.from_path(Path(target_doc))


def _backend_direction(source_backend: str, to: str) -> str:
    return f"{source_backend}->{to}"


def _cmd_migrate(args: argparse.Namespace) -> int:
    from lib.migrate import compute_loss_axes, estimate_kf_calls, render_report  # type: ignore[import-not-found]

    source_board = _load_board(args.board)
    if args.to == source_board.backend:
        print(f"error: --to {args.to} equals the current backend; nothing to migrate.", file=sys.stderr)
        return 2
    target_board = _load_target_board(args.target_doc)
    direction = _backend_direction(source_board.backend, args.to)

    src = source_board.provider
    tgt = target_board.provider
    items = src.list_open_items()
    edges = src.fetch_blocked_by_edges()
    axes = compute_loss_axes(
        source_caps=src.capabilities(), target_caps=tgt.capabilities(), direction=direction
    )
    # annotate edge-count magnitude on the native_dependencies axis
    for a in axes:
        if a.key == "native_dependencies":
            a.count = len(edges)
    kf_estimate = (
        estimate_kf_calls(
            item_count=len(items), extra_fields_per_item=1, edge_count=len(edges), comment_count=0
        )
        if args.to == "kanbanflow"
        else 0
    )
    report = render_report(
        direction=direction, item_count=len(items), axes=axes, kf_call_estimate=kf_estimate
    )
    print(report)

    if not args.apply:
        print("\nDry-run only. Re-run with --apply to perform the migration.")
        return 0

    return _apply_migration(args, source_board, target_board, direction, items, edges)  # Phase 3
```

(Add a temporary `def _apply_migration(...): raise NotImplementedError` so dry-run tests pass before Phase 3.)

- [ ] **Step 4: Run to confirm pass.** `… pytest tests/test_cmd_migrate.py -q` → PASS.

- [ ] **Step 5: Commit.**

```bash
git add skills/jared/scripts/jared tests/test_cmd_migrate.py
git commit -m "feat(318): migrate dry-run pipeline — report + estimate, no writes (Phase 2.2)"
```

### Task 2.3: Target-structure validation (TDD)

For a KanbanFlow target, refuse up front if columns for every Status / dropdown fields for Priority+extras / swimlanes for every milestone do not pre-exist (the API cannot create them). Reuse `provider.validate_fields()` per distinct (priority,status) pair and `_swimlane_id`/`list_milestones` to probe structure, collecting a precise missing-structure list before any write.

- [ ] **Step 1–4:** Write a test that seeds the target stub to raise `FieldNotFound` for an unmapped Status, assert `_cmd_migrate --apply` exits non-zero with a "missing target structure:" message listing the gap, implement `_validate_target_structure(tgt, items)` that aggregates `validate_fields` misses, run red→green.
- [ ] **Step 5: Commit** `feat(318): migrate target-structure validation refuses on missing columns/fields (Phase 2.3)`.

---

## Phase 3 — Apply path

Item creation (preserve `#N` GH→KF / accumulate map KF→GH) → fields/status/milestone → second-pass edges → comment portage (backdate + author prepend) → emit artifact. Confirmation gate before any write.

### Task 3.1: Confirmation gate + item creation with number map (TDD)

> **GATE: do not start until the `#N`-preservation design-tension above is resolved.** If option (a): land the additive `file(..., number=None)` contract edit (its own sub-task: extend Protocol + both impls + a test that `KanbanFlowProvider.file(number=318)` threads `number_value=318`, GitHub ignores it) **before** this task, and re-tell session-1 the seam. If option (b): `#N`-preservation is a named loss and GH→KF passes no number.

- [ ] Write a test: `--apply --yes` on the 2-item stub creates 2 target items and records an old→new map; without `--yes`, monkeypatch `input` to "n" and assert zero writes. Implement `_apply_migration` to: print report, require `--apply` + (`--yes` or interactive `y`), then for each source item (skipping `ledger.is_done`) call `tgt.file(...)` and `ledger.mark(old=item.number, new=created.number)`. **Number handling depends on the resolved decision:** option (a) → GH→KF passes `number=item.number` so the new number equals the old; option (b) → no number passed, KF assigns its own and the map is non-identity in both directions. Apply Status via `move`, extra fields via `set_field`, milestone via `set_milestone`. Bodies get `rewrite_cross_refs(body, ledger.number_map())` **after** all items exist (Task 3.3 re-pass) — on first creation write the raw body, then rewrite in the second pass.
- [ ] Commit `feat(318): migrate apply — confirmation gate + item creation + number map (Phase 3.1)`.

### Task 3.2: Second-pass edges (TDD)
- [ ] Test: after creation, `translate_edges(source_edges, ledger.number_map())` is applied via `tgt.add_blocked_by(dep, blk)`; assert calls. Implement the second pass. Commit `feat(318): migrate apply — second-pass blocked-by edges (Phase 3.2)`.

### Task 3.3: Body + comment cross-ref rewrite & comment portage (TDD)
- [ ] Test: a source body "see #1" with map {1:101} results in `tgt.set_body(new, "see #101")`; comments are read via `src.list_comments` and written via `tgt.comment`, GH→KF prepending `(originally @{author}, {created_at})`. Implement: second pass calls `set_body(new, rewrite_cross_refs(get_body(old), nm))`; for each source comment, rewrite refs, prepend attribution when `direction == "github->kanbanflow"`, write via `tgt.comment`. Commit `feat(318): migrate apply — cross-ref rewrite + comment portage with attribution (Phase 3.3)`.

### Task 3.4: Emit run artifact / ledger (TDD)
- [ ] Test: `--out map.json` writes `MigrationLedger.to_json()`; default path is a timestamped file. Implement: write the ledger after the run; default `--out` to `tmp/migrate-<src>-to-<dst>-<stamp>.json` (stamp passed in, not generated in pure code). Commit `feat(318): migrate apply — emit run artifact / resume ledger (Phase 3.4)`.

---

## Phase 4 — Resumability (Q3)

### Task 4.1: Resume from an existing ledger (TDD)
- [ ] Test: pre-seed `--out` with a ledger marking item #1 done; run `--apply`; assert #1's `file()` is NOT called again and the second pass still re-keys edges using the full map. Implement: at apply start, if the `--out` path exists, load `MigrationLedger.from_json`; skip `ledger.is_done(old)`; persist after each item so an aborted run leaves a re-runnable ledger. Commit `feat(318): migrate resumability — skip already-created items via ledger (Phase 4.1)`.

---

## Phase 5 — Flip the source backend selector on success (Q4)

After a successful `--apply`, rewrite the **source** `docs/project-board.md` so the project now points at the target backend, reusing the init-time doc writer (`bootstrap-project.py`). This makes the migrated board authoritative.

### Task 5.1: Flip on success (TDD)
- [ ] Test: after a successful apply (all items + edges done, no exception), the source doc's backend selector is rewritten to the target (assert via reading the rewritten file in a tmp repo). Implement `_flip_backend_selector(source_doc_path, new_backend, target_board)` that regenerates the doc for the target backend (delegating to the existing bootstrap doc writer; for a KF target it writes `- backend: kanbanflow`, `Repo:`, `Board ID/URL`, `### Status column map` and drops GitHub field/option blocks — exactly what `jared init` produces). Gate strictly on full success; never flip on a partial/aborted run. Commit `feat(318): migrate flips source backend selector on success (Phase 5.1)`.

> If reusing `bootstrap-project.py`'s writer requires refactor beyond a thin call, STOP and confirm scope with the operator — a doc-rewrite that diverges from `jared init` output is a design-tension signal, not a silent choice.

---

## Phase 6 — End-to-end + acceptance gates

### Task 6.1: Grep-clean command (acceptance)
- [ ] Add a test asserting `lib/migrate.py` and the `_cmd_migrate`/`_apply_migration` region contain **zero** occurrences of `gh`, `GraphQL`, `field_id`, `option_id`, KanbanFlow `_id` (provider-purity acceptance). Run: `grep -nE "gh |graphql|field_id|option_id|_id\b" skills/jared/scripts/lib/migrate.py` → expect no matches. Commit `test(318): assert migrate command is provider-pure (Phase 6.1)`.

### Task 6.2: Full offline gate
- [ ] Run: `cd /home/brockamer/Code/jared-318 && /home/brockamer/Code/jared/.venv/bin/ruff check . && /home/brockamer/Code/jared/.venv/bin/ruff format --check . && /home/brockamer/Code/jared/.venv/bin/mypy && /home/brockamer/Code/jared/.venv/bin/python -m pytest -q`
  Expected: all clean, full suite green. Fix anything red before proceeding.

### Task 6.3: LIVE verification (required — fake is insufficient)
- [ ] **This gate cannot be satisfied offline.** Exercise a real GitHub↔KanbanFlow round-trip against a **real** KanbanFlow board (needs `KANBANFLOW_API_TOKEN` for a premium board with pre-seeded columns/fields/swimlanes). The live API returns `{taskId}` on create / `null` on update where `FakeKanbanFlowClient` returns full objects — a fake-only green run hides the real write contract (#317 / PR #334).
  - [ ] Dry-run GH→KF against the testbed project; confirm the report + call estimate.
  - [ ] `--apply --yes`; confirm items land with `#N` preserved, blocked-by markers present, comments ported with attribution, artifact written.
  - [ ] Re-read the target's edges via `tgt.fetch_blocked_by_edges()`; assert the dependency graph matches the source's (translated through the map).
  - [ ] Abort mid-run (Ctrl-C) and re-run; confirm the ledger resumes without duplication.
  - [ ] Record the live-run evidence (commands + key output) in the PR description.

> **Operator dependency:** Task 6.3 needs a disposable real KanbanFlow board + token. Surface this to the operator before starting Phase 6.3 — it is the one step that cannot be completed autonomously and must not be faked-green.

---

## Phase 7 — Documentation + ship

### Task 7.1: Docs (append-only; #319-seam-safe)
- [ ] `docs/project-board.md`: backend-switching via `jared migrate`, named lossiness per direction, the KanbanFlow target-structure prerequisite.
- [ ] `CLAUDE.md`: add `migrate` to the CLI surface inventory (bump "~18 subcommands") and the three-tier note.
- [ ] `skills/jared/references/operations.md`: the `migrate` operation, dry-run/apply discipline, `--target-doc`, resume, quota guidance.
- [ ] Commit `docs(318): document jared migrate (Phase 7.1)`.

### Task 7.2: CHANGELOG + PR
- [ ] `CHANGELOG.md`: a `**Features**` line — `jared migrate copies a board between GitHub Projects and KanbanFlow with named, accepted lossiness, resumable, dry-run by default (#318)`.
- [ ] Open the PR from the session-2 worktree branch; in the body, include the live-run evidence and a note that the `ALL_SUBCOMMANDS`/parser region is a mechanical union with #319.
- [ ] At merge, reconcile the `skills/jared/scripts/jared` hunk against whatever #319 landed.

---

## Self-review (run before declaring the plan done)

**Spec coverage** — every spec requirement maps to a task:
- Provider-only command → Task 6.1 (grep gate) + the `_cmd_migrate` design.
- Dry-run default + `--apply` + confirmation + call estimate → Tasks 2.2, 3.1.
- GH→KF preserves `#N`; KF→GitHub emits old→new map → Tasks 3.1, 3.4.
- blocked-by preserved across renumber (verified by re-read) → Tasks 3.2, 6.3.
- Each Appendix-A loss itemized before writing → Tasks 1.1, 2.2.
- Live verification → Task 6.3.
- `pytest`/`ruff`/`mypy` green → Task 6.2.
- Docs/CHANGELOG → Phase 7.
- Resolved Q1 (`--include-closed`) → flag wired in 2.1; closed items only read under the flag (extend `list_open_items` read with a closed-items read in 3.1 when `--include-closed`; if the providers lack a closed-items reader, that is a contract gap — STOP and confirm before adding, do not scope-creep silently).

**Placeholder scan** — Phases 2.3, 3.1–3.4, 4.1, 5.1 describe tests in prose with explicit assertions and name the exact functions/flows; the load-bearing pure code (Phase 0, 1) is shown in full. Before executing those phases, the engineer writes the shown-shape test first (red), then the implementation (green). No "TBD"/"add error handling" placeholders remain.

**Type consistency** — `NumberMap.to_new` returns `int | None` (callers guard); `compute_loss_axes`/`render_report`/`estimate_kf_calls` are keyword-only and named consistently across Phase 1 and their call site in Task 2.2; `Comment(author, body, created_at)` is identical across Phase 0 and Phase 3.3.

**Open dependency to surface to the operator before Phase 3/6:** `--include-closed` requires a closed-items *read* path the contract may not have (only `recently_closed` exists, and KF degrades it to `[]`). If closed-history migration is wanted in v1, that is an additional contract gap — confirm scope before implementing; otherwise `--include-closed` ships as a flag that warns "closed-item migration not yet supported on this backend" and is a named follow-up.
