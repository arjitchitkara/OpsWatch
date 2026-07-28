from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import desc, select
from sqlalchemy.orm import Session, selectinload

from opswatch.api.auth import is_authenticated, require_admin, require_dashboard_admin
from opswatch.config import get_settings
from opswatch.database import get_db
from opswatch.models import Incident, Monitor, MonitorCheck
from opswatch.monitoring.http_checks import check_monitor_endpoint
from opswatch.monitoring.incident_lifecycle import record_monitor_check_result
from opswatch.schemas import (
    IncidentRead,
    IncidentUpdate,
    MonitorCheckRead,
    MonitorCreate,
    MonitorRead,
    MonitorUpdate,
)

templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
dashboard_router = APIRouter()
api_router = APIRouter(prefix="/api/v1")


def get_monitor_or_404(db: Session, monitor_id: int) -> Monitor:
    """Return a monitor or raise a 404 error."""

    monitor = db.get(Monitor, monitor_id)
    if monitor is None:
        raise HTTPException(status_code=404, detail="Monitor not found")
    return monitor


def get_incident_or_404(db: Session, incident_id: int) -> Incident:
    """Return an incident or raise a 404 error."""

    incident = db.get(Incident, incident_id)
    if incident is None:
        raise HTTPException(status_code=404, detail="Incident not found")
    return incident


@dashboard_router.get("/login", response_class=HTMLResponse)
def login_page(request: Request) -> HTMLResponse:
    """Render the admin login page."""

    return templates.TemplateResponse(request=request, name="login.html", context={"error": None})


@dashboard_router.post("/login")
def login(request: Request, username: str = Form(...), password: str = Form(...)):
    """Start an admin session when the credentials are valid."""

    settings = get_settings()
    if username == settings.admin_username and password == settings.admin_password:
        request.session["admin_authenticated"] = True
        return RedirectResponse("/", status_code=status.HTTP_303_SEE_OTHER)
    return templates.TemplateResponse(
        request=request,
        name="login.html",
        context={"error": "Invalid username or password"},
        status_code=status.HTTP_401_UNAUTHORIZED,
    )


@dashboard_router.post("/logout")
def logout(request: Request):
    """Clear the admin session and return to the login page."""

    request.session.clear()
    return RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)


@dashboard_router.get("/", response_class=HTMLResponse)
def overview_page(request: Request, db: Session = Depends(get_db), _: None = Depends(require_dashboard_admin)):
    """Render the dashboard overview page."""

    monitors = db.scalars(select(Monitor).order_by(Monitor.name)).all()
    open_incidents = db.scalars(
        select(Incident)
        .options(selectinload(Incident.monitor))
        .where(Incident.status.in_(["open", "acknowledged"]))
        .order_by(desc(Incident.started_at))
    ).all()
    recent_checks = db.scalars(
        select(MonitorCheck)
        .options(selectinload(MonitorCheck.monitor))
        .order_by(desc(MonitorCheck.checked_at), desc(MonitorCheck.id))
        .limit(10)
    ).all()
    return templates.TemplateResponse(
        request=request,
        name="overview.html",
        context={
            "monitors": monitors,
            "open_incidents": open_incidents,
            "recent_checks": recent_checks,
            "authenticated": is_authenticated(request),
        },
    )


@dashboard_router.get("/monitors", response_class=HTMLResponse)
def monitors_page(request: Request, db: Session = Depends(get_db), _: None = Depends(require_dashboard_admin)):
    """Render the monitor list page."""

    monitors = db.scalars(select(Monitor).order_by(Monitor.name)).all()
    return templates.TemplateResponse(request=request, name="monitors.html", context={"monitors": monitors})


@dashboard_router.post("/monitors")
def create_monitor_form(
    request: Request,
    name: str = Form(...),
    url: str = Form(...),
    method: str = Form("GET"),
    expected_status: int = Form(200),
    expected_body: str = Form(""),
    interval_seconds: int = Form(60),
    timeout_seconds: int = Form(5),
    failure_threshold: int = Form(3),
    enabled: bool = Form(False),
    db: Session = Depends(get_db),
    _: None = Depends(require_dashboard_admin),
):
    """Create a monitor from the dashboard form."""

    monitor = Monitor(
        name=name,
        url=url,
        method=method.upper(),
        expected_status=expected_status,
        expected_body=expected_body or None,
        interval_seconds=interval_seconds,
        timeout_seconds=timeout_seconds,
        failure_threshold=failure_threshold,
        enabled=enabled,
    )
    db.add(monitor)
    db.commit()
    return RedirectResponse("/monitors", status_code=status.HTTP_303_SEE_OTHER)


