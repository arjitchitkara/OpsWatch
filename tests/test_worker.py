import json
import logging

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from opswatch.models import Base, Monitor
from opswatch.monitoring.http_checks import MonitorCheckResult
from opswatch.observability.worker_metrics import WorkerLoopTimer, worker_metrics
from opswatch.worker import main as worker


@pytest.fixture(autouse=True)
def reset_worker_metrics():
    """Clear worker metrics before and after each test."""

    worker_metrics.reset()
    yield
    worker_metrics.reset()


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


def test_worker_logs_disabled_monitor_skip(monkeypatch, caplog):
    db = make_session()
    monitor = add_monitor(db, enabled=False)

    def fake_check_monitor_endpoint(monitor):
        raise AssertionError("disabled monitor should not be checked")

    monkeypatch.setattr(worker, "check_monitor_endpoint", fake_check_monitor_endpoint)
    caplog.set_level(logging.INFO, logger="opswatch.worker")

    checked = worker.check_monitor_if_due(db, monitor)
    events = [json.loads(record.message) for record in caplog.records]

    assert checked is False
    assert events == [
        {
            "component": "worker",
            "event": "monitor_check_skipped",
            "monitor_id": monitor.id,
            "reason": "disabled",
        }
    ]
    metrics_text = worker_metrics.render_prometheus_text()
    assert 'opswatch_worker_monitor_check_skipped_total{reason="disabled"} 1' in metrics_text


def test_worker_checks_enabled_due_monitor(monkeypatch, caplog):
    db = make_session()
    monitor = add_monitor(db, enabled=True)

    def fake_check_monitor_endpoint(monitor):
        return MonitorCheckResult(True, 200, 10, None, None)

    monkeypatch.setattr(worker, "check_monitor_endpoint", fake_check_monitor_endpoint)
    caplog.set_level(logging.INFO, logger="opswatch.worker")

    checked = worker.check_monitor_if_due(db, monitor)
    db.refresh(monitor)
    events = [json.loads(record.message) for record in caplog.records]

    assert checked is True
    assert monitor.status == "healthy"
    assert monitor.last_status_code == 200
    assert events[0]["event"] == "monitor_check_started"
    assert events[0]["component"] == "worker"
    assert events[0]["monitor_id"] == monitor.id
    assert events[0]["monitor_name"] == "Demo"
    assert events[1]["event"] == "monitor_check_completed"
    assert events[1]["component"] == "worker"
    assert events[1]["monitor_id"] == monitor.id
    assert events[1]["success"] is True
    assert events[1]["status_code"] == 200
    assert events[1]["response_time_ms"] == 10
    assert events[1]["monitor_status"] == "healthy"
    metrics_text = worker_metrics.render_prometheus_text()
    assert 'opswatch_worker_monitor_checks_total{error_type="none",result="success"} 1' in metrics_text
    assert 'opswatch_worker_monitor_check_duration_seconds_count{error_type="none",result="success"} 1' in metrics_text
    assert 'opswatch_worker_monitor_check_duration_seconds_sum{error_type="none",result="success"} 0.010000' in metrics_text


def test_worker_loop_timer_records_failed_loop():
    with pytest.raises(RuntimeError):
        with WorkerLoopTimer():
            raise RuntimeError("database failed")

    metrics_text = worker_metrics.render_prometheus_text()

    assert "opswatch_worker_loop_runs_total 1" in metrics_text
    assert "opswatch_worker_loop_failures_total 1" in metrics_text
    assert "opswatch_worker_loop_duration_seconds_count 1" in metrics_text
