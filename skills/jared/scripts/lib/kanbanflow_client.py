"""Wire-level KanbanFlow REST client (epic #313, Phase 2 / #315).

Pure transport: auth, quota policy, typed resources, error mapping. No semantic
board mapping — that is the KanbanFlowProvider's job (#316). Stdlib only.

All network I/O flows through the module-level `_raw_http` seam; `_sleep` and
`_now` are the other two seams. Tests monkeypatch these three. See the design
spec's Appendix B for the verified API surface.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request

# --------------------------------------------------------------------------- #
# Module-level seams (the only impure functions; monkeypatched in tests)      #
# --------------------------------------------------------------------------- #


def _raw_http(
    method: str, url: str, headers: dict[str, str], data: bytes | None
) -> tuple[int, dict[str, str], bytes]:
    """Perform one HTTP request. Returns (status, response_headers, body_bytes).

    Non-2xx responses (urllib raises HTTPError) are captured and returned like
    any other response, so `_request` maps them uniformly. Connection-level
    failures (URLError that is not HTTPError) propagate to the caller.
    """
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status, dict(resp.headers.items()), resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, dict(exc.headers.items()), exc.read()


def _sleep(seconds: float) -> None:
    time.sleep(seconds)


def _now() -> float:
    return time.time()


# --------------------------------------------------------------------------- #
# Typed exceptions                                                            #
# --------------------------------------------------------------------------- #


class KanbanFlowError(Exception):
    """Base for all client errors (also transport/JSON failures)."""


class KanbanFlowAuthError(KanbanFlowError):
    """401 — missing or invalid token."""


class KanbanFlowForbiddenError(KanbanFlowError):
    """403 — refused; validation failures surface here, not 400/422."""


class KanbanFlowNotFoundError(KanbanFlowError):
    """404 — resource not found."""


class KanbanFlowRateLimitError(KanbanFlowError):
    """429 or local budget exhaustion."""


class KanbanFlowServerError(KanbanFlowError):
    """500 — server error."""


_EXCEPTION_FOR_STATUS: dict[int, type[KanbanFlowError]] = {
    401: KanbanFlowAuthError,
    403: KanbanFlowForbiddenError,
    404: KanbanFlowNotFoundError,
    429: KanbanFlowRateLimitError,
    500: KanbanFlowServerError,
}


def _parse_error(body: bytes) -> str:
    """Extract the human message from {"errors":[{"message":"..."}]}."""
    try:
        payload = json.loads(body)
        errors = payload.get("errors") or []
        if errors and isinstance(errors, list):
            return str(errors[0].get("message", "")) or "unknown error"
    except (ValueError, AttributeError):
        pass
    return body.decode(errors="replace") or "unknown error"


class KanbanFlowClient:
    """Typed, quota-aware KanbanFlow REST client."""

    def __init__(
        self,
        token: str,
        base_url: str = "https://kanbanflow.com/api/v1",
        *,
        request_floor: int = 50,
        daily_ceiling: int = 4000,
        max_retries: int = 3,
    ) -> None:
        self._token = token
        self._base_url = base_url.rstrip("/")
        self._request_floor = request_floor
        self._daily_ceiling = daily_ceiling
        self._max_retries = max_retries
        # quota state, updated from response headers
        self._remaining: int | None = None
        self._reset: int | None = None
        self._daily_count = 0

    def _build_url(self, path: str, params: dict[str, object] | None) -> str:
        url = f"{self._base_url}/{path.lstrip('/')}"
        if params:
            clean = {k: str(v) for k, v in params.items() if v is not None}
            if clean:
                url = f"{url}?{urllib.parse.urlencode(clean)}"
        return url

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, object] | None = None,
        body: dict[str, object] | None = None,
    ) -> object:
        for attempt in range(self._max_retries + 1):
            self._budget_gate()
            url = self._build_url(path, params)
            headers = {"Authorization": f"Bearer {self._token}"}
            data: bytes | None = None
            if body is not None:
                data = json.dumps(body).encode()
                headers["Content-Type"] = "application/json"
            try:
                status, resp_headers, resp_body = _raw_http(method, url, headers, data)
            except urllib.error.URLError as exc:
                if attempt < self._max_retries:
                    _sleep(self._backoff(attempt))
                    continue
                raise KanbanFlowError(f"transport error: {exc}") from exc

            self._record_quota(resp_headers)

            if 200 <= status < 300:
                if not resp_body:
                    return None
                try:
                    return json.loads(resp_body)
                except ValueError as exc:
                    raise KanbanFlowError(f"invalid JSON in response body: {exc}") from exc

            message = _parse_error(resp_body)
            if status == 429 and attempt < self._max_retries:
                _sleep(self._retry_delay(resp_headers))
                continue
            if status >= 500 and attempt < self._max_retries:
                _sleep(self._backoff(attempt))
                continue
            raise _EXCEPTION_FOR_STATUS.get(status, KanbanFlowError)(message)

        raise KanbanFlowRateLimitError("request retries exhausted")

    # quota helpers filled in Task 3 — minimal stubs so Task 1 tests pass
    def _budget_gate(self) -> None:
        self._daily_count += 1

    def _record_quota(self, headers: dict[str, str]) -> None:
        return None

    def _retry_delay(self, headers: dict[str, str]) -> float:
        return 0.0

    def _backoff(self, attempt: int) -> float:
        return 0.0
