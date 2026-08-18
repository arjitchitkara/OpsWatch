from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import desc, func, or_, select
from sqlalchemy.orm import Session, selectinload

from opswatch.api.auth import is_authenticated, require_admin, require_dashboard_admin
from opswatch.api.ui_helpers import (
    build_template_context,
    datetime_as_utc,
    format_datetime_utc,
    format_duration,
    humanize_error,
    monitor_form_values,
    pagination_details,
    require_valid_csrf_token,
    set_flash_message,
    validate_monitor_form,
)
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

templates = Jinja2Templates(
    directory=str(Path(__file__).parent / "templates"),
    context_processors=[build_template_context],
)
templates.env.filters["datetime_as_utc"] = datetime_as_utc
templates.env.filters["format_datetime"] = format_datetime_utc
templates.env.globals["format_duration"] = format_duration
templates.env.globals["humanize_error"] = humanize_error
dashboard_router = APIRouter()
api_router = APIRouter(prefix="/api/v1")

MONITORS_PER_PAGE = 12
CHECKS_PER_PAGE = 20
INCIDENTS_PER_PAGE = 15


def status_for_enabled_change(enabled: bool, current_status: str | None = None) -> str:
    """Return the monitor status after an enabled value change."""

    if not enabled:
        return "paused"
    if current_status == "paused":
        return "unknown"
    return current_status or "unknown"


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


def build_monitor_list_context(
    db: Session,
    search: str = "",
    status_filter: str = "",
    page: int = 1,
    form_values: dict | None = None,
    form_errors: dict | None = None,
) -> dict:
    """Return monitor list, filter, pagination, and form values."""

    query = select(Monitor)
    if search:
        search_pattern = f"%{search}%"
        query = query.where(or_(Monitor.name.ilike(search_pattern), Monitor.url.ilike(search_pattern)))
    if status_filter in {"healthy", "degraded", "down", "unknown", "paused"}:
        query = query.where(Monitor.status == status_filter)

    total_items = db.scalar(select(func.count()).select_from(query.order_by(None).subquery())) or 0
    pagination = pagination_details(total_items, page, MONITORS_PER_PAGE)
    monitors = db.scalars(
        query.order_by(Monitor.name)
        .offset((int(pagination["current_page"]) - 1) * MONITORS_PER_PAGE)
        .limit(MONITORS_PER_PAGE)
    ).all()
    return {
        "monitors": monitors,
        "search": search,
        "status_filter": status_filter,
        "pagination": pagination,
        "form_values": form_values or monitor_form_values(),
        "form_errors": form_errors or {},
        "form_open": bool(form_errors),
    }


def build_monitor_detail_context(
    db: Session,
    monitor: Monitor,
    check_page: int = 1,
    form_values: dict | None = None,
    form_errors: dict | None = None,
) -> dict:
    """Return monitor health, recent checks, incidents, and form values."""

    one_day_ago = datetime.now(timezone.utc) - timedelta(hours=24)
    checks_24h = db.scalar(
        select(func.count(MonitorCheck.id)).where(
            MonitorCheck.monitor_id == monitor.id,
            MonitorCheck.checked_at >= one_day_ago,
        )
    ) or 0
    successful_checks_24h = db.scalar(
        select(func.count(MonitorCheck.id)).where(
            MonitorCheck.monitor_id == monitor.id,
            MonitorCheck.checked_at >= one_day_ago,
            MonitorCheck.success.is_(True),
        )
    ) or 0
    average_response_time = db.scalar(
        select(func.avg(MonitorCheck.response_time_ms)).where(
            MonitorCheck.monitor_id == monitor.id,
            MonitorCheck.checked_at >= one_day_ago,
            MonitorCheck.response_time_ms.is_not(None),
        )
    )
    last_success_at = db.scalar(
        select(MonitorCheck.checked_at)
        .where(MonitorCheck.monitor_id == monitor.id, MonitorCheck.success.is_(True))
        .order_by(desc(MonitorCheck.checked_at), desc(MonitorCheck.id))
        .limit(1)
    )
    active_incident = db.scalar(
        select(Incident)
        .where(Incident.monitor_id == monitor.id, Incident.status.in_(["open", "acknowledged"]))
        .order_by(desc(Incident.started_at))
        .limit(1)
    )
    total_checks = db.scalar(
        select(func.count(MonitorCheck.id)).where(MonitorCheck.monitor_id == monitor.id)
    ) or 0
    pagination = pagination_details(total_checks, check_page, CHECKS_PER_PAGE)
    checks = db.scalars(
        select(MonitorCheck)
        .where(MonitorCheck.monitor_id == monitor.id)
        .order_by(desc(MonitorCheck.checked_at), desc(MonitorCheck.id))
        .offset((int(pagination["current_page"]) - 1) * CHECKS_PER_PAGE)
        .limit(CHECKS_PER_PAGE)
    ).all()
    check_history = db.scalars(
        select(MonitorCheck)
        .where(MonitorCheck.monitor_id == monitor.id)
        .order_by(desc(MonitorCheck.checked_at), desc(MonitorCheck.id))
        .limit(30)
    ).all()
    check_history.reverse()
    incidents = db.scalars(
        select(Incident)
        .where(Incident.monitor_id == monitor.id)
        .order_by(desc(Incident.started_at))
        .limit(10)
    ).all()

    next_check_at = None
    if monitor.enabled and monitor.last_checked_at:
        next_check_at = monitor.last_checked_at + timedelta(seconds=monitor.interval_seconds)
    availability_percent = round((successful_checks_24h / checks_24h) * 100, 1) if checks_24h else None
    return {
        "monitor": monitor,
        "checks": checks,
        "check_history": check_history,
        "incidents": incidents,
        "active_incident": active_incident,
        "checks_24h": checks_24h,
        "availability_percent": availability_percent,
        "average_response_time_ms": round(average_response_time) if average_response_time is not None else None,
        "last_success_at": last_success_at,
        "next_check_at": next_check_at,
        "pagination": pagination,
        "form_values": form_values or monitor_form_values(monitor),
        "form_errors": form_errors or {},
        "form_open": bool(form_errors),
    }


