"""workout_sessions, workout_exercises, workout_sets

Revision ID: 0011_workout_tracking
Revises: 0010_propagate_action
Create Date: 2026-08-15

SP-120..125 (núcleo Bloco 3): tabelas de treino estruturado
(sessão → exercícios → séries). FK opcional em activity_records
(workout_session_id) para trilha reversa SP-126/INV-17.

- INV-15: no máximo uma sessão `status='active'` por usuário — enforced
  por índice único parcial `(user_id) WHERE status='active'`.
- Índice `(normalized_name, user_id)` em workout_exercises para lookup
  histórico (SP-121/127); recência via `sequence_index` (SP-123).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0011_workout_tracking"
down_revision: str | None = "0010_propagate_action"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # workout_sessions — SP-120..125
    # ------------------------------------------------------------------
    op.create_table(
        "workout_sessions",
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
        sa.Column(
            "day_log_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("day_logs.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("workout_type", sa.Text(), nullable=False),
        sa.Column("detected_name", sa.Text(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.Text(), nullable=False, server_default="active"),
        sa.Column("end_reason", sa.Text(), nullable=True),
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
        sa.CheckConstraint(
            "workout_type IN ('push','pull','legs','upper','lower','full_body','cardio','other')",
            name="ck_workout_sessions_workout_type",
        ),
        sa.CheckConstraint(
            "status IN ('active','ended')",
            name="ck_workout_sessions_status",
        ),
        sa.CheckConstraint(
            "end_reason IS NULL OR end_reason IN ('user','auto_new_session','auto_close_day')",
            name="ck_workout_sessions_end_reason",
        ),
    )
    # INV-15: única sessão ativa por usuário (enforce no DB)
    op.create_index(
        "uq_workout_sessions_user_active",
        "workout_sessions",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )
    op.execute(
        "CREATE TRIGGER trg_workout_sessions_updated_at BEFORE UPDATE ON workout_sessions "
        "FOR EACH ROW EXECUTE FUNCTION set_updated_at()"
    )

    # ------------------------------------------------------------------
    # workout_exercises — SP-121/123
    # ------------------------------------------------------------------
    op.create_table(
        "workout_exercises",
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
        sa.Column(
            "workout_session_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("workout_sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("normalized_name", sa.Text(), nullable=False),
        sa.Column("sequence_index", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
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
        sa.CheckConstraint(
            "sequence_index >= 0",
            name="ck_workout_exercises_sequence_index",
        ),
    )
    op.create_index(
        "ix_workout_exercises_historical",
        "workout_exercises",
        ["normalized_name", "user_id"],
    )
    op.create_index(
        "ix_workout_exercises_session_seq",
        "workout_exercises",
        ["workout_session_id", "sequence_index"],
    )
    op.execute(
        "CREATE TRIGGER trg_workout_exercises_updated_at BEFORE UPDATE ON workout_exercises "
        "FOR EACH ROW EXECUTE FUNCTION set_updated_at()"
    )

    # ------------------------------------------------------------------
    # workout_sets — SP-122
    # ------------------------------------------------------------------
    op.create_table(
        "workout_sets",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            primary_key=True,
        ),
        sa.Column(
            "workout_exercise_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("workout_exercises.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("sequence_index", sa.Integer(), nullable=False),
        sa.Column("weight_kg", sa.Numeric(8, 3), nullable=False),
        sa.Column("reps", sa.Integer(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
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
        sa.CheckConstraint(
            "weight_kg > 0", name="ck_workout_sets_weight_positive"
        ),
        sa.CheckConstraint("reps > 0", name="ck_workout_sets_reps_positive"),
        sa.CheckConstraint(
            "sequence_index >= 0", name="ck_workout_sets_sequence_index"
        ),
    )
    op.create_index(
        "ix_workout_sets_exercise_seq",
        "workout_sets",
        ["workout_exercise_id", "sequence_index"],
    )
    op.execute(
        "CREATE TRIGGER trg_workout_sets_updated_at BEFORE UPDATE ON workout_sets "
        "FOR EACH ROW EXECUTE FUNCTION set_updated_at()"
    )

    # ------------------------------------------------------------------
    # activity_records.workout_session_id — FK opcional (SP-126/INV-17)
    # ------------------------------------------------------------------
    op.add_column(
        "activity_records",
        sa.Column(
            "workout_session_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("workout_sessions.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_activity_records_workout_session",
        "activity_records",
        ["workout_session_id"],
    )
    op.drop_constraint("ck_activity_records_calc_method", "activity_records", type_="check")
    op.create_check_constraint(
        "ck_activity_records_calc_method",
        "activity_records",
        "calc_method IN ('mets_body_weight','llm_estimate','user_manual','workout_session')",
    )


def downgrade() -> None:
    op.create_check_constraint(
        "ck_activity_records_calc_method",
        "activity_records",
        "calc_method IN ('mets_body_weight','llm_estimate','user_manual')",
    )
    op.drop_constraint("ck_activity_records_calc_method", "activity_records", type_="check")
    op.drop_index("ix_activity_records_workout_session", table_name="activity_records")
    op.drop_column("activity_records", "workout_session_id")

    op.execute("DROP TRIGGER IF EXISTS trg_workout_sets_updated_at ON workout_sets")
    op.drop_index("ix_workout_sets_exercise_seq", table_name="workout_sets")
    op.drop_table("workout_sets")

    op.execute("DROP TRIGGER IF EXISTS trg_workout_exercises_updated_at ON workout_exercises")
    op.drop_index("ix_workout_exercises_session_seq", table_name="workout_exercises")
    op.drop_index("ix_workout_exercises_historical", table_name="workout_exercises")
    op.drop_table("workout_exercises")

    op.execute("DROP TRIGGER IF EXISTS trg_workout_sessions_updated_at ON workout_sessions")
    op.drop_index("uq_workout_sessions_user_active", table_name="workout_sessions")
    op.drop_table("workout_sessions")