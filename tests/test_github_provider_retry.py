"""Tests for transient-read retry on GitHubProjectsProvider (#342).

`jared migrate` reads from the GitHub source via list_open_items /
fetch_blocked_by_edges / list_comments, which raise GhInvocationError on a
transient GitHub failure (the flaky `read:project` scope rejection, HTTP 401
"Requires authentication", 5xx, secondary rate limits). Before #342 a single
blip aborted the whole migration. These tests pin the retry behaviour:

- transient failures retry with bounded backoff, then succeed (criteria 1-2);
- a genuinely persistent failure surfaces a clear error after retries are
  exhausted — retry never masks a real auth misconfiguration (criterion 3);
- terminal (non-transient) errors raise immediately, no wasted retries.

The module-level `_sleep` seam is patched so the suite never actually sleeps.
"""

from __future__ import annotations

import json

import pytest

from skills.jared.scripts.lib import github_provider as gp
from skills.jared.scripts.lib.board import GhInvocationError
from skills.jared.scripts.lib.github_provider import (
    _MAX_READ_RETRIES,
    _backoff,
    _is_transient_gh_error,
    _retry_transient_read,
)


@pytest.fixture(autouse=True)
def _no_real_sleep(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    """Patch the module-level _sleep seam; record the durations it was asked to wait."""
    waited: list[float] = []
    monkeypatch.setattr(gp, "_sleep", lambda s: waited.append(s))
    return waited


# --------------------------------------------------------------------------- #
# _is_transient_gh_error — the transient/terminal classifier                   #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "message",
    [
        "gh api graphql exited 1: gh: Requires authentication (HTTP 401)",
        "gh api graphql exited 1: gh: Bad credentials (HTTP 401)",
        "gh api graphql exited 1: HTTP 401: Bad credentials",
        "gh api graphql exited 1: Resource not accessible by personal access token",
        "gh issue view 5 exited 1: HTTP 502: Bad gateway",
        "gh api graphql exited 1: HTTP 503 Service Unavailable",
        "gh api graphql exited 1: HTTP 500 Internal Server Error",
        "gh issue view 5 exited 1: You have exceeded a secondary rate limit",
        "gh api graphql exited 1: HTTP 429: too many requests",
        # GraphQL insufficient-scopes wire form: HTTP 200 + errors[], so gh's
        # stderr carries NO status line — only the message text. NOT locally
        # observed (the PR #341 occurrence was the 401 form); added defensively
        # from GitHub's documented GraphQL error phrasing per the #342 review.
        "gh api graphql exited 1: gh: Your token has not been granted the required "
        "scopes to execute this query. The 'id' field requires one of the following "
        "scopes: ['read:project'], but your token has only been granted the: [] scopes.",
    ],
)
def test_is_transient_accepts_known_transient_signatures(message: str) -> None:
    assert _is_transient_gh_error(GhInvocationError(message)) is True


@pytest.mark.parametrize(
    "message",
    [
        "gh issue view 9999 exited 1: HTTP 404: Not Found",
        "gh api graphql exited 1: HTTP 422: Validation failed",
        "gh api graphql exited 1: HTTP 403: Forbidden",  # genuine permission, not rate limit
        "gh returned non-JSON output: <html>...",
        # list_open_items' own pagination guard must NOT be retried.
        "list_open_items() query returned hasNextPage=true; >100 open issues",
    ],
)
def test_is_transient_rejects_terminal_signatures(message: str) -> None:
    assert _is_transient_gh_error(GhInvocationError(message)) is False


# --------------------------------------------------------------------------- #
# _retry_transient_read — the bounded-backoff retry wrapper                     #
# --------------------------------------------------------------------------- #


def test_retry_returns_immediately_when_call_succeeds(_no_real_sleep: list[float]) -> None:
    calls = {"n": 0}

    def fn() -> str:
        calls["n"] += 1
        return "ok"

    assert _retry_transient_read(fn) == "ok"
    assert calls["n"] == 1
    assert _no_real_sleep == []  # no sleep on the happy path


