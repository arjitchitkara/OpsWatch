from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from opswatch.models import Base, Incident, Monitor
from opswatch.monitoring.http_checks import MonitorCheckResult
from opswatch.monitoring.incident_lifecycle import record_monitor_check_result


def make_session():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False)()


def add_monitor(db, failure_threshold=3, recovery_threshold=2, enabled=True):
    monitor = Monitor(
        name="Demo",
        url="http://example.test",
        method="GET",
        expected_status=200,
        interval_seconds=60,
        timeout_seconds=5,
        failure_threshold=failure_threshold,
        recovery_threshold=recovery_threshold,
        enabled=enabled,
        status="unknown" if enabled else "paused",
    )
    db.add(monitor)
    db.commit()
    db.refresh(monitor)
    return monitor


def failed(message="failed"):
    return MonitorCheckResult(False, 500, 10, "unexpected_status", message)


def succeeded():
    return MonitorCheckResult(True, 200, 10, None, None)


def incidents(db):
    return db.scalars(select(Incident).order_by(Incident.id)).all()


def refresh(db, model):
    db.refresh(model)
    return model


def test_new_enabled_monitor_starts_unknown():
    db = make_session()
    monitor = add_monitor(db)

    assert monitor.status == "unknown"
    assert monitor.last_checked_at is None


def test_new_disabled_monitor_starts_paused():
    db = make_session()
    monitor = add_monitor(db, enabled=False)

    assert monitor.status == "paused"


def test_failed_check_marks_monitor_degraded_before_threshold():
    db = make_session()
    monitor = add_monitor(db, failure_threshold=2)

    record_monitor_check_result(db, monitor, failed("first"))
    refresh(db, monitor)

    assert monitor.status == "degraded"
    assert monitor.last_status_code == 500
    assert monitor.last_response_time_ms == 10
    assert monitor.last_error_type == "unexpected_status"
    assert monitor.last_error_message == "first"
    assert incidents(db) == []


def test_failure_threshold_marks_down_and_opens_one_incident():
    db = make_session()
    monitor = add_monitor(db, failure_threshold=2)

    record_monitor_check_result(db, monitor, failed("first"))
    record_monitor_check_result(db, monitor, failed("second"))
    record_monitor_check_result(db, monitor, failed("third"))
    refresh(db, monitor)

    opened = incidents(db)
    assert monitor.status == "down"
    assert len(opened) == 1
    assert opened[0].status == "open"


def test_recovery_threshold_resolves_incident_and_marks_healthy():
    db = make_session()
    monitor = add_monitor(db, failure_threshold=1, recovery_threshold=2)

    record_monitor_check_result(db, monitor, failed())
    record_monitor_check_result(db, monitor, succeeded())
    refresh(db, monitor)
    first = incidents(db)[0]

    assert monitor.status == "degraded"
    assert first.status == "open"
    assert first.resolved_at is None

    record_monitor_check_result(db, monitor, succeeded())
    refresh(db, monitor)
    refresh(db, first)

    assert monitor.status == "healthy"
    assert first.status == "resolved"
    assert first.resolved_at is not None


def test_later_failure_can_open_new_incident_after_recovery():
    db = make_session()
    monitor = add_monitor(db, failure_threshold=1, recovery_threshold=1)

    record_monitor_check_result(db, monitor, failed())
    record_monitor_check_result(db, monitor, succeeded())
    record_monitor_check_result(db, monitor, failed())
    refresh(db, monitor)

    all_incidents = incidents(db)
    assert monitor.status == "down"
    assert len(all_incidents) == 2
    assert all_incidents[0].status == "resolved"
    assert all_incidents[1].status == "open"


def test_disabled_monitor_records_check_but_stays_paused():
    db = make_session()
    monitor = add_monitor(db, enabled=False)

    record_monitor_check_result(db, monitor, failed())
    refresh(db, monitor)

    assert monitor.status == "paused"
    assert monitor.last_status_code == 500
    assert incidents(db) == []
