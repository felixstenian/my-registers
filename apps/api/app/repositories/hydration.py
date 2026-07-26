import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import WaterRecord


class WaterRecordRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        *,
        user_id: uuid.UUID,
        day_log_id: uuid.UUID,
        message_id: uuid.UUID | None,
        occurred_at: datetime,
        volume_ml: int,
        source: str,
        confidence: Decimal | None,
        is_estimate: bool,
    ) -> WaterRecord:
        record = WaterRecord(
            user_id=user_id,
            day_log_id=day_log_id,
            message_id=message_id,
            occurred_at=occurred_at,
            volume_ml=volume_ml,
            source=source,
            confidence=confidence,
            is_estimate=is_estimate,
        )
        self.session.add(record)
        await self.session.flush()
        return record
