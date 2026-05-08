"""add audit_log recordings integration tables

Revision ID: 002
Revises: 001
Create Date: 2025-06-01 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "audit_log",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("timestamp", sa.Float, nullable=False),
        sa.Column("action", sa.Text, nullable=False),
        sa.Column("username", sa.Text, nullable=False),
        sa.Column("resource_type", sa.Text, nullable=False, server_default=""),
        sa.Column("resource_id", sa.Text, nullable=False, server_default=""),
        sa.Column("detail", sa.Text, nullable=False, server_default=""),
        sa.Column("ip_address", sa.Text, nullable=False, server_default=""),
        sa.Column("user_agent", sa.Text, nullable=False, server_default=""),
    )
    op.create_index("idx_audit_timestamp", "audit_log", ["timestamp"])
    op.create_index("idx_audit_username", "audit_log", ["username"])
    op.create_index("idx_audit_action", "audit_log", ["action"])

    op.create_table(
        "recordings",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("protocol", sa.Text, nullable=False),
        sa.Column("start_time", sa.Float, nullable=False),
        sa.Column("end_time", sa.Float, server_default="0"),
        sa.Column("messages", sa.Text, nullable=False, server_default="[]"),
        sa.Column("metadata", sa.Text, nullable=False, server_default="{}"),
    )
    op.create_index("idx_recordings_protocol", "recordings", ["protocol"])

    op.create_table(
        "integration_config",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("key", sa.Text, nullable=False, unique=True),
        sa.Column("value", sa.Text, nullable=False),
        sa.Column("description", sa.Text, server_default=""),
        sa.Column("created_at", sa.TIMESTAMP, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.TIMESTAMP, server_default=sa.text("CURRENT_TIMESTAMP")),
    )

    op.create_table(
        "alarm_reaction_rules",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("rule_id", sa.Text, nullable=False, unique=True),
        sa.Column("source_device_id", sa.Text, server_default=""),
        sa.Column("alarm_severity", sa.Text, server_default=""),
        sa.Column("action", sa.Text, nullable=False, server_default="stop_device"),
        sa.Column("target_device_id", sa.Text, server_default=""),
        sa.Column("action_params", sa.Text, server_default="{}"),
        sa.Column("enabled", sa.Integer, nullable=False, server_default="1"),
        sa.Column("created_at", sa.TIMESTAMP, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.TIMESTAMP, server_default=sa.text("CURRENT_TIMESTAMP")),
    )


def downgrade() -> None:
    op.drop_table("alarm_reaction_rules")
    op.drop_table("integration_config")
    op.drop_table("recordings")
    op.drop_table("audit_log")