def build_incident_list_context(
    db: Session,
    status_filter: str = "",
    severity_filter: str = "",
    page: int = 1,
) -> dict:
    """Return filtered and paginated incident values."""

    query = select(Incident).options(selectinload(Incident.monitor))
    if status_filter in {"open", "acknowledged", "resolved"}:
        query = query.where(Incident.status == status_filter)
    if severity_filter in {"info", "warning", "critical"}:
        query = query.where(Incident.severity == severity_filter)
    count_query = select(func.count(Incident.id))
    if status_filter in {"open", "acknowledged", "resolved"}:
        count_query = count_query.where(Incident.status == status_filter)
    if severity_filter in {"info", "warning", "critical"}:
        count_query = count_query.where(Incident.severity == severity_filter)
    total_items = db.scalar(count_query) or 0
    pagination = pagination_details(total_items, page, INCIDENTS_PER_PAGE)
    incidents = db.scalars(
        query.order_by(desc(Incident.started_at))
        .offset((int(pagination["current_page"]) - 1) * INCIDENTS_PER_PAGE)
        .limit(INCIDENTS_PER_PAGE)
    ).all()
    return {
        "incidents": incidents,
        "status_filter": status_filter,
        "severity_filter": severity_filter,
        "pagination": pagination,
    }


@dashboard_router.get("/login", response_class=HTMLResponse)
def login_page(request: Request) -> HTMLResponse:
    """Render the admin login page."""

    if is_authenticated(request):
        return RedirectResponse("/", status_code=status.HTTP_303_SEE_OTHER)
    return templates.TemplateResponse(request=request, name="login.html", context={"error": None})


@dashboard_router.post("/login")
def login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    _: None = Depends(require_valid_csrf_token),
):
    """Start an admin session when the credentials are valid."""

    settings = get_settings()
    if username == settings.admin_username and password == settings.admin_password:
        request.session["admin_authenticated"] = True
        set_flash_message(request, "Signed in successfully.")
        return RedirectResponse("/", status_code=status.HTTP_303_SEE_OTHER)
    return templates.TemplateResponse(
        request=request,
        name="login.html",
        context={"error": "Invalid username or password"},
        status_code=status.HTTP_401_UNAUTHORIZED,
    )


@dashboard_router.post("/logout")
def logout(
    request: Request,
    _: None = Depends(require_dashboard_admin),
    __: None = Depends(require_valid_csrf_token),
):
    """Clear the admin session and return to the login page."""

    request.session.clear()
    return RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)


@dashboard_router.get("/", response_class=HTMLResponse)
def overview_page(request: Request, db: Session = Depends(get_db), _: None = Depends(require_dashboard_admin)):
    """Render the dashboard overview page."""

    monitors = db.scalars(select(Monitor).order_by(Monitor.name)).all()
    monitor_status_counts = {
        "healthy": sum(monitor.status == "healthy" for monitor in monitors),
        "degraded": sum(monitor.status == "degraded" for monitor in monitors),
        "down": sum(monitor.status == "down" for monitor in monitors),
        "paused": sum(monitor.status == "paused" for monitor in monitors),
        "unknown": sum(monitor.status == "unknown" for monitor in monitors),
    }
    active_incidents = db.scalars(
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
            "monitor_status_counts": monitor_status_counts,
            "active_incidents": active_incidents,
            "total_monitors": len(monitors),
            "monitors_needing_attention": monitor_status_counts["degraded"] + monitor_status_counts["down"],
            "recent_checks": recent_checks,
            "page_loaded_at": datetime.now(timezone.utc),
        },
    )


