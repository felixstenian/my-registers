"""daily_snapshots.narrative

Revision ID: 0005_daily_snapshot_narrative
Revises: 0004_hydration_beverage_activity
Create Date: 2026-07-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005_daily_snapshot_narrative"
down_revision: str | None = "0004_hydration_beverage_activity"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "daily_snapshots",
        sa.Column("narrative", sa.Text(), nullable=True),
    )
    # Fase 7 usa `audit_events.action='close'` para o fechamento do dia
    # (INV-10 / Const. §22). O CHECK original só permitia create/update/
    # delete/correct.
    op.drop_constraint(
        "ck_audit_events_action", "audit_events", type_="check"
    )
    op.create_check_constraint(
        "ck_audit_events_action",
        "audit_events",
        "action IN ('create','update','delete','correct','close')",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_audit_events_action", "audit_events", type_="check"
    )
    op.create_check_constraint(
        "ck_audit_events_action",
        "audit_events",
        "action IN ('create','update','delete','correct')",
    )
    op.drop_column("daily_snapshots", "narrative")
