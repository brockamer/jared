"""Tests for the ETag/conditional GET layer on fetch_issue_body_rest (#216).

`fetch_issue_body_rest` is the body-read twin of `fetch_issue_state_rest`
(#147): it rides the same `_fetch_issue_rest_with_etag` layer so a repeat
read of an unchanged body short-circuits to a 304 without spending REST
`core` points, then extracts the `body` field.

  - First call: `gh api -i` returns 200 with headers + body. The wrapper
    captures the ETag and writes both etag + body to disk; the helper
    returns the `body` string.
  - Second call: sends `If-None-Match: <etag>` and gets 304 (exit 1, no
    body). The wrapper returns the cached body; the helper extracts `body`.
  - JARED_NO_CACHE=1 falls back to the unconditional REST path.
  - Any failure mode (network error, 304 with empty cache, missing body
    field) resolves to "" — matching the `data.get("body") or ""` contract
    the two batch call sites already rely on.
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
    """Build a `gh api -i` 304 response shape (stdout, stderr, returncode)."""
    stdout = f"HTTP/2.0 304 Not Modified\r\nEtag: {etag}\r\n\r\n"
    return stdout, "gh: HTTP 304", 1


def test_first_call_with_empty_cache_returns_body_and_no_conditional_header(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cache miss path: returns the body string, no If-None-Match in gh args."""
    from skills.jared.scripts.lib import board

    captured: list[list[str]] = []

    class FakeResult:
        returncode = 0
        stdout = _make_200_response('W/"abc123"', '{"body": "## Context\\nhello"}')
        stderr = ""

    def fake_run(args: list[str], **kw: Any) -> FakeResult:
        captured.append(args)
        return FakeResult()

    monkeypatch.setattr("skills.jared.scripts.lib.board.subprocess.run", fake_run)

    body = board.fetch_issue_body_rest("brockamer/jared", 216)
    assert body == "## Context\nhello"
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
        stdout = _make_200_response('W/"abc123"', '{"body": "the spec"}')
        stderr = ""

    monkeypatch.setattr(
        "skills.jared.scripts.lib.board.subprocess.run",
        lambda *a, **kw: FakeResult(),
    )

    body = board.fetch_issue_body_rest("brockamer/jared", 216)
    assert body == "the spec"

    cache_dir = Path(os.environ["JARED_CACHE_DIR"])
    cached = cache.get_issue_etag("brockamer/jared", 216, cache_dir=cache_dir)
    assert cached is not None
    etag, cached_body = cached
    assert etag == 'W/"abc123"'
    assert cached_body["body"] == "the spec"


def test_second_call_sends_conditional_header_and_uses_cached_body_on_304(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With a cached ETag, send If-None-Match and return cached body on 304."""
    from skills.jared.scripts.lib import board

    cache_dir = Path(os.environ["JARED_CACHE_DIR"])
    cache.set_issue_etag(
        "brockamer/jared",
        216,
        etag='W/"abc123"',
        body={"body": "cached spec text"},
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

    body = board.fetch_issue_body_rest("brockamer/jared", 216)
    assert body == "cached spec text"

    args = captured[0]
    assert "-H" in args
    h_idx = args.index("-H")
    assert args[h_idx + 1] == 'If-None-Match: W/"abc123"'


def test_no_cache_env_var_bypasses_etag_layer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """JARED_NO_CACHE=1 skips `-i` and conditional GET entirely."""
    monkeypatch.setenv("JARED_NO_CACHE", "1")
    from skills.jared.scripts.lib import board

    captured: list[list[str]] = []

    class FakeResult:
        returncode = 0
        stdout = '{"body": "uncached path"}'
        stderr = ""

    def fake_run(args: list[str], **kw: Any) -> FakeResult:
        captured.append(args)
        return FakeResult()

    monkeypatch.setattr("skills.jared.scripts.lib.board.subprocess.run", fake_run)

    body = board.fetch_issue_body_rest("brockamer/jared", 99)
    assert body == "uncached path"
    args = captured[0]
    assert "-i" not in args
    assert "If-None-Match:" not in " ".join(args)


def test_gh_failure_without_http_status_returns_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Network failure / bad invocation surfaces "" rather than crashing."""
    from skills.jared.scripts.lib import board

    class FakeResult:
        returncode = 1
        stdout = ""
        stderr = "gh: connection refused"

    monkeypatch.setattr(
        "skills.jared.scripts.lib.board.subprocess.run",
        lambda *a, **kw: FakeResult(),
    )

    body = board.fetch_issue_body_rest("brockamer/jared", 99999)
    assert body == ""


def test_304_with_no_cached_body_returns_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """304 with an empty cache surfaces "" rather than a silent stale read."""
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

    body = board.fetch_issue_body_rest("brockamer/jared", 216)
    assert body == ""


def test_missing_body_field_returns_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A 200 response whose payload has a null/absent body field yields ""."""
    from skills.jared.scripts.lib import board

    class FakeResult:
        returncode = 0
        stdout = _make_200_response('W/"nobody"', '{"body": null}')
        stderr = ""

    monkeypatch.setattr(
        "skills.jared.scripts.lib.board.subprocess.run",
        lambda *a, **kw: FakeResult(),
    )

    body = board.fetch_issue_body_rest("brockamer/jared", 216)
    assert body == ""