@dashboard_router.get("/monitors", response_class=HTMLResponse)
def monitors_page(
    request: Request,
    search: str = Query(default="", max_length=120),
    status_filter: str = Query(default="", alias="status"),
    page: int = Query(default=1, ge=1),
    db: Session = Depends(get_db),
    _: None = Depends(require_dashboard_admin),
):
    """Render the monitor list page."""

    context = build_monitor_list_context(db, search.strip(), status_filter, page)
    return templates.TemplateResponse(request=request, name="monitors.html", context=context)


@dashboard_router.post("/monitors")
async def create_monitor_form(
    request: Request,
    db: Session = Depends(get_db),
    _: None = Depends(require_dashboard_admin),
    __: None = Depends(require_valid_csrf_token),
):
    """Create a monitor from the dashboard form."""

    payload, form_values, form_errors = await validate_monitor_form(request)
    if payload is None:
        context = build_monitor_list_context(db, form_values=form_values, form_errors=form_errors)
        return templates.TemplateResponse(
            request=request,
            name="monitors.html",
            context=context,
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        )
    monitor = Monitor(**payload.model_dump())
    monitor.status = status_for_enabled_change(monitor.enabled)
    db.add(monitor)
    db.commit()
    set_flash_message(request, f"Monitor '{monitor.name}' was created.")
    return RedirectResponse("/monitors", status_code=status.HTTP_303_SEE_OTHER)


@dashboard_router.post("/monitors/{monitor_id}")
async def update_monitor_form(
    request: Request,
    monitor_id: int,
    db: Session = Depends(get_db),
    _: None = Depends(require_dashboard_admin),
    __: None = Depends(require_valid_csrf_token),
):
    """Update a monitor from the dashboard form."""

    monitor = get_monitor_or_404(db, monitor_id)
    payload, form_values, form_errors = await validate_monitor_form(request)
    if payload is None:
        context = build_monitor_detail_context(
            db,
            monitor,
            form_values=form_values,
            form_errors=form_errors,
        )
        return templates.TemplateResponse(
            request=request,
            name="monitor_detail.html",
            context=context,
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        )
    previous_enabled = monitor.enabled
    for field_name, value in payload.model_dump().items():
        setattr(monitor, field_name, value)
    if previous_enabled != monitor.enabled:
        monitor.status = status_for_enabled_change(monitor.enabled, monitor.status)
    db.commit()
    set_flash_message(request, f"Monitor '{monitor.name}' was updated.")
    return RedirectResponse(f"/monitors/{monitor_id}", status_code=status.HTTP_303_SEE_OTHER)


@dashboard_router.get("/monitors/{monitor_id}", response_class=HTMLResponse)
def monitor_detail_page(
    request: Request,
    monitor_id: int,
    check_page: int = Query(default=1, ge=1),
    db: Session = Depends(get_db),
    _: None = Depends(require_dashboard_admin),
):
    """Render one monitor with its checks and incidents."""

    monitor = get_monitor_or_404(db, monitor_id)
    context = build_monitor_detail_context(db, monitor, check_page)
    return templates.TemplateResponse(
        request=request,
        name="monitor_detail.html",
        context=context,
    )


@dashboard_router.post("/monitors/{monitor_id}/check")
def run_manual_monitor_check_form(
    request: Request,
    monitor_id: int,
    db: Session = Depends(get_db),
    _: None = Depends(require_dashboard_admin),
    __: None = Depends(require_valid_csrf_token),
):
    """Run one monitor check from the dashboard."""

    monitor = get_monitor_or_404(db, monitor_id)
    result = check_monitor_endpoint(monitor)
    record_monitor_check_result(db, monitor, result)
    if result.success:
        set_flash_message(request, "Manual check completed successfully.")
    else:
        set_flash_message(request, "Manual check failed. The result was saved.", "warning")
    return RedirectResponse(f"/monitors/{monitor_id}", status_code=status.HTTP_303_SEE_OTHER)


