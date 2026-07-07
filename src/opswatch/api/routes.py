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
from opswatch.models import Check, Incident, Target
from opswatch.schemas import CheckRead, IncidentRead, IncidentUpdate, TargetCreate, TargetRead, TargetUpdate
from opswatch.services.checker import run_http_check
from opswatch.services.incidents import record_check_and_update_incidents

templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
dashboard_router = APIRouter()
api_router = APIRouter(prefix="/api/v1")


def _target_or_404(db: Session, target_id: int) -> Target:
    target = db.get(Target, target_id)
    if target is None:
        raise HTTPException(status_code=404, detail="Target not found")
    return target


def _incident_or_404(db: Session, incident_id: int) -> Incident:
    incident = db.get(Incident, incident_id)
    if incident is None:
        raise HTTPException(status_code=404, detail="Incident not found")
    return incident


@dashboard_router.get("/login", response_class=HTMLResponse)
def login_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request=request, name="login.html", context={"error": None})


@dashboard_router.post("/login")
def login(request: Request, username: str = Form(...), password: str = Form(...)):
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
    request.session.clear()
    return RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)


@dashboard_router.get("/", response_class=HTMLResponse)
def overview(request: Request, db: Session = Depends(get_db), _: None = Depends(require_dashboard_admin)):
    targets = db.scalars(select(Target).order_by(Target.name)).all()
    open_incidents = db.scalars(
        select(Incident)
        .options(selectinload(Incident.target))
        .where(Incident.status.in_(["open", "acknowledged"]))
        .order_by(desc(Incident.started_at))
    ).all()
    recent_checks = db.scalars(
        select(Check).options(selectinload(Check.target)).order_by(desc(Check.checked_at), desc(Check.id)).limit(10)
    ).all()
    return templates.TemplateResponse(
        request=request,
        name="overview.html",
        context={
            "targets": targets,
            "open_incidents": open_incidents,
            "recent_checks": recent_checks,
            "authenticated": is_authenticated(request),
        },
    )


@dashboard_router.get("/targets", response_class=HTMLResponse)
def targets_page(request: Request, db: Session = Depends(get_db), _: None = Depends(require_dashboard_admin)):
    targets = db.scalars(select(Target).order_by(Target.name)).all()
    return templates.TemplateResponse(request=request, name="targets.html", context={"targets": targets})


