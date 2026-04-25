---
**Shipped in #35 on 2026-04-25. Final decisions captured in issue body.**
---

# /jared-wrap Optional Session Handoff Prompt — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an optional, derived, ephemeral session handoff prompt to `/jared-wrap`, plus a board-derived skeleton emitter as a new `jared next-session-prompt` CLI subcommand.

**Architecture:** Two-layer generation. The CLI subcommand emits a deterministic, board-derived skeleton (In Progress + last Session note one-liners, Up Next, Recently closed). The `/jared-wrap` slash command calls the CLI for the skeleton, then layers conversation-context synthesis (frame, anti-targets, strategic narrative) on top, and writes the result to `tmp/next-session-prompt-<TIMESTAMP>.md`. The prompt is `.gitignore`d, ephemeral, and never authoritative — it bridges sessions; durable records remain on issues, in plans/specs, and in memory.

**Tech Stack:** Python 3.11, argparse (CLI), pytest with `tests/conftest.py` helpers (`patch_gh`, `patch_gh_by_arg`, `import_cli`), `gh` CLI invoked via existing `Board.run_gh*`, ruff + mypy in strict mode.

**Spec:** `docs/superpowers/specs/2026-04-25-jared-wrap-next-session-prompt-design.md` (commits `8e42ed6`, `54e1b01`).

**Tracking issue:** brockamer/jared#35.

