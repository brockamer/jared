"""Tests for bootstrap-project.py's link_project_to_repo helper (#25)."""

import json

import pytest

from tests.conftest import FakeGhResult, import_bootstrap


def _patch_graphql_responses(
    monkeypatch: pytest.MonkeyPatch, responses: dict[str, str]
) -> list[list[str]]:
    """Route `gh api graphql` calls by substring match on the serialized
    query payload. Responses are raw JSON strings.
    """
    calls: list[list[str]] = []

    def fake_run(args: list[str], **kw: object) -> FakeGhResult:
        calls.append(args)
        joined = " ".join(args)
        for substring, stdout in responses.items():
            if substring in joined:
                return FakeGhResult(stdout=stdout)
        return FakeGhResult(stdout="{}")

    monkeypatch.setattr(
        "skills.jared.scripts.lib.board.subprocess.run",
        fake_run,
    )
    return calls


def test_link_happy_path(monkeypatch: pytest.MonkeyPatch) -> None:
    mod = import_bootstrap()
    calls = _patch_graphql_responses(
        monkeypatch,
        {
            "repository(owner:": json.dumps(
                {"data": {"repository": {"id": "R_kgDOabc"}}}
            ),
            "linkProjectV2ToRepository": json.dumps(
                {"data": {"linkProjectV2ToRepository": {"repository": {"id": "R_kgDOabc"}}}}
            ),
        },
    )

    ok, msg = mod.link_project_to_repo("PVT_test", "brockamer/trailscribe")

    assert ok is True, msg
    assert "brockamer/trailscribe" in msg
    # Must have made both the repo-id lookup and the mutation.
    assert any("repository(owner:" in " ".join(c) for c in calls)
    assert any("linkProjectV2ToRepository" in " ".join(c) for c in calls)


def test_link_invalid_slug_returns_false(monkeypatch: pytest.MonkeyPatch) -> None:
    mod = import_bootstrap()
    calls = _patch_graphql_responses(monkeypatch, {})

    ok, msg = mod.link_project_to_repo("PVT_test", "just-a-repo")

    assert ok is False
    assert "invalid" in msg.lower() or "slug" in msg.lower()
    # No gh calls on malformed input.
    assert calls == []


def test_link_repo_id_missing_returns_false(monkeypatch: pytest.MonkeyPatch) -> None:
    mod = import_bootstrap()
    _patch_graphql_responses(
        monkeypatch,
        {"repository(owner:": json.dumps({"data": {"repository": None}})},
    )

    ok, msg = mod.link_project_to_repo("PVT_test", "brockamer/nonexistent")

    assert ok is False


def test_link_gh_error_does_not_raise(monkeypatch: pytest.MonkeyPatch) -> None:
    """Permission / already-linked / network errors should return (False, msg),
    not propagate — #25 requires warn-don't-abort behavior."""
    mod = import_bootstrap()

    def fake_run(args: list[str], **kw: object) -> FakeGhResult:
        # Simulate gh api failure (nonzero exit).
        return FakeGhResult(stdout="", returncode=1, stderr="HTTP 403")

    monkeypatch.setattr("skills.jared.scripts.lib.board.subprocess.run", fake_run)

    ok, msg = mod.link_project_to_repo("PVT_test", "brockamer/restricted")

    assert ok is False
    assert msg  # Some diagnostic, not empty.
