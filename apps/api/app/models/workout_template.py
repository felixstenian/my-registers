import uuid
from typing import Any

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Integer, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

WORKOUT_TEMPLATE_TYPE_VALUES = (
    "push",
    "pull",
    "legs",
    "upper",
    "lower",
    "full_body",
    "cardio",
    "other",
)


class WorkoutTemplate(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """SP-170/171. Treino reutilizável cadastrado pelo usuário.

    `active` controla a aba *Ativos* do `/workouts` e o seletor do fluxo
    guiado (INV-19); `muscle_groups` guarda o agrupamento muscular (ex.
    ["peito", "ombro", "triceps"]) para musculação. Exercícios-alvo vivem
    em `workout_template_exercises`. Sempre `user_id`-scoped (INV-18).
    """

    __tablename__ = "workout_templates"
    __table_args__ = (
        CheckConstraint(
            "workout_type IN ('push','pull','legs','upper','lower','full_body','cardio','other')",
            name="ck_workout_templates_workout_type",
        ),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    workout_type: Mapped[str] = mapped_column(Text, nullable=False)
    muscle_groups: Mapped[list[Any] | None] = mapped_column(JSONB, nullable=True)
    active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="true", default=True
    )


class WorkoutTemplateExercise(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """SP-171. Exercício-alvo de um template.

    `normalized_name` permite o lookup da última realização no fluxo
    guiado (SP-178); `target_sets`/`target_reps` são o plano sugerido.
    Sem `positional_order` — a listagem segue `order by created_at`
    (ordem de cadastro).
    """

    __tablename__ = "workout_template_exercises"
    __table_args__ = (
        CheckConstraint("target_sets > 0", name="ck_workout_template_exercises_target_sets"),
        CheckConstraint("target_reps > 0", name="ck_workout_template_exercises_target_reps"),
    )

    template_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workout_templates.id", ondelete="CASCADE"),
        nullable=False,
    )
    exercise_name: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_name: Mapped[str] = mapped_column(Text, nullable=False)
    target_sets: Mapped[int | None] = mapped_column(Integer, nullable=True)
    target_reps: Mapped[int | None] = mapped_column(Integer, nullable=True)