**Branch:** `feature/wrap-next-session-prompt` (per `feedback_jared_git_workflow` — feature/* pre-authorized; main via PR; phase-numbered commits).

---

## File structure

| File | Phase | Responsibility |
|---|---|---|
| `skills/jared/scripts/jared` | 1, 2 | New `_cmd_next_session_prompt` + argparse subparser; reads `--include-session-checks` flag in P2 |
| `skills/jared/scripts/lib/board.py` | 2 | New parsing for `## Jared config` and `## Session start checks` sections |
| `tests/test_cmd_next_session_prompt.py` | 1 | Unit tests for the CLI subcommand (no network, all gh calls patched) |
| `tests/test_board.py` | 2 | Add tests for the new config parsing |
| `skills/jared/assets/next-session-prompt.md.template` | 2 | Default scaffold with section headings (Frame, What's likely to want attention, What NOT to do, Context, Health check) |
| `skills/jared/assets/project-board.md.template` | 2 | Add documented `## Jared config` and `## Session start checks` sections |
| `.gitignore` | 2 | Ensure `tmp/next-session-prompt-*.md` is ignored (verify `tmp/` already covers it) |
| `commands/jared-wrap.md` | 3 | Extend Step 6 with the optional draft-prompt step |
| `skills/jared/SKILL.md` | 4 | Reframe line 218 anti-pattern; cross-reference new section |
| `skills/jared/references/session-continuity.md` | 4 | New "Optional handoff prompt" section explaining contract: derived, ephemeral, never authoritative |
| `.claude-plugin/plugin.json` | 4 | Bump version `0.3.1` → `0.4.0` |

---

## Phase 1: `jared next-session-prompt` CLI subcommand (skeleton)

**Phase outcome:** A new CLI subcommand that, given a board, prints a markdown skeleton to stdout listing In Progress (with last Session-note one-liners), top 3 Up Next, recently closed (last 7 days), and a footer. Independently mergeable as a useful skeleton command. No config-key awareness yet.

### Task 1.1: Failing test — basic skeleton structure

**Files:**
- Create: `tests/test_cmd_next_session_prompt.py`

- [ ] **Step 1: Write the failing test**

```python
"""Tests for `jared next-session-prompt` — the board-derived handoff skeleton.

Covers the deterministic, mechanical output: In Progress section with last
Session note one-liners, Up Next top 3, Recently closed last 7 days, footer.
All gh calls are patched; no network. Slash-command synthesis is not tested
here (it lives in commands/jared-wrap.md, not in code).
"""

from pathlib import Path

import pytest

from tests.conftest import import_cli, patch_gh_by_arg, write_minimal_board


def test_next_session_prompt_renders_basic_sections(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    board_md = write_minimal_board(tmp_path)

    # gh project item-list returns one In Progress, two Up Next, one closed
    item_list = (
        '{"items": ['
        '{"id": "a", "content": {"number": 65, "title": "Buried-gems UI"}, '
        '"status": "In Progress", "priority": "High"},'
        '{"id": "b", "content": {"number": 273, "title": "Filter facets"}, '
        '"status": "Up Next", "priority": "High"},'
        '{"id": "c", "content": {"number": 274, "title": "Indeed diagnostic"}, '
        '"status": "Up Next", "priority": "Medium"}'
        "]}"
    )
    # gh issue view <N> --json comments returns the latest Session note
    issue_comments = (
        '{"comments": ['
        '{"createdAt": "2026-04-24T10:00:00Z", "body": "## Session 2026-04-24\\n\\n'
        "**Progress:** wired prefilter\\n\\n"
        "**Next action:** decide YAML ordering question and unblock the third test."
        '"}'
        "]}"
    )
    # gh issue list for recently closed (state=closed, closed within 7d)
    closed_list = '[{"number": 251, "title": "v0.4 release", "closedAt": "2026-04-23T15:00:00Z"}]'

    patch_gh_by_arg(
        monkeypatch,
        responses={
            "item-list": item_list,
            "issue view 65": issue_comments,
            "issue list": closed_list,
        },
    )

    mod = import_cli()
    rc = mod.main(["--board", str(board_md), "next-session-prompt"])
    out = capsys.readouterr().out

    assert rc == 0
    # Headings
    assert "# Session handoff" in out
    assert "## In flight" in out
    assert "## Top of Up Next" in out
    assert "## Recently closed" in out
    assert "## To start" in out
    # In Progress item
    assert "#65" in out and "Buried-gems UI" in out
    # Last Session note one-liner — Next action sentence
    assert "decide YAML ordering question" in out
    # Up Next top 3 (only 2 in this fixture)
    assert "#273" in out and "#274" in out
    # Recently closed
    assert "#251" in out and "v0.4 release" in out
    # Footer warning
    assert "Regenerated each wrap" in out
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_cmd_next_session_prompt.py::test_next_session_prompt_renders_basic_sections -v`

Expected: FAIL — argparse will reject `next-session-prompt` as an invalid choice with a SystemExit / "invalid choice" error.

- [ ] **Step 3: Add the subparser and stub command function**

Edit `skills/jared/scripts/jared`:

In `ALL_SUBCOMMANDS` list (currently lines 29–38), add `"next-session-prompt"`:

```python
ALL_SUBCOMMANDS = [
    "get-item",
    "summary",
    "set",
    "move",
    "close",
    "comment",
    "file",
    "blocked-by",
    "next-session-prompt",
]
```

In `build_parser()`, after the `dep` subparser block (after line 125), add:

```python
    nsp = sub.add_parser(
        "next-session-prompt",
        help="Emit a board-derived session handoff skeleton (markdown to stdout).",
    )
    nsp.set_defaults(func=_cmd_next_session_prompt)
```

Then below `_cmd_summary` (around line 547), add:

```python
def _cmd_next_session_prompt(args: argparse.Namespace) -> int:
    """Emit a board-derived session handoff skeleton.

    Pure read: lists In Progress (with last Session-note one-liners), top 3
    Up Next, recently closed (last 7 days), plus a kickoff footer. No
    GitHub side effects; no synthesis. The /jared-wrap slash command calls
    this and layers conversation-context synthesis (frame, anti-targets) on
    top before writing to tmp/next-session-prompt-<TIMESTAMP>.md.

    The output's structural contract is what the slash command depends on,
    so changes here are user-visible.
    """
    board = Board.from_path(Path(args.board))
    items = _fetch_board_items(board)
    in_progress = [i for i in items if i.get("status") == "In Progress"]
    up_next = [i for i in items if i.get("status") == "Up Next"][:3]
    closed = _fetch_recently_closed(board, days=7)

    print(f"# Session handoff — {board.repo} — {_now_local_iso()}")
    print()
    print("## In flight")
    print()
    if in_progress:
        for item in in_progress:
            _render_in_flight(board, item)
    else:
        print("(nothing in progress)")
    print()
    print("## Top of Up Next")
    print()
    if up_next:
        for item in up_next:
            content = item.get("content") or {}
            prio = item.get("priority") or "-"
            print(f"- #{content.get('number')} [{prio}] {content.get('title', '')}")
    else:
        print("(empty queue)")
    print()
    print("## Recently closed (last 7 days)")
    print()
    if closed:
        for c in closed:
            date = (c.get("closedAt") or "")[:10]
            print(f"- #{c['number']} {c['title']}  ({date})")
    else:
        print("(none)")
    print()
    print("## To start")
    print()
    print("Read the sections above, decide which issue to pull, then:")
    print()
    print("```")
    print("/jared-start <#N>")
    print("```")
    print()
    print("---")
    print(
        "Regenerated each wrap; do not edit. Source of truth is the issues, "
        "plans, and memory."
    )
    return 0
```

Add helper functions just above `_cmd_next_session_prompt` (still in the same file):

```python
def _fetch_board_items(board: Board) -> list[dict[str, Any]]:
    """Mirror of _cmd_summary's item-list call.

    Kept inline rather than refactored into Board to keep this phase's
    diff narrow; if a third caller appears, lift to Board.list_items().
    """
    data = board.run_gh(
        [
            "project",
            "item-list",
            str(board.project_number),
            "--owner",
            board.owner,
            "--limit",
            "500",
            "--format",
            "json",
        ]
    )
    items: list[dict[str, Any]] = data.get("items", [])
    return items


def _fetch_recently_closed(board: Board, *, days: int) -> list[dict[str, Any]]:
    """Use `gh issue list --state closed --search "closed:>YYYY-MM-DD"`.

    Returns a list of {"number", "title", "closedAt"} dicts, sorted by
    closedAt desc (newest first). Empty list if none.
    """
    cutoff = _date_n_days_ago(days)
    data = board.run_gh(
        [
            "issue",
            "list",
            "--repo",
            board.repo,
            "--state",
            "closed",
            "--search",
            f"closed:>={cutoff}",
            "--limit",
            "50",
            "--json",
            "number,title,closedAt",
        ]
    )
    # gh returns a top-level list, not an object — run_gh hands back whatever
    # JSON it parsed. Accept both shapes defensively.
    if isinstance(data, list):
        items = data
    else:
        items = data.get("issues", [])
    items.sort(key=lambda c: c.get("closedAt") or "", reverse=True)
    return items


def _render_in_flight(board: Board, item: dict[str, Any]) -> None:
    """Print one bullet for an In Progress item with last Session-note one-liner."""
    content = item.get("content") or {}
    num = content.get("number")
    prio = item.get("priority") or "-"
    title = content.get("title", "")
    print(f"- #{num} [{prio}] {title}")
    note_one_liner = _latest_session_note_oneliner(board, num) if isinstance(num, int) else None
    if note_one_liner is not None:
        print(f"  Last session: \"{note_one_liner}\"")


def _latest_session_note_oneliner(board: Board, issue_number: int) -> str | None:
    """Pull the most recent comment whose body starts with `## Session ` and
    extract the **Next action:** sentence. Returns None if no Session note
    exists or no Next action line is found.

    The `## Session ` prefix is the discipline laid out in
    `references/session-continuity.md` — comments that don't match are
    ordinary discussion and are skipped.
    """
    data = board.run_gh(
        [
            "issue",
            "view",
            str(issue_number),
            "--repo",
            board.repo,
            "--json",
            "comments",
        ]
    )
    comments = data.get("comments", []) if isinstance(data, dict) else []
    session_notes = [c for c in comments if (c.get("body") or "").startswith("## Session ")]
    if not session_notes:
        return None
    # gh returns comments in chronological order; the latest is the last one.
    latest = session_notes[-1]
    body = latest.get("body", "")
    return _extract_next_action(body)


_NEXT_ACTION_RE = re.compile(
    r"\*\*Next action:\*\*\s*(.+?)(?:\n\n|\n\*\*|\Z)",
    re.DOTALL,
)


def _extract_next_action(session_note_body: str) -> str | None:
    """Pull the **Next action:** body from a Session note. Returns None if not found.

    Stops at the next bold-label paragraph or end of body. Whitespace
    collapsed so the one-liner fits on a single line.
    """
    m = _NEXT_ACTION_RE.search(session_note_body)
    if not m:
        return None
    text = m.group(1).strip()
    return " ".join(text.split())


def _date_n_days_ago(days: int) -> str:
    """ISO date (YYYY-MM-DD) `days` days ago in local time."""
    from datetime import datetime, timedelta

    return (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")


def _now_local_iso() -> str:
    """Local timezone-naive ISO timestamp to the minute, for prompt headers."""
    from datetime import datetime

    return datetime.now().strftime("%Y-%m-%d %H:%M")
```

Add the `import re` at the top of `skills/jared/scripts/jared` (it isn't currently imported there). Place it alphabetically with the other stdlib imports (after `import json`):

```python
import json
import re
import sys
import tempfile
import time
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_cmd_next_session_prompt.py::test_next_session_prompt_renders_basic_sections -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git checkout -b feature/wrap-next-session-prompt
git add tests/test_cmd_next_session_prompt.py skills/jared/scripts/jared
git commit -m "$(cat <<'EOF'
feat(cli): add jared next-session-prompt skeleton (#35, phase 1.1)

Adds a new CLI subcommand that emits a board-derived markdown
skeleton: In Progress with last Session note one-liners, top 3
Up Next, recently closed (7d), kickoff footer. Pure read; no
synthesis (that lives in /jared-wrap).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

### Task 1.2: Edge cases — empty board, no Session notes, missing Next action

**Files:**
- Modify: `tests/test_cmd_next_session_prompt.py`

- [ ] **Step 1: Add three failing tests**

Append to `tests/test_cmd_next_session_prompt.py`:

```python
def test_empty_board_renders_placeholders(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    board_md = write_minimal_board(tmp_path)
    patch_gh_by_arg(
        monkeypatch,
        responses={
            "item-list": '{"items": []}',
            "issue list": "[]",
        },
    )
    mod = import_cli()
    rc = mod.main(["--board", str(board_md), "next-session-prompt"])
    out = capsys.readouterr().out

    assert rc == 0
    assert "(nothing in progress)" in out
    assert "(empty queue)" in out
    assert "(none)" in out


def test_in_progress_without_session_notes_skips_one_liner(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    board_md = write_minimal_board(tmp_path)
    item_list = (
        '{"items": ['
        '{"id": "a", "content": {"number": 7, "title": "Cold issue"}, '
        '"status": "In Progress", "priority": "Medium"}'
        "]}"
    )
    # No comments at all
    patch_gh_by_arg(
        monkeypatch,
        responses={
            "item-list": item_list,
            "issue view 7": '{"comments": []}',
            "issue list": "[]",
        },
    )
    mod = import_cli()
    rc = mod.main(["--board", str(board_md), "next-session-prompt"])
    out = capsys.readouterr().out

    assert rc == 0
    assert "#7" in out and "Cold issue" in out
    # No Last session line should be emitted when no Session note exists
    assert "Last session" not in out


def test_session_note_without_next_action_field_skips_one_liner(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    board_md = write_minimal_board(tmp_path)
    item_list = (
        '{"items": ['
        '{"id": "a", "content": {"number": 9, "title": "Half-noted issue"}, '
        '"status": "In Progress", "priority": "Medium"}'
        "]}"
    )
    # Comment matches Session prefix but lacks **Next action:**
    issue_comments = (
        '{"comments": ['
        '{"body": "## Session 2026-04-24\\n\\n**Progress:** stuff happened.\\n"}'
        "]}"
    )
    patch_gh_by_arg(
        monkeypatch,
        responses={
            "item-list": item_list,
            "issue view 9": issue_comments,
            "issue list": "[]",
        },
    )
    mod = import_cli()
    rc = mod.main(["--board", str(board_md), "next-session-prompt"])
    out = capsys.readouterr().out

    assert rc == 0
    assert "#9" in out and "Half-noted issue" in out
    # The Next-action extractor returned None; no Last session line
    assert "Last session" not in out
```

- [ ] **Step 2: Run all three tests to verify they pass**

Run: `pytest tests/test_cmd_next_session_prompt.py -v`

Expected: All three new tests PASS (Phase 1.1 implementation already handles these branches).

- [ ] **Step 3: Run lint + type check**

```bash
ruff check tests/test_cmd_next_session_prompt.py skills/jared/scripts/jared
ruff format --check tests/test_cmd_next_session_prompt.py skills/jared/scripts/jared
mypy
```

Expected: all clean. If anything fails, fix it now (don't defer).

- [ ] **Step 4: Run the full unit-test suite**

Run: `pytest`

Expected: all tests pass; integration tests are skipped per `addopts = "-m 'not integration'"`.

- [ ] **Step 5: Commit**

```bash
git add tests/test_cmd_next_session_prompt.py
git commit -m "$(cat <<'EOF'
test(cli): cover edge cases for next-session-prompt (#35, phase 1.2)

Empty board, in-progress without Session notes, and Session notes
that lack a Next action field. Verification folded into producing
phase per feedback_deferred_verification_drift.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Phase 2: Board config parsing + `--include-session-checks` flag + assets + .gitignore

**Phase outcome:** `Board` learns to read `## Jared config` (single-line bullets) and `## Session start checks` (fenced bash blocks). The CLI subcommand gets a `--include-session-checks` flag that emits a "## Quick health check on session start" section using whatever the board defines. New asset template (`next-session-prompt.md.template`). Project-board template documents the two new sections. `.gitignore` covers `tmp/next-session-prompt-*.md`. Independently mergeable: any board can opt in via the new sections; CLI ignores them by default.

### Task 2.1: Failing test — Board parses `## Jared config`

**Files:**
- Modify: `tests/test_board.py`
- Modify: `skills/jared/scripts/lib/board.py`

- [ ] **Step 1: Inspect existing test_board.py for the helper pattern**

Run: `pytest tests/test_board.py -v --collect-only`

Expected: a list of existing test names. Read the file briefly to mirror the style.

- [ ] **Step 2: Add a failing test**

Append to `tests/test_board.py`:

```python
def test_board_parses_jared_config_section(tmp_path: Path) -> None:
    """Board surfaces session-handoff-prompt and session-start-checks from the
    optional sections in docs/project-board.md.

    The Jared config bullets are name: value pairs; the Session start checks
    are fenced bash blocks. Boards without these sections leave both fields
    at their defaults.
    """
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

        ## Jared config

        - session-handoff-prompt: always

        ## Session start checks

        ```bash
        ${CLAUDE_PLUGIN_ROOT}/skills/jared/scripts/jared summary
        ```

        ```bash
        ssh docker.lan 'sudo -u lad docker compose ps'
        ```
        """)
    )

    board = Board.from_path(board_md)
    assert board.session_handoff_prompt == "always"
    assert board.session_start_checks == [
        "${CLAUDE_PLUGIN_ROOT}/skills/jared/scripts/jared summary",
        "ssh docker.lan 'sudo -u lad docker compose ps'",
    ]


def test_board_defaults_when_jared_config_absent(tmp_path: Path) -> None:
    """A board doc with no Jared config / Session start checks sections
    leaves both fields at their defaults — empty list, ask mode."""
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
    assert board.session_handoff_prompt == "ask"
    assert board.session_start_checks == []
```

If `dedent` and `Path` are not already imported at the top of `tests/test_board.py`, add them — match whatever the existing file uses.

- [ ] **Step 3: Run the failing tests**

Run: `pytest tests/test_board.py::test_board_parses_jared_config_section tests/test_board.py::test_board_defaults_when_jared_config_absent -v`

Expected: FAIL — `Board` has no `session_handoff_prompt` or `session_start_checks` attribute.

- [ ] **Step 4: Add the new fields to `Board` dataclass**

Edit `skills/jared/scripts/lib/board.py`. In the `@dataclass` for `Board` (around lines 33–41), add two new fields:

```python
@dataclass
class Board:
    project_number: int
    project_id: str
    owner: str
    repo: str
    project_url: str
    _field_ids: dict[str, str] = field(default_factory=dict)
    _field_options: dict[str, dict[str, str]] = field(default_factory=dict)
    session_handoff_prompt: str = "ask"
    session_start_checks: list[str] = field(default_factory=list)
```

In `Board._parse` (around lines 51–126), after `field_ids, field_options = cls._parse_field_blocks(text)`, parse the new sections:

```python
        field_ids, field_options = cls._parse_field_blocks(text)
        session_handoff_prompt = cls._parse_jared_config(text).get(
            "session-handoff-prompt", "ask"
        )
        session_start_checks = cls._parse_session_start_checks(text)

        return cls(
            project_number=project_number_val,
            project_id=project_id,
            owner=owner,
            repo=repo,
            project_url=project_url,
            _field_ids=field_ids,
            _field_options=field_options,
            session_handoff_prompt=session_handoff_prompt,
            session_start_checks=session_start_checks,
        )
```

Add the two parser staticmethods alongside `_parse_field_blocks` (around line 128):

```python
    @staticmethod
    def _parse_jared_config(text: str) -> dict[str, str]:
        """Parse the optional `## Jared config` section's bullets.

        Bullets are `- name: value` pairs. Anything that doesn't match the
        bullet form is skipped. Section ends at the next `##` heading or
        end-of-file. Returns an empty dict if the section is absent.
        """
        m = re.search(
            r"^## Jared config\s*\n(.*?)(?=^##\s|\Z)",
            text,
            re.MULTILINE | re.DOTALL,
        )
        if not m:
            return {}
        result: dict[str, str] = {}
        for line in m.group(1).splitlines():
            bullet = re.match(r"^\s*-\s*([\w-]+):\s*(.+?)\s*$", line)
            if bullet:
                result[bullet.group(1)] = bullet.group(2)
        return result

    @staticmethod
    def _parse_session_start_checks(text: str) -> list[str]:
        """Parse the optional `## Session start checks` section's fenced bash blocks.

        Each ```bash ... ``` (or just ``` ... ```) becomes one entry, joined
        by newlines if the block has multiple lines. Section ends at the next
        `##` heading or end-of-file. Returns [] if section is absent.
        """
        m = re.search(
            r"^## Session start checks\s*\n(.*?)(?=^##\s|\Z)",
            text,
            re.MULTILINE | re.DOTALL,
        )
        if not m:
            return []
        section = m.group(1)
        checks: list[str] = []
        for fenced in re.finditer(r"```(?:bash)?\s*\n(.*?)```", section, re.DOTALL):
            body = fenced.group(1).strip()
            if body:
                checks.append(body)
        return checks
```

- [ ] **Step 5: Run the tests to verify pass**

Run: `pytest tests/test_board.py::test_board_parses_jared_config_section tests/test_board.py::test_board_defaults_when_jared_config_absent -v`

Expected: PASS.

- [ ] **Step 6: Run the full board test suite to confirm no regression**

Run: `pytest tests/test_board.py -v`

Expected: all PASS, including pre-existing tests.

- [ ] **Step 7: Run lint + type check**

```bash
ruff check tests/test_board.py skills/jared/scripts/lib/board.py
ruff format --check tests/test_board.py skills/jared/scripts/lib/board.py
mypy
```

Expected: clean.

- [ ] **Step 8: Commit**

```bash
git add tests/test_board.py skills/jared/scripts/lib/board.py
git commit -m "$(cat <<'EOF'
feat(board): parse Jared config + Session start checks (#35, phase 2.1)

Board now reads two optional project-board.md sections:
- ## Jared config: bullet-style name:value pairs (currently
  session-handoff-prompt; default "ask").
- ## Session start checks: fenced bash blocks; one entry per fence.

Both fields default to safe values when sections are absent — boards
without them keep working unchanged.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

### Task 2.2: Failing test — `--include-session-checks` flag

**Files:**
- Modify: `tests/test_cmd_next_session_prompt.py`
- Modify: `skills/jared/scripts/jared`

- [ ] **Step 1: Add a failing test**

Append to `tests/test_cmd_next_session_prompt.py`:

```python
def test_include_session_checks_emits_health_check_section(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """When the board has Session start checks defined and --include-session-checks
    is passed, the prompt includes a Quick health check section with the
    fenced commands. Without the flag, the section is omitted."""
    from textwrap import dedent

    board_md = tmp_path / "docs" / "project-board.md"
    board_md.parent.mkdir(parents=True)
    board_md.write_text(
        dedent("""\
        - Project URL: https://github.com/users/brockamer/projects/7
        - Project number: 7
        - Project ID: PVT_kwHO_xyz
        - Owner: brockamer
        - Repo: brockamer/findajob

        ## Session start checks

        ```bash
        echo health-check-one
        ```

        ```bash
        echo health-check-two
        ```
        """)
    )
    patch_gh_by_arg(
        monkeypatch,
        responses={
            "item-list": '{"items": []}',
            "issue list": "[]",
        },
    )
    mod = import_cli()
    rc = mod.main(
        [
            "--board",
            str(board_md),
            "next-session-prompt",
            "--include-session-checks",
        ]
    )
    out = capsys.readouterr().out

    assert rc == 0
    assert "## Quick health check on session start" in out
    assert "echo health-check-one" in out
    assert "echo health-check-two" in out


def test_session_checks_omitted_without_flag(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Even with checks defined, omitting the flag leaves the section out."""
    from textwrap import dedent

    board_md = tmp_path / "docs" / "project-board.md"
    board_md.parent.mkdir(parents=True)
    board_md.write_text(
        dedent("""\
        - Project URL: https://github.com/users/brockamer/projects/7
        - Project number: 7
        - Project ID: PVT_kwHO_xyz
        - Owner: brockamer
        - Repo: brockamer/findajob

        ## Session start checks

        ```bash
        echo should-not-appear
        ```
        """)
    )
    patch_gh_by_arg(
        monkeypatch,
        responses={
            "item-list": '{"items": []}',
            "issue list": "[]",
        },
    )
    mod = import_cli()
    rc = mod.main(["--board", str(board_md), "next-session-prompt"])
    out = capsys.readouterr().out

    assert rc == 0
    assert "Quick health check" not in out
    assert "echo should-not-appear" not in out
```

- [ ] **Step 2: Run the failing tests**

Run: `pytest tests/test_cmd_next_session_prompt.py::test_include_session_checks_emits_health_check_section tests/test_cmd_next_session_prompt.py::test_session_checks_omitted_without_flag -v`

Expected: FAIL — argparse rejects `--include-session-checks` for the first; the second passes accidentally because the section isn't emitted yet.

- [ ] **Step 3: Add the flag and section emit**

Edit `skills/jared/scripts/jared`. In the `next-session-prompt` subparser block (added in Phase 1), add the flag:

```python
    nsp = sub.add_parser(
        "next-session-prompt",
        help="Emit a board-derived session handoff skeleton (markdown to stdout).",
    )
    nsp.add_argument(
        "--include-session-checks",
        action="store_true",
        help=(
            "Include the Quick health check section using "
            "`## Session start checks` from docs/project-board.md."
        ),
    )
    nsp.set_defaults(func=_cmd_next_session_prompt)
```

In `_cmd_next_session_prompt`, between the "Recently closed" block and the "## To start" block, insert:

```python
    if args.include_session_checks and board.session_start_checks:
        print("## Quick health check on session start")
        print()
        for check in board.session_start_checks:
            print("```bash")
            print(check)
            print("```")
            print()
```

- [ ] **Step 4: Run the new tests + the full subcommand suite**

Run: `pytest tests/test_cmd_next_session_prompt.py -v`

Expected: PASS for all 5 tests (3 from Phase 1, 2 new).

- [ ] **Step 5: Run lint + type check**

```bash
ruff check tests/test_cmd_next_session_prompt.py skills/jared/scripts/jared
ruff format --check tests/test_cmd_next_session_prompt.py skills/jared/scripts/jared
mypy
```

Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add tests/test_cmd_next_session_prompt.py skills/jared/scripts/jared
git commit -m "$(cat <<'EOF'
feat(cli): add --include-session-checks flag (#35, phase 2.2)

next-session-prompt now optionally emits a Quick health check
section using the board's Session start checks. Default omitted —
the flag is opt-in so the skeleton stays minimal unless caller
asks for the operational extras.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

### Task 2.3: Asset template + project-board.md.template + .gitignore

**Files:**
- Create: `skills/jared/assets/next-session-prompt.md.template`
- Modify: `skills/jared/assets/project-board.md.template`
- Modify: `.gitignore`

- [ ] **Step 1: Create the prompt asset template**

Create `skills/jared/assets/next-session-prompt.md.template`:

```markdown
# Session handoff — <PROJECT_REPO> — <YYYY-MM-DD HH:MM>

> Regenerated each `/jared-wrap`; do not edit. Source of truth is the
> issues, plans, and memory.

## Frame

<1–3 sentence narrative synthesized by /jared-wrap from the prior session's
conversation: release context, what shipped, what's load-bearing right now.
Falls back to a board-derived bullet list when no synthesis is available.>

## What's likely to want attention this session

<Ordered list with reasoning. Pulls from In Progress + Up Next; the slash
command layers strategic framing on top — why #N first, what binds the
sequence. Falls back to plain priority order on a low-context wrap.>

## What NOT to do

<Anti-targets with rationale. Synthesized from: scheduled-agent reminders
firing in the future, memory entries flagged as session-applicable, and
explicit user statements during wrap. Empty if no anti-targets surfaced.>

## Context you'll need

- `CLAUDE.md` and any `CLAUDE.local.md` for project + collaborator context
- `docs/project-board.md` — board conventions
- Plan/spec files referenced in the active issues' `## Planning` sections
- Saved memory entries cited in the prior session

## Quick health check on session start

<Only emitted when the board defines `## Session start checks`. The
slash command runs `jared next-session-prompt --include-session-checks`
to get this rendered.>

## To start

Read the sections above, decide which issue to pull, then:

```
/jared-start <#N>
```
```

- [ ] **Step 2: Update `project-board.md.template` with documented config sections**

Edit `skills/jared/assets/project-board.md.template`. Append after the existing "Further conventions" section (after current line 99):

```markdown

## Jared config

Project-level knobs that change Jared's behavior on this board. Each bullet is `name: value`. Omit any line to use its default.

- `session-handoff-prompt: ask` — when `/jared-wrap` finishes, ask whether to draft a session handoff prompt for the next session. Values: `ask` (default), `always`, `never`. Used by `/jared-wrap`. The prompt is written to `tmp/next-session-prompt-<TIMESTAMP>.md` and is `.gitignore`d — ephemeral by design.

## Session start checks

Operational commands that the session handoff prompt should embed in its "Quick health check on session start" section. Each fenced ```bash block is one check command; the slash command runs `jared next-session-prompt --include-session-checks` to render them. Omit the section if you don't want any.

Example for a project with a Docker-hosted operator and a sqlite pipeline:

\`\`\`bash
${CLAUDE_PLUGIN_ROOT}/skills/jared/scripts/jared summary
\`\`\`

\`\`\`bash
ssh docker.lan 'sudo -u lad docker compose -f /opt/stacks/<project>/compose.yaml ps'
\`\`\`

These commands are user-authored and user-maintained. Jared does not infer them; if they rot, that's your signal to refresh them.
```

(Note: in the actual file, the example's ` ```bash ` fences should be literal triple-backtick fences, not escaped. The escaping above is only for embedding the template inside this plan document.)

- [ ] **Step 3: Verify `.gitignore` covers `tmp/next-session-prompt-*.md`**

Run: `cat .gitignore`

If `tmp/` is already listed (or `tmp/*`), no change needed. If not, append:

```
# Session handoff prompts — ephemeral, regenerated each /jared-wrap.
tmp/next-session-prompt-*.md
```

Commit only if a change was made to `.gitignore`.

- [ ] **Step 4: Confirm test suite still passes**

Run: `pytest`

Expected: all unit tests still pass (templates aren't exercised by tests directly; this is a sanity sweep).

- [ ] **Step 5: Commit**

```bash
git add skills/jared/assets/next-session-prompt.md.template skills/jared/assets/project-board.md.template
# Add .gitignore only if changed:
git status .gitignore && git add .gitignore || true
git commit -m "$(cat <<'EOF'
feat(assets): templates + project-board config docs (#35, phase 2.3)

- New skills/jared/assets/next-session-prompt.md.template with the
  five-section default scaffold (Frame, What's likely…, What NOT
  to do, Context, Health check, To start).
- project-board.md.template documents the new ## Jared config and
  ## Session start checks sections that Board now parses.
- .gitignore covers tmp/next-session-prompt-*.md when not already
  matched by tmp/.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Phase 3: `/jared-wrap` slash command extension

**Phase outcome:** `commands/jared-wrap.md` is updated so that, after Step 6 (the existing close-out summary), Claude offers to draft the session handoff prompt and writes it to `tmp/next-session-prompt-<TIMESTAMP>.md` when accepted. Pure documentation/instructions change — no code, no tests; the contract is the markdown.

### Task 3.1: Extend the slash command

**Files:**
- Modify: `commands/jared-wrap.md`

- [ ] **Step 1: Read the current command file**

Run: `cat commands/jared-wrap.md`

Confirm it matches the structure read during the spec phase. The current step 6 prints the close-out summary.

- [ ] **Step 2: Replace step 6 and add a new step 7**

Edit `commands/jared-wrap.md`. Replace the existing step 6 line:

```
6. **Confirm and close out.** Print a one-line summary: "Wrapped N issues, filed N new, archived N plans, reconciled N drift items. Ready for next session."
```

with:

```
6. **Confirm and close out.** Print a one-line summary: "Wrapped N issues, filed N new, archived N plans, reconciled N drift items. Ready for next session."

7. **Offer the session handoff prompt.** Read the board's `session-handoff-prompt` config (parse `## Jared config` in `docs/project-board.md`):

   - `never` → skip this step entirely.
   - `always` → produce the prompt without asking.
   - `ask` (default, or absent) → ask: *"Draft a session-start prompt for the next session? (y/n)"* and only proceed on `y`.

   When producing the prompt:

   1. Generate the board-derived skeleton:

      ```bash
      ${CLAUDE_PLUGIN_ROOT}/skills/jared/scripts/jared next-session-prompt --include-session-checks
      ```

      Always pass `--include-session-checks`; the CLI no-ops the section when the board has no `## Session start checks` configured.

   2. Layer **synthesis** on top using this session's conversation context, the Session notes you just posted, and any saved memory entries that surfaced. Fill in the asset template at `${CLAUDE_PLUGIN_ROOT}/skills/jared/assets/next-session-prompt.md.template` (or use it as scaffolding):

      - **Frame** — 1–3 sentences on what shipped, what's load-bearing right now, the strategic posture for next session.
      - **What's likely to want attention this session** — ordered list with reasoning ("#N first because the binding constraint is X, not Y"). Pulls from Up Next + In Progress + your synthesis. If synthesis is thin (short session, few decisions), fall back to a plain priority-ordered bullet list.
      - **What NOT to do** — anti-targets with rationale. Sources: scheduled-agent reminders firing in the future, memory entries flagged as session-applicable, explicit user statements during the wrap (e.g. "don't pursue #X yet, we agreed to wait for the agent fire on Y"). Empty if no anti-targets surfaced.
      - **Context you'll need** — pointers to `CLAUDE.md` / `CLAUDE.local.md`, plan/spec files referenced in active issues' `## Planning` sections, relevant memory entry names.
      - **Quick health check on session start** — present iff the board has `## Session start checks` configured.
      - **To start** — call-to-action: *"`/jared-start <#N>` for the issue you decide to pull."*

   3. Write the result to `tmp/next-session-prompt-<YYYY-MM-DD-HHMM>.md` (timestamp = local time). Use `mkdir -p tmp` if `tmp/` doesn't exist. The file is `.gitignore`d (see `.gitignore`) — ephemeral, regenerated each wrap, never authoritative.

   4. End the wrap by telling the user: *"Handoff prompt at `tmp/next-session-prompt-<TIMESTAMP>.md`. Pipe it into your next session and clear when ready."*

   **Important contract.** The prompt is **derived**, not authoritative. Session notes on issues, plans, specs, and memory entries are the durable records. The prompt is a one-shot bridge between sessions and is regenerated next wrap. **Do not edit the prompt to record decisions** — capture them on issues, in plans, or as memory entries. The prompt's footer reminds the reader of this; honor it.

The next session's `/jared` or auto-orientation reads these Session notes directly. The handoff prompt is an additional convenience for queue-heavy projects.
```

(Replace the final paragraph after step 6 — the "The next session's…" line — with the version above; the new closing paragraph clarifies the prompt is *additional*, not replacement.)

- [ ] **Step 3: Smoke-check the file renders correctly**

Run: `cat commands/jared-wrap.md | head -100`

Expected: the new step 7 sits cleanly under step 6, code blocks intact, no broken markdown.

- [ ] **Step 4: Run the test suite for sanity**

Run: `pytest`

Expected: all tests still pass (this phase only edits a markdown command; nothing in code changed).

- [ ] **Step 5: Commit**

```bash
git add commands/jared-wrap.md
git commit -m "$(cat <<'EOF'
feat(wrap): extend /jared-wrap with optional handoff prompt (#35, phase 3)

Adds step 7 to commands/jared-wrap.md: ask (or auto-act per
session-handoff-prompt config), call jared next-session-prompt for
the skeleton, layer synthesis, write to tmp/next-session-prompt-
<TIMESTAMP>.md (gitignored). Contract: derived, ephemeral, never
authoritative.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Phase 4: Doctrine alignment + version bump

**Phase outcome:** SKILL.md anti-pattern bullet reframed (not "no prompts," but "no hand-rolled prompts outside `/jared-wrap`"). `references/session-continuity.md` gains an "Optional handoff prompt" section explaining the contract. Plugin version bumps `0.3.1 → 0.4.0` (changes `/jared-wrap` semantics; minor bump is right).

### Task 4.1: Reframe SKILL.md line 218

**Files:**
- Modify: `skills/jared/SKILL.md`

- [ ] **Step 1: Locate the line**

Run: `grep -n "next-session prompt" skills/jared/SKILL.md`

Expected: at least one match, including the anti-pattern line and a reference to `session-continuity.md`.

- [ ] **Step 2: Replace the anti-pattern bullet**

Find the line in `skills/jared/SKILL.md` that reads:

```
- **Writing a next-session prompt.** Use `/jared-wrap` instead.
```

Replace with:

```
- **Hand-rolling a next-session prompt outside `/jared-wrap`.** If you want one, ask `/jared-wrap` for it — the wrap-time prompt is derived from durable records (Session notes, board, memory) and stays ephemeral; a hand-rolled tmp file becomes a parallel source of truth and rots. See `references/session-continuity.md` § "Optional handoff prompt".
```

- [ ] **Step 3: Verify the change**

Run: `grep -n "Hand-rolling a next-session" skills/jared/SKILL.md`

Expected: one match.

- [ ] **Step 4: Commit**

```bash
git add skills/jared/SKILL.md
git commit -m "$(cat <<'EOF'
docs(skill): reframe next-session-prompt anti-pattern (#35, phase 4.1)

The original bullet treated *all* next-session prompts as the
anti-pattern. The actual problem is hand-rolled prompts that become
parallel sources of truth. /jared-wrap-derived prompts are ephemeral,
sourced from durable records, and bridge sessions safely — that's
fine. Reframed the bullet to make this distinction.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

### Task 4.2: Add new section to `session-continuity.md`

**Files:**
- Modify: `skills/jared/references/session-continuity.md`

- [ ] **Step 1: Append the new section**

Open `skills/jared/references/session-continuity.md`. After the existing "Why this beats tmp/handoff-prompt.md" section (around line 161), and before "Migrating away from existing tmp prompts", insert:

```markdown
## Optional handoff prompt

For projects with long, well-defined queues — findajob, trailscribe — Session notes capture per-issue state but can't capture cross-issue narrative or the strategic frame that makes "what to pull next" obvious. The optional handoff prompt fills that gap.

**The contract:**

- **Derived.** The prompt is generated by `/jared-wrap` from durable records: posted Session notes, board state, memory entries, the just-finished session's conversation. Nothing in the prompt is the source of truth — every claim points back at one of those records.
- **Ephemeral.** Written to `tmp/next-session-prompt-<TIMESTAMP>.md`. `.gitignore`d. Regenerated each wrap. The footer warns against editing.
- **Opt-in.** `docs/project-board.md` can declare `session-handoff-prompt: always | ask | never` under `## Jared config`. Default is `ask` — `/jared-wrap` asks at the end of every wrap. Projects without the config get prompted; projects that say `never` are never asked.
- **Complementary, not replacement.** The next session still reads Session notes (via `/jared` auto-orientation) and uses `/jared-start <#>` to drill into a specific issue. The handoff prompt sits at the *session* level — picking which issue to pull. `/jared-start` operates at the *issue* level — drilling into the one you picked.

**Two-layer generation:**

1. **CLI skeleton.** `${CLAUDE_PLUGIN_ROOT}/skills/jared/scripts/jared next-session-prompt` emits the board-derived sections deterministically: In flight (with last-Session-note one-liners), Top of Up Next, Recently closed (7d), kickoff footer. Useful on its own for retroactive handoff after a wrap-less session.
2. **Synthesis layer.** `/jared-wrap` calls the CLI for the skeleton, then layers in Frame, What NOT to do, and (optionally) a Quick health check section using the board's `## Session start checks`. The synthesis comes from the wrap session's conversation context — that's the only place it lives.

**When the wrap is low-context** (short session, few decisions), the synthesis sections collapse to plain board-derived bullets. The prompt degrades gracefully — board state alone is still better than starting cold.

**The anti-pattern that remains.** Hand-rolling a `tmp/next-session-prompt.md` outside `/jared-wrap` is still wrong: the file becomes a parallel source of truth, the durable records drift, and the discipline rots. If you want a handoff prompt, ask `/jared-wrap` for it.
```

- [ ] **Step 2: Verify the section reads cleanly**

Run: `grep -n "## Optional handoff prompt" skills/jared/references/session-continuity.md`

Expected: one match.

- [ ] **Step 3: Commit**

```bash
git add skills/jared/references/session-continuity.md
git commit -m "$(cat <<'EOF'
docs(reference): add Optional handoff prompt section (#35, phase 4.2)

Documents the contract for /jared-wrap-generated handoff prompts:
derived from durable records, ephemeral, opt-in via project config,
complementary to (not replacing) Session notes and /jared-start.
Calls out the graceful-degradation rule for low-context wraps.
Reaffirms the anti-pattern: hand-rolled prompts outside /jared-wrap.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

### Task 4.3: Bump plugin version to 0.4.0

**Files:**
- Modify: `.claude-plugin/plugin.json`

- [ ] **Step 1: Bump the version**

Edit `.claude-plugin/plugin.json`. Change:

```json
  "version": "0.3.1",
```

to:

```json
  "version": "0.4.0",
```

- [ ] **Step 2: Verify**

Run: `grep '"version"' .claude-plugin/plugin.json`

Expected: `"version": "0.4.0",`

- [ ] **Step 3: Run the full test suite a final time**

Run: `pytest`

Expected: all unit tests pass.

Run: `ruff check . && ruff format --check . && mypy`

Expected: clean.

- [ ] **Step 4: Commit**

```bash
git add .claude-plugin/plugin.json
git commit -m "$(cat <<'EOF'
chore(plugin): bump version 0.3.1 → 0.4.0 (#35, phase 4.3)

/jared-wrap now offers an optional session handoff prompt;
that's a user-visible change to the wrap workflow. Minor bump.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

### Task 4.4: Open the PR

- [ ] **Step 1: Push the branch**

```bash
git push -u origin feature/wrap-next-session-prompt
```

- [ ] **Step 2: Open the PR**

```bash
gh pr create --title "feat: optional session handoff prompt for /jared-wrap (#35)" --body "$(cat <<'EOF'
## Summary

- New `jared next-session-prompt` CLI subcommand emits a board-derived markdown skeleton (In flight + last Session note one-liners, Up Next, Recently closed, kickoff footer).
- `/jared-wrap` extended with an optional Step 7 that calls the CLI for the skeleton, layers conversation-context synthesis (Frame, What NOT to do, Health check) on top, and writes the result to `tmp/next-session-prompt-<TIMESTAMP>.md` (gitignored).
- New per-project config under `## Jared config` (`session-handoff-prompt: ask|always|never`) and `## Session start checks` (fenced bash blocks). Defaults preserve current behavior for boards that don't opt in.
- SKILL.md line 218 anti-pattern reframed; `references/session-continuity.md` gains an "Optional handoff prompt" section explaining the contract.
- Plugin version bumps 0.3.1 → 0.4.0.

Closes #35.

## Test plan

- [ ] `pytest` — full unit suite passes (5 new tests on `next-session-prompt`, 2 new tests on `Board` config parsing).
- [ ] `ruff check . && ruff format --check . && mypy` — clean.
- [ ] Run `${CLAUDE_PLUGIN_ROOT}/skills/jared/scripts/jared next-session-prompt` against the jared board manually; confirm In flight / Up Next / Recently closed render correctly.
- [ ] Run `${CLAUDE_PLUGIN_ROOT}/skills/jared/scripts/jared next-session-prompt --include-session-checks` against a board without `## Session start checks` and confirm no health-check section appears.
- [ ] After merge, `/plugin update jared` then `/jared-wrap` end-to-end on the jared project; verify the handoff prompt is offered, written to `tmp/next-session-prompt-*.md`, and contains the expected sections.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

- [ ] **Step 3: Confirm CI passes**

Wait for any configured CI to land green. If a hook or check fails, investigate and fix the underlying issue (do not skip hooks per `feedback_jared_git_workflow`).

---

## Self-review checklist

After all phases complete, before declaring done:

- [ ] **Spec coverage.** Each section of `docs/superpowers/specs/2026-04-25-jared-wrap-next-session-prompt-design.md` maps to at least one task above. Specifically:
  - "Two layers of generation" → Phase 1 (CLI) + Phase 3 (slash command)
  - "Prompt structure" → Phase 2.3 (asset template) + Phase 3 (slash command instructions)
  - "Opt-in mechanism" → Phase 2.1 (Board config) + Phase 3 (slash command honors it)
  - "Relationship to /jared-start" → Phase 4.2 (session-continuity.md update)
  - "Anti-pattern reconciliation" → Phase 4.1 (SKILL.md edit)
  - "Files touched" → all phases
- [ ] **No placeholders** in the plan (no TBDs, no "implement appropriately"). Confirmed during writing.
- [ ] **Type/name consistency.** `Board.session_handoff_prompt`, `Board.session_start_checks`, `_cmd_next_session_prompt`, `_fetch_board_items`, `_fetch_recently_closed`, `_render_in_flight`, `_latest_session_note_oneliner`, `_extract_next_action`, `_date_n_days_ago`, `_now_local_iso` — all consistent across phases.
- [ ] **Verification folded into phases** per `feedback_deferred_verification_drift`. Each phase ends with tests + ruff + mypy + commit; no "verify later" deferred.

## Execution Handoff

**Plan complete and saved to `docs/superpowers/plans/2026-04-25-jared-wrap-next-session-prompt.md`. Two execution options:**

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints

**Which approach?**
