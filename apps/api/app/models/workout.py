import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, Numeric, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

WORKOUT_TYPE_VALUES = (
    "push",
    "pull",
    "legs",
    "upper",
    "lower",
    "full_body",
    "cardio",
    "other",
)
SESSION_STATUS_VALUES = ("active", "ended")
END_REASON_VALUES = ("user", "auto_new_session", "auto_close_day")


class WorkoutSession(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """SP-120..125. Sessão de treino de força: raiz da estrutura
    sessão → exercícios → séries. `status='active'` no máximo uma por
    usuário (INV-15, enforced por índice único parcial). Consolidada em
    1 `activity_record` no encerramento (SP-126).
    """

    __tablename__ = "workout_sessions"
    __table_args__ = (
        CheckConstraint(
            "workout_type IN ('push','pull','legs','upper','lower','full_body','cardio','other')",
            name="ck_workout_sessions_workout_type",
        ),
        CheckConstraint("status IN ('active','ended')", name="ck_workout_sessions_status"),
        CheckConstraint(
            "end_reason IS NULL OR end_reason IN ('user','auto_new_session','auto_close_day')",
            name="ck_workout_sessions_end_reason",
        ),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    day_log_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("day_logs.id", ondelete="RESTRICT"),
        nullable=False,
    )
    workout_type: Mapped[str] = mapped_column(Text, nullable=False)
    detected_name: Mapped[str] = mapped_column(Text, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="active")
    end_reason: Mapped[str | None] = mapped_column(Text, nullable=True)


class WorkoutExercise(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """SP-121/123. Exercício dentro de uma sessão. `normalized_name`
    para lookup histórico (SP-121/127); recência via `sequence_index`
    (SP-123 — exercício não tem `ended_at`).
    """

    __tablename__ = "workout_exercises"
    __table_args__ = (
        CheckConstraint("sequence_index >= 0", name="ck_workout_exercises_sequence_index"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    workout_session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workout_sessions.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_name: Mapped[str] = mapped_column(Text, nullable=False)
    sequence_index: Mapped[int] = mapped_column(Integer, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class WorkoutSet(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """SP-122. Série de um exercício. `weight_kg`/`reps` validados no
    backend (`> 0`); peso pt-BR é parseado pela LLM, backend só valida.
    Pertence ao último exercício da sessão ativa (INV-16).
    """

    __tablename__ = "workout_sets"
    __table_args__ = (
        CheckConstraint("weight_kg > 0", name="ck_workout_sets_weight_positive"),
        CheckConstraint("reps > 0", name="ck_workout_sets_reps_positive"),
        CheckConstraint("sequence_index >= 0", name="ck_workout_sets_sequence_index"),
    )

    workout_exercise_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workout_exercises.id", ondelete="CASCADE"),
        nullable=False,
    )
    sequence_index: Mapped[int] = mapped_column(Integer, nullable=False)
    weight_kg: Mapped[Decimal] = mapped_column(Numeric(8, 3), nullable=False)
    reps: Mapped[int] = mapped_column(Integer, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
