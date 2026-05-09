"""Tests for the LLM-overlay ties analyzer (#80, lib.ties_llm).

The anthropic SDK is mocked everywhere — these tests do NOT make network
calls. Exact JSON shape and request-payload assertions verify the contract
without depending on live API behavior.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest


@dataclass
class _FakeBlock:
    type: str
    text: str


@dataclass
class _FakeResponse:
    content: list[_FakeBlock]


@dataclass
class _FakeCount:
    input_tokens: int


class _FakeClient:
    """Mock anthropic client. Captures kwargs for assertion."""

    def __init__(self, *, count_tokens_value: int, response_text: str | None) -> None:
        self.count_tokens_value = count_tokens_value
        self.response_text = response_text
        self.create_kwargs: dict[str, Any] = {}
        self.count_kwargs: dict[str, Any] = {}
        self.messages = self  # so .messages.count_tokens / .messages.create both work

    def count_tokens(self, **kwargs: Any) -> _FakeCount:
        self.count_kwargs = kwargs
        return _FakeCount(input_tokens=self.count_tokens_value)

    def create(self, **kwargs: Any) -> _FakeResponse:
        self.create_kwargs = kwargs
        if self.response_text is None:
            raise AssertionError("create() called when response_text was None")
        return _FakeResponse(content=[_FakeBlock(type="text", text=self.response_text)])


def _target() -> Any:
    from skills.jared.scripts.lib.ties import OpenIssueForTies

    return OpenIssueForTies(
        number=80,
        title="LLM-pass overlay for semantic ties",
        body="Add an LLM overlay on top of the deterministic ties analyzer.",
        labels=("enhancement",),
        milestone="v1.0",
        status="In Progress",
        priority="Low",
        blocked_by=(),
    )


def _open_issues() -> list[Any]:
    from skills.jared.scripts.lib.ties import OpenIssueForTies

    return [
        OpenIssueForTies(
            number=82,
            title="Add semantic similarity scoring to ties",
            body="Detect when two issues describe overlapping work.",
            labels=("enhancement",),
            milestone="v1.0",
            status="Backlog",
            priority="Medium",
            blocked_by=(),
        ),
        OpenIssueForTies(
            number=83,
            title="Refactor sweep.py logging",
            body="Consolidate log output across sweep checks.",
            labels=("refactor",),
            milestone=None,
            status="Backlog",
            priority="Low",
            blocked_by=(),
        ),
    ]


def test_happy_path_produces_signal_hits() -> None:
    """Valid JSON response is parsed into SignalHit objects with confidence='llm'."""
    from skills.jared.scripts.lib import ties_llm

    response_json = (
        '{"ties": ['
        '{"number": 82, "label": "semantic_overlap",'
        ' "rationale": "both describe semantic similarity"}'
        "]}"
    )
    client = _FakeClient(count_tokens_value=1000, response_text=response_json)

    hits = ties_llm.analyze_semantic_ties(
        _target(), _open_issues(), budget_tokens=10_000, client=client
    )

    assert len(hits) == 1
    assert hits[0].related_n == 82
    assert hits[0].name == "semantic_overlap"
    assert hits[0].confidence == "llm"
    assert "semantic similarity" in hits[0].evidence


def test_empty_ties_list_returns_empty() -> None:
    """{"ties": []} is the valid 'nothing semantic' answer."""
    from skills.jared.scripts.lib import ties_llm

    client = _FakeClient(count_tokens_value=1000, response_text='{"ties": []}')
    hits = ties_llm.analyze_semantic_ties(
        _target(), _open_issues(), budget_tokens=10_000, client=client
    )
    assert hits == []


def test_self_tie_is_dropped() -> None:
    """A tie referencing the target's own number is filtered out — defensive
    parse, since the model should never produce one but we don't trust it."""
    from skills.jared.scripts.lib import ties_llm

    response_json = (
        '{"ties": ['
        '{"number": 80, "label": "semantic_overlap", "rationale": "same"},'
        '{"number": 82, "label": "semantic_overlap", "rationale": "real tie"}'
        "]}"
    )
    client = _FakeClient(count_tokens_value=1000, response_text=response_json)
    hits = ties_llm.analyze_semantic_ties(
        _target(), _open_issues(), budget_tokens=10_000, client=client
    )
    assert [h.related_n for h in hits] == [82]


def test_budget_exceeded_raises_before_api_call() -> None:
    """If count_tokens returns more than budget, no API call is made."""
    from skills.jared.scripts.lib import ties_llm

    client = _FakeClient(count_tokens_value=99_999, response_text=None)
    with pytest.raises(ties_llm.BudgetExceededError) as exc:
        ties_llm.analyze_semantic_ties(
            _target(), _open_issues(), budget_tokens=10_000, client=client
        )
    assert "99999" in str(exc.value) or "99,999" in str(exc.value)
    assert client.create_kwargs == {}  # create was never called


