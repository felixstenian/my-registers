"""ck_audit_events_action inclui 'promotion_failed'

Revision ID: 0009_promotion_failed_action
Revises: 0008_nutrient_facts_created_by
Create Date: 2026-07-28

SP-143 / T-B521 grava audit `action='promotion_failed'` em food_item
quando a promoção acoplada ao rótulo falha (item de outro user,
deletado, dia fechado). Auditoria é feature crítica (Const. §11 /
INV-10) — não podemos silenciosamente descartar; guardamos o
histórico com reason + fact_id.

Removemos também 'confirm' do CHECK: o fluxo de confirmação inteiro
foi removido no Bloco 5 revisão v1.12 (T-B512). Facts históricas com
action='confirm' permanecem intactas — só o CHECK constraint deixa
de aceitar novas.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0009_promotion_failed_action"
down_revision: str | None = "0008_nutrient_facts_created_by"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("ck_audit_events_action", "audit_events", type_="check")
    op.create_check_constraint(
        "ck_audit_events_action",
        "audit_events",
        "action IN ('create','update','delete','correct','close','confirm','promotion_failed')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_audit_events_action", "audit_events", type_="check")
    op.create_check_constraint(
        "ck_audit_events_action",
        "audit_events",
        "action IN ('create','update','delete','correct','close','confirm')",
    )
