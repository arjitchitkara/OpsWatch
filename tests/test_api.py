from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from opswatch.api.main import app
from opswatch.database import get_db
from opswatch.models import Base, Incident, Monitor


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


def login(client: TestClient) -> None:
    response = client.post("/login", data={"username": "admin", "password": "admin"}, follow_redirects=False)
    assert response.status_code == 303


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
