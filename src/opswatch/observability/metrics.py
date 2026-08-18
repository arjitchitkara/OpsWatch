from collections.abc import Iterable

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from opswatch.models import Incident, Monitor, MonitorCheck


def escape_metric_label_value(value: str) -> str:
    """Return a safe Prometheus label value."""

    return value.replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')


def build_metric_line(name: str, value: int, labels: dict[str, str] | None = None) -> str:
    """Return one Prometheus metric line."""

    if not labels:
        return f"{name} {value}"

    label_pairs = ",".join(
        f'{label_name}="{escape_metric_label_value(label_value)}"' for label_name, label_value in sorted(labels.items())
    )
    return f"{name}{{{label_pairs}}} {value}"


def count_rows(db: Session, model) -> int:
    """Return the number of rows for one database model."""

    return db.scalar(select(func.count()).select_from(model)) or 0


def count_rows_by_field(db: Session, model, field) -> Iterable[tuple[str, int]]:
    """Return row counts grouped by one model field."""

    rows = db.execute(select(field, func.count()).select_from(model).group_by(field).order_by(field)).all()
    for field_value, row_count in rows:
        yield str(field_value), row_count


def build_opswatch_metrics(db: Session) -> str:
    """Return OpsWatch metrics in Prometheus text format."""

    lines = [
        "# HELP opswatch_monitors_count Current number of monitors.",
        "# TYPE opswatch_monitors_count gauge",
        build_metric_line("opswatch_monitors_count", count_rows(db, Monitor)),
        "# HELP opswatch_monitor_status_count Current number of monitors by status.",
        "# TYPE opswatch_monitor_status_count gauge",
    ]

    for monitor_status, monitor_count in count_rows_by_field(db, Monitor, Monitor.status):
        lines.append(build_metric_line("opswatch_monitor_status_count", monitor_count, {"status": monitor_status}))

    lines.extend(
        [
            "# HELP opswatch_monitor_enabled_count Current number of monitors by enabled state.",
            "# TYPE opswatch_monitor_enabled_count gauge",
        ]
    )
    for enabled_value, monitor_count in count_rows_by_field(db, Monitor, Monitor.enabled):
        lines.append(build_metric_line("opswatch_monitor_enabled_count", monitor_count, {"enabled": enabled_value.lower()}))

    lines.extend(
        [
            "# HELP opswatch_monitor_checks_count Current number of saved monitor checks.",
            "# TYPE opswatch_monitor_checks_count gauge",
            build_metric_line("opswatch_monitor_checks_count", count_rows(db, MonitorCheck)),
            "# HELP opswatch_monitor_check_result_count Current number of saved monitor checks by result.",
            "# TYPE opswatch_monitor_check_result_count gauge",
        ]
    )
    for success_value, check_count in count_rows_by_field(db, MonitorCheck, MonitorCheck.success):
        lines.append(build_metric_line("opswatch_monitor_check_result_count", check_count, {"success": success_value.lower()}))

    lines.extend(
        [
            "# HELP opswatch_incidents_count Current number of incidents.",
            "# TYPE opswatch_incidents_count gauge",
            build_metric_line("opswatch_incidents_count", count_rows(db, Incident)),
            "# HELP opswatch_incident_status_count Current number of incidents by status.",
            "# TYPE opswatch_incident_status_count gauge",
        ]
    )
    for incident_status, incident_count in count_rows_by_field(db, Incident, Incident.status):
        lines.append(build_metric_line("opswatch_incident_status_count", incident_count, {"status": incident_status}))

    return "\n".join(lines) + "\n"
