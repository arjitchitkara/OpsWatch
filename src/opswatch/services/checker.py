from dataclasses import dataclass
from time import perf_counter

import httpx

from opswatch.models import Target


@dataclass(frozen=True)
class CheckOutcome:
    success: bool
    status_code: int | None
    response_time_ms: int | None
    error_type: str | None
    error_message: str | None


def run_http_check(target: Target, client: httpx.Client | None = None) -> CheckOutcome:
    method = target.method.upper()
    if method not in {"GET", "HEAD"}:
        return CheckOutcome(False, None, None, "invalid_method", f"Unsupported method: {target.method}")

    should_close = client is None
    if client is None:
        client = httpx.Client(follow_redirects=True, timeout=target.timeout_seconds)

    started = perf_counter()
    try:
        response = client.request(method, target.url)
        elapsed_ms = int((perf_counter() - started) * 1000)
    except httpx.TimeoutException as exc:
        elapsed_ms = int((perf_counter() - started) * 1000)
        return CheckOutcome(False, None, elapsed_ms, "timeout", str(exc) or "Request timed out")
    except httpx.RequestError as exc:
        elapsed_ms = int((perf_counter() - started) * 1000)
        return CheckOutcome(False, None, elapsed_ms, "request_error", str(exc))
    finally:
        if should_close:
            client.close()

    if response.status_code != target.expected_status:
        return CheckOutcome(
            False,
            response.status_code,
            elapsed_ms,
            "unexpected_status",
            f"Expected {target.expected_status}, got {response.status_code}",
        )

    if target.expected_body and target.expected_body not in response.text:
        return CheckOutcome(
            False,
            response.status_code,
            elapsed_ms,
            "expected_body_missing",
            "Expected response body text was not found",
        )

    return CheckOutcome(True, response.status_code, elapsed_ms, None, None)
