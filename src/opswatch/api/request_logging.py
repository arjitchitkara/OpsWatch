import json
import logging
from time import perf_counter
from uuid import uuid4

from fastapi import Request

logger = logging.getLogger("opswatch.api")


def configure_api_logging() -> None:
    """Set a simple log format for API events."""

    logging.basicConfig(level=logging.INFO, format="%(message)s")


def build_api_log_event(event: str, **fields) -> str:
    """Return one API log event as a JSON string."""

    payload = {"event": event, "component": "api", **fields}
    return json.dumps(payload, default=str, separators=(",", ":"), sort_keys=True)


def get_request_id(request: Request) -> str:
    """Return the request id from headers or create one."""

    return request.headers.get("x-request-id") or str(uuid4())


def get_client_ip(request: Request) -> str | None:
    """Return the best client IP value available."""

    forwarded_for = request.headers.get("x-forwarded-for")
    if forwarded_for:
        return forwarded_for.split(",", maxsplit=1)[0].strip()
    if request.client is None:
        return None
    return request.client.host


def log_api_request(
    request: Request,
    request_id: str,
    status_code: int,
    duration_ms: int,
    error_type: str | None = None,
) -> None:
    """Write one structured API request log event."""

    logger.info(
        build_api_log_event(
            "api_request_completed",
            request_id=request_id,
            method=request.method,
            path=request.url.path,
            status_code=status_code,
            duration_ms=duration_ms,
            client_ip=get_client_ip(request),
            user_agent=request.headers.get("user-agent"),
            error_type=error_type,
        )
    )


def started_request_timer() -> float:
    """Return the start time for a request."""

    return perf_counter()


def elapsed_request_time_ms(started_at: float) -> int:
    """Return elapsed request time in milliseconds."""

    return int((perf_counter() - started_at) * 1000)
