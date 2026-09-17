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


# --- list_comments_batch (#395) --------------------------------------------
# next-session-prompt needs every in-flight item's comments at once. The
# GitHub implementation keeps the single aliased round trip; KanbanFlow loops
# over list_comments. Both return neutral Comments keyed by IssueRef, with the
# same author/body/created_at contract list_comments promises.


def test_github_list_comments_batch_uses_one_cached_gh_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[list[str]] = []

    class FakeResult:
        returncode = 0
        stderr = ""
        stdout = (
            '{"data": {"repository": {'
            '"i10": {"comments": {"nodes": ['
            '  {"author": {"login": "brockamer"},'
            '   "body": "## Session 2026-04-30", "createdAt": "2026-04-30T12:00:00Z"}'
            "]}},"
            '"i11": {"comments": {"nodes": []}}'
            "}}}"
        )

    def fake_run(args: list[str], **kw: object) -> FakeResult:
        captured.append(args)
        return FakeResult()

    monkeypatch.setattr("skills.jared.scripts.lib.board.subprocess.run", fake_run)

    result = _gh_provider().list_comments_batch([10, 11])
    assert len(captured) == 1, "N refs must still cost exactly one gh call"
    # The 60s cache is part of "the GitHub path is unchanged" — dropping it
    # would be an invisible regression in round-trip cost.
    assert "--cache" in captured[0] and "60s" in captured[0]
    # Pin the author selection itself: the fixture supplies an author key, so
    # without this the test would still pass if the query stopped asking for
    # one — and list_comments_batch's author contract would silently go empty.
    assert "author { login }" in " ".join(captured[0])
    assert result == {
        10: [
            Comment(
                author="brockamer",
                body="## Session 2026-04-30",
                created_at="2026-04-30T12:00:00Z",
            )
        ],
        11: [],
    }


def test_github_list_comments_batch_empty_refs_skips_gh(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(args: list[str], **kw: object) -> object:
        raise AssertionError("gh must not be called for empty refs")

    monkeypatch.setattr("skills.jared.scripts.lib.board.subprocess.run", fake_run)
    assert _gh_provider().list_comments_batch([]) == {}


def test_kanbanflow_list_comments_batch_returns_comments_per_ref() -> None:
    from tests.fake_kanbanflow import make_kf_provider_with_tasks

    provider, _client = make_kf_provider_with_tasks(
        users={"u1": "Daniel Brock"},
        tasks={
            12: [
                {
                    "text": "## Session 2026-09-16\n\n**Next action:** wire the provider seam.",
                    "createdTimestamp": "2026-09-16T10:00:00Z",
                    "authorUserId": "u1",
                }
            ],
            13: [],
        },
    )

    assert provider.list_comments_batch([12, 13]) == {
        12: [
            Comment(
                author="Daniel Brock",
                body="## Session 2026-09-16\n\n**Next action:** wire the provider seam.",
                created_at="2026-09-16T10:00:00Z",
            )
        ],
        13: [],
    }


def test_kanbanflow_list_comments_batch_never_invokes_gh(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC4: a KanbanFlow board has no GitHub repo — this path must not shell to gh."""
    from tests.fake_kanbanflow import make_kf_provider_with_tasks

    def fake_run(args: list[str], **kw: object) -> object:
        raise AssertionError(f"gh must not be invoked on the KanbanFlow path: {args}")

    monkeypatch.setattr("skills.jared.scripts.lib.board.subprocess.run", fake_run)

    provider, _client = make_kf_provider_with_tasks(tasks={12: []})
    assert provider.list_comments_batch([12]) == {12: []}


def test_kanbanflow_unknown_author_resolves_to_empty_not_raw_id() -> None:
    """An unresolvable author must not leak the KanbanFlow `_id` (#414).

    `Comment.author` promises "" when unresolved, and provider-internal ids
    never cross the neutral boundary. A comment whose authorUserId is absent
    from /users (a removed board member) used to surface that raw id as if it
    were a display name.
    """
    from tests.fake_kanbanflow import make_kf_provider_with_tasks

    provider, _client = make_kf_provider_with_tasks(
        users={"u1": "Daniel Brock"},
        tasks={
            12: [
                {
                    "text": "note from a departed user",
                    "createdTimestamp": "2026-09-16T10:00:00Z",
                    "authorUserId": "u-deleted",
                }
            ]
        },
    )

    (comment,) = provider.list_comments(12)
    assert comment.author == "", f"leaked a provider-internal id: {comment.author!r}"