@dashboard_router.post("/targets")
def create_target_form(
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
    target = Target(
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
    db.add(target)
    db.commit()
    return RedirectResponse("/targets", status_code=status.HTTP_303_SEE_OTHER)


@dashboard_router.get("/targets/{target_id}", response_class=HTMLResponse)
def target_detail(
    request: Request,
    target_id: int,
    db: Session = Depends(get_db),
    _: None = Depends(require_dashboard_admin),
):
    target = _target_or_404(db, target_id)
    checks = db.scalars(
        select(Check).where(Check.target_id == target_id).order_by(desc(Check.checked_at), desc(Check.id)).limit(50)
    ).all()
    incidents = db.scalars(
        select(Incident).where(Incident.target_id == target_id).order_by(desc(Incident.started_at)).limit(20)
    ).all()
    return templates.TemplateResponse(
        request=request,
        name="target_detail.html",
        context={"target": target, "checks": checks, "incidents": incidents},
    )


@dashboard_router.post("/targets/{target_id}/check")
def manual_check_form(target_id: int, db: Session = Depends(get_db), _: None = Depends(require_dashboard_admin)):
    target = _target_or_404(db, target_id)
    outcome = run_http_check(target)
    record_check_and_update_incidents(db, target, outcome)
    return RedirectResponse(f"/targets/{target_id}", status_code=status.HTTP_303_SEE_OTHER)


@dashboard_router.post("/targets/{target_id}/delete")
def delete_target_form(target_id: int, db: Session = Depends(get_db), _: None = Depends(require_dashboard_admin)):
    target = _target_or_404(db, target_id)
    db.delete(target)
    db.commit()
    return RedirectResponse("/targets", status_code=status.HTTP_303_SEE_OTHER)


@dashboard_router.get("/incidents", response_class=HTMLResponse)
def incidents_page(request: Request, db: Session = Depends(get_db), _: None = Depends(require_dashboard_admin)):
    incidents = db.scalars(
        select(Incident).options(selectinload(Incident.target)).order_by(desc(Incident.started_at))
    ).all()
    return templates.TemplateResponse(request=request, name="incidents.html", context={"incidents": incidents})


@dashboard_router.get("/incidents/{incident_id}", response_class=HTMLResponse)
def incident_detail(
    request: Request,
    incident_id: int,
    db: Session = Depends(get_db),
    _: None = Depends(require_dashboard_admin),
):
    incident = _incident_or_404(db, incident_id)
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
    incident = _incident_or_404(db, incident_id)
    incident.status = status_value
    incident.severity = severity
    incident.notes = notes or None
    if status_value == "acknowledged" and incident.acknowledged_at is None:
        incident.acknowledged_at = datetime.now(timezone.utc)
    if status_value == "resolved" and incident.resolved_at is None:
        incident.resolved_at = datetime.now(timezone.utc)
    db.commit()
    return RedirectResponse(f"/incidents/{incident_id}", status_code=status.HTTP_303_SEE_OTHER)


@api_router.get("/targets", response_model=list[TargetRead])
def list_targets(db: Session = Depends(get_db)):
    return db.scalars(select(Target).order_by(Target.name)).all()


@api_router.post("/targets", response_model=TargetRead, status_code=status.HTTP_201_CREATED)
def create_target(payload: TargetCreate, db: Session = Depends(get_db), _: None = Depends(require_admin)):
    target = Target(**payload.model_dump())
    target.method = target.method.upper()
    db.add(target)
    db.commit()
    db.refresh(target)
    return target


@api_router.get("/targets/{target_id}", response_model=TargetRead)
def get_target(target_id: int, db: Session = Depends(get_db)):
    return _target_or_404(db, target_id)


@api_router.patch("/targets/{target_id}", response_model=TargetRead)
def update_target(
    target_id: int,
    payload: TargetUpdate,
    db: Session = Depends(get_db),
    _: None = Depends(require_admin),
):
    target = _target_or_404(db, target_id)
    updates = payload.model_dump(exclude_unset=True)
    for field, value in updates.items():
        setattr(target, field, value.upper() if field == "method" and value else value)
    db.commit()
    db.refresh(target)
    return target


@api_router.delete("/targets/{target_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_target(target_id: int, db: Session = Depends(get_db), _: None = Depends(require_admin)):
    target = _target_or_404(db, target_id)
    db.delete(target)
    db.commit()
    return None


@api_router.post("/targets/{target_id}/check", response_model=CheckRead)
def run_manual_check(target_id: int, db: Session = Depends(get_db), _: None = Depends(require_admin)):
    target = _target_or_404(db, target_id)
    outcome = run_http_check(target)
    return record_check_and_update_incidents(db, target, outcome)


@api_router.get("/checks", response_model=list[CheckRead])
def list_checks(
    target_id: int | None = Query(default=None),
    success: bool | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
):
    query = select(Check).order_by(desc(Check.checked_at), desc(Check.id)).limit(limit)
    if target_id is not None:
        query = query.where(Check.target_id == target_id)
    if success is not None:
        query = query.where(Check.success.is_(success))
    return db.scalars(query).all()


@api_router.get("/targets/{target_id}/checks", response_model=list[CheckRead])
def list_target_checks(target_id: int, limit: int = Query(default=100, ge=1, le=500), db: Session = Depends(get_db)):
    _target_or_404(db, target_id)
    return db.scalars(
        select(Check).where(Check.target_id == target_id).order_by(desc(Check.checked_at), desc(Check.id)).limit(limit)
    ).all()


@api_router.get("/incidents", response_model=list[IncidentRead])
def list_incidents(status_filter: str | None = Query(default=None, alias="status"), db: Session = Depends(get_db)):
    query = select(Incident).order_by(desc(Incident.started_at))
    if status_filter:
        query = query.where(Incident.status == status_filter)
    return db.scalars(query).all()


@api_router.get("/incidents/{incident_id}", response_model=IncidentRead)
def get_incident(incident_id: int, db: Session = Depends(get_db)):
    return _incident_or_404(db, incident_id)


@api_router.patch("/incidents/{incident_id}", response_model=IncidentRead)
def update_incident(
    incident_id: int,
    payload: IncidentUpdate,
    db: Session = Depends(get_db),
    _: None = Depends(require_admin),
):
    incident = _incident_or_404(db, incident_id)
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
