"""Integration test for #71 — empirically verify `gh project item-add` is idempotent
on an already-on-board issue.

Gated by `pytest -m integration`. Requires tests/testbed.env (see tests/testbed-setup.md).
The default test run skips this (pyproject sets `addopts = "-m 'not integration'"`).

Empirical probe on 2026-05-01 against project #4 (jared itself, real account) confirmed
behavior (a) from the issue body: a duplicate item-add returns exit 0 with stdout JSON
containing the existing item-id. This test pins that behavior so a future gh release
that regresses to a duplicate-add error is caught at the testbed.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest


def _load_testbed_env() -> dict[str, str]:
    """Parse tests/testbed.env into a dict. Skips the test if missing."""
    env_path = Path(__file__).parent / "testbed.env"
    if not env_path.exists():
        pytest.skip("tests/testbed.env not present — see tests/testbed-setup.md")
    out: dict[str, str] = {}
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        k, v = line.split("=", 1)
        out[k.strip()] = v.strip()
    return out


@pytest.mark.integration
def test_gh_project_item_add_is_idempotent_on_already_added_issue() -> None:
    """Calling `gh project item-add` twice on the same issue against the testbed
    should return exit 0 both times with the same item-id in stdout."""
    env_vars = _load_testbed_env()
    project_number = env_vars.get("TESTBED_PROJECT_NUMBER")
    owner = env_vars.get("TESTBED_OWNER")
    repo = env_vars.get("TESTBED_REPO")
    if not (project_number and owner and repo):
        pytest.skip("TESTBED_PROJECT_NUMBER / TESTBED_OWNER / TESTBED_REPO unset")

    # Use seed issue #1 — should always exist on the testbed (see seed-issues.yaml).
    issue_url = f"https://github.com/{repo}/issues/1"

    # Match jared's child-env discipline (#65) — scrub GH_TOKEN/GITHUB_TOKEN so the
    # call uses the OAuth session jared expects to be authoritative.
    child_env = os.environ.copy()
    child_env.pop("GH_TOKEN", None)
    child_env.pop("GITHUB_TOKEN", None)

    args = [
        "gh",
        "project",
        "item-add",
        project_number,
        "--owner",
        owner,
        "--url",
        issue_url,
        "--format",
        "json",
    ]

    first = subprocess.run(args, capture_output=True, text=True, check=False, env=child_env)
    assert first.returncode == 0, f"first item-add failed: {first.stderr}"
    first_id = json.loads(first.stdout)["id"]

    second = subprocess.run(args, capture_output=True, text=True, check=False, env=child_env)
    assert second.returncode == 0, (
        "second item-add on already-added issue failed — gh idempotency assumption "
        f"broken (#71). stderr: {second.stderr}"
    )
    second_id = json.loads(second.stdout)["id"]

    assert first_id == second_id, (
        f"second item-add returned a different item-id ({second_id} vs {first_id}) — "
        "this would also break the assume_new=True short-circuit assumption (#71)."
    )
