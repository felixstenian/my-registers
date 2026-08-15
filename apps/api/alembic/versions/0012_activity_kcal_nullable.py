"""activity_records.kcal_burned nullable (sem server_default)

Revision ID: 0012_activity_kcal_nullable
Revises: 0011_workout_tracking
Create Date: 2026-08-15

SP-126 (núcleo Bloco 3): `consolidate_to_activity` cria `activity_record`
com `kcal_burned=NULL` quando o usuário não tem `weight_kg` no perfil
(warning `weight_kg_required_for_kcal`) — treino registrado, kcal fica
pendente. Torna a coluna nullable E remove o `server_default='0'`, para
NULL persistir de verdade (não ser transformado em 0 pelo default).
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0012_activity_kcal_nullable"
down_revision: str | None = "0011_workout_tracking"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "activity_records",
        "kcal_burned",
        existing_type=sa.Numeric(10, 2),
        existing_server_default=sa.text("0"),
        server_default=None,
        nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        "activity_records",
        "kcal_burned",
        existing_type=sa.Numeric(10, 2),
        server_default=sa.text("0"),
        nullable=False,
    )