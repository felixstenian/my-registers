"""Endpoints REST do módulo de treino (SP-170, SP-172).

- `GET /workouts/templates` — listagem com `?active=` (abas Ativos/Inativos).
- `GET /workouts/templates/{id}` — detalhe com exercícios-alvo.
- `PATCH /workouts/templates/{id}` — toggle `active` (SP-172, INV-19).

Toda query é `user_id`-scoped (Const. Art. V §21, INV-18). Auditoria em
mutação (INV-10).
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_session
from app.core.exceptions import NotFoundError
from app.models import User
from app.repositories.food import AuditEventRepository
from app.schemas.workout import (
    WorkoutTemplateDetailOut,
    WorkoutTemplateExerciseOut,
    WorkoutTemplateOut,
    WorkoutTemplateToggleIn,
)

router = APIRouter(prefix="/workouts", tags=["workouts"])


@router.get("/templates", response_model=list[WorkoutTemplateOut])
async def list_templates(
    active: bool | None = Query(default=None),
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> list[WorkoutTemplateOut]:
    """SP-170: `active=true` alimenta a aba *Ativos*; `active=false` a
    *Inativos*; sem filtro devolve tudo (INV-19)."""
    from app.repositories.workout import WorkoutRepository

    rows = await WorkoutRepository(session).list_templates(current_user.id, active=active)
    out: list[WorkoutTemplateOut] = []
    for t in rows:
        out.append(
            WorkoutTemplateOut(
                id=t.id,
                name=t.name,
                workout_type=t.workout_type,
                muscle_groups=t.muscle_groups,
                active=t.active,
                created_at=t.created_at,
                updated_at=t.updated_at,
            )
        )
    return out


@router.get("/templates/{template_id}", response_model=WorkoutTemplateDetailOut)
async def get_template(
    template_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> WorkoutTemplateDetailOut:
    from app.repositories.workout import WorkoutRepository

    repo = WorkoutRepository(session)
    template = await repo.get_template(current_user.id, template_id)
    if template is None:
        raise NotFoundError("workout template not found", code="workout_template_not_found")
    exercises = await repo.list_template_exercises(template.id)
    out_exercises: list[WorkoutTemplateExerciseOut] = []
    for e in exercises:
        out_exercises.append(
            WorkoutTemplateExerciseOut(
                id=e.id,
                exercise_name=e.exercise_name,
                target_sets=e.target_sets,
                target_reps=e.target_reps,
                created_at=e.created_at,
            )
        )
    return WorkoutTemplateDetailOut(
        **WorkoutTemplateOut(
            id=template.id,
            name=template.name,
            workout_type=template.workout_type,
            muscle_groups=template.muscle_groups,
            active=template.active,
            created_at=template.created_at,
            updated_at=template.updated_at,
        ).model_dump(),
        exercises=out_exercises,
    )


@router.patch("/templates/{template_id}", response_model=WorkoutTemplateOut)
async def toggle_template(
    template_id: uuid.UUID,
    payload: WorkoutTemplateToggleIn,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> WorkoutTemplateOut:
    """SP-172: inverte `active`; sessões já finalizadas permanecem no
    histórico (INV-19 — congeladas, sem referência ao template)."""
    from app.models import WorkoutTemplate as WT

    stmt = select(WT).where(WT.id == template_id, WT.user_id == current_user.id)
    template = (await session.execute(stmt)).scalar_one_or_none()
    if template is None:
        raise NotFoundError("workout template not found", code="workout_template_not_found")

    before = template.active
    template.active = payload.active
    await AuditEventRepository(session).record(
        user_id=current_user.id,
        entity_type="workout_template",
        entity_id=template.id,
        action="update",
        actor="user",
        message_id=None,
        before={"active": before},
        after={"active": template.active},
    )
    await session.flush()
    await session.refresh(template)
    return WorkoutTemplateOut(
        id=template.id,
        name=template.name,
        workout_type=template.workout_type,
        muscle_groups=template.muscle_groups,
        active=template.active,
        created_at=template.created_at,
        updated_at=template.updated_at,
    )
