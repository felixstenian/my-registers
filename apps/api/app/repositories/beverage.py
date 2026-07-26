import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import BeverageRecord


class BeverageRecordRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        *,
        user_id: uuid.UUID,
        day_log_id: uuid.UUID,
        message_id: uuid.UUID | None,
        occurred_at: datetime,
        detected_name: str,
        normalized_name: str,
        brand: str | None,
        volume_ml: int,
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
    ) -> BeverageRecord:
        record = BeverageRecord(
            user_id=user_id,
            day_log_id=day_log_id,
            message_id=message_id,
            occurred_at=occurred_at,
            detected_name=detected_name,
            normalized_name=normalized_name,
            brand=brand,
            volume_ml=volume_ml,
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
        self.session.add(record)
        await self.session.flush()
        return record