@dashboard_router.get("/monitors/{monitor_id}", response_class=HTMLResponse)
def monitor_detail_page(
    request: Request,
    monitor_id: int,
    db: Session = Depends(get_db),
    _: None = Depends(require_dashboard_admin),
):
    """Render one monitor with its checks and incidents."""

    monitor = get_monitor_or_404(db, monitor_id)
    checks = db.scalars(
        select(MonitorCheck)
        .where(MonitorCheck.monitor_id == monitor_id)
        .order_by(desc(MonitorCheck.checked_at), desc(MonitorCheck.id))
        .limit(50)
    ).all()
    incidents = db.scalars(
        select(Incident).where(Incident.monitor_id == monitor_id).order_by(desc(Incident.started_at)).limit(20)
    ).all()
    return templates.TemplateResponse(
        request=request,
        name="monitor_detail.html",
        context={"monitor": monitor, "checks": checks, "incidents": incidents},
    )


@dashboard_router.post("/monitors/{monitor_id}/check")
def run_manual_monitor_check_form(
    monitor_id: int,
    db: Session = Depends(get_db),
    _: None = Depends(require_dashboard_admin),
):
    """Run one monitor check from the dashboard."""

    monitor = get_monitor_or_404(db, monitor_id)
    result = check_monitor_endpoint(monitor)
    record_monitor_check_result(db, monitor, result)
    return RedirectResponse(f"/monitors/{monitor_id}", status_code=status.HTTP_303_SEE_OTHER)


@dashboard_router.post("/monitors/{monitor_id}/delete")
def delete_monitor_form(monitor_id: int, db: Session = Depends(get_db), _: None = Depends(require_dashboard_admin)):
    """Delete a monitor from the dashboard."""

    monitor = get_monitor_or_404(db, monitor_id)
    db.delete(monitor)
    db.commit()
    return RedirectResponse("/monitors", status_code=status.HTTP_303_SEE_OTHER)


@dashboard_router.get("/incidents", response_class=HTMLResponse)
def incidents_page(request: Request, db: Session = Depends(get_db), _: None = Depends(require_dashboard_admin)):
    """Render the incident list page."""

    incidents = db.scalars(
        select(Incident).options(selectinload(Incident.monitor)).order_by(desc(Incident.started_at))
    ).all()
    return templates.TemplateResponse(request=request, name="incidents.html", context={"incidents": incidents})


@dashboard_router.get("/incidents/{incident_id}", response_class=HTMLResponse)
def incident_detail_page(
    request: Request,
    incident_id: int,
    db: Session = Depends(get_db),
    _: None = Depends(require_dashboard_admin),
):
    """Render one incident."""

    incident = get_incident_or_404(db, incident_id)
    return templates.TemplateResponse(request=request, name="incident_detail.html", context={"incident": incident})


@dashboard_router.post("/incidents/{incident_id}")
def update_incident_form(
    incident_id: int,
    status_value: str = Form(...),
    severity: str = Form("warning"),
    notes: str = Form(""),
    db: Session = Depends(get_db),
    _: None = Depends(require_dashboard_admin),
):
    """Update an incident from the dashboard form."""

    incident = get_incident_or_404(db, incident_id)
    incident.status = status_value
    incident.severity = severity
    incident.notes = notes or None
    if status_value == "acknowledged" and incident.acknowledged_at is None:
        incident.acknowledged_at = datetime.now(timezone.utc)
    if status_value == "resolved" and incident.resolved_at is None:
        incident.resolved_at = datetime.now(timezone.utc)
    db.commit()
    return RedirectResponse(f"/incidents/{incident_id}", status_code=status.HTTP_303_SEE_OTHER)


@api_router.get("/monitors", response_model=list[MonitorRead])
def list_monitors(db: Session = Depends(get_db)):
    """Return all monitors as JSON."""

    return db.scalars(select(Monitor).order_by(Monitor.name)).all()


