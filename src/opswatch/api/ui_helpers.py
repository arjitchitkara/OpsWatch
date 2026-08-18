import secrets
from datetime import datetime, timezone
from math import ceil
from pathlib import Path
from typing import Any

from fastapi import Form, HTTPException, Request, status
from pydantic import ValidationError

from opswatch.models import Monitor
from opswatch.schemas import MonitorCreate

STATIC_DIRECTORY = Path(__file__).parent / "static"
STATIC_ASSET_VERSION = max(
    int((STATIC_DIRECTORY / "styles.css").stat().st_mtime),
    int((STATIC_DIRECTORY / "app.js").stat().st_mtime),
)


def get_or_create_csrf_token(request: Request) -> str:
    """Return the session CSRF token, creating it when needed."""

    token = request.session.get("csrf_token")
    if not token:
        token = secrets.token_urlsafe(32)
        request.session["csrf_token"] = token
    return token


def require_valid_csrf_token(request: Request, csrf_token: str = Form(...)) -> None:
    """Reject a dashboard form when its CSRF token is invalid."""

    session_token = request.session.get("csrf_token")
    if not session_token or not secrets.compare_digest(session_token, csrf_token):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid form security token")


def set_flash_message(request: Request, message: str, category: str = "success") -> None:
    """Store one message for the next dashboard page."""

    request.session["flash_message"] = {"message": message, "category": category}


def build_template_context(request: Request) -> dict[str, Any]:
    """Return values shared by every dashboard template."""

    return {
        "current_path": request.url.path,
        "csrf_token": get_or_create_csrf_token(request),
        "flash_message": request.session.pop("flash_message", None),
        "static_asset_version": STATIC_ASSET_VERSION,
    }


def datetime_as_utc(value: datetime | None) -> str:
    """Return a datetime in the ISO format used by HTML time elements."""

    if value is None:
        return ""
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def format_datetime_utc(value: datetime | None) -> str:
    """Return a short UTC date and time for pages without JavaScript."""

    if value is None:
        return "-"
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).strftime("%b %d, %Y at %H:%M UTC")


def format_duration(started_at: datetime | None, ended_at: datetime | None = None) -> str:
    """Return the elapsed time between two datetimes."""

    if started_at is None:
        return "-"
    if started_at.tzinfo is None:
        started_at = started_at.replace(tzinfo=timezone.utc)
    end_value = ended_at or datetime.now(timezone.utc)
    if end_value.tzinfo is None:
        end_value = end_value.replace(tzinfo=timezone.utc)
    total_seconds = max(0, int((end_value - started_at).total_seconds()))
    days, remaining_seconds = divmod(total_seconds, 86400)
    hours, remaining_seconds = divmod(remaining_seconds, 3600)
    minutes, seconds = divmod(remaining_seconds, 60)
    if days:
        return f"{days}d {hours}h"
    if hours:
        return f"{hours}h {minutes}m"
    if minutes:
        return f"{minutes}m {seconds}s"
    return f"{seconds}s"


def humanize_error(error_type: str | None, error_message: str | None = None) -> str:
    """Return a clear dashboard message for a saved check error."""

    if not error_type and not error_message:
        return "-"
    normalized_type = (error_type or "").lower()
    normalized_message = (error_message or "").lower()
    if "timeout" in normalized_type or "timed out" in normalized_message:
        return "Request timed out"
    if "unexpected_status" in normalized_type:
        return "Unexpected HTTP status"
    if "expected_body_missing" in normalized_type:
        return "Expected response text was missing"
    if "invalid_method" in normalized_type:
        return "Unsupported HTTP method"
    if "name or service not known" in normalized_message or "getaddrinfo" in normalized_message:
        return "DNS resolution failed"
    if "connection refused" in normalized_message:
        return "Connection refused"
    if normalized_type == "request_error":
        return "Request failed"
    return error_message or error_type or "Request failed"


def pagination_details(total_items: int, requested_page: int, items_per_page: int) -> dict[str, int | bool]:
    """Return safe pagination values for a list page."""

    total_pages = max(1, ceil(total_items / items_per_page))
    current_page = min(max(1, requested_page), total_pages)
    return {
        "current_page": current_page,
        "total_pages": total_pages,
        "total_items": total_items,
        "items_per_page": items_per_page,
        "has_previous": current_page > 1,
        "has_next": current_page < total_pages,
        "previous_page": max(1, current_page - 1),
        "next_page": min(total_pages, current_page + 1),
    }


def monitor_form_values(monitor: Monitor | None = None) -> dict[str, Any]:
    """Return monitor values for a create or edit form."""

    if monitor is None:
        return {
            "name": "",
            "url": "",
            "method": "GET",
            "expected_status": 200,
            "expected_body": "",
            "interval_seconds": 60,
            "timeout_seconds": 5,
            "failure_threshold": 3,
            "recovery_threshold": 2,
            "enabled": True,
        }
    return {
        "name": monitor.name,
        "url": monitor.url,
        "method": monitor.method,
        "expected_status": monitor.expected_status,
        "expected_body": monitor.expected_body or "",
        "interval_seconds": monitor.interval_seconds,
        "timeout_seconds": monitor.timeout_seconds,
        "failure_threshold": monitor.failure_threshold,
        "recovery_threshold": monitor.recovery_threshold,
        "enabled": monitor.enabled,
    }


async def validate_monitor_form(request: Request) -> tuple[MonitorCreate | None, dict[str, Any], dict[str, str]]:
    """Validate monitor form values with the API schema rules."""

    form = await request.form()
    values = {
        "name": str(form.get("name", "")).strip(),
        "url": str(form.get("url", "")).strip(),
        "method": str(form.get("method", "GET")).upper(),
        "expected_status": form.get("expected_status", "200"),
        "expected_body": str(form.get("expected_body", "")).strip() or None,
        "interval_seconds": form.get("interval_seconds", "60"),
        "timeout_seconds": form.get("timeout_seconds", "5"),
        "failure_threshold": form.get("failure_threshold", "3"),
        "recovery_threshold": form.get("recovery_threshold", "2"),
        "enabled": form.get("enabled") == "true",
    }
    display_values = {**values, "expected_body": values["expected_body"] or ""}
    try:
        return MonitorCreate.model_validate(values), display_values, {}
    except ValidationError as exc:
        errors: dict[str, str] = {}
        for error in exc.errors():
            field_name = str(error["loc"][-1])
            message = error["msg"].removeprefix("Value error, ")
            errors.setdefault(field_name, message)
        return None, display_values, errors
