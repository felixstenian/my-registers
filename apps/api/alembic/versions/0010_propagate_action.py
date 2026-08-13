"""ck_audit_events_action inclui 'propagate'

Revision ID: 0010_propagate_action
Revises: 0009_promotion_failed_action
Create Date: 2026-08-12

SP-163 / INV-14: NutrientFactPropagationService grava audit
`action='propagate'` em food_items e beverage_records quando um
NutrientFact editado propaga novos macros para registros vivos.

Auditoria é feature crítica (Const. §11 / INV-10).
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0010_propagate_action"
down_revision: str | None = "0009_promotion_failed_action"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("ck_audit_events_action", "audit_events", type_="check")
    op.create_check_constraint(
        "ck_audit_events_action",
        "audit_events",
        "action IN ('create','update','delete','correct','close','confirm','promotion_failed','propagate')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_audit_events_action", "audit_events", type_="check")
    op.create_check_constraint(
        "ck_audit_events_action",
        "audit_events",
        "action IN ('create','update','delete','correct','close','confirm','promotion_failed')",
    )