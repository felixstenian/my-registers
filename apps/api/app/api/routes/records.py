"""Endpoints REST para correção e remoção de registros.

SP-81: DELETE idempotente (2ª chamada retorna 200 sem efeito).
Const. Art. VIII §28 (INV-5): dia fechado → 409.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_session
from app.core.exceptions import AppError, ConflictError, NotFoundError
from app.models import User
from app.services.correction import DayClosedError
from app.services.correction_matcher import TargetKind
from app.services.daily_recompute import DailyRecomputeService
from app.services.deletion import DeletionService

router = APIRouter(prefix="/records", tags=["records"])


class DeletionOut(BaseModel):
    kind: str
    entity_id: uuid.UUID
    already_deleted: bool


class FoodItemPatch(BaseModel):
    grams: float | None = Field(default=None, gt=0)
    ml: float | None = Field(default=None, gt=0)
    quantity: float | None = Field(default=None, gt=0)
    unit: str | None = None


class RecordSummary(BaseModel):
    id: uuid.UUID
    kcal: float | None = None
    grams: float | None = None
    ml: float | None = None


def _kind_from_path(path: str) -> TargetKind:
    return {
        "food-items": TargetKind.FOOD,
        "water": TargetKind.WATER,
        "beverage": TargetKind.BEVERAGE,
        "activity": TargetKind.ACTIVITY,
    }[path]


async def _delete_generic(
    path: str,
    entity_id: uuid.UUID,
    current_user: User,
    session: AsyncSession,
) -> DeletionOut:
    try:
        outcome = await DeletionService(session).delete_by_id(
            user=current_user,
            kind=_kind_from_path(path),
            entity_id=entity_id,
        )
    except DayClosedError as exc:
        raise ConflictError(
            "day is closed", code="conflict_closed_day"
        ) from exc
    except AppError as exc:
        if exc.code == "target_not_found":
            raise NotFoundError("record not found", code="not_found") from exc
        raise
    if not outcome.already_deleted:
        # SP-80 exige recompute após soft delete.
        await DailyRecomputeService(session).recompute(outcome.day_log_id)
    return DeletionOut(
        kind=outcome.kind.value,
        entity_id=outcome.entity_id,
        already_deleted=outcome.already_deleted,
    )


@router.delete("/food-items/{entity_id}", response_model=DeletionOut)
async def delete_food_item(
    entity_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> DeletionOut:
    return await _delete_generic("food-items", entity_id, current_user, session)


@router.delete("/water/{entity_id}", response_model=DeletionOut)
async def delete_water(
    entity_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> DeletionOut:
    return await _delete_generic("water", entity_id, current_user, session)


@router.delete("/beverage/{entity_id}", response_model=DeletionOut)
async def delete_beverage(
    entity_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> DeletionOut:
    return await _delete_generic("beverage", entity_id, current_user, session)


@router.delete("/activity/{entity_id}", response_model=DeletionOut)
async def delete_activity(
    entity_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> DeletionOut:
    return await _delete_generic("activity", entity_id, current_user, session)


@router.patch(
    "/food-items/{entity_id}",
    response_model=RecordSummary,
    status_code=status.HTTP_200_OK,
)
async def patch_food_item(
    entity_id: uuid.UUID,
    payload: FoodItemPatch,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> RecordSummary:
    from sqlalchemy import select

    from app.integrations.nutrition.catalog import LookupQuery
    from app.integrations.nutrition.local_tbca import LocalTBCACatalog
    from app.models import FoodItem, FoodRecord
    from app.repositories.food import AuditEventRepository
    from app.services.nutrition_calculator import NutritionCalculator

    stmt = (
        select(FoodItem, FoodRecord)
        .join(FoodRecord, FoodRecord.id == FoodItem.food_record_id)
        .where(FoodItem.id == entity_id, FoodRecord.user_id == current_user.id)
    )
    row = (await session.execute(stmt)).one_or_none()
    if row is None:
        raise NotFoundError("food_item not found", code="not_found")
    item, food_record = row
    if item.deleted_at is not None:
        raise NotFoundError("food_item deleted", code="not_found")

    from app.models import DayLog

    day_log = await session.get(DayLog, food_record.day_log_id)
    if day_log is not None and day_log.status == "closed":
        raise ConflictError("day is closed", code="conflict_closed_day")

    before: dict[str, Any] = {
        "grams": float(item.grams) if item.grams is not None else None,
        "ml": float(item.ml) if item.ml is not None else None,
        "quantity": float(item.quantity) if item.quantity is not None else None,
        "unit": item.unit,
        "kcal": float(item.kcal) if item.kcal is not None else None,
    }
    changed = False
    if payload.grams is not None:
        item.grams = Decimal(str(payload.grams))
        changed = True
    if payload.ml is not None:
        item.ml = Decimal(str(payload.ml))
        changed = True
    if payload.quantity is not None:
        item.quantity = Decimal(str(payload.quantity))
        changed = True
    if payload.unit is not None:
        item.unit = payload.unit
        changed = True

    if changed and (payload.grams is not None or payload.ml is not None):
        hit = None
        if item.catalog_ref_id is not None:
            catalog = LocalTBCACatalog(session)
            hit = await catalog.lookup(
                LookupQuery(name=item.normalized_name, brand=item.brand)
            )
        computed = NutritionCalculator.compute(
            hit=hit, grams=item.grams, ml=item.ml
        )
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

    if not changed:
        return RecordSummary(
            id=item.id,
            kcal=float(item.kcal) if item.kcal else None,
            grams=float(item.grams) if item.grams else None,
            ml=float(item.ml) if item.ml else None,
        )

    item.source = "user_corrected"
    await session.flush()

    after: dict[str, Any] = {
        "grams": float(item.grams) if item.grams is not None else None,
        "ml": float(item.ml) if item.ml is not None else None,
        "quantity": float(item.quantity) if item.quantity is not None else None,
        "unit": item.unit,
        "kcal": float(item.kcal) if item.kcal is not None else None,
    }
    await AuditEventRepository(session).record(
        user_id=current_user.id,
        entity_type="food_item",
        entity_id=item.id,
        action="correct",
        actor="user",
        message_id=None,
        before=before,
        after=after,
    )
    await DailyRecomputeService(session).recompute(food_record.day_log_id)

    return RecordSummary(
        id=item.id,
        kcal=float(item.kcal) if item.kcal else None,
        grams=float(item.grams) if item.grams else None,
        ml=float(item.ml) if item.ml else None,
    )
