"""messages.via (SP-173) — pool de messages isolado por via

Revision ID: 0013_messages_via
Revises: 0012_activity_kcal_nullable
Create Date: 2026-08-15

SP-173 (Bloco 3.b / módulo de treino): o chat de treino dedicado reusa o
mesmo pool de `messages` do chat de alimentação, isolado por coluna nova
`via` (`'food'` default, `'workout'` para treino). Sem backfill — o
`server_default` cobre as linhas pré-existentes. Índice
`idx_messages_user_via ON messages(user_id, via, created_at)` alimenta
listagem e polling do chat por `user_id`+`via`.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0013_messages_via"
down_revision: str | None = "0012_activity_kcal_nullable"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "messages",
        sa.Column(
            "via",
            sa.Text(),
            server_default="food",
            nullable=False,
        ),
    )
    op.create_index(
        "idx_messages_user_via",
        "messages",
        ["user_id", "via", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("idx_messages_user_via", table_name="messages")
    op.drop_column("messages", "via")