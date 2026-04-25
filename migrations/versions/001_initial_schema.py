"""initial schema

Revision ID: 001
Revises:
Create Date: 2025-01-01 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "devices",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("protocol", sa.Text, nullable=False),
        sa.Column("template_id", sa.Text, nullable=True),
        sa.Column("points", sa.Text, nullable=False, server_default="[]"),
        sa.Column("protocol_config", sa.Text, nullable=False, server_default="{}"),
        sa.Column("created_at", sa.TIMESTAMP, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_index("idx_devices_protocol", "devices", ["protocol"])

    op.create_table(
        "scenarios",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("description", sa.Text, nullable=False, server_default=""),
        sa.Column("devices", sa.Text, nullable=False, server_default="[]"),
        sa.Column("rules", sa.Text, nullable=False, server_default="[]"),
        sa.Column("created_at", sa.TIMESTAMP, server_default=sa.text("CURRENT_TIMESTAMP")),
    )

    op.create_table(
        "templates",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("protocol", sa.Text, nullable=False),
        sa.Column("description", sa.Text, nullable=False, server_default=""),
        sa.Column("manufacturer", sa.Text, nullable=False, server_default=""),
        sa.Column("model", sa.Text, nullable=False, server_default=""),
        sa.Column("points", sa.Text, nullable=False, server_default="[]"),
        sa.Column("protocol_config", sa.Text, nullable=False, server_default="{}"),
        sa.Column("tags", sa.Text, nullable=False, server_default="[]"),
    )
    op.create_index("idx_templates_protocol", "templates", ["protocol"])

    op.create_table(
        "test_cases",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("description", sa.Text, nullable=False, server_default=""),
        sa.Column("tags", sa.Text, nullable=False, server_default="[]"),
        sa.Column("steps", sa.Text, nullable=False, server_default="[]"),
        sa.Column("setup_steps", sa.Text, nullable=False, server_default="[]"),
        sa.Column("teardown_steps", sa.Text, nullable=False, server_default="[]"),
        sa.Column("created_at", sa.TIMESTAMP, server_default=sa.text("CURRENT_TIMESTAMP")),
    )

    op.create_table(
        "test_suites",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("description", sa.Text, nullable=False, server_default=""),
        sa.Column("test_case_ids", sa.Text, nullable=False, server_default="[]"),
        sa.Column("tags", sa.Text, nullable=False, server_default="[]"),
        sa.Column("created_at", sa.Float, nullable=False, server_default="0"),
        sa.Column("updated_at", sa.Float, nullable=False, server_default="0"),
    )

    op.create_table(
        "test_reports",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("start_time", sa.Float, nullable=False, server_default="0"),
        sa.Column("end_time", sa.Float, nullable=False, server_default="0"),
        sa.Column("total", sa.Integer, nullable=False, server_default="0"),
        sa.Column("passed", sa.Integer, nullable=False, server_default="0"),
        sa.Column("failed", sa.Integer, nullable=False, server_default="0"),
        sa.Column("errors", sa.Integer, nullable=False, server_default="0"),
        sa.Column("skipped", sa.Integer, nullable=False, server_default="0"),
        sa.Column("environment", sa.Text, nullable=False, server_default="{}"),
        sa.Column("test_cases", sa.Text, nullable=False, server_default="[]"),
        sa.Column("created_at", sa.TIMESTAMP, server_default=sa.text("CURRENT_TIMESTAMP")),
    )

    op.create_table(
        "users",
        sa.Column("username", sa.Text, primary_key=True),
        sa.Column("id", sa.Text, nullable=False),
        sa.Column("password_hash", sa.Text, nullable=False),
        sa.Column("role", sa.Text, nullable=False, server_default="user"),
        sa.Column("created_at", sa.Float, nullable=False, server_default="0"),
        sa.Column("login_attempts", sa.Integer, nullable=False, server_default="0"),
        sa.Column("locked_until", sa.Float, nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_table("users")
    op.drop_table("test_reports")
    op.drop_table("test_suites")
    op.drop_table("test_cases")
    op.drop_table("templates")
    op.drop_table("scenarios")
    op.drop_table("devices")
