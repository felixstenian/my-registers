import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ActivityRecord


class ActivityRecordRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_workout_session(self, session_id: uuid.UUID) -> ActivityRecord | None:
        """SP-126/INV-17: activity_record consolidado de uma sessão de
        treino (upsert por `workout_session_id` — não duplica em
        reconsoidação). Só busca não-deletado."""
        stmt = select(ActivityRecord).where(
            ActivityRecord.workout_session_id == session_id,
            ActivityRecord.deleted_at.is_(None),
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

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
        kcal_burned: Decimal | None,
        calc_method: str,
        confidence: Decimal | None,
        notes: str | None = None,
        workout_session_id: uuid.UUID | None = None,
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
            workout_session_id=workout_session_id,
        )
        self.session.add(record)
        await self.session.flush()
        return record
