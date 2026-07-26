import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditEvent, FoodItem, FoodRecord


class FoodRecordRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        *,
        user_id: uuid.UUID,
        day_log_id: uuid.UUID,
        message_id: uuid.UUID | None,
        meal_slot: str,
        occurred_at: datetime,
        notes: str | None = None,
    ) -> FoodRecord:
        record = FoodRecord(
            user_id=user_id,
            day_log_id=day_log_id,
            message_id=message_id,
            meal_slot=meal_slot,
            occurred_at=occurred_at,
            notes=notes,
        )
        self.session.add(record)
        await self.session.flush()
        return record


class FoodItemRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        *,
        food_record_id: uuid.UUID,
        detected_name: str,
        normalized_name: str,
        brand: str | None,
        quantity: Decimal | None,
        unit: str | None,
        grams: Decimal | None,
        ml: Decimal | None,
        source: str,
        confidence: Decimal | None,
        is_estimate: bool,
        needs_confirmation: bool,
        catalog_ref_id: uuid.UUID | None,
        kcal: Decimal,
        protein_g: Decimal,
        carbs_g: Decimal,
        fat_g: Decimal,
        fiber_g: Decimal,
        sodium_mg: Decimal,
        calcium_mg: Decimal,
        iron_mg: Decimal,
        potassium_mg: Decimal,
    ) -> FoodItem:
        item = FoodItem(
            food_record_id=food_record_id,
            detected_name=detected_name,
            normalized_name=normalized_name,
            brand=brand,
            quantity=quantity,
            unit=unit,
            grams=grams,
            ml=ml,
            source=source,
            confidence=confidence,
            is_estimate=is_estimate,
            needs_confirmation=needs_confirmation,
            catalog_ref_id=catalog_ref_id,
            kcal=kcal,
            protein_g=protein_g,
            carbs_g=carbs_g,
            fat_g=fat_g,
            fiber_g=fiber_g,
            sodium_mg=sodium_mg,
            calcium_mg=calcium_mg,
            iron_mg=iron_mg,
            potassium_mg=potassium_mg,
        )
        self.session.add(item)
        await self.session.flush()
        return item

    async def list_alive_for_day(self, day_log_id: uuid.UUID) -> list[FoodItem]:
        stmt = (
            select(FoodItem)
            .join(FoodRecord, FoodRecord.id == FoodItem.food_record_id)
            .where(
                FoodRecord.day_log_id == day_log_id,
                FoodRecord.deleted_at.is_(None),
                FoodItem.deleted_at.is_(None),
            )
        )
        return list((await self.session.execute(stmt)).scalars())


class AuditEventRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def record(
        self,
        *,
        user_id: uuid.UUID,
        entity_type: str,
        entity_id: uuid.UUID,
        action: str,
        actor: str,
        message_id: uuid.UUID | None,
        before: dict[str, Any] | None = None,
        after: dict[str, Any] | None = None,
    ) -> AuditEvent:
        event = AuditEvent(
            user_id=user_id,
            entity_type=entity_type,
            entity_id=entity_id,
            action=action,
            actor=actor,
            message_id=message_id,
            before=before,
            after=after,
        )
        self.session.add(event)
        await self.session.flush()
        return event
