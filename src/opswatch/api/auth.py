from fastapi import HTTPException, Request, status


def is_authenticated(request: Request) -> bool:
    """Return true when the admin session is logged in."""

    return bool(request.session.get("admin_authenticated"))


def require_admin(request: Request) -> None:
    """Require admin login for JSON API routes."""

    if not is_authenticated(request):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")


def require_dashboard_admin(request: Request) -> None:
    """Require admin login for dashboard pages."""

    if not is_authenticated(request):
        raise HTTPException(status_code=status.HTTP_303_SEE_OTHER, headers={"Location": "/login"})