def test_budget_from_env_var(monkeypatch: pytest.MonkeyPatch) -> None:
    """JARED_TIES_LLM_BUDGET overrides the default."""
    from skills.jared.scripts.lib import ties_llm

    monkeypatch.setenv("JARED_TIES_LLM_BUDGET", "500")
    client = _FakeClient(count_tokens_value=600, response_text=None)
    with pytest.raises(ties_llm.BudgetExceededError) as exc:
        ties_llm.analyze_semantic_ties(_target(), _open_issues(), client=client)
    assert "500" in str(exc.value)


def test_invalid_json_raises_llm_analysis_error() -> None:
    """A malformed text block surfaces as LlmAnalysisError, not a bare JSONDecodeError."""
    from skills.jared.scripts.lib import ties_llm

    client = _FakeClient(count_tokens_value=1000, response_text="not json {")
    with pytest.raises(ties_llm.LlmAnalysisError):
        ties_llm.analyze_semantic_ties(
            _target(), _open_issues(), budget_tokens=10_000, client=client
        )


def test_invalid_label_raises() -> None:
    """A label outside the enum surfaces as LlmAnalysisError."""
    from skills.jared.scripts.lib import ties_llm

    response_json = '{"ties": [{"number": 82, "label": "totally_made_up", "rationale": "x"}]}'
    client = _FakeClient(count_tokens_value=1000, response_text=response_json)
    with pytest.raises(ties_llm.LlmAnalysisError):
        ties_llm.analyze_semantic_ties(
            _target(), _open_issues(), budget_tokens=10_000, client=client
        )


def test_request_uses_cache_control_on_system() -> None:
    """The system prompt is sent as a list with cache_control: ephemeral so the
    prefix caches across repeated invocations within the 5-minute TTL window."""
    from skills.jared.scripts.lib import ties_llm

    client = _FakeClient(count_tokens_value=1000, response_text='{"ties": []}')
    ties_llm.analyze_semantic_ties(_target(), _open_issues(), budget_tokens=10_000, client=client)

    system = client.create_kwargs["system"]
    assert isinstance(system, list)
    assert system[0]["cache_control"] == {"type": "ephemeral"}


def test_request_uses_haiku_by_default() -> None:
    """Default model is Haiku per user choice — cost-sensitive overlay."""
    from skills.jared.scripts.lib import ties_llm

    client = _FakeClient(count_tokens_value=1000, response_text='{"ties": []}')
    ties_llm.analyze_semantic_ties(_target(), _open_issues(), budget_tokens=10_000, client=client)
    assert client.create_kwargs["model"] == "claude-haiku-4-5"


def test_request_uses_structured_output_schema() -> None:
    """Response format is locked to the JSON schema — model can't return free text."""
    from skills.jared.scripts.lib import ties_llm

    client = _FakeClient(count_tokens_value=1000, response_text='{"ties": []}')
    ties_llm.analyze_semantic_ties(_target(), _open_issues(), budget_tokens=10_000, client=client)
    output_config = client.create_kwargs["output_config"]
    assert output_config["format"]["type"] == "json_schema"
    schema = output_config["format"]["schema"]
    assert schema["properties"]["ties"]["items"]["properties"]["label"]["enum"] == [
        "possibly_already_done",
        "semantic_overlap",
    ]


def test_target_excluded_from_digest() -> None:
    """The target issue is not duplicated into the open-issues digest."""
    from skills.jared.scripts.lib import ties_llm

    target = _target()
    digest = ties_llm._build_digest(target, [target, *_open_issues()])
    assert f"#{target.number}:" not in digest


def test_digest_clipped_to_max_issues() -> None:
    """Boards larger than MAX_OPEN_ISSUES_IN_DIGEST get truncated to bound input."""
    from skills.jared.scripts.lib import ties_llm
    from skills.jared.scripts.lib.ties import OpenIssueForTies

    many = [
        OpenIssueForTies(
            number=200 + i,
            title=f"issue {i}",
            body="body",
            labels=(),
            milestone=None,
            status="Backlog",
            priority=None,
            blocked_by=(),
        )
        for i in range(ties_llm.MAX_OPEN_ISSUES_IN_DIGEST + 10)
    ]
    digest = ties_llm._build_digest(_target(), many)
    digest_lines = [ln for ln in digest.split("\n") if ln.startswith("#")]
    assert len(digest_lines) == ties_llm.MAX_OPEN_ISSUES_IN_DIGEST
