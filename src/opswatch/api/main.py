from pathlib import Path

from fastapi import Depends, FastAPI
from fastapi.responses import PlainTextResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from starlette.middleware.sessions import SessionMiddleware

from opswatch.api.request_logging import (
    configure_api_logging,
    elapsed_request_time_ms,
    get_request_id,
    log_api_request,
    started_request_timer,
)
from opswatch.api.routes import api_router, dashboard_router
from opswatch.config import get_settings
from opswatch.database import get_db
from opswatch.observability.metrics import build_opswatch_metrics

configure_api_logging()
settings = get_settings()

app = FastAPI(title="OpsWatch", version=settings.app_version)
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.session_secret,
    same_site="lax",
    https_only=False,
)
app.mount("/static", StaticFiles(directory=str(Path(__file__).parent / "static")), name="static")
app.include_router(dashboard_router)
app.include_router(api_router)


@app.middleware("http")
async def structured_request_logging(request, call_next):
    """Write one structured log event for each API request."""

    request_id = get_request_id(request)
    started_at = started_request_timer()
    try:
        response = await call_next(request)
    except Exception as exc:
        log_api_request(
            request,
            request_id,
            status_code=500,
            duration_ms=elapsed_request_time_ms(started_at),
            error_type=type(exc).__name__,
        )
        raise

    response.headers["x-request-id"] = request_id
    log_api_request(
        request,
        request_id,
        status_code=response.status_code,
        duration_ms=elapsed_request_time_ms(started_at),
    )
    return response


@app.get("/health")
def health() -> dict[str, str]:
    """Return a basic process health response."""

    return {"status": "ok"}


@app.get("/ready")
def ready(db=Depends(get_db)) -> dict[str, str]:
    """Return ready when the app can query the database."""

    db.execute(text("select 1"))
    return {"status": "ready"}


@app.get("/version")
def version() -> dict[str, str]:
    """Return the app version and git commit value."""

    return {"version": settings.app_version, "git_sha": settings.git_sha}


@app.get("/metrics", response_class=PlainTextResponse)
def metrics(db=Depends(get_db)) -> PlainTextResponse:
    """Return application metrics in Prometheus text format."""

    return PlainTextResponse(
        build_opswatch_metrics(db),
        media_type="text/plain; version=0.0.4; charset=utf-8",
    )
