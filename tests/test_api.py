from collections.abc import Generator
import json
import logging
import re

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from opswatch.api.main import app
from opswatch.database import get_db
from opswatch.models import Base, Incident, Monitor, MonitorCheck


@pytest.fixture
def client() -> Generator[TestClient, None, None]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(engine)

    def override_db():
        db = TestingSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def csrf_token_from(response) -> str:
    """Return the CSRF token rendered in a dashboard form."""

    match = re.search(r'name="csrf_token" value="([^"]+)"', response.text)
    assert match is not None
    return match.group(1)


def login(client: TestClient) -> str:
    """Start a dashboard session and return its CSRF token."""

    csrf_token = csrf_token_from(client.get("/login"))
    response = client.post(
        "/login",
        data={"username": "admin", "password": "admin", "csrf_token": csrf_token},
        follow_redirects=False,
    )
    assert response.status_code == 303
    return csrf_token


def test_login_page_renders(client: TestClient):
    response = client.get("/login")
    assert response.status_code == 200
    assert "OpsWatch" in response.text


def test_unauthenticated_mutation_is_rejected(client: TestClient):
    response = client.post(
        "/api/v1/monitors",
        json={"name": "Demo", "url": "http://example.test", "method": "GET"},
    )
    assert response.status_code == 401


def test_monitor_crud_with_session_auth(client: TestClient):
    login(client)
    created = client.post(
        "/api/v1/monitors",
        json={
            "name": "Demo",
            "url": "http://example.test",
            "method": "GET",
            "expected_status": 200,
            "interval_seconds": 60,
            "timeout_seconds": 5,
            "failure_threshold": 3,
            "recovery_threshold": 2,
            "enabled": True,
        },
    )
    assert created.status_code == 201
    created_payload = created.json()
    monitor_id = created_payload["id"]
    assert created_payload["status"] == "unknown"
    assert created_payload["last_checked_at"] is None
    assert created_payload["recovery_threshold"] == 2

    listed = client.get("/api/v1/monitors")
    assert listed.status_code == 200
    assert listed.json()[0]["name"] == "Demo"

    patched = client.patch(f"/api/v1/monitors/{monitor_id}", json={"enabled": False})
    assert patched.status_code == 200
    assert patched.json()["enabled"] is False
    assert patched.json()["status"] == "paused"

    resumed = client.patch(f"/api/v1/monitors/{monitor_id}", json={"enabled": True})
    assert resumed.status_code == 200
    assert resumed.json()["enabled"] is True
    assert resumed.json()["status"] == "unknown"

    deleted = client.delete(f"/api/v1/monitors/{monitor_id}")
    assert deleted.status_code == 204


def test_dashboard_can_update_monitor_and_pause_resume(client: TestClient):
    csrf_token = login(client)
    created = client.post(
        "/api/v1/monitors",
        json={
            "name": "Demo",
            "url": "http://example.test",
            "method": "GET",
            "expected_status": 200,
            "interval_seconds": 60,
            "timeout_seconds": 5,
            "failure_threshold": 3,
            "recovery_threshold": 2,
            "enabled": True,
        },
    )
    monitor_id = created.json()["id"]

    paused = client.post(
        f"/monitors/{monitor_id}",
        data={
            "csrf_token": csrf_token,
            "name": "Updated Demo",
            "url": "http://example.test/health",
            "method": "HEAD",
            "expected_status": 204,
            "expected_body": "",
            "interval_seconds": 30,
            "timeout_seconds": 3,
            "failure_threshold": 2,
            "recovery_threshold": 4,
        },
        follow_redirects=False,
    )
    assert paused.status_code == 303

    paused_payload = client.get(f"/api/v1/monitors/{monitor_id}").json()
    assert paused_payload["name"] == "Updated Demo"
    assert paused_payload["method"] == "HEAD"
    assert paused_payload["expected_status"] == 204
    assert paused_payload["interval_seconds"] == 30
    assert paused_payload["timeout_seconds"] == 3
    assert paused_payload["failure_threshold"] == 2
    assert paused_payload["recovery_threshold"] == 4
    assert paused_payload["enabled"] is False
    assert paused_payload["status"] == "paused"

    resumed = client.post(
        f"/monitors/{monitor_id}",
        data={
            "csrf_token": csrf_token,
            "name": "Updated Demo",
            "url": "http://example.test/health",
            "method": "HEAD",
            "expected_status": 204,
            "expected_body": "",
            "interval_seconds": 30,
            "timeout_seconds": 3,
            "failure_threshold": 2,
            "recovery_threshold": 4,
            "enabled": "true",
        },
        follow_redirects=False,
    )
    assert resumed.status_code == 303

    resumed_payload = client.get(f"/api/v1/monitors/{monitor_id}").json()
    assert resumed_payload["enabled"] is True
    assert resumed_payload["status"] == "unknown"


def test_dashboard_rejects_invalid_csrf_token(client: TestClient):
    response = client.post(
        "/login",
        data={"username": "admin", "password": "admin", "csrf_token": "invalid"},
        follow_redirects=False,
    )

    assert response.status_code == 403


