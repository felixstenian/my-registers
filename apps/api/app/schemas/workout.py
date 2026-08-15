"""Schemas de API do módulo de treino (Bloco 3.b) — fora do contrato LLM.

Diferenciados de `app.schemas.llm` porque estes são contratos HTTP/REST
(GET/PATCH /workouts/...), não o envelope interpretado pela LLM.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class WorkoutTemplateExerciseOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    exercise_name: str
    target_sets: int | None = None
    target_reps: int | None = None
    created_at: datetime


class WorkoutTemplateOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    workout_type: str
    muscle_groups: list[str] | None = None
    active: bool
    created_at: datetime
    updated_at: datetime


class WorkoutTemplateDetailOut(WorkoutTemplateOut):
    exercises: list[WorkoutTemplateExerciseOut] = Field(default_factory=list)


class WorkoutTemplateToggleIn(BaseModel):
    active: bool


class WorkoutSessionActiveOut(BaseModel):
    """SP-179 (via SP-173/T-B317): sessão ativa do usuário (ou null).

    Alimenta a troca "Iniciar treino" → "Finalizar treino" no header do
    chat de treino e o `Stopwatch` (T-B320). Sempre `user_id`-scoped
    (INV-18); no máximo uma sessão `active` por usuário (INV-15).
    """

    id: uuid.UUID
    workout_type: str | None = None
    detected_name: str | None = None
    started_at: datetime | None = None
