"""workout_templates + workout_template_exercises (SP-170/171)

Revision ID: 0014_workout_templates
Revises: 0013_messages_via
Create Date: 2026-08-15

SP-170/SP-171/SP-172 (Bloco 3.b, E2): treinos reutilizáveis cadastrados
pelo usuário. `workout_templates.active` controla a aba *Ativos* do
`/workouts` e o seletor do fluxo guiado (INV-19); toda query é
`user_id`-scoped (INV-18). `workout_template_exercises` guarda os
exercícios-alvo com o plano sugerido (target_sets/target_reps).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0014_workout_templates"
down_revision: str | None = "0013_messages_via"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "workout_templates",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("workout_type", sa.Text(), nullable=False),
        sa.Column("muscle_groups", postgresql.JSONB(), nullable=True),
        sa.Column("active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.CheckConstraint(
            "workout_type IN ('push','pull','legs','upper','lower','full_body','cardio','other')",
            name="ck_workout_templates_workout_type",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_workout_templates_user_active",
        "workout_templates",
        ["user_id", "active"],
    )
    op.execute(
        "CREATE TRIGGER trg_workout_templates_updated_at BEFORE UPDATE ON workout_templates "
        "FOR EACH ROW EXECUTE FUNCTION set_updated_at()"
    )
    op.create_table(
        "workout_template_exercises",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("template_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("exercise_name", sa.Text(), nullable=False),
        sa.Column("normalized_name", sa.Text(), nullable=False),
        sa.Column("target_sets", sa.Integer(), nullable=True),
        sa.Column("target_reps", sa.Integer(), nullable=True),
        sa.CheckConstraint("target_sets > 0", name="ck_workout_template_exercises_target_sets"),
        sa.CheckConstraint("target_reps > 0", name="ck_workout_template_exercises_target_reps"),
        sa.ForeignKeyConstraint(
            ["template_id"],
            ["workout_templates.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_workout_template_exercises_template",
        "workout_template_exercises",
        ["template_id"],
    )
    op.execute(
        "CREATE TRIGGER trg_workout_template_exercises_updated_at BEFORE UPDATE "
        "ON workout_template_exercises "
        "FOR EACH ROW EXECUTE FUNCTION set_updated_at()"
    )


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER IF EXISTS trg_workout_template_exercises_updated_at "
        "ON workout_template_exercises"
    )
    op.drop_index("ix_workout_template_exercises_template", table_name="workout_template_exercises")
    op.drop_table("workout_template_exercises")
    op.execute("DROP TRIGGER IF EXISTS trg_workout_templates_updated_at ON workout_templates")
    op.drop_index("ix_workout_templates_user_active", table_name="workout_templates")
    op.drop_table("workout_templates")
