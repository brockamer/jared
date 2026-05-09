"""LLM-overlay analyzer for ties (#80).

Adds opt-in semantic-tie detection on top of the deterministic six analyzers
in lib.ties. Each LLM-produced SignalHit carries confidence="llm" so it can
be rendered in a separate "Semantic ties (LLM):" sub-block, downstream of
the deterministic "Ties to consider:" block.

Off by default. Enabled per-call via `jared ties --llm`, or per-project via
`### Tie Analysis` -> `- llm-overlay: enabled` in docs/project-board.md.

The anthropic SDK is imported lazily — non-LLM users do not need it
installed. Cost is bounded per process by JARED_TIES_LLM_BUDGET (env var,
default 50_000 input tokens). The pre-call estimate is computed via
client.messages.count_tokens and aborts cleanly if it would exceed the
budget — no API call is made in that case.

Threading the LLM signals into the existing combine/format pipeline is the
job of the CLI (phase 3); this module is pure analysis.
"""

from __future__ import annotations

import json
import os
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .ties import OpenIssueForTies, SignalHit

DEFAULT_MODEL = "claude-haiku-4-5"
DEFAULT_BUDGET_TOKENS = 50_000
MAX_OPEN_ISSUES_IN_DIGEST = 60
TARGET_BODY_CLIP = 1500
DIGEST_PARA_CLIP = 300
RATIONALE_CLIP = 200

# System prompt is intentionally stable across calls so the prefix caches.
# Volatile content (target body, open-issue digest) lives in the user turn,
# after the cache_control breakpoint. See claude-api skill: prefix caching.
SYSTEM_PROMPT = (
    "You are reviewing a GitHub Projects board to find semantic relationships "
    "between issues that a regex-based analyzer cannot detect.\n"
    "\n"
    "Given a target issue and a list of other open issues, identify which "
    "(if any) of the other issues are:\n"
    "\n"
    "1. **possibly_already_done** — the work the target describes may have "
    "already shipped under a different issue. Look for issues whose "
    "acceptance/scope substantially covers what the target is asking for, "
    "even if titles differ.\n"
    "2. **semantic_overlap** — the target and another issue cover meaningfully "
    "overlapping scope (not just adjacent). They might be candidates for "
    "merging, sequencing, or one superseding the other.\n"
    "\n"
    "Be strict. The deterministic analyzer already covers cross-references, "
    "blocked-by edges, milestones, file paths, labels, and title tokens. "
    "Do NOT surface ties for issues that are merely milestone-mates, share a "
    "label, or have superficially similar titles — those are deterministic-"
    "tier signals and the operator already sees them.\n"
    "\n"
    "Only return ties you have real semantic confidence in. An empty list is "
    "a valid and correct answer when nothing semantic stands out.\n"
)

_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "ties": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "number": {"type": "integer"},
                    "label": {
                        "type": "string",
                        "enum": ["possibly_already_done", "semantic_overlap"],
                    },
                    "rationale": {"type": "string"},
                },
                "required": ["number", "label", "rationale"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["ties"],
    "additionalProperties": False,
}


class LlmAnalysisError(Exception):
    """Wraps SDK / parsing failures with operator-friendly context."""


class BudgetExceededError(LlmAnalysisError):
    """Raised when the pre-call token estimate exceeds the configured budget."""


def analyze_semantic_ties(
    target: OpenIssueForTies,
    open_issues: list[OpenIssueForTies],
    *,
    model: str = DEFAULT_MODEL,
    budget_tokens: int | None = None,
    client: Any = None,
) -> list[SignalHit]:
    """Call Claude API to find semantic ties between target and open_issues.

    Returns list[SignalHit] with confidence="llm". The list may be empty
    (legitimate result — nothing semantic surfaced).

    `client` is for tests; pass an instance with messages.count_tokens and
    messages.create methods. Production callers should leave it None and
    let this function construct an anthropic.Anthropic() from env auth.
    """
    if budget_tokens is None:
        budget_tokens = int(os.environ.get("JARED_TIES_LLM_BUDGET", DEFAULT_BUDGET_TOKENS))

    if client is None:
        client = _construct_client()

    digest = _build_digest(target, open_issues)
    user_message = _build_user_message(target, digest)

    # Pre-call budget gate. count_tokens is free; messages.create costs API
    # tokens. If a single call would already blow the budget, surface that
    # before paying for it.
    count = client.messages.count_tokens(
        model=model,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_message}],
    )
    if count.input_tokens > budget_tokens:
        raise BudgetExceededError(
            f"Pre-call token estimate ({count.input_tokens}) exceeds budget "
            f"({budget_tokens}). Raise JARED_TIES_LLM_BUDGET or skip --llm."
        )

    response = _call_messages_create(client, model, user_message)
    text = _extract_text(response)
    return _parse_response(text, target.number)


