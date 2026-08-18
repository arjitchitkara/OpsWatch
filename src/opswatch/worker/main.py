import json
import logging
import time
from datetime import datetime, timezone

from sqlalchemy import desc, select

from opswatch.config import get_settings
from opswatch.database import SessionLocal
from opswatch.models import Monitor, MonitorCheck
from opswatch.monitoring.http_checks import check_monitor_endpoint
from opswatch.monitoring.incident_lifecycle import record_monitor_check_result
from opswatch.observability.worker_metrics import (
    WorkerLoopTimer,
    start_worker_metrics_server,
    worker_metrics,
)

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("opswatch.worker")
logging.getLogger("httpx").setLevel(logging.WARNING)


def build_worker_log_event(event: str, **fields) -> str:
    """Return one worker log event as a JSON string."""

    payload = {"event": event, "component": "worker", **fields}
    return json.dumps(payload, default=str, separators=(",", ":"), sort_keys=True)


def log_worker_event(event: str, **fields) -> None:
    """Write one structured worker log event."""

    logger.info(build_worker_log_event(event, **fields))


def monitor_is_due_for_check(db, monitor: Monitor) -> bool:
    """Return true when a monitor should be checked now."""

    latest_check = db.scalar(
        select(MonitorCheck)
        .where(MonitorCheck.monitor_id == monitor.id)
        .order_by(desc(MonitorCheck.checked_at), desc(MonitorCheck.id))
        .limit(1)
    )
    if latest_check is None:
        return True
    elapsed = datetime.now(timezone.utc) - latest_check.checked_at
    return elapsed.total_seconds() >= monitor.interval_seconds


def run_due_monitor_checks_once() -> None:
    """Check each enabled monitor that is due for a check."""

    with SessionLocal() as db:
        monitors = db.scalars(select(Monitor).where(Monitor.enabled.is_(True)).order_by(Monitor.id)).all()
        for monitor in monitors:
            check_monitor_if_due(db, monitor)


def check_monitor_if_due(db, monitor: Monitor) -> bool:
    """Check one enabled monitor when it is due."""

    if not monitor.enabled:
        log_worker_event("monitor_check_skipped", monitor_id=monitor.id, reason="disabled")
        worker_metrics.record_monitor_check_skip("disabled")
        return False
    if not monitor_is_due_for_check(db, monitor):
        log_worker_event("monitor_check_skipped", monitor_id=monitor.id, reason="not_due")
        worker_metrics.record_monitor_check_skip("not_due")
        return False
    log_worker_event(
        "monitor_check_started",
        monitor_id=monitor.id,
        monitor_name=monitor.name,
        method=monitor.method,
        url=monitor.url,
        expected_status=monitor.expected_status,
    )
    result = check_monitor_endpoint(monitor)
    duration_seconds = result.response_time_ms / 1000 if result.response_time_ms is not None else None
    worker_metrics.record_monitor_check(result.success, result.error_type, duration_seconds)
    check = record_monitor_check_result(db, monitor, result)
    log_worker_event(
        "monitor_check_completed",
        monitor_id=monitor.id,
        monitor_name=monitor.name,
        check_id=check.id,
        success=result.success,
        status_code=result.status_code,
        response_time_ms=result.response_time_ms,
        error_type=result.error_type,
        monitor_status=monitor.status,
    )
    return True


def main() -> None:
    """Run the monitor worker loop forever."""

    settings = get_settings()
    start_worker_metrics_server(settings.worker_metrics_port)
    log_worker_event(
        "worker_started",
        poll_interval_seconds=settings.worker_poll_seconds,
        metrics_port=settings.worker_metrics_port,
    )
    while True:
        try:
            with WorkerLoopTimer():
                run_due_monitor_checks_once()
        except Exception as exc:
            logger.exception(
                build_worker_log_event(
                    "worker_loop_failed",
                    error_type=type(exc).__name__,
                    error_message=str(exc),
                )
            )
        time.sleep(settings.worker_poll_seconds)


if __name__ == "__main__":
    main()
