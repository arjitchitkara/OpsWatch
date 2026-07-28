from dataclasses import dataclass
from time import perf_counter

import httpx

from opswatch.models import Monitor


@dataclass(frozen=True)
class MonitorCheckResult:
    success: bool
    status_code: int | None
    response_time_ms: int | None
    error_type: str | None
    error_message: str | None


def check_monitor_endpoint(monitor: Monitor, client: httpx.Client | None = None) -> MonitorCheckResult:
    method = monitor.method.upper()
    if method not in {"GET", "HEAD"}:
        return MonitorCheckResult(False, None, None, "invalid_method", f"Unsupported method: {monitor.method}")

    should_close = client is None
    if client is None:
        client = httpx.Client(follow_redirects=True, timeout=monitor.timeout_seconds)

    started = perf_counter()
    try:
        response = client.request(method, monitor.url)
        elapsed_ms = int((perf_counter() - started) * 1000)
    except httpx.TimeoutException as exc:
        elapsed_ms = int((perf_counter() - started) * 1000)
        return MonitorCheckResult(False, None, elapsed_ms, "timeout", str(exc) or "Request timed out")
    except httpx.RequestError as exc:
        elapsed_ms = int((perf_counter() - started) * 1000)
        return MonitorCheckResult(False, None, elapsed_ms, "request_error", str(exc))
    finally:
        if should_close:
            client.close()

    if response.status_code != monitor.expected_status:
        return MonitorCheckResult(
            False,
            response.status_code,
            elapsed_ms,
            "unexpected_status",
            f"Expected {monitor.expected_status}, got {response.status_code}",
        )

    if monitor.expected_body and monitor.expected_body not in response.text:
        return MonitorCheckResult(
            False,
            response.status_code,
            elapsed_ms,
            "expected_body_missing",
            "Expected response body text was not found",
        )

    return MonitorCheckResult(True, response.status_code, elapsed_ms, None, None)
