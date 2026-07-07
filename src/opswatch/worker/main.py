import logging
import time
from datetime import datetime, timezone

from sqlalchemy import desc, select

from opswatch.config import get_settings
from opswatch.database import SessionLocal
from opswatch.models import Check, Target
from opswatch.services.checker import run_http_check
from opswatch.services.incidents import record_check_and_update_incidents

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("opswatch.worker")


def target_is_due(db, target: Target) -> bool:
    latest_check = db.scalar(
        select(Check).where(Check.target_id == target.id).order_by(desc(Check.checked_at), desc(Check.id)).limit(1)
    )
    if latest_check is None:
        return True
    elapsed = datetime.now(timezone.utc) - latest_check.checked_at
    return elapsed.total_seconds() >= target.interval_seconds


def run_once() -> None:
    with SessionLocal() as db:
        targets = db.scalars(select(Target).where(Target.enabled.is_(True)).order_by(Target.id)).all()
        for target in targets:
            if not target_is_due(db, target):
                continue
            logger.info("checking target id=%s name=%s url=%s", target.id, target.name, target.url)
            outcome = run_http_check(target)
            record_check_and_update_incidents(db, target, outcome)


def main() -> None:
    settings = get_settings()
    logger.info("OpsWatch worker started; poll interval=%ss", settings.worker_poll_seconds)
    while True:
        try:
            run_once()
        except Exception:
            logger.exception("worker loop failed")
        time.sleep(settings.worker_poll_seconds)


if __name__ == "__main__":
    main()
