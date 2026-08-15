"""workout_sessions.template_id (SP-178, INV-20)

Revision ID: 0015_workout_session_template_id
Revises: 0014_workout_templates
Create Date: 2026-08-15

SP-178/INV-20 (Bloco 3.b, E4): sessão do fluxo guiado referencia o
template escolhido. `workout_sessions.template_id` é nullable — sessão
livre (SP-120) não tem template. FK sem ON DELETE: template nunca é
deletado (API só toggla `active`), então a referência fica estável para
sessões encerradas (INV-20 — snapshot congelado).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0015_workout_session_template_id"
down_revision: str | None = "0014_workout_templates"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "workout_sessions",
        sa.Column("template_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_workout_sessions_template_id",
        "workout_sessions",
        "workout_templates",
        ["template_id"],
        ["id"],
    )
    op.create_index(
        "ix_workout_sessions_user_template",
        "workout_sessions",
        ["user_id", "template_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_workout_sessions_user_template", table_name="workout_sessions")
    op.drop_constraint("fk_workout_sessions_template_id", "workout_sessions", type_="foreignkey")
    op.drop_column("workout_sessions", "template_id")