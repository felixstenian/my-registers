"""ck_audit_events_action inclui 'confirm'

Revision ID: 0006_confirm_action
Revises: 0005_daily_snapshot_narrative
Create Date: 2026-07-19
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0006_confirm_action"
down_revision: str | None = "0005_daily_snapshot_narrative"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Fase confirm_items (parte de chat do SP-24) usa
    # audit_events.action='confirm'.
    op.drop_constraint("ck_audit_events_action", "audit_events", type_="check")
    op.create_check_constraint(
        "ck_audit_events_action",
        "audit_events",
        "action IN ('create','update','delete','correct','close','confirm')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_audit_events_action", "audit_events", type_="check")
    op.create_check_constraint(
        "ck_audit_events_action",
        "audit_events",
        "action IN ('create','update','delete','correct','close')",
    )
