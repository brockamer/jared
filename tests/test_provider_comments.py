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
    c1 = '{"author": {"login": "brockamer"}, "body": "first", "createdAt": "2026-06-01T00:00:00Z"}'
    c2 = '{"author": {"login": "octocat"}, "body": "second", "createdAt": "2026-06-02T00:00:00Z"}'
    patch_gh(monkeypatch, stdout=f'{{"comments": [{c1},{c2}]}}')
    comments = _gh_provider().list_comments(318)
    assert comments == [
        Comment(author="brockamer", body="first", created_at="2026-06-01T00:00:00Z"),
        Comment(author="octocat", body="second", created_at="2026-06-02T00:00:00Z"),
    ]


def test_github_list_comments_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    patch_gh(monkeypatch, stdout='{"comments": []}')
    assert _gh_provider().list_comments(318) == []


from tests.fake_kanbanflow import make_kf_provider_with_task  # noqa: E402


def test_kanbanflow_list_comments_resolves_author_name() -> None:
    provider, client, ref = make_kf_provider_with_task(
        users={"u1": "Daniel Brock"},
        comments=[
            {"text": "note one", "createdTimestamp": "2026-06-01T00:00:00Z", "authorUserId": "u1"},
        ],
    )
    comments = provider.list_comments(ref)
    assert comments == [
        Comment(author="Daniel Brock", body="note one", created_at="2026-06-01T00:00:00Z")
    ]
