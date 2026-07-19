import uuid
from datetime import date

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import DayLog


class DayLogRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, *, user_id: uuid.UUID, log_date: date) -> DayLog | None:
        stmt = select(DayLog).where(DayLog.user_id == user_id, DayLog.log_date == log_date)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def get_or_create(self, *, user_id: uuid.UUID, log_date: date) -> DayLog:
        """Idempotente. Usa INSERT ... ON CONFLICT DO NOTHING para evitar corrida.

        A UNIQUE(user_id, log_date) protege contra duplicatas mesmo com
        múltiplas requisições simultâneas.
        """
        stmt = (
            pg_insert(DayLog)
            .values(user_id=user_id, log_date=log_date)
            .on_conflict_do_nothing(index_elements=["user_id", "log_date"])
        )
        await self.session.execute(stmt)
        await self.session.flush()
        existing = await self.get(user_id=user_id, log_date=log_date)
        assert existing is not None, "day_log should exist after upsert"
        return existing
