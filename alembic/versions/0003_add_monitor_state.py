"""Add monitor state fields."""

import sqlalchemy as sa
from alembic import op

revision = "0003_add_monitor_state"
down_revision = "0002_rename_targets_to_monitors"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("monitors", sa.Column("recovery_threshold", sa.Integer(), nullable=False, server_default="2"))
    op.add_column("monitors", sa.Column("status", sa.String(length=40), nullable=False, server_default="unknown"))
    op.add_column("monitors", sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("monitors", sa.Column("last_status_code", sa.Integer(), nullable=True))
    op.add_column("monitors", sa.Column("last_response_time_ms", sa.Integer(), nullable=True))
    op.add_column("monitors", sa.Column("last_error_type", sa.String(length=80), nullable=True))
    op.add_column("monitors", sa.Column("last_error_message", sa.Text(), nullable=True))
    op.execute("update monitors set status = 'paused' where enabled = false")


def downgrade() -> None:
    op.drop_column("monitors", "last_error_message")
    op.drop_column("monitors", "last_error_type")
    op.drop_column("monitors", "last_response_time_ms")
    op.drop_column("monitors", "last_status_code")
    op.drop_column("monitors", "last_checked_at")
    op.drop_column("monitors", "status")
    op.drop_column("monitors", "recovery_threshold")
