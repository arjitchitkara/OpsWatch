from sqlalchemy import text

from opswatch.database import SessionLocal


def main() -> None:
    """Check that the worker can query the database."""

    with SessionLocal() as db:
        db.execute(text("select 1"))


if __name__ == "__main__":
    main()