def test_retry_recovers_after_transient_failures(_no_real_sleep: list[float]) -> None:
    calls = {"n": 0}

    def fn() -> str:
        calls["n"] += 1
        if calls["n"] < 3:
            raise GhInvocationError("gh api graphql exited 1: HTTP 401: Requires authentication")
        return "recovered"

    assert _retry_transient_read(fn) == "recovered"
    assert calls["n"] == 3  # failed twice, succeeded on the third attempt
    # bounded EXPONENTIAL backoff, not just "some sleeps" — guards against the
    # schedule silently collapsing to 0s (criterion: "bounded backoff").
    assert _no_real_sleep == [1.0, 2.0]


def test_backoff_is_bounded_exponential() -> None:
    assert [_backoff(n) for n in (0, 1, 2, 3)] == [1.0, 2.0, 4.0, 8.0]
    assert _backoff(20) == 30.0  # capped, never unbounded


def test_retry_raises_the_transient_error_after_exhaustion(_no_real_sleep: list[float]) -> None:
    """A genuinely persistent failure (e.g. a token actually missing project scope)
    must surface clearly after retries are exhausted — never silently swallowed."""
    calls = {"n": 0}
    persistent = GhInvocationError(
        "gh api graphql exited 1: Resource not accessible by personal access token"
    )

    def fn() -> str:
        calls["n"] += 1
        raise persistent

    with pytest.raises(GhInvocationError) as excinfo:
        _retry_transient_read(fn)

    assert excinfo.value is persistent  # the real error is surfaced, not masked
    assert calls["n"] == _MAX_READ_RETRIES + 1  # initial attempt + all retries
    assert len(_no_real_sleep) == _MAX_READ_RETRIES


def test_retry_does_not_retry_terminal_errors(_no_real_sleep: list[float]) -> None:
    calls = {"n": 0}

    def fn() -> str:
        calls["n"] += 1
        raise GhInvocationError("gh issue view 9999 exited 1: HTTP 404: Not Found")

    with pytest.raises(GhInvocationError):
        _retry_transient_read(fn)

    assert calls["n"] == 1  # raised on the first attempt, no retry
    assert _no_real_sleep == []  # and no backoff sleep


def test_retry_emits_a_stderr_note_on_transient(
    _no_real_sleep: list[float], capsys: pytest.CaptureFixture[str]
) -> None:
    """A retry is announced on stderr so the operator sees why migrate paused —
    the recovery is bounded, not silent."""
    calls = {"n": 0}

    def fn() -> str:
        calls["n"] += 1
        if calls["n"] < 2:
            raise GhInvocationError("gh api graphql exited 1: HTTP 502: Bad gateway")
        return "ok"

    _retry_transient_read(fn)
    err = capsys.readouterr().err.lower()
    assert "retr" in err  # mentions retrying


# --------------------------------------------------------------------------- #
# Wiring — the provider read methods route through the retry wrapper            #
# --------------------------------------------------------------------------- #


def _provider() -> gp.GitHubProjectsProvider:
    return gp.GitHubProjectsProvider(
        project_number=7,
        project_id="PVT_x",
        owner="brockamer",
        repo="brockamer/findajob",
        field_ids={"Status": "F1", "Priority": "F2"},
        field_options={
            "Status": {"Backlog": "OID_B", "Up Next": "OID_U", "In Progress": "OID_I"},
            "Priority": {"High": "OID_H", "Medium": "OID_M", "Low": "OID_L"},
        },
    )


_EMPTY_OPEN_ITEMS = json.dumps(
    {"data": {"repository": {"issues": {"pageInfo": {"hasNextPage": False}, "nodes": []}}}}
)


def test_list_open_items_recovers_from_a_transient_read(
    monkeypatch: pytest.MonkeyPatch, _no_real_sleep: list[float]
) -> None:
    calls = {"n": 0}

    def fake_graphql(query: str, **kwargs: object) -> object:
        calls["n"] += 1
        if calls["n"] < 2:
            raise GhInvocationError("gh api graphql exited 1: HTTP 401: Requires authentication")
        return json.loads(_EMPTY_OPEN_ITEMS)

    monkeypatch.setattr(gp, "run_graphql", fake_graphql)

    assert _provider().list_open_items() == []
    assert calls["n"] == 2  # one transient failure, then success


