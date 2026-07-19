"""weekly_reports

Revision ID: 0007_weekly_reports
Revises: 0006_confirm_action
Create Date: 2026-07-19
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0007_weekly_reports"
down_revision: str | None = "0006_confirm_action"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "weekly_reports",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            primary_key=True,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("window_start", sa.Date(), nullable=True),
        sa.Column("window_end", sa.Date(), nullable=True),
        sa.Column("days_included", sa.Integer(), nullable=False),
        sa.Column(
            "totals", postgresql.JSONB(), nullable=False, server_default="{}"
        ),
        sa.Column(
            "averages", postgresql.JSONB(), nullable=False, server_default="{}"
        ),
        sa.Column(
            "per_day", postgresql.JSONB(), nullable=False, server_default="[]"
        ),
        sa.Column(
            "warnings",
            postgresql.JSONB(),
            nullable=False,
            server_default="[]",
        ),
        sa.Column(
            "snapshot_versions",
            postgresql.JSONB(),
            nullable=False,
            server_default="[]",
        ),
        sa.Column("narrative", sa.Text(), nullable=True),
        sa.Column(
            "generated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "version", sa.Integer(), nullable=False, server_default="1"
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint(
            "user_id",
            "window_start",
            "window_end",
            name="uq_weekly_reports_user_window",
        ),
    )
    op.create_index(
        "ix_weekly_reports_user_generated",
        "weekly_reports",
        ["user_id", sa.text("generated_at DESC")],
    )
    op.execute(
        "CREATE TRIGGER set_updated_at BEFORE UPDATE ON weekly_reports "
        "FOR EACH ROW EXECUTE FUNCTION set_updated_at()"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS set_updated_at ON weekly_reports")
    op.drop_index("ix_weekly_reports_user_generated", table_name="weekly_reports")
    op.drop_table("weekly_reports")
