from __future__ import annotations

import pytest

from skills.jared.scripts.lib.board_provider import Comment
from skills.jared.scripts.lib.github_provider import GitHubProjectsProvider
from tests.conftest import patch_gh, patch_gh_by_arg


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


def test_kanbanflow_file_honors_explicit_number() -> None:
    provider, client, _ = make_kf_provider_with_task()  # fresh board with one task at #1
    item = provider.file(title="t", body="b", priority="High", status="Backlog", number=318)
    assert item.number == 318  # NOT _next_number()'s 2


def test_github_file_ignores_number(monkeypatch: pytest.MonkeyPatch) -> None:
    # GitHub auto-assigns; number= is accepted-and-ignored (no TypeError, no effect).
    patch_gh_by_arg(
        monkeypatch,
        {
            "issue create": "https://github.com/brockamer/jared/issues/42\n",
            "item-add": '{"id": "PVTI_new"}',
            "api graphql": "{}",
        },
    )
    provider = GitHubProjectsProvider(
        project_number=7,
        project_id="PVT_x",
        owner="brockamer",
        repo="brockamer/jared",
        field_ids={"Priority": "f-p", "Status": "f-s"},
        field_options={"Priority": {"High": "opt-h"}, "Status": {"Backlog": "opt-b"}},
    )
    # Passing number=999 must not raise TypeError; the returned item number
    # comes from GitHub's URL (42 here), not from the number= kwarg.
    item = provider.file(title="t", body="b", priority="High", status="Backlog", number=999)
    assert item.number == 42