def test_list_open_items_surfaces_a_persistent_scope_error(
    monkeypatch: pytest.MonkeyPatch, _no_real_sleep: list[float]
) -> None:
    def always_scope_error(query: str, **kwargs: object) -> object:
        raise GhInvocationError(
            "gh api graphql exited 1: Resource not accessible by personal access token"
        )

    monkeypatch.setattr(gp, "run_graphql", always_scope_error)

    with pytest.raises(GhInvocationError, match="personal access token"):
        _provider().list_open_items()


def test_list_comments_recovers_from_a_transient_read(
    monkeypatch: pytest.MonkeyPatch, _no_real_sleep: list[float]
) -> None:
    calls = {"n": 0}

    def fake_run_gh(args: list[str], **kwargs: object) -> object:
        calls["n"] += 1
        if calls["n"] < 2:
            raise GhInvocationError("gh issue view 5 exited 1: HTTP 502: Bad gateway")
        return {"comments": []}

    monkeypatch.setattr(gp, "run_gh", fake_run_gh)

    assert _provider().list_comments(5) == []
    assert calls["n"] == 2


def test_fetch_blocked_by_edges_recovers_from_a_transient_read(
    monkeypatch: pytest.MonkeyPatch, _no_real_sleep: list[float]
) -> None:
    calls = {"n": 0}

    def fake_edges(repo: str, **kwargs: object) -> dict[int, list[dict[str, object]]]:
        calls["n"] += 1
        if calls["n"] < 2:
            raise GhInvocationError("gh api graphql exited 1: HTTP 503 Service Unavailable")
        return {}

    monkeypatch.setattr(gp, "_fetch_blocked_by_edges", fake_edges)

    assert _provider().fetch_blocked_by_edges() == []
    assert calls["n"] == 2


def test_get_body_recovers_from_a_transient_read(
    monkeypatch: pytest.MonkeyPatch, _no_real_sleep: list[float]
) -> None:
    calls = {"n": 0}

    def fake_run_gh(args: list[str], **kwargs: object) -> object:
        calls["n"] += 1
        if calls["n"] < 2:
            raise GhInvocationError(
                "gh api repos/o/r/issues/5 exited 1: gh: Bad gateway (HTTP 502)"
            )
        return {"body": "the real body"}

    monkeypatch.setattr(gp, "run_gh", fake_run_gh)

    assert _provider().get_body(5) == "the real body"
    assert calls["n"] == 2  # one transient failure, then the real body


def test_get_body_surfaces_a_persistent_read_failure(
    monkeypatch: pytest.MonkeyPatch, _no_real_sleep: list[float]
) -> None:
    """A persistent body-read failure must RAISE (criterion 3), never silently
    port an empty body — the migrate data-loss vector the #342 review found."""

    def always_fail(args: list[str], **kwargs: object) -> object:
        raise GhInvocationError(
            "gh api repos/o/r/issues/5 exited 1: gh: Bad credentials (HTTP 401)"
        )

    monkeypatch.setattr(gp, "run_gh", always_fail)

    with pytest.raises(GhInvocationError, match="HTTP 401"):
        _provider().get_body(5)


def test_get_body_returns_empty_for_a_genuinely_absent_body(
    monkeypatch: pytest.MonkeyPatch, _no_real_sleep: list[float]
) -> None:
    """A 200 with no body field is a real empty body, not a failure: return ""
    immediately, no retry (preserves the pre-existing empty-body contract)."""
    calls = {"n": 0}

    def fake_run_gh(args: list[str], **kwargs: object) -> object:
        calls["n"] += 1
        return {"number": 5}  # valid response, body field absent

    monkeypatch.setattr(gp, "run_gh", fake_run_gh)

    assert _provider().get_body(5) == ""
    assert calls["n"] == 1  # no retry on a genuine empty body
