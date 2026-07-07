from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from opswatch.models import Base, Incident, Target
from opswatch.services.checker import CheckOutcome
from opswatch.services.incidents import record_check_and_update_incidents


def make_session():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False)()


def add_target(db, threshold=3):
    target = Target(
        name="Demo",
        url="http://example.test",
        method="GET",
        expected_status=200,
        interval_seconds=60,
        timeout_seconds=5,
        failure_threshold=threshold,
        enabled=True,
    )
    db.add(target)
    db.commit()
    db.refresh(target)
    return target


def failed(message="failed"):
    return CheckOutcome(False, 500, 10, "unexpected_status", message)


def succeeded():
    return CheckOutcome(True, 200, 10, None, None)


def incidents(db):
    return db.scalars(select(Incident).order_by(Incident.id)).all()


def test_threshold_opens_one_incident():
    db = make_session()
    target = add_target(db, threshold=3)

    record_check_and_update_incidents(db, target, failed("first"))
    record_check_and_update_incidents(db, target, failed("second"))
    assert incidents(db) == []

    record_check_and_update_incidents(db, target, failed("third"))
    opened = incidents(db)
    assert len(opened) == 1
    assert opened[0].status == "open"


def test_more_failures_do_not_duplicate_open_incident():
    db = make_session()
    target = add_target(db, threshold=2)

    record_check_and_update_incidents(db, target, failed())
    record_check_and_update_incidents(db, target, failed())
    record_check_and_update_incidents(db, target, failed())

    assert len(incidents(db)) == 1


def test_success_resolves_open_incident_and_later_failure_can_reopen():
    db = make_session()
    target = add_target(db, threshold=1)

    record_check_and_update_incidents(db, target, failed())
    record_check_and_update_incidents(db, target, succeeded())
    first = incidents(db)[0]
    assert first.status == "resolved"
    assert first.resolved_at is not None

    record_check_and_update_incidents(db, target, failed())
    all_incidents = incidents(db)
    assert len(all_incidents) == 2
    assert all_incidents[1].status == "open"
