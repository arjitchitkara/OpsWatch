"""Rename targets to monitors."""

from alembic import op

revision = "0002_rename_targets_to_monitors"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_index("ix_incidents_target_status", table_name="incidents")
    op.drop_index("ix_checks_success", table_name="checks")
    op.drop_index("ix_checks_target_checked", table_name="checks")
    op.drop_index("ix_targets_enabled", table_name="targets")

    op.rename_table("targets", "monitors")
    op.rename_table("checks", "monitor_checks")
    op.alter_column("monitor_checks", "target_id", new_column_name="monitor_id")
    op.alter_column("incidents", "target_id", new_column_name="monitor_id")

    op.create_index("ix_monitors_enabled", "monitors", ["enabled"])
    op.create_index("ix_monitor_checks_monitor_checked", "monitor_checks", ["monitor_id", "checked_at"])
    op.create_index("ix_monitor_checks_success", "monitor_checks", ["success"])
    op.create_index("ix_incidents_monitor_status", "incidents", ["monitor_id", "status"])


def downgrade() -> None:
    op.drop_index("ix_incidents_monitor_status", table_name="incidents")
    op.drop_index("ix_monitor_checks_success", table_name="monitor_checks")
    op.drop_index("ix_monitor_checks_monitor_checked", table_name="monitor_checks")
    op.drop_index("ix_monitors_enabled", table_name="monitors")

    op.alter_column("incidents", "monitor_id", new_column_name="target_id")
    op.alter_column("monitor_checks", "monitor_id", new_column_name="target_id")
    op.rename_table("monitor_checks", "checks")
    op.rename_table("monitors", "targets")

    op.create_index("ix_targets_enabled", "targets", ["enabled"])
    op.create_index("ix_checks_target_checked", "checks", ["target_id", "checked_at"])
    op.create_index("ix_checks_success", "checks", ["success"])
    op.create_index("ix_incidents_target_status", "incidents", ["target_id", "status"])
