from datetime import datetime, timezone

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from opswatch.models import Incident, Monitor, MonitorCheck
from opswatch.monitoring.http_checks import MonitorCheckResult


def record_monitor_check_result(db: Session, monitor: Monitor, result: MonitorCheckResult) -> MonitorCheck:
    """Save a check result and update the matching incident state."""

    checked_at = datetime.now(timezone.utc)
    check = MonitorCheck(
        monitor_id=monitor.id,
        checked_at=checked_at,
        success=result.success,
        status_code=result.status_code,
        response_time_ms=result.response_time_ms,
        error_type=result.error_type,
        error_message=result.error_message,
    )
    db.add(check)
    db.flush()
    update_monitor_last_check(monitor, result, checked_at)

    open_incident = db.scalar(
        select(Incident)
        .where(Incident.monitor_id == monitor.id, Incident.status.in_(["open", "acknowledged"]))
        .order_by(desc(Incident.started_at))
    )

    if not monitor.enabled:
        monitor.status = "paused"
        db.commit()
        db.refresh(check)
        return check

    if result.success:
        if open_incident and monitor_has_reached_recovery_threshold(db, monitor):
            open_incident.status = "resolved"
            open_incident.resolved_at = checked_at
            monitor.status = "healthy"
        elif open_incident:
            monitor.status = "degraded"
        else:
            monitor.status = "healthy"
        db.commit()
        db.refresh(check)
        return check

    if open_incident or monitor_has_reached_failure_threshold(db, monitor):
        monitor.status = "down"

    if open_incident is None and monitor.status == "down":
        db.add(
            Incident(
                monitor_id=monitor.id,
                title=f"{monitor.name} is failing health checks",
                severity="warning",
                status="open",
                started_at=checked_at,
                failure_reason=result.error_message or result.error_type,
            )
        )
    elif monitor.status != "down":
        monitor.status = "degraded"

    db.commit()
    db.refresh(check)
    return check


def acknowledge_incident(db: Session, incident: Incident) -> Incident:
    """Mark an open incident as acknowledged."""

    incident.status = "acknowledged"
    incident.acknowledged_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(incident)
    return incident


def resolve_incident(db: Session, incident: Incident) -> Incident:
    """Mark an incident as resolved."""

    incident.status = "resolved"
    incident.resolved_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(incident)
    return incident


def update_monitor_last_check(monitor: Monitor, result: MonitorCheckResult, checked_at: datetime) -> None:
    """Store the latest check summary on the monitor."""

    monitor.last_checked_at = checked_at
    monitor.last_status_code = result.status_code
    monitor.last_response_time_ms = result.response_time_ms
    monitor.last_error_type = result.error_type
    monitor.last_error_message = result.error_message


def monitor_has_reached_failure_threshold(db: Session, monitor: Monitor) -> bool:
    """Return true when the latest checks meet the monitor failure threshold."""

    threshold = max(monitor.failure_threshold, 1)
    recent_checks = db.scalars(
        select(MonitorCheck)
        .where(MonitorCheck.monitor_id == monitor.id)
        .order_by(desc(MonitorCheck.checked_at), desc(MonitorCheck.id))
        .limit(threshold)
    ).all()
    return len(recent_checks) == threshold and all(not check.success for check in recent_checks)


def monitor_has_reached_recovery_threshold(db: Session, monitor: Monitor) -> bool:
    """Return true when the latest checks meet the monitor recovery threshold."""

    threshold = max(monitor.recovery_threshold, 1)
    recent_checks = db.scalars(
        select(MonitorCheck)
        .where(MonitorCheck.monitor_id == monitor.id)
        .order_by(desc(MonitorCheck.checked_at), desc(MonitorCheck.id))
        .limit(threshold)
    ).all()
    return len(recent_checks) == threshold and all(check.success for check in recent_checks)