@dashboard_router.post("/monitors/{monitor_id}/state")
def change_monitor_enabled_state(
    request: Request,
    monitor_id: int,
    enabled: bool = Form(...),
    return_to: str = Form("/monitors"),
    db: Session = Depends(get_db),
    _: None = Depends(require_dashboard_admin),
    __: None = Depends(require_valid_csrf_token),
):
    """Pause or resume a monitor from the dashboard."""

    monitor = get_monitor_or_404(db, monitor_id)
    monitor.enabled = enabled
    monitor.status = status_for_enabled_change(enabled, monitor.status)
    db.commit()
    action = "resumed" if enabled else "paused"
    set_flash_message(request, f"Monitor '{monitor.name}' was {action}.")
    redirect_path = return_to if return_to.startswith("/monitors") else "/monitors"
    return RedirectResponse(redirect_path, status_code=status.HTTP_303_SEE_OTHER)


@dashboard_router.post("/monitors/{monitor_id}/delete")
def delete_monitor_form(
    request: Request,
    monitor_id: int,
    db: Session = Depends(get_db),
    _: None = Depends(require_dashboard_admin),
    __: None = Depends(require_valid_csrf_token),
):
    """Delete a monitor from the dashboard."""

    monitor = get_monitor_or_404(db, monitor_id)
    monitor_name = monitor.name
    db.delete(monitor)
    db.commit()
    set_flash_message(request, f"Monitor '{monitor_name}' was deleted.", "warning")
    return RedirectResponse("/monitors", status_code=status.HTTP_303_SEE_OTHER)


@dashboard_router.get("/incidents", response_class=HTMLResponse)
def incidents_page(
    request: Request,
    status_filter: str = Query(default="", alias="status"),
    severity_filter: str = Query(default="", alias="severity"),
    page: int = Query(default=1, ge=1),
    db: Session = Depends(get_db),
    _: None = Depends(require_dashboard_admin),
):
    """Render the incident list page."""

    context = build_incident_list_context(db, status_filter, severity_filter, page)
    return templates.TemplateResponse(request=request, name="incidents.html", context=context)


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
    request: Request,
    incident_id: int,
    status_value: str = Form(...),
    severity: str = Form("warning"),
    notes: str = Form(""),
    db: Session = Depends(get_db),
    _: None = Depends(require_dashboard_admin),
    __: None = Depends(require_valid_csrf_token),
):
    """Update an incident from the dashboard form."""

    incident = get_incident_or_404(db, incident_id)
    if status_value not in {"open", "acknowledged", "resolved"}:
        raise HTTPException(status_code=422, detail="Invalid incident status")
    if severity not in {"info", "warning", "critical"}:
        raise HTTPException(status_code=422, detail="Invalid incident severity")
    incident.status = status_value
    incident.severity = severity
    incident.notes = notes or None
    if status_value == "acknowledged" and incident.acknowledged_at is None:
        incident.acknowledged_at = datetime.now(timezone.utc)
    if status_value == "resolved" and incident.resolved_at is None:
        incident.resolved_at = datetime.now(timezone.utc)
    if status_value != "resolved":
        incident.resolved_at = None
    db.commit()
    set_flash_message(request, "Incident details were updated.")
    return RedirectResponse(f"/incidents/{incident_id}", status_code=status.HTTP_303_SEE_OTHER)


@dashboard_router.post("/incidents/{incident_id}/acknowledge")
def acknowledge_incident_form(
    request: Request,
    incident_id: int,
    db: Session = Depends(get_db),
    _: None = Depends(require_dashboard_admin),
    __: None = Depends(require_valid_csrf_token),
):
    """Mark an open incident as acknowledged."""

    incident = get_incident_or_404(db, incident_id)
    if incident.status == "open":
        incident.status = "acknowledged"
        incident.acknowledged_at = datetime.now(timezone.utc)
        db.commit()
        set_flash_message(request, "Incident was acknowledged.")
    else:
        set_flash_message(request, "Only an open incident can be acknowledged.", "warning")
    return RedirectResponse(f"/incidents/{incident_id}", status_code=status.HTTP_303_SEE_OTHER)


@dashboard_router.post("/incidents/{incident_id}/resolve")
def resolve_incident_form(
    request: Request,
    incident_id: int,
    db: Session = Depends(get_db),
    _: None = Depends(require_dashboard_admin),
    __: None = Depends(require_valid_csrf_token),
):
    """Mark an active incident as resolved."""

    incident = get_incident_or_404(db, incident_id)
    if incident.status in {"open", "acknowledged"}:
        incident.status = "resolved"
        incident.resolved_at = datetime.now(timezone.utc)
        db.commit()
        set_flash_message(request, "Incident was resolved.")
    else:
        set_flash_message(request, "This incident is already resolved.", "warning")
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
    monitor.status = status_for_enabled_change(monitor.enabled)
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
    if "enabled" in updates:
        monitor.status = status_for_enabled_change(monitor.enabled, monitor.status)
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
