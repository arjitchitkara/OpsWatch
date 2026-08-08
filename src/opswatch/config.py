from dataclasses import dataclass
from functools import lru_cache
import os


@dataclass(frozen=True)
class Settings:
    """Runtime settings loaded from environment variables."""

    app_version: str = "0.4.0"
    git_sha: str = "local"
    admin_username: str = "admin"
    admin_password: str = "admin"
    session_secret: str = "change-me-for-local-dev"
    database_url: str = "postgresql+psycopg://opswatch:opswatch@localhost:6432/opswatch"
    migration_database_url: str = "postgresql+psycopg://opswatch:opswatch@localhost:5432/opswatch"
    worker_poll_seconds: int = 5


def _int_env(name: str, default: int) -> int:
    """Read an integer environment variable or return the default."""

    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


@lru_cache
def get_settings() -> Settings:
    """Return cached application settings."""

    return Settings(
        app_version=os.getenv("APP_VERSION", "0.4.0"),
        git_sha=os.getenv("GIT_SHA", "local"),
        admin_username=os.getenv("ADMIN_USERNAME", "admin"),
        admin_password=os.getenv("ADMIN_PASSWORD", "admin"),
        session_secret=os.getenv("SESSION_SECRET", "change-me-for-local-dev"),
        database_url=os.getenv(
            "DATABASE_URL",
            "postgresql+psycopg://opswatch:opswatch@localhost:6432/opswatch",
        ),
        migration_database_url=os.getenv(
            "MIGRATION_DATABASE_URL",
            "postgresql+psycopg://opswatch:opswatch@localhost:5432/opswatch",
        ),
        worker_poll_seconds=_int_env("WORKER_POLL_SECONDS", 5),
    )
