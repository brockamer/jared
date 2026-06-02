from skills.jared.scripts.lib.board_provider import BoardProvider, Capability
from skills.jared.scripts.lib.github_provider import GitHubProjectsProvider


def _provider() -> GitHubProjectsProvider:
    return GitHubProjectsProvider(
        project_number=4,
        project_id="PVT_x",
        owner="o",
        repo="o/r",
        field_ids={"Status": "F1", "Priority": "F2"},
        field_options={"Status": {"Done": "D"}, "Priority": {"High": "H"}},
    )


def test_github_provider_satisfies_protocol() -> None:
    assert isinstance(_provider(), BoardProvider)


def test_github_provider_advertises_full_capability_set() -> None:
    assert _provider().capabilities() == frozenset(Capability)
