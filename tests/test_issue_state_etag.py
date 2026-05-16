"""Tests for the ETag/conditional GET layer on fetch_issue_state_rest (#147).

The ETag layer wraps `fetch_issue_state_rest`:
  - First call: `gh api -i` returns 200 with headers + body. The wrapper
    captures the ETag and writes both etag + body to disk.
  - Second call: sends `If-None-Match: <etag>` and gets 304 (exit 1, no
    body). The wrapper recognizes 304 and returns the cached body.
  - JARED_NO_CACHE=1 falls back to the unconditional REST path tested
    elsewhere.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest

from skills.jared.scripts.lib import cache


def _make_200_response(etag: str, body_json: str) -> str:
    """Build a `gh api -i` 200 response: status line, headers, blank, body."""
    return (
        "HTTP/2.0 200 OK\r\n"
        "Content-Type: application/json; charset=utf-8\r\n"
        f"Etag: {etag}\r\n"
        "\r\n"
        f"{body_json}"
    )


def _make_304_response(etag: str) -> tuple[str, str, int]:
    """Build a `gh api -i` 304 response shape (stdout, stderr, returncode).

    Mirrors the empirical shape verified against `gh api -i repos/cli/cli/issues/1
    -H 'If-None-Match: ...'`: stdout has headers only (no body), stderr is
    `gh: HTTP 304`, exit code is 1.
    """
    stdout = f"HTTP/2.0 304 Not Modified\r\nEtag: {etag}\r\n\r\n"
    return stdout, "gh: HTTP 304", 1


def test_first_call_with_empty_cache_sends_no_conditional_header(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cache miss path: no If-None-Match header in the gh args."""
    from skills.jared.scripts.lib import board

    captured: list[list[str]] = []

    class FakeResult:
        returncode = 0
        stdout = _make_200_response('W/"abc123"', '{"state": "open"}')
        stderr = ""

    def fake_run(args: list[str], **kw: Any) -> FakeResult:
        captured.append(args)
        return FakeResult()

    monkeypatch.setattr("skills.jared.scripts.lib.board.subprocess.run", fake_run)

    state, _closed_at = board.fetch_issue_state_rest("brockamer/jared", 52)
    assert state == "OPEN"
    assert len(captured) == 1
    args = captured[0]
    assert args[:3] == ["gh", "api", "-i"]
    assert "If-None-Match:" not in " ".join(args)


def test_first_call_writes_etag_and_body_to_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A successful 200 response must populate the on-disk ETag cache."""
    from skills.jared.scripts.lib import board

    class FakeResult:
        returncode = 0
        stdout = _make_200_response(
            'W/"abc123"', '{"state": "closed", "closed_at": "2026-05-16T10:00:00Z"}'
        )
        stderr = ""

    monkeypatch.setattr(
        "skills.jared.scripts.lib.board.subprocess.run",
        lambda *a, **kw: FakeResult(),
    )

    state, closed_at = board.fetch_issue_state_rest("brockamer/jared", 52)
    assert state == "CLOSED"
    assert closed_at == "2026-05-16T10:00:00Z"

    cache_dir = Path(os.environ["JARED_CACHE_DIR"])
    cached = cache.get_issue_etag("brockamer/jared", 52, cache_dir=cache_dir)
    assert cached is not None
    etag, body = cached
    assert etag == 'W/"abc123"'
    assert body["state"] == "closed"
    assert body["closed_at"] == "2026-05-16T10:00:00Z"


def test_second_call_sends_conditional_header_and_uses_cached_body_on_304(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With a cached ETag, the wrapper sends If-None-Match and returns cached body on 304."""
    from skills.jared.scripts.lib import board

    cache_dir = Path(os.environ["JARED_CACHE_DIR"])
    cache.set_issue_etag(
        "brockamer/jared",
        52,
        etag='W/"abc123"',
        body={
            "state": "closed",
            "closed_at": "2026-05-16T10:00:00Z",
            "pull_request": None,
        },
        cache_dir=cache_dir,
    )

    captured: list[list[str]] = []
    stdout_304, stderr_304, rc_304 = _make_304_response('"abc123"')

    class FakeResult:
        returncode = rc_304
        stdout = stdout_304
        stderr = stderr_304

    def fake_run(args: list[str], **kw: Any) -> FakeResult:
        captured.append(args)
        return FakeResult()

    monkeypatch.setattr("skills.jared.scripts.lib.board.subprocess.run", fake_run)

    state, closed_at = board.fetch_issue_state_rest("brockamer/jared", 52)
    assert state == "CLOSED"
    assert closed_at == "2026-05-16T10:00:00Z"

    args = captured[0]
    assert "-H" in args
    h_idx = args.index("-H")
    assert args[h_idx + 1] == 'If-None-Match: W/"abc123"'


