import logging
import time
from datetime import datetime, timezone

from sqlalchemy import desc, select

from opswatch.config import get_settings
from opswatch.database import SessionLocal
from opswatch.models import Monitor, MonitorCheck
from opswatch.monitoring.http_checks import check_monitor_endpoint
from opswatch.monitoring.incident_lifecycle import record_monitor_check_result

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("opswatch.worker")


def monitor_is_due_for_check(db, monitor: Monitor) -> bool:
    latest_check = db.scalar(
        select(MonitorCheck)
        .where(MonitorCheck.monitor_id == monitor.id)
        .order_by(desc(MonitorCheck.checked_at), desc(MonitorCheck.id))
        .limit(1)
    )
    if latest_check is None:
        return True
    elapsed = datetime.now(timezone.utc) - latest_check.checked_at
    return elapsed.total_seconds() >= monitor.interval_seconds


def run_due_monitor_checks_once() -> None:
    with SessionLocal() as db:
        monitors = db.scalars(select(Monitor).where(Monitor.enabled.is_(True)).order_by(Monitor.id)).all()
        for monitor in monitors:
            if not monitor_is_due_for_check(db, monitor):
                continue
            logger.info("checking monitor id=%s name=%s url=%s", monitor.id, monitor.name, monitor.url)
            result = check_monitor_endpoint(monitor)
            record_monitor_check_result(db, monitor, result)


def main() -> None:
    settings = get_settings()
    logger.info("OpsWatch worker started; poll interval=%ss", settings.worker_poll_seconds)
    while True:
        try:
            run_due_monitor_checks_once()
        except Exception:
            logger.exception("worker loop failed")
        time.sleep(settings.worker_poll_seconds)


if __name__ == "__main__":
    main()
