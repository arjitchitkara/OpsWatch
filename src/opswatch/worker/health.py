from urllib.request import urlopen

from sqlalchemy import text

from opswatch.config import get_settings
from opswatch.database import SessionLocal


def main() -> None:
    """Check that the worker can query the database and metrics server."""

    settings = get_settings()
    with SessionLocal() as db:
        db.execute(text("select 1"))
    urlopen(f"http://127.0.0.1:{settings.worker_metrics_port}/health", timeout=2).read()


if __name__ == "__main__":
    main()