def test_304_with_pull_request_merged_at_returns_merged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The cached body must round-trip through _parse_issue_state_payload so
    merged PRs keep reporting as MERGED even when served from the 304 path."""
    from skills.jared.scripts.lib import board

    cache_dir = Path(os.environ["JARED_CACHE_DIR"])
    cache.set_issue_etag(
        "brockamer/jared",
        415,
        etag='W/"pr-merged"',
        body={
            "state": "closed",
            "closed_at": "2026-05-02T15:30:00Z",
            "pull_request": {"merged_at": "2026-05-02T15:30:00Z"},
        },
        cache_dir=cache_dir,
    )

    stdout_304, stderr_304, rc_304 = _make_304_response('"pr-merged"')

    class FakeResult:
        returncode = rc_304
        stdout = stdout_304
        stderr = stderr_304

    monkeypatch.setattr(
        "skills.jared.scripts.lib.board.subprocess.run",
        lambda *a, **kw: FakeResult(),
    )

    state, _ = board.fetch_issue_state_rest("brockamer/jared", 415)
    assert state == "MERGED"


def test_no_cache_env_var_bypasses_etag_layer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """JARED_NO_CACHE=1 skips `-i` and conditional GET entirely."""
    monkeypatch.setenv("JARED_NO_CACHE", "1")
    from skills.jared.scripts.lib import board

    captured: list[list[str]] = []

    class FakeResult:
        returncode = 0
        stdout = '{"state": "open"}'
        stderr = ""

    def fake_run(args: list[str], **kw: Any) -> FakeResult:
        captured.append(args)
        return FakeResult()

    monkeypatch.setattr("skills.jared.scripts.lib.board.subprocess.run", fake_run)

    state, _ = board.fetch_issue_state_rest("brockamer/jared", 99)
    assert state == "OPEN"
    args = captured[0]
    assert "-i" not in args
    assert "If-None-Match:" not in " ".join(args)


def test_gh_failure_without_http_status_returns_unknown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Network failure / bad invocation surfaces UNKNOWN, not a crash."""
    from skills.jared.scripts.lib import board

    class FakeResult:
        returncode = 1
        stdout = ""
        stderr = "gh: connection refused"

    monkeypatch.setattr(
        "skills.jared.scripts.lib.board.subprocess.run",
        lambda *a, **kw: FakeResult(),
    )

    state, closed_at = board.fetch_issue_state_rest("brockamer/jared", 99999)
    assert state == "UNKNOWN"
    assert closed_at is None


def test_304_with_no_cached_body_returns_unknown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If gh returns 304 but the cache is empty (e.g. it was nuked between the
    If-None-Match send and the response read), surface UNKNOWN rather than
    a silent stale read."""
    from skills.jared.scripts.lib import board

    stdout_304, stderr_304, rc_304 = _make_304_response('"abc123"')

    class FakeResult:
        returncode = rc_304
        stdout = stdout_304
        stderr = stderr_304

    monkeypatch.setattr(
        "skills.jared.scripts.lib.board.subprocess.run",
        lambda *a, **kw: FakeResult(),
    )

    state, _ = board.fetch_issue_state_rest("brockamer/jared", 52)
    assert state == "UNKNOWN"


def test_corrupt_cache_falls_through_to_fresh_fetch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A malformed cache file must be treated as a miss so a normal 200 fetch
    repopulates it. The wrapper should not crash on parse errors."""
    from skills.jared.scripts.lib import board

    cache_dir = Path(os.environ["JARED_CACHE_DIR"])
    path = cache_dir / "etags" / "brockamer" / "jared" / "52.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not valid json")

    captured: list[list[str]] = []

    class FakeResult:
        returncode = 0
        stdout = _make_200_response('W/"new"', '{"state": "open"}')
        stderr = ""

    def fake_run(args: list[str], **kw: Any) -> FakeResult:
        captured.append(args)
        return FakeResult()

    monkeypatch.setattr("skills.jared.scripts.lib.board.subprocess.run", fake_run)

    state, _ = board.fetch_issue_state_rest("brockamer/jared", 52)
    assert state == "OPEN"
    assert "If-None-Match:" not in " ".join(captured[0])

    cached = cache.get_issue_etag("brockamer/jared", 52, cache_dir=cache_dir)
    assert cached is not None
    assert cached[0] == 'W/"new"'
