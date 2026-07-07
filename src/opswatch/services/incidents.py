from datetime import datetime, timezone

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from opswatch.models import Check, Incident, Target
from opswatch.services.checker import CheckOutcome


def record_check_and_update_incidents(db: Session, target: Target, outcome: CheckOutcome) -> Check:
    check = Check(
        target_id=target.id,
        checked_at=datetime.now(timezone.utc),
        success=outcome.success,
        status_code=outcome.status_code,
        response_time_ms=outcome.response_time_ms,
        error_type=outcome.error_type,
        error_message=outcome.error_message,
    )
    db.add(check)
    db.flush()

    open_incident = db.scalar(
        select(Incident)
        .where(Incident.target_id == target.id, Incident.status.in_(["open", "acknowledged"]))
        .order_by(desc(Incident.started_at))
    )

    if outcome.success:
        if open_incident:
            open_incident.status = "resolved"
            open_incident.resolved_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(check)
        return check

    if open_incident is None and _has_reached_failure_threshold(db, target):
        db.add(
            Incident(
                target_id=target.id,
                title=f"{target.name} is failing health checks",
                severity="warning",
                status="open",
                started_at=datetime.now(timezone.utc),
                failure_reason=outcome.error_message or outcome.error_type,
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


def _has_reached_failure_threshold(db: Session, target: Target) -> bool:
    threshold = max(target.failure_threshold, 1)
    recent_checks = db.scalars(
        select(Check)
        .where(Check.target_id == target.id)
        .order_by(desc(Check.checked_at), desc(Check.id))
        .limit(threshold)
    ).all()
    return len(recent_checks) == threshold and all(not check.success for check in recent_checks)
