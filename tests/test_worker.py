from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from opswatch.models import Base, Monitor
from opswatch.monitoring.http_checks import MonitorCheckResult
from opswatch.worker import main as worker


def make_session():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False)()


def add_monitor(db, enabled=True):
    monitor = Monitor(
        name="Demo",
        url="http://example.test",
        method="GET",
        expected_status=200,
        interval_seconds=60,
        timeout_seconds=5,
        failure_threshold=3,
        recovery_threshold=2,
        enabled=enabled,
        status="unknown" if enabled else "paused",
    )
    db.add(monitor)
    db.commit()
    db.refresh(monitor)
    return monitor


def test_worker_skips_disabled_monitor(monkeypatch):
    db = make_session()
    monitor = add_monitor(db, enabled=False)
    calls = []

    def fake_check_monitor_endpoint(monitor):
        calls.append(monitor.id)
        return MonitorCheckResult(True, 200, 10, None, None)

    monkeypatch.setattr(worker, "check_monitor_endpoint", fake_check_monitor_endpoint)

    checked = worker.check_monitor_if_due(db, monitor)

    assert checked is False
    assert calls == []


def test_worker_checks_enabled_due_monitor(monkeypatch):
    db = make_session()
    monitor = add_monitor(db, enabled=True)

    def fake_check_monitor_endpoint(monitor):
        return MonitorCheckResult(True, 200, 10, None, None)

    monkeypatch.setattr(worker, "check_monitor_endpoint", fake_check_monitor_endpoint)

    checked = worker.check_monitor_if_due(db, monitor)
    db.refresh(monitor)

    assert checked is True
    assert monitor.status == "healthy"
    assert monitor.last_status_code == 200
