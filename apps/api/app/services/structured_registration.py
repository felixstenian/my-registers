"""StructuredRegistrationService — criação estruturada de registros (SP-185).

Sem LLM: o formulário de `/day/[date]` envia valores já estruturados. O backend
resolve o `day_log` por data (default hoje — `local_today`), valida dia aberto e
não-futuro (INV-25), e cria comida/água/bebida/atividade com cálculo
determinístico (Art. II §5), auditoria (Art. III §11) e recompute do snapshot
(Art. III §10). Reusa os mesmos repositories/services do fluxo via chat.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ValidationAppError
from app.integrations.nutrition.catalog import LookupQuery
from app.integrations.nutrition.local_tbca import LocalTBCACatalog
from app.integrations.nutrition.normalize import normalize_name
from app.models import (
    ActivityRecord,
    BeverageRecord,
    DayLog,
    FoodItem,
    FoodRecord,
    User,
    WaterRecord,
)
from app.repositories.activity import ActivityRecordRepository
from app.repositories.beverage import BeverageRecordRepository
from app.repositories.day_log import DayLogRepository
from app.repositories.food import (
    AuditEventRepository,
    FoodItemRepository,
    FoodRecordRepository,
)
from app.repositories.hydration import WaterRecordRepository
from app.services.activity_calculator import ActivityCalculator
from app.services.chat import local_today
from app.services.correction import DayClosedError
from app.services.daily_recompute import DailyRecomputeService
from app.services.nutrition_calculator import NutritionCalculator


@dataclass(slots=True)
class FoodItemSpec:
    detected_name: str
    grams: Decimal | None
    ml: Decimal | None
    quantity: Decimal | None
    unit: str | None
    brand: str | None


@dataclass(slots=True)
class FoodCreation:
    food_record: FoodRecord
    items: list[FoodItem]


class StructuredRegistrationService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.day_logs = DayLogRepository(session)
        self.food_records = FoodRecordRepository(session)
        self.food_items = FoodItemRepository(session)
        self.water = WaterRecordRepository(session)
        self.beverage = BeverageRecordRepository(session)
        self.activity = ActivityRecordRepository(session)
        self.audit = AuditEventRepository(session)
        self.recompute = DailyRecomputeService(session)

    async def resolve_day_log(self, *, user: User, log_date: date | None) -> DayLog:
        target = log_date or local_today(user.timezone)
        if target > local_today(user.timezone):
            raise ValidationAppError("não é possível registrar em data futura", code="future_date")
        day_log = await self.day_logs.get_or_create(user_id=user.id, log_date=target)
        if day_log.status == "closed":
            raise DayClosedError()
        return day_log

    async def create_food(
        self,
        *,
        user: User,
        log_date: date | None,
        meal_slot: str,
        occurred_at: datetime | None,
        items: list[FoodItemSpec],
    ) -> FoodCreation:
        day_log = await self.resolve_day_log(user=user, log_date=log_date)
        occurred = occurred_at or datetime.now(UTC)
        catalog = LocalTBCACatalog(self.session)

        record = await self.food_records.create(
            user_id=user.id,
            day_log_id=day_log.id,
            message_id=None,
            meal_slot=meal_slot,
            occurred_at=occurred,
        )

        created: list[FoodItem] = []
        for spec in items:
            normalized = normalize_name(spec.detected_name)
            hit = await catalog.lookup(LookupQuery(name=normalized, brand=spec.brand))
            computed = NutritionCalculator.compute(hit=hit, grams=spec.grams, ml=spec.ml)
            item = await self.food_items.create(
                food_record_id=record.id,
                detected_name=spec.detected_name,
                normalized_name=normalized,
                brand=spec.brand,
                quantity=spec.quantity,
                unit=spec.unit,
                grams=spec.grams,
                ml=spec.ml,
                source="manual",
                confidence=None,
                is_estimate=False,
                needs_confirmation=False,
                catalog_ref_id=uuid.UUID(hit.fact_id) if hit else None,
                kcal=computed.kcal,
                protein_g=computed.protein_g,
                carbs_g=computed.carbs_g,
                fat_g=computed.fat_g,
                fiber_g=computed.fiber_g,
                sodium_mg=computed.sodium_mg,
                calcium_mg=computed.calcium_mg,
                iron_mg=computed.iron_mg,
                potassium_mg=computed.potassium_mg,
            )
            created.append(item)

        await self.audit.record(
            user_id=user.id,
            entity_type="food_record",
            entity_id=record.id,
            action="create",
            actor="user",
            message_id=None,
            after={
                "meal_slot": meal_slot,
                "occurred_at": occurred.isoformat(),
                "item_ids": [str(i.id) for i in created],
            },
        )
        await self.recompute.recompute(day_log.id)
        return FoodCreation(food_record=record, items=created)

    async def create_water(
        self,
        *,
        user: User,
        log_date: date | None,
        volume_ml: int,
        occurred_at: datetime | None,
    ) -> WaterRecord:
        day_log = await self.resolve_day_log(user=user, log_date=log_date)
        occurred = occurred_at or datetime.now(UTC)
        record = await self.water.create(
            user_id=user.id,
            day_log_id=day_log.id,
            message_id=None,
            occurred_at=occurred,
            volume_ml=volume_ml,
            source="manual",
            confidence=None,
            is_estimate=False,
        )
        await self.audit.record(
            user_id=user.id,
            entity_type="water_record",
            entity_id=record.id,
            action="create",
            actor="user",
            message_id=None,
            after={"volume_ml": volume_ml, "occurred_at": occurred.isoformat()},
        )
        await self.recompute.recompute(day_log.id)
        return record

    async def create_beverage(
        self,
        *,
        user: User,
        log_date: date | None,
        detected_name: str,
        volume_ml: int,
        occurred_at: datetime | None,
    ) -> BeverageRecord:
        day_log = await self.resolve_day_log(user=user, log_date=log_date)
        occurred = occurred_at or datetime.now(UTC)
        normalized = normalize_name(detected_name)
        catalog = LocalTBCACatalog(self.session)
        hit = await catalog.lookup(LookupQuery(name=normalized, brand=None))
        computed = NutritionCalculator.compute(hit=hit, grams=None, ml=Decimal(volume_ml))

        record = await self.beverage.create(
            user_id=user.id,
            day_log_id=day_log.id,
            message_id=None,
            occurred_at=occurred,
            detected_name=detected_name,
            normalized_name=normalized,
            brand=None,
            volume_ml=volume_ml,
            source="manual",
            confidence=None,
            is_estimate=False,
            needs_confirmation=False,
            catalog_ref_id=uuid.UUID(hit.fact_id) if hit else None,
            kcal=computed.kcal,
            protein_g=computed.protein_g,
            carbs_g=computed.carbs_g,
            fat_g=computed.fat_g,
            fiber_g=computed.fiber_g,
            sodium_mg=computed.sodium_mg,
            calcium_mg=computed.calcium_mg,
            iron_mg=computed.iron_mg,
            potassium_mg=computed.potassium_mg,
        )
        await self.audit.record(
            user_id=user.id,
            entity_type="beverage_record",
            entity_id=record.id,
            action="create",
            actor="user",
            message_id=None,
            after={
                "volume_ml": volume_ml,
                "detected_name": detected_name,
                "occurred_at": occurred.isoformat(),
            },
        )
        await self.recompute.recompute(day_log.id)
        return record

    async def create_activity(
        self,
        *,
        user: User,
        log_date: date | None,
        detected_name: str,
        activity_type: str,
        duration_minutes: Decimal,
        intensity: str,
        kcal_burned: Decimal | None,
        occurred_at: datetime | None,
    ) -> ActivityRecord:
        day_log = await self.resolve_day_log(user=user, log_date=log_date)
        occurred = occurred_at or datetime.now(UTC)

        if kcal_burned is not None:
            met_value = ActivityCalculator.lookup_met(activity_type, intensity)
            calc_method = "user_manual"
        else:
            if user.weight_kg is None:
                raise ValidationAppError(
                    "peso não informado; informe kcal ou cadastre o peso",
                    code="weight_kg_required",
                )
            computation = ActivityCalculator.compute(
                activity_type=activity_type,
                intensity=intensity,
                duration_minutes=duration_minutes,
                weight_kg=Decimal(str(user.weight_kg)),
            )
            kcal_burned = computation.kcal_burned
            met_value = computation.met_value
            calc_method = computation.calc_method

        record = await self.activity.create(
            user_id=user.id,
            day_log_id=day_log.id,
            message_id=None,
            occurred_at=occurred,
            detected_name=detected_name,
            normalized_name=normalize_name(detected_name),
            activity_type=activity_type,
            duration_minutes=duration_minutes,
            distance_km=None,
            intensity=intensity,
            met_value=met_value,
            kcal_burned=kcal_burned,
            calc_method=calc_method,
            confidence=None,
        )
        await self.audit.record(
            user_id=user.id,
            entity_type="activity_record",
            entity_id=record.id,
            action="create",
            actor="user",
            message_id=None,
            after={
                "activity_type": activity_type,
                "duration_minutes": float(duration_minutes),
                "kcal_burned": float(kcal_burned),
                "calc_method": calc_method,
                "occurred_at": occurred.isoformat(),
            },
        )
        await self.recompute.recompute(day_log.id)
        return record
