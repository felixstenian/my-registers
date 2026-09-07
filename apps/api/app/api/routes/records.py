"""Endpoints REST para correção e remoção de registros.

SP-81: DELETE idempotente (2ª chamada retorna 200 sem efeito).
SP-164/165/166: PATCH water/beverage/activity para edição inline.
Const. Art. VIII §28 (INV-5): dia fechado → 409.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
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
from app.services.structured_registration import FoodItemSpec, StructuredRegistrationService

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
    detected_name: str | None = None


class FoodRecordPatch(BaseModel):
    meal_slot: Literal["breakfast", "lunch", "snack", "dinner", "other", "unspecified"] | None = (
        None
    )
    occurred_at: datetime | None = None


class CloneFactOut(BaseModel):
    fact_id: uuid.UUID


class FoodItemCreateIn(BaseModel):
    detected_name: str
    grams: float | None = Field(default=None, gt=0)
    ml: float | None = Field(default=None, gt=0)
    quantity: float | None = Field(default=None, gt=0)
    unit: str | None = None
    brand: str | None = None


class FoodCreateIn(BaseModel):
    log_date: date | None = None
    meal_slot: Literal["breakfast", "lunch", "snack", "dinner", "other", "unspecified"] = (
        "unspecified"
    )
    occurred_at: datetime | None = None
    items: list[FoodItemCreateIn] = Field(min_length=1)


class WaterCreateIn(BaseModel):
    log_date: date | None = None
    volume_ml: int = Field(gt=0)
    occurred_at: datetime | None = None


class BeverageCreateIn(BaseModel):
    log_date: date | None = None
    detected_name: str
    volume_ml: int = Field(gt=0)
    occurred_at: datetime | None = None


class ActivityCreateIn(BaseModel):
    log_date: date | None = None
    detected_name: str
    activity_type: str
    duration_minutes: float = Field(gt=0)
    intensity: Literal["light", "moderate", "vigorous", "unknown"] = "unknown"
    kcal_burned: float | None = Field(default=None, ge=0)
    occurred_at: datetime | None = None


class FoodCreateOut(BaseModel):
    food_record_id: uuid.UUID
    item_ids: list[uuid.UUID]


class RecordCreateOut(BaseModel):
    id: uuid.UUID


class RecordSummary(BaseModel):
    id: uuid.UUID
    kcal: float | None = None
    grams: float | None = None
    ml: float | None = None
    volume_ml: int | None = None
    duration_minutes: float | None = None


class WaterPatch(BaseModel):
    volume_ml: int | None = Field(default=None, gt=0)
    occurred_at: datetime | None = None


class BeveragePatch(BaseModel):
    volume_ml: int | None = Field(default=None, gt=0)
    detected_name: str | None = None
    occurred_at: datetime | None = None


class ActivityPatch(BaseModel):
    duration_minutes: float | None = Field(default=None, gt=0)
    intensity: Literal["light", "moderate", "vigorous", "unknown"] | None = None
    kcal_burned: float | None = Field(default=None, ge=0)
    detected_name: str | None = None
    occurred_at: datetime | None = None


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
    from app.integrations.nutrition.normalize import normalize_name
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
        "detected_name": item.detected_name,
        "grams": float(item.grams) if item.grams is not None else None,
        "ml": float(item.ml) if item.ml is not None else None,
        "quantity": float(item.quantity) if item.quantity is not None else None,
        "unit": item.unit,
        "kcal": float(item.kcal) if item.kcal is not None else None,
    }
    changed = False
    if payload.detected_name is not None:
        item.detected_name = payload.detected_name
        item.normalized_name = normalize_name(payload.detected_name)
        changed = True
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
        "detected_name": item.detected_name,
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

    before: dict[str, Any] = {
        "volume_ml": record.volume_ml,
        "occurred_at": record.occurred_at.isoformat(),
    }
    volume_changed = False
    if payload.volume_ml is not None:
        record.volume_ml = payload.volume_ml
        volume_changed = True
    if payload.occurred_at is not None:
        record.occurred_at = payload.occurred_at

    if not volume_changed and payload.occurred_at is None:
        return RecordSummary(id=record.id, volume_ml=record.volume_ml)

    record.source = "user_corrected"
    await session.flush()
    after: dict[str, Any] = {
        "volume_ml": record.volume_ml,
        "occurred_at": record.occurred_at.isoformat(),
    }

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
    if volume_changed:
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
    from app.integrations.nutrition.normalize import normalize_name
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

    if payload.volume_ml is None and payload.detected_name is None and payload.occurred_at is None:
        return RecordSummary(
            id=record.id,
            kcal=float(record.kcal) if record.kcal else None,
            volume_ml=record.volume_ml,
        )

    before: dict[str, Any] = {
        "detected_name": record.detected_name,
        "volume_ml": record.volume_ml,
        "kcal": float(record.kcal) if record.kcal is not None else None,
        "source": record.source,
        "occurred_at": record.occurred_at.isoformat(),
    }

    if payload.detected_name is not None:
        record.detected_name = payload.detected_name
        record.normalized_name = normalize_name(payload.detected_name)

    if payload.occurred_at is not None:
        record.occurred_at = payload.occurred_at

    if payload.volume_ml is not None:
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
        computed = NutritionCalculator.compute(
            hit=hit, grams=None, ml=Decimal(str(record.volume_ml))
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
            setattr(record, field, getattr(computed, field))

    record.source = "user_corrected"
    await session.flush()
    after: dict[str, Any] = {
        "detected_name": record.detected_name,
        "volume_ml": record.volume_ml,
        "kcal": float(record.kcal) if record.kcal is not None else None,
        "source": record.source,
        "occurred_at": record.occurred_at.isoformat(),
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
    if payload.volume_ml is not None:
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
    from app.integrations.nutrition.normalize import normalize_name
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

    kcal_changed = False
    before: dict[str, Any] = {
        "detected_name": record.detected_name,
        "occurred_at": record.occurred_at.isoformat(),
        "duration_minutes": float(record.duration_minutes)
        if record.duration_minutes is not None
        else None,
        "intensity": record.intensity,
        "kcal_burned": float(record.kcal_burned) if record.kcal_burned is not None else None,
        "calc_method": record.calc_method,
        "met_value": float(record.met_value) if record.met_value is not None else None,
    }

    if payload.detected_name is not None:
        record.detected_name = payload.detected_name
        record.normalized_name = normalize_name(payload.detected_name)
    if payload.occurred_at is not None:
        record.occurred_at = payload.occurred_at

    if payload.duration_minutes is not None:
        record.duration_minutes = Decimal(str(payload.duration_minutes))
        kcal_changed = True
    if payload.intensity is not None:
        record.intensity = payload.intensity
        kcal_changed = True

    if payload.kcal_burned is not None:
        # Explicit kcal overrides MET calculation (Const. Art. II §5).
        record.kcal_burned = Decimal(str(payload.kcal_burned))
        record.calc_method = "user_manual"
        record.met_value = None
        kcal_changed = True
    elif kcal_changed and current_user.weight_kg is not None:
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

    any_change = (
        kcal_changed or payload.detected_name is not None or payload.occurred_at is not None
    )
    if not any_change:
        return RecordSummary(
            id=record.id,
            kcal=float(record.kcal_burned) if record.kcal_burned else None,
            duration_minutes=float(record.duration_minutes) if record.duration_minutes else None,
        )

    await session.flush()
    after: dict[str, Any] = {
        "detected_name": record.detected_name,
        "occurred_at": record.occurred_at.isoformat(),
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
    if kcal_changed:
        await DailyRecomputeService(session).recompute(record.day_log_id)

    return RecordSummary(
        id=record.id,
        kcal=float(record.kcal_burned) if record.kcal_burned else None,
        duration_minutes=float(record.duration_minutes) if record.duration_minutes else None,
    )


# ---------------------------------------------------------------------------
# SP-183 — PATCH /records/food-records/{id} (meal_slot + occurred_at)
# ---------------------------------------------------------------------------


class FoodRecordOut(BaseModel):
    id: uuid.UUID
    meal_slot: str
    occurred_at: datetime


@router.patch("/food-records/{entity_id}", response_model=FoodRecordOut)
async def patch_food_record(
    entity_id: uuid.UUID,
    payload: FoodRecordPatch,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> FoodRecordOut:
    from app.models import FoodRecord
    from app.repositories.food import AuditEventRepository

    stmt = select(FoodRecord).where(
        FoodRecord.id == entity_id,
        FoodRecord.user_id == current_user.id,
        FoodRecord.deleted_at.is_(None),
    )
    record = (await session.execute(stmt)).scalar_one_or_none()
    if record is None:
        raise NotFoundError("food_record not found", code="not_found")

    day_log = await session.get(DayLog, record.day_log_id)
    if day_log is not None and day_log.status == "closed":
        raise ConflictError("day is closed", code="conflict_closed_day")

    changed = False
    before: dict[str, Any] = {
        "meal_slot": record.meal_slot,
        "occurred_at": record.occurred_at.isoformat(),
    }
    if payload.meal_slot is not None:
        record.meal_slot = payload.meal_slot
        changed = True
    if payload.occurred_at is not None:
        record.occurred_at = payload.occurred_at
        changed = True

    if not changed:
        return FoodRecordOut(
            id=record.id, meal_slot=record.meal_slot, occurred_at=record.occurred_at
        )

    await session.flush()
    after: dict[str, Any] = {
        "meal_slot": record.meal_slot,
        "occurred_at": record.occurred_at.isoformat(),
    }
    await AuditEventRepository(session).record(
        user_id=current_user.id,
        entity_type="food_record",
        entity_id=record.id,
        action="correct",
        actor="user",
        message_id=None,
        before=before,
        after=after,
    )
    return FoodRecordOut(id=record.id, meal_slot=record.meal_slot, occurred_at=record.occurred_at)


# ---------------------------------------------------------------------------
# SP-182 — POST /records/food-items/{id}/clone-fact (override canônico por clone)
# ---------------------------------------------------------------------------


@router.post("/food-items/{entity_id}/clone-fact", response_model=CloneFactOut)
async def clone_food_item_fact(
    entity_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> CloneFactOut:
    from app.models import FoodItem, FoodRecord, NutrientFact
    from app.repositories.food import AuditEventRepository

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

    if item.catalog_ref_id is None:
        raise ConflictError("item has no catalog fact", code="not_cloneable")
    source_fact = await session.get(NutrientFact, item.catalog_ref_id)
    if source_fact is None or source_fact.source not in {"TBCA_2023", "USDA_FDC"}:
        raise ConflictError("fact is not canonical", code="not_cloneable")

    clone = NutrientFact(
        canonical_name=source_fact.canonical_name,
        aliases=list(source_fact.aliases),
        brand=source_fact.brand,
        source="manual",
        serving_grams=source_fact.serving_grams,
        kcal=source_fact.kcal,
        protein_g=source_fact.protein_g,
        carbs_g=source_fact.carbs_g,
        fat_g=source_fact.fat_g,
        fiber_g=source_fact.fiber_g,
        sodium_mg=source_fact.sodium_mg,
        calcium_mg=source_fact.calcium_mg,
        iron_mg=source_fact.iron_mg,
        potassium_mg=source_fact.potassium_mg,
        basis=source_fact.basis,
        barcode=source_fact.barcode,
        verified_by_user=True,
        created_by=current_user.id,
    )
    session.add(clone)
    await session.flush()

    item.catalog_ref_id = clone.id
    item.source = "user_corrected"
    await session.flush()

    await AuditEventRepository(session).record(
        user_id=current_user.id,
        entity_type="nutrient_fact",
        entity_id=clone.id,
        action="create",
        actor="user",
        message_id=None,
        before={"cloned_from_id": str(source_fact.id)},
        after={"cloned_from_id": str(source_fact.id), "canonical_name": clone.canonical_name},
    )
    return CloneFactOut(fact_id=clone.id)


# ---------------------------------------------------------------------------
# SP-185 — criação estruturada de registros (formulário de /day/[date])
# ---------------------------------------------------------------------------


def _create_food_specs(items: list[FoodItemCreateIn]) -> list[FoodItemSpec]:
    return [
        FoodItemSpec(
            detected_name=i.detected_name,
            grams=Decimal(str(i.grams)) if i.grams is not None else None,
            ml=Decimal(str(i.ml)) if i.ml is not None else None,
            quantity=Decimal(str(i.quantity)) if i.quantity is not None else None,
            unit=i.unit,
            brand=i.brand,
        )
        for i in items
    ]


@router.post("/food", response_model=FoodCreateOut, status_code=status.HTTP_201_CREATED)
async def create_food_record(
    payload: FoodCreateIn,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> FoodCreateOut:
    service = StructuredRegistrationService(session)
    try:
        result = await service.create_food(
            user=current_user,
            log_date=payload.log_date,
            meal_slot=payload.meal_slot,
            occurred_at=payload.occurred_at,
            items=_create_food_specs(payload.items),
        )
    except DayClosedError as exc:
        raise ConflictError("day is closed", code="conflict_closed_day") from exc
    return FoodCreateOut(
        food_record_id=result.food_record.id, item_ids=[i.id for i in result.items]
    )


@router.post("/water", response_model=RecordCreateOut, status_code=status.HTTP_201_CREATED)
async def create_water_record(
    payload: WaterCreateIn,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> RecordCreateOut:
    service = StructuredRegistrationService(session)
    try:
        record = await service.create_water(
            user=current_user,
            log_date=payload.log_date,
            volume_ml=payload.volume_ml,
            occurred_at=payload.occurred_at,
        )
    except DayClosedError as exc:
        raise ConflictError("day is closed", code="conflict_closed_day") from exc
    return RecordCreateOut(id=record.id)


@router.post("/beverage", response_model=RecordCreateOut, status_code=status.HTTP_201_CREATED)
async def create_beverage_record(
    payload: BeverageCreateIn,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> RecordCreateOut:
    service = StructuredRegistrationService(session)
    try:
        record = await service.create_beverage(
            user=current_user,
            log_date=payload.log_date,
            detected_name=payload.detected_name,
            volume_ml=payload.volume_ml,
            occurred_at=payload.occurred_at,
        )
    except DayClosedError as exc:
        raise ConflictError("day is closed", code="conflict_closed_day") from exc
    return RecordCreateOut(id=record.id)


@router.post("/activity", response_model=RecordCreateOut, status_code=status.HTTP_201_CREATED)
async def create_activity_record(
    payload: ActivityCreateIn,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> RecordCreateOut:
    service = StructuredRegistrationService(session)
    try:
        record = await service.create_activity(
            user=current_user,
            log_date=payload.log_date,
            detected_name=payload.detected_name,
            activity_type=payload.activity_type,
            duration_minutes=Decimal(str(payload.duration_minutes)),
            intensity=payload.intensity,
            kcal_burned=Decimal(str(payload.kcal_burned))
            if payload.kcal_burned is not None
            else None,
            occurred_at=payload.occurred_at,
        )
    except DayClosedError as exc:
        raise ConflictError("day is closed", code="conflict_closed_day") from exc
    return RecordCreateOut(id=record.id)
