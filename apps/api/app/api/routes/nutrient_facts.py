"""PATCH /nutrient-facts/{id} — SP-33.

Usuário confirma (ou ajusta) valores nutricionais lidos de rótulo. A ação
sempre marca `verified_by_user=true`, mesmo sem mudança de valor — é o
sinal de "revisado e OK" para a precedência do catálogo (SP-35).
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_session
from app.core.exceptions import NotFoundError, ValidationAppError
from app.models import NutrientFact, User
from app.repositories.food import AuditEventRepository
from app.schemas.nutrient_facts import NutrientFactOut, NutrientFactPatch

router = APIRouter(prefix="/nutrient-facts", tags=["nutrient-facts"])

_EDITABLE_FIELDS = (
    "kcal",
    "protein_g",
    "carbs_g",
    "fat_g",
    "fiber_g",
    "sodium_mg",
    "calcium_mg",
    "iron_mg",
    "potassium_mg",
    "serving_grams",
)


@router.patch("/{entity_id}", response_model=NutrientFactOut, status_code=status.HTTP_200_OK)
async def patch_nutrient_fact(
    entity_id: uuid.UUID,
    payload: NutrientFactPatch,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> NutrientFactOut:
    stmt = select(NutrientFact).where(NutrientFact.id == entity_id)
    fact = (await session.execute(stmt)).scalar_one_or_none()
    if fact is None:
        raise NotFoundError("nutrient_fact not found", code="not_found")

    # SP-35: usuário não sobrescreve fact do catálogo canônico. Só edita
    # label_ocr / manual.
    if fact.source not in {"label_ocr", "manual"}:
        raise ValidationAppError(
            f"nutrient_fact source={fact.source} is not editable",
            code="not_editable",
        )

    before: dict[str, Any] = {
        "verified_by_user": fact.verified_by_user,
        **{k: _dec(getattr(fact, k)) for k in _EDITABLE_FIELDS},
    }
    for field in _EDITABLE_FIELDS:
        value = getattr(payload, field)
        if value is not None:
            setattr(fact, field, Decimal(str(value)))
    fact.verified_by_user = True

    await session.flush()

    after: dict[str, Any] = {
        "verified_by_user": True,
        **{k: _dec(getattr(fact, k)) for k in _EDITABLE_FIELDS},
    }
    await AuditEventRepository(session).record(
        user_id=current_user.id,
        entity_type="nutrient_fact",
        entity_id=fact.id,
        action="update",
        actor="user",
        message_id=None,
        before=before,
        after=after,
    )

    return NutrientFactOut.model_validate(fact)


def _dec(value: Decimal | None) -> float | None:
    if value is None:
        return None
    return float(value)
