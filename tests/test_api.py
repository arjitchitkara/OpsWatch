from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from opswatch.api.main import app
from opswatch.database import get_db
from opswatch.models import Base, Incident, Target


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


def test_unauthenticated_mutation_is_rejected(client: TestClient):
    response = client.post(
        "/api/v1/targets",
        json={"name": "Demo", "url": "http://example.test", "method": "GET"},
    )
    assert response.status_code == 401


def test_target_crud_with_session_auth(client: TestClient):
    login(client)
    created = client.post(
        "/api/v1/targets",
        json={
            "name": "Demo",
            "url": "http://example.test",
            "method": "GET",
            "expected_status": 200,
            "interval_seconds": 60,
            "timeout_seconds": 5,
            "failure_threshold": 3,
            "enabled": True,
        },
    )
    assert created.status_code == 201
    target_id = created.json()["id"]

    listed = client.get("/api/v1/targets")
    assert listed.status_code == 200
    assert listed.json()[0]["name"] == "Demo"

    patched = client.patch(f"/api/v1/targets/{target_id}", json={"enabled": False})
    assert patched.status_code == 200
    assert patched.json()["enabled"] is False

    deleted = client.delete(f"/api/v1/targets/{target_id}")
    assert deleted.status_code == 204


def test_incident_patch_sets_acknowledged_timestamp(client: TestClient):
    login(client)

    db: Session = next(app.dependency_overrides[get_db]())
    target = Target(name="Demo", url="http://example.test", method="GET")
    db.add(target)
    db.commit()
    db.refresh(target)
    incident = Incident(target_id=target.id, title="Demo failing", status="open", severity="warning")
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
