from datetime import datetime, timezone

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from opswatch.models import Incident, Monitor, MonitorCheck
from opswatch.monitoring.http_checks import MonitorCheckResult


def record_monitor_check_result(db: Session, monitor: Monitor, result: MonitorCheckResult) -> MonitorCheck:
    check = MonitorCheck(
        monitor_id=monitor.id,
        checked_at=datetime.now(timezone.utc),
        success=result.success,
        status_code=result.status_code,
        response_time_ms=result.response_time_ms,
        error_type=result.error_type,
        error_message=result.error_message,
    )
    db.add(check)
    db.flush()

    open_incident = db.scalar(
        select(Incident)
        .where(Incident.monitor_id == monitor.id, Incident.status.in_(["open", "acknowledged"]))
        .order_by(desc(Incident.started_at))
    )

    if result.success:
        if open_incident:
            open_incident.status = "resolved"
            open_incident.resolved_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(check)
        return check

    if open_incident is None and monitor_has_reached_failure_threshold(db, monitor):
        db.add(
            Incident(
                monitor_id=monitor.id,
                title=f"{monitor.name} is failing health checks",
                severity="warning",
                status="open",
                started_at=datetime.now(timezone.utc),
                failure_reason=result.error_message or result.error_type,
            )
        )

    db.commit()
    db.refresh(check)
    return check


def acknowledge_incident(db: Session, incident: Incident) -> Incident:
    incident.status = "acknowledged"
    incident.acknowledged_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(incident)
    return incident


def resolve_incident(db: Session, incident: Incident) -> Incident:
    incident.status = "resolved"
    incident.resolved_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(incident)
    return incident


def monitor_has_reached_failure_threshold(db: Session, monitor: Monitor) -> bool:
    threshold = max(monitor.failure_threshold, 1)
    recent_checks = db.scalars(
        select(MonitorCheck)
        .where(MonitorCheck.monitor_id == monitor.id)
        .order_by(desc(MonitorCheck.checked_at), desc(MonitorCheck.id))
        .limit(threshold)
    ).all()
    return len(recent_checks) == threshold and all(not check.success for check in recent_checks)