@api_router.post("/monitors", response_model=MonitorRead, status_code=status.HTTP_201_CREATED)
def create_monitor(payload: MonitorCreate, db: Session = Depends(get_db), _: None = Depends(require_admin)):
    """Create a monitor from JSON input."""

    monitor = Monitor(**payload.model_dump())
    monitor.method = monitor.method.upper()
    db.add(monitor)
    db.commit()
    db.refresh(monitor)
    return monitor


@api_router.get("/monitors/{monitor_id}", response_model=MonitorRead)
def get_monitor(monitor_id: int, db: Session = Depends(get_db)):
    """Return one monitor as JSON."""

    return get_monitor_or_404(db, monitor_id)


@api_router.patch("/monitors/{monitor_id}", response_model=MonitorRead)
def update_monitor(
    monitor_id: int,
    payload: MonitorUpdate,
    db: Session = Depends(get_db),
    _: None = Depends(require_admin),
):
    """Update one monitor from JSON input."""

    monitor = get_monitor_or_404(db, monitor_id)
    updates = payload.model_dump(exclude_unset=True)
    for field, value in updates.items():
        setattr(monitor, field, value.upper() if field == "method" and value else value)
    db.commit()
    db.refresh(monitor)
    return monitor


@api_router.delete("/monitors/{monitor_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_monitor(monitor_id: int, db: Session = Depends(get_db), _: None = Depends(require_admin)):
    """Delete one monitor."""

    monitor = get_monitor_or_404(db, monitor_id)
    db.delete(monitor)
    db.commit()
    return None


@api_router.post("/monitors/{monitor_id}/check", response_model=MonitorCheckRead)
def run_manual_monitor_check(monitor_id: int, db: Session = Depends(get_db), _: None = Depends(require_admin)):
    """Run one monitor check and return the saved result as JSON."""

    monitor = get_monitor_or_404(db, monitor_id)
    result = check_monitor_endpoint(monitor)
    return record_monitor_check_result(db, monitor, result)


@api_router.get("/checks", response_model=list[MonitorCheckRead])
def list_monitor_checks(
    monitor_id: int | None = Query(default=None),
    success: bool | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
):
    """Return monitor checks as JSON with optional filters."""

    query = select(MonitorCheck).order_by(desc(MonitorCheck.checked_at), desc(MonitorCheck.id)).limit(limit)
    if monitor_id is not None:
        query = query.where(MonitorCheck.monitor_id == monitor_id)
    if success is not None:
        query = query.where(MonitorCheck.success.is_(success))
    return db.scalars(query).all()


@api_router.get("/monitors/{monitor_id}/checks", response_model=list[MonitorCheckRead])
def list_checks_for_monitor(
    monitor_id: int,
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
):
    """Return checks for one monitor as JSON."""

    get_monitor_or_404(db, monitor_id)
    return db.scalars(
        select(MonitorCheck)
        .where(MonitorCheck.monitor_id == monitor_id)
        .order_by(desc(MonitorCheck.checked_at), desc(MonitorCheck.id))
        .limit(limit)
    ).all()


@api_router.get("/incidents", response_model=list[IncidentRead])
def list_incidents(status_filter: str | None = Query(default=None, alias="status"), db: Session = Depends(get_db)):
    """Return incidents as JSON with an optional status filter."""

    query = select(Incident).order_by(desc(Incident.started_at))
    if status_filter:
        query = query.where(Incident.status == status_filter)
    return db.scalars(query).all()


@api_router.get("/incidents/{incident_id}", response_model=IncidentRead)
def get_incident(incident_id: int, db: Session = Depends(get_db)):
    """Return one incident as JSON."""

    return get_incident_or_404(db, incident_id)


@api_router.patch("/incidents/{incident_id}", response_model=IncidentRead)
def update_incident(
    incident_id: int,
    payload: IncidentUpdate,
    db: Session = Depends(get_db),
    _: None = Depends(require_admin),
):
    """Update one incident from JSON input."""

    incident = get_incident_or_404(db, incident_id)
    updates = payload.model_dump(exclude_unset=True)
    for field, value in updates.items():
        setattr(incident, field, value)
    if incident.status == "acknowledged" and incident.acknowledged_at is None:
        incident.acknowledged_at = datetime.now(timezone.utc)
    if incident.status == "resolved" and incident.resolved_at is None:
        incident.resolved_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(incident)
    return incident