def _construct_client() -> Any:
    """Lazy-import anthropic so non-LLM users don't need the SDK installed."""
    try:
        import anthropic  # type: ignore[import-not-found]
    except ImportError as e:
        raise LlmAnalysisError(
            "anthropic SDK is required for --llm. Install with: pip install anthropic"
        ) from e
    return anthropic.Anthropic()


def _call_messages_create(client: Any, model: str, user_message: str) -> Any:
    """Wrap the SDK call so anthropic.APIError surfaces as LlmAnalysisError.

    Imports anthropic up front so the except clause can reference its
    exception types — bringing the import inside the try would make
    anthropic a local that the except clause can't resolve cleanly.
    """
    api_error_cls: type[Exception] = Exception
    try:
        import anthropic

        api_error_cls = anthropic.APIError
    except ImportError:
        # No SDK installed; `client` was supplied by a test fixture (or the
        # caller bypassed _construct_client). Fall through and treat any
        # exception from create() as an LlmAnalysisError, since we can't
        # narrow it without the SDK's exception hierarchy.
        pass

    try:
        return client.messages.create(
            model=model,
            max_tokens=2048,
            system=[
                {
                    "type": "text",
                    "text": SYSTEM_PROMPT,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=[{"role": "user", "content": user_message}],
            output_config={"format": {"type": "json_schema", "schema": _RESPONSE_SCHEMA}},
        )
    except api_error_cls as e:
        raise LlmAnalysisError(f"Claude API call failed: {e}") from e


def _extract_text(response: Any) -> str:
    """Pull the first text block from a Message response, or empty string."""
    for block in response.content:
        if getattr(block, "type", None) == "text":
            return str(block.text)
    return ""


def _build_digest(target: OpenIssueForTies, open_issues: list[OpenIssueForTies]) -> str:
    """Compact per-issue summary: number, title, labels, first paragraph.

    Capped at MAX_OPEN_ISSUES_IN_DIGEST entries to bound input tokens. Boards
    larger than that fall back on the deterministic analyzer plus whatever
    the digest cap could fit; the cap is documented in the cost-budget error
    message so operators can override.
    """
    lines: list[str] = []
    count = 0
    for issue in open_issues:
        if issue.number == target.number:
            continue
        if count >= MAX_OPEN_ISSUES_IN_DIGEST:
            break
        first_para = issue.body.split("\n\n", 1)[0][:DIGEST_PARA_CLIP] if issue.body else ""
        labels = ", ".join(issue.labels) if issue.labels else "(none)"
        lines.append(
            f"#{issue.number}: {issue.title}\n  Labels: {labels}\n  Summary: {first_para}\n"
        )
        count += 1
    return "\n".join(lines)


def _build_user_message(target: OpenIssueForTies, digest: str) -> str:
    target_body = target.body or "(no body)"
    return (
        f"# Target issue\n\n"
        f"#{target.number}: {target.title}\n\n"
        f"{target_body[:TARGET_BODY_CLIP]}\n\n"
        f"---\n\n"
        f"# Other open issues\n\n"
        f"{digest}\n\n"
        f"Return semantic ties only. Empty list is correct when nothing stands out."
    )


def _parse_response(text: str, target_number: int) -> list[SignalHit]:
    """Parse the JSON-schema-validated text block into SignalHit objects."""
    from .ties import SignalHit

    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise LlmAnalysisError(f"LLM response is not valid JSON: {e}") from e

    hits: list[SignalHit] = []
    for tie in data.get("ties", []):
        try:
            related_n = int(tie["number"])
        except (KeyError, ValueError, TypeError) as e:
            raise LlmAnalysisError(f"Tie missing or invalid 'number' field: {tie}") from e
        if related_n == target_number:
            continue
        label = tie.get("label")
        if label not in ("possibly_already_done", "semantic_overlap"):
            raise LlmAnalysisError(f"Unexpected label: {label!r}")
        rationale = str(tie.get("rationale", ""))[:RATIONALE_CLIP]
        hits.append(
            SignalHit(
                related_n=related_n,
                name=label,
                confidence="llm",
                evidence=rationale,
            )
        )
    return hits
