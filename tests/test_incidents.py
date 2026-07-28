from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from opswatch.models import Base, Incident, Monitor
from opswatch.monitoring.http_checks import MonitorCheckResult
from opswatch.monitoring.incident_lifecycle import record_monitor_check_result


def make_session():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False)()


def add_monitor(db, threshold=3):
    monitor = Monitor(
        name="Demo",
        url="http://example.test",
        method="GET",
        expected_status=200,
        interval_seconds=60,
        timeout_seconds=5,
        failure_threshold=threshold,
        enabled=True,
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


def test_threshold_opens_one_incident():
    db = make_session()
    monitor = add_monitor(db, threshold=3)

    record_monitor_check_result(db, monitor, failed("first"))
    record_monitor_check_result(db, monitor, failed("second"))
    assert incidents(db) == []

    record_monitor_check_result(db, monitor, failed("third"))
    opened = incidents(db)
    assert len(opened) == 1
    assert opened[0].status == "open"


def test_more_failures_do_not_duplicate_open_incident():
    db = make_session()
    monitor = add_monitor(db, threshold=2)

    record_monitor_check_result(db, monitor, failed())
    record_monitor_check_result(db, monitor, failed())
    record_monitor_check_result(db, monitor, failed())

    assert len(incidents(db)) == 1


def test_success_resolves_open_incident_and_later_failure_can_reopen():
    db = make_session()
    monitor = add_monitor(db, threshold=1)

    record_monitor_check_result(db, monitor, failed())
    record_monitor_check_result(db, monitor, succeeded())
    first = incidents(db)[0]
    assert first.status == "resolved"
    assert first.resolved_at is not None

    record_monitor_check_result(db, monitor, failed())
    all_incidents = incidents(db)
    assert len(all_incidents) == 2
    assert all_incidents[1].status == "open"