def test_dashboard_monitor_form_uses_api_validation_rules(client: TestClient):
    csrf_token = login(client)

    response = client.post(
        "/monitors",
        data={
            "csrf_token": csrf_token,
            "name": "Invalid URL",
            "url": "example.test",
            "method": "GET",
            "expected_status": 200,
            "interval_seconds": 60,
            "timeout_seconds": 5,
            "failure_threshold": 3,
            "recovery_threshold": 2,
            "enabled": "true",
        },
    )

    assert response.status_code == 422
    assert "Enter a complete HTTP or HTTPS URL" in response.text
    assert client.get("/api/v1/monitors").json() == []


def test_dashboard_monitor_state_action_sets_flash_message(client: TestClient):
    csrf_token = login(client)
    created = client.post(
        "/api/v1/monitors",
        json={"name": "Demo", "url": "http://example.test", "method": "GET"},
    )
    monitor_id = created.json()["id"]

    paused = client.post(
        f"/monitors/{monitor_id}/state",
        data={"csrf_token": csrf_token, "enabled": "false", "return_to": f"/monitors/{monitor_id}"},
        follow_redirects=False,
    )

    assert paused.status_code == 303
    assert paused.headers["location"] == f"/monitors/{monitor_id}"
    detail_page = client.get(f"/monitors/{monitor_id}")
    assert "was paused" in detail_page.text
    assert client.get(f"/api/v1/monitors/{monitor_id}").json()["status"] == "paused"


def test_dashboard_incident_actions_update_timeline(client: TestClient):
    csrf_token = login(client)
    db: Session = next(app.dependency_overrides[get_db]())
    monitor = Monitor(name="Demo", url="http://example.test", method="GET")
    db.add(monitor)
    db.commit()
    db.refresh(monitor)
    incident = Incident(monitor_id=monitor.id, title="Demo failing", status="open", severity="warning")
    db.add(incident)
    db.commit()
    db.refresh(incident)
    incident_id = incident.id
    db.close()

    acknowledged = client.post(
        f"/incidents/{incident_id}/acknowledge",
        data={"csrf_token": csrf_token},
        follow_redirects=False,
    )
    assert acknowledged.status_code == 303

    resolved = client.post(
        f"/incidents/{incident_id}/resolve",
        data={"csrf_token": csrf_token},
        follow_redirects=False,
    )
    assert resolved.status_code == 303

    payload = client.get(f"/api/v1/incidents/{incident_id}").json()
    assert payload["status"] == "resolved"
    assert payload["acknowledged_at"] is not None
    assert payload["resolved_at"] is not None


def test_incident_patch_sets_acknowledged_timestamp(client: TestClient):
    login(client)

    db: Session = next(app.dependency_overrides[get_db]())
    monitor = Monitor(name="Demo", url="http://example.test", method="GET")
    db.add(monitor)
    db.commit()
    db.refresh(monitor)
    incident = Incident(monitor_id=monitor.id, title="Demo failing", status="open", severity="warning")
    db.add(incident)
    db.commit()
    db.refresh(incident)
    incident_id = incident.id
    db.close()

    response = client.patch(f"/api/v1/incidents/{incident_id}", json={"status": "acknowledged", "notes": "checking"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "acknowledged"
    assert payload["acknowledged_at"] is not None


def test_check_listing_filter(client: TestClient):
    login(client)
    response = client.get("/api/v1/checks?success=true")
    assert response.status_code == 200
    assert response.json() == []


def test_metrics_returns_prometheus_text(client: TestClient):
    db: Session = next(app.dependency_overrides[get_db]())
    monitor = Monitor(name="Demo", url="http://example.test", method="GET", enabled=True, status="healthy")
    db.add(monitor)
    db.commit()
    db.refresh(monitor)
    db.add(MonitorCheck(monitor_id=monitor.id, success=True, status_code=200, response_time_ms=10))
    db.add(Incident(monitor_id=monitor.id, title="Demo failing", status="open", severity="warning"))
    db.commit()
    db.close()

    response = client.get("/metrics")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert "opswatch_monitors_count 1" in response.text
    assert 'opswatch_monitor_status_count{status="healthy"} 1' in response.text
    assert 'opswatch_monitor_check_result_count{success="true"} 1' in response.text
    assert 'opswatch_incident_status_count{status="open"} 1' in response.text


def test_api_writes_structured_request_log(client: TestClient, caplog):
    caplog.set_level(logging.INFO, logger="opswatch.api")

    response = client.get("/health", headers={"x-request-id": "test-request-id"})

    events = [json.loads(record.message) for record in caplog.records]
    request_events = [event for event in events if event["event"] == "api_request_completed"]

    assert response.status_code == 200
    assert response.headers["x-request-id"] == "test-request-id"
    assert request_events[-1]["component"] == "api"
    assert request_events[-1]["request_id"] == "test-request-id"
    assert request_events[-1]["method"] == "GET"
    assert request_events[-1]["path"] == "/health"
    assert request_events[-1]["status_code"] == 200
    assert isinstance(request_events[-1]["duration_ms"], int)
