import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ActivityRecord


class ActivityRecordRepository:
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
        activity_type: str,
        duration_minutes: Decimal,
        distance_km: Decimal | None,
        intensity: str,
        met_value: Decimal | None,
        kcal_burned: Decimal,
        calc_method: str,
        confidence: Decimal | None,
        notes: str | None = None,
    ) -> ActivityRecord:
        record = ActivityRecord(
            user_id=user_id,
            day_log_id=day_log_id,
            message_id=message_id,
            occurred_at=occurred_at,
            detected_name=detected_name,
            normalized_name=normalized_name,
            activity_type=activity_type,
            duration_minutes=duration_minutes,
            distance_km=distance_km,
            intensity=intensity,
            met_value=met_value,
            kcal_burned=kcal_burned,
            calc_method=calc_method,
            confidence=confidence,
            notes=notes,
        )
        self.session.add(record)
        await self.session.flush()
        return record
