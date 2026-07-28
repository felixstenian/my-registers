"""nutrient_facts.created_by (Bloco 5 / SP-141)

Revision ID: 0008_nutrient_facts_created_by
Revises: 0007_weekly_reports
Create Date: 2026-07-27

Adiciona coluna `created_by` (FK users.id, nullable) em `nutrient_facts`.
Necessária para SP-141 (cadastro manual isolado por usuário) e SP-142
(promoção de item legado por dono conhecido). Existing rows do seed
TBCA / label_ocr ficam com `created_by=NULL` — comportamento correto,
porque catálogo canônico não tem dono.

O CHECK de `source` já inclui `'manual'` — não precisa migração pra
adicionar `'user_manual'`. Reusamos `'manual'` (semântica igual).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0008_nutrient_facts_created_by"
down_revision: str | None = "0007_weekly_reports"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "nutrient_facts",
        sa.Column(
            "created_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    # Índice parcial: só rows com `created_by` (facts pessoais).
    # Consulta comum: "meus facts manuais" — WHERE created_by = $1.
    op.create_index(
        "ix_nutrient_facts_created_by",
        "nutrient_facts",
        ["created_by"],
        postgresql_where=sa.text("created_by IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_nutrient_facts_created_by", table_name="nutrient_facts")
    op.drop_column("nutrient_facts", "created_by")
