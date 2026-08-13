"""Endpoints REST para correção e remoção de registros.

SP-81: DELETE idempotente (2ª chamada retorna 200 sem efeito).
SP-164/165/166: PATCH water/beverage/activity para edição inline.
Const. Art. VIII §28 (INV-5): dia fechado → 409.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any, Literal

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_session
from app.core.exceptions import AppError, ConflictError, NotFoundError
from app.models import DayLog, User
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
    volume_ml: int | None = None
    duration_minutes: float | None = None


class WaterPatch(BaseModel):
    volume_ml: int = Field(gt=0)


class BeveragePatch(BaseModel):
    volume_ml: int | None = Field(default=None, gt=0)


class ActivityPatch(BaseModel):
    duration_minutes: float | None = Field(default=None, gt=0)
    intensity: Literal["light", "moderate", "vigorous", "unknown"] | None = None
    kcal_burned: float | None = Field(default=None, ge=0)


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
        raise ConflictError("day is closed", code="conflict_closed_day") from exc
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
    from app.integrations.nutrition.catalog import CatalogHit, LookupQuery
    from app.integrations.nutrition.local_tbca import LocalTBCACatalog
    from app.models import FoodItem, FoodRecord, NutrientFact
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
        # If the item already has a catalog_ref_id, fetch the fact
        # directly by ID — name-based lookup can miss when
        # normalized_name doesn't match aliases/canonical_name.
        # Name-based lookup is only used as fallback for items without
        # catalog_ref_id (promotion from "no catalog" to "with catalog").
        if item.catalog_ref_id is not None:
            fact = await session.get(NutrientFact, item.catalog_ref_id)
            hit = CatalogHit.from_model(fact) if fact else None
        else:
            catalog = LocalTBCACatalog(session)
            hit = await catalog.lookup(LookupQuery(name=item.normalized_name, brand=item.brand))
            if hit is not None:
                item.catalog_ref_id = uuid.UUID(hit.fact_id)
        computed = NutritionCalculator.compute(hit=hit, grams=item.grams, ml=item.ml)
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


# ---------------------------------------------------------------------------
# SP-164 — PATCH /records/water/{id}
# ---------------------------------------------------------------------------


@router.patch(
    "/water/{entity_id}",
    response_model=RecordSummary,
    status_code=status.HTTP_200_OK,
)
async def patch_water(
    entity_id: uuid.UUID,
    payload: WaterPatch,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> RecordSummary:
    from app.models import WaterRecord
    from app.repositories.food import AuditEventRepository

    stmt = select(WaterRecord).where(
        WaterRecord.id == entity_id,
        WaterRecord.user_id == current_user.id,
        WaterRecord.deleted_at.is_(None),
    )
    record = (await session.execute(stmt)).scalar_one_or_none()
    if record is None:
        raise NotFoundError("water_record not found", code="not_found")

    day_log = await session.get(DayLog, record.day_log_id)
    if day_log is not None and day_log.status == "closed":
        raise ConflictError("day is closed", code="conflict_closed_day")

    before: dict[str, Any] = {"volume_ml": record.volume_ml}
    record.volume_ml = payload.volume_ml
    record.source = "user_corrected"
    await session.flush()
    after: dict[str, Any] = {"volume_ml": record.volume_ml}

    await AuditEventRepository(session).record(
        user_id=current_user.id,
        entity_type="water_record",
        entity_id=record.id,
        action="correct",
        actor="user",
        message_id=None,
        before=before,
        after=after,
    )
    await DailyRecomputeService(session).recompute(record.day_log_id)

    return RecordSummary(id=record.id, volume_ml=record.volume_ml)


# ---------------------------------------------------------------------------
# SP-165 — PATCH /records/beverage/{id}
# ---------------------------------------------------------------------------


@router.patch(
    "/beverage/{entity_id}",
    response_model=RecordSummary,
    status_code=status.HTTP_200_OK,
)
async def patch_beverage(
    entity_id: uuid.UUID,
    payload: BeveragePatch,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> RecordSummary:
    from app.integrations.nutrition.catalog import CatalogHit, LookupQuery
    from app.integrations.nutrition.local_tbca import LocalTBCACatalog
    from app.models import BeverageRecord, NutrientFact
    from app.repositories.food import AuditEventRepository
    from app.services.nutrition_calculator import NutritionCalculator

    stmt = select(BeverageRecord).where(
        BeverageRecord.id == entity_id,
        BeverageRecord.user_id == current_user.id,
        BeverageRecord.deleted_at.is_(None),
    )
    record = (await session.execute(stmt)).scalar_one_or_none()
    if record is None:
        raise NotFoundError("beverage_record not found", code="not_found")

    day_log = await session.get(DayLog, record.day_log_id)
    if day_log is not None and day_log.status == "closed":
        raise ConflictError("day is closed", code="conflict_closed_day")

    if payload.volume_ml is None:
        return RecordSummary(
            id=record.id,
            kcal=float(record.kcal) if record.kcal else None,
            volume_ml=record.volume_ml,
        )

    before: dict[str, Any] = {
        "volume_ml": record.volume_ml,
        "kcal": float(record.kcal) if record.kcal is not None else None,
        "source": record.source,
    }
    record.volume_ml = payload.volume_ml

    # If beverage already has catalog_ref_id, fetch fact directly by ID.
    # Name-based lookup only as fallback for items without catalog_ref_id.
    if record.catalog_ref_id is not None:
        fact = await session.get(NutrientFact, record.catalog_ref_id)
        hit = CatalogHit.from_model(fact) if fact else None
    else:
        catalog = LocalTBCACatalog(session)
        hit = await catalog.lookup(LookupQuery(name=record.normalized_name, brand=record.brand))
        if hit is not None:
            record.catalog_ref_id = uuid.UUID(hit.fact_id)
    computed = NutritionCalculator.compute(hit=hit, grams=None, ml=Decimal(str(record.volume_ml)))
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
        setattr(record, field, getattr(computed, field))

    record.source = "user_corrected"
    await session.flush()
    after: dict[str, Any] = {
        "volume_ml": record.volume_ml,
        "kcal": float(record.kcal) if record.kcal is not None else None,
        "source": record.source,
    }

    await AuditEventRepository(session).record(
        user_id=current_user.id,
        entity_type="beverage_record",
        entity_id=record.id,
        action="correct",
        actor="user",
        message_id=None,
        before=before,
        after=after,
    )
    await DailyRecomputeService(session).recompute(record.day_log_id)

    return RecordSummary(
        id=record.id,
        kcal=float(record.kcal) if record.kcal else None,
        volume_ml=record.volume_ml,
    )


# ---------------------------------------------------------------------------
# SP-166 — PATCH /records/activity/{id}
# ---------------------------------------------------------------------------


@router.patch(
    "/activity/{entity_id}",
    response_model=RecordSummary,
    status_code=status.HTTP_200_OK,
)
async def patch_activity(
    entity_id: uuid.UUID,
    payload: ActivityPatch,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> RecordSummary:
    from app.models import ActivityRecord
    from app.repositories.food import AuditEventRepository
    from app.services.activity_calculator import ActivityCalculator

    stmt = select(ActivityRecord).where(
        ActivityRecord.id == entity_id,
        ActivityRecord.user_id == current_user.id,
        ActivityRecord.deleted_at.is_(None),
    )
    record = (await session.execute(stmt)).scalar_one_or_none()
    if record is None:
        raise NotFoundError("activity_record not found", code="not_found")

    day_log = await session.get(DayLog, record.day_log_id)
    if day_log is not None and day_log.status == "closed":
        raise ConflictError("day is closed", code="conflict_closed_day")

    changed = False
    before: dict[str, Any] = {
        "duration_minutes": float(record.duration_minutes)
        if record.duration_minutes is not None
        else None,
        "intensity": record.intensity,
        "kcal_burned": float(record.kcal_burned) if record.kcal_burned is not None else None,
        "calc_method": record.calc_method,
        "met_value": float(record.met_value) if record.met_value is not None else None,
    }

    if payload.duration_minutes is not None:
        record.duration_minutes = Decimal(str(payload.duration_minutes))
        changed = True
    if payload.intensity is not None:
        record.intensity = payload.intensity
        changed = True

    if payload.kcal_burned is not None:
        # Explicit kcal overrides MET calculation (Const. Art. II §5).
        record.kcal_burned = Decimal(str(payload.kcal_burned))
        record.calc_method = "user_manual"
        record.met_value = None
        changed = True
    elif changed and current_user.weight_kg is not None:
        computation = ActivityCalculator.compute(
            activity_type=record.activity_type,
            intensity=record.intensity,
            duration_minutes=record.duration_minutes,
            weight_kg=Decimal(str(current_user.weight_kg)),
        )
        record.kcal_burned = computation.kcal_burned
        record.met_value = computation.met_value
        if computation.calc_method == "mets_body_weight":
            record.calc_method = "mets_body_weight"

    if not changed:
        return RecordSummary(
            id=record.id,
            kcal=float(record.kcal_burned) if record.kcal_burned else None,
            duration_minutes=float(record.duration_minutes) if record.duration_minutes else None,
        )

    await session.flush()
    after: dict[str, Any] = {
        "duration_minutes": float(record.duration_minutes)
        if record.duration_minutes is not None
        else None,
        "intensity": record.intensity,
        "kcal_burned": float(record.kcal_burned) if record.kcal_burned is not None else None,
        "calc_method": record.calc_method,
        "met_value": float(record.met_value) if record.met_value is not None else None,
    }

    await AuditEventRepository(session).record(
        user_id=current_user.id,
        entity_type="activity_record",
        entity_id=record.id,
        action="correct",
        actor="user",
        message_id=None,
        before=before,
        after=after,
    )
    await DailyRecomputeService(session).recompute(record.day_log_id)

    return RecordSummary(
        id=record.id,
        kcal=float(record.kcal_burned) if record.kcal_burned else None,
        duration_minutes=float(record.duration_minutes) if record.duration_minutes else None,
    )
