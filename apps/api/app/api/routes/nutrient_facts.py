"""Endpoints de `nutrient_facts`.

- **PATCH /nutrient-facts/{id}** (SP-33): usuário confirma/ajusta valores
  lidos de rótulo. Sempre marca `verified_by_user=true`.
- **POST /nutrient-facts/manual** (SP-141/SP-142): cadastro manual sem
  foto; opcionalmente promove um `food_item` legado (kcal=0 por não ter
  catálogo na criação) usando o fact recém-criado.
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
from app.models import DayLog, FoodItem, FoodRecord, NutrientFact, User
from app.repositories.food import AuditEventRepository
from app.schemas.nutrient_facts import (
    ManualNutrientFactIn,
    ManualNutrientFactOut,
    NutrientFactOut,
    NutrientFactPatch,
)
from app.services.daily_recompute import DailyRecomputeService
from app.services.nutrition_calculator import NutritionCalculator

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


_MANUAL_FIELDS_REQUIRED = ("kcal", "protein_g", "carbs_g", "fat_g")
_MANUAL_FIELDS_OPTIONAL = (
    "fiber_g",
    "sodium_mg",
    "calcium_mg",
    "iron_mg",
    "potassium_mg",
    "serving_grams",
)


@router.post(
    "/manual",
    response_model=ManualNutrientFactOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_manual_nutrient_fact(
    payload: ManualNutrientFactIn,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> ManualNutrientFactOut:
    """SP-141: cria fact `source='manual'` de dono conhecido (`created_by`).

    SP-142: se `promote_food_item_id` presente, tenta promover o item
    legado (kcal=0 / `catalog_ref_id=NULL`) — atualiza `catalog_ref_id`,
    recomputa macros, desmarca `needs_confirmation` e recompute snapshot.
    Falha silenciosa devolve fact criado + `promotion_warning`.
    """
    aliases = sorted({payload.canonical_name, *payload.aliases})
    fact = NutrientFact(
        canonical_name=payload.canonical_name,
        aliases=aliases,
        brand=payload.brand,
        source="manual",
        basis=payload.basis,
        verified_by_user=True,
        created_by=current_user.id,
    )
    for field in _MANUAL_FIELDS_REQUIRED:
        setattr(fact, field, Decimal(str(getattr(payload, field))))
    for field in _MANUAL_FIELDS_OPTIONAL:
        value = getattr(payload, field)
        if value is not None:
            setattr(fact, field, Decimal(str(value)))

    session.add(fact)
    await session.flush()

    await AuditEventRepository(session).record(
        user_id=current_user.id,
        entity_type="nutrient_fact",
        entity_id=fact.id,
        action="create",
        actor="user",
        message_id=None,
        before=None,
        after={
            "source": "manual",
            "canonical_name": fact.canonical_name,
            "basis": fact.basis,
            "kcal": _dec(fact.kcal),
        },
    )

    promotion_warning: str | None = None
    promoted_item_id: uuid.UUID | None = None

    if payload.promote_food_item_id is not None:
        promotion_warning, promoted_item_id = await _try_promote_item(
            session=session,
            user=current_user,
            item_id=payload.promote_food_item_id,
            fact=fact,
        )

    out = ManualNutrientFactOut.model_validate(fact)
    out.promotion_warning = promotion_warning
    out.promoted_item_id = promoted_item_id
    return out


async def _try_promote_item(
    *,
    session: AsyncSession,
    user: User,
    item_id: uuid.UUID,
    fact: NutrientFact,
) -> tuple[str | None, uuid.UUID | None]:
    """SP-142. Retorna (warning|None, promoted_id|None).

    Fails silently — o fact criado prevalece. Cenários que geram warning:
    item não achado, deletado, de outro user, dia fechado. Sucesso →
    (None, item.id) + recompute do snapshot.
    """
    stmt = (
        select(FoodItem, FoodRecord)
        .join(FoodRecord, FoodRecord.id == FoodItem.food_record_id)
        .where(FoodItem.id == item_id, FoodRecord.user_id == user.id)
    )
    row = (await session.execute(stmt)).one_or_none()
    if row is None:
        return ("promotion_failed:item_not_found", None)
    item, food_record = row
    if item.deleted_at is not None:
        return ("promotion_failed:item_deleted", None)

    day_log = await session.get(DayLog, food_record.day_log_id)
    if day_log is not None and day_log.status == "closed":
        return ("promotion_failed:day_closed", None)

    before: dict[str, Any] = {
        "catalog_ref_id": str(item.catalog_ref_id) if item.catalog_ref_id else None,
        "kcal": _dec(item.kcal),
        "needs_confirmation": item.needs_confirmation,
    }

    from app.integrations.nutrition.catalog import CatalogHit

    computed = NutritionCalculator.compute(
        hit=CatalogHit.from_model(fact), grams=item.grams, ml=item.ml
    )
    item.catalog_ref_id = fact.id
    for field in (
        "kcal",
        "protein_g",
        "carbs_g",
        "fat_g",
        "fiber_g",
        "sodium_mg",
        "calcium_mg",
        "iron_mg",
        "potassium_mg",
    ):
        setattr(item, field, getattr(computed, field))
    item.needs_confirmation = False
    item.source = "user_corrected"
    await session.flush()

    await AuditEventRepository(session).record(
        user_id=user.id,
        entity_type="food_item",
        entity_id=item.id,
        action="correct",
        actor="user",
        message_id=None,
        before=before,
        after={
            "catalog_ref_id": str(fact.id),
            "kcal": _dec(item.kcal),
            "needs_confirmation": False,
            "promoted_from": "manual_catalog",
        },
    )
    await DailyRecomputeService(session).recompute(food_record.day_log_id)
    return (None, item.id)


