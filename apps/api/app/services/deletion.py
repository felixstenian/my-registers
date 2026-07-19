"""DeletionService — soft delete de qualquer tipo de registro.

SP-80/SP-81/SP-82 + INV-5/INV-10. Idempotente: chamada em registro já
apagado é no-op (`already_deleted=True` no resultado).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ValidationAppError
from app.models import (
    ActivityRecord,
    BeverageRecord,
    DayLog,
    FoodItem,
    User,
    WaterRecord,
)
from app.repositories.food import AuditEventRepository
from app.schemas.llm import LLMEnvelope
from app.services.correction import DayClosedError, _snapshot
from app.services.correction_matcher import Candidate, TargetKind, TargetMatcher


@dataclass(slots=True)
class DeletionResult:
    kind: TargetKind
    entity_id: uuid.UUID
    day_log_id: uuid.UUID
    already_deleted: bool


class DeletionService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.matcher = TargetMatcher(session)
        self.audit = AuditEventRepository(session)

    async def apply_from_llm(
        self,
        *,
        user: User,
        day_log_id: uuid.UUID,
        message_id: uuid.UUID | None,
        envelope: LLMEnvelope,
    ) -> DeletionResult:
        if envelope.deletion is None:
            raise ValidationAppError(
                "envelope missing deletion block",
                code="invalid_deletion_envelope",
            )
        await _ensure_day_open(self.session, day_log_id)

        candidate = await self.matcher.resolve(
            day_log_id=day_log_id,
            target_hint=envelope.deletion.target_hint,
        )
        return await self._soft_delete(user, candidate, message_id)

    async def delete_by_id(
        self,
        *,
        user: User,
        kind: TargetKind,
        entity_id: uuid.UUID,
        message_id: uuid.UUID | None = None,
    ) -> DeletionResult:
        """Path direto para os endpoints REST (SP-81 idempotente)."""
        entity = await _load_by_id(self.session, kind, entity_id, user.id)
        if entity is None:
            raise ValidationAppError(
                "target not found", code="target_not_found"
            )
        await _ensure_day_open(self.session, entity.day_log_id)
        candidate = Candidate(
            kind=kind, entity_id=entity_id, entity=entity, score=0
        )
        return await self._soft_delete(user, candidate, message_id)

    async def _soft_delete(
        self,
        user: User,
        candidate: Candidate,
        message_id: uuid.UUID | None,
    ) -> DeletionResult:
        entity = candidate.entity
        day_log_id = await _resolve_day_log_id(
            self.session, entity, candidate.kind
        )
        if entity.deleted_at is not None:
            # SP-81: idempotente — 2ª chamada é no-op.
            return DeletionResult(
                kind=candidate.kind,
                entity_id=candidate.entity_id,
                day_log_id=day_log_id,
                already_deleted=True,
            )

        before = _snapshot(entity, candidate.kind)
        entity.deleted_at = datetime.now(UTC)
        await self.session.flush()

        await self.audit.record(
            user_id=user.id,
            entity_type=_entity_type_for_audit(candidate.kind),
            entity_id=candidate.entity_id,
            action="delete",
            actor="llm" if message_id else "user",
            message_id=message_id,
            before=before,
            after=None,
        )
        return DeletionResult(
            kind=candidate.kind,
            entity_id=candidate.entity_id,
            day_log_id=day_log_id,
            already_deleted=False,
        )


async def _ensure_day_open(session: AsyncSession, day_log_id: uuid.UUID) -> None:
    day_log = await session.get(DayLog, day_log_id)
    if day_log is None:
        raise ValidationAppError(
            f"day_log {day_log_id} not found", code="day_log_not_found"
        )
    if day_log.status == "closed":
        raise DayClosedError()


async def _load_by_id(
    session: AsyncSession,
    kind: TargetKind,
    entity_id: uuid.UUID,
    user_id: uuid.UUID,
) -> Any | None:
    from sqlalchemy import select

    model = {
        TargetKind.FOOD: FoodItem,
        TargetKind.WATER: WaterRecord,
        TargetKind.BEVERAGE: BeverageRecord,
        TargetKind.ACTIVITY: ActivityRecord,
    }[kind]
    if kind == TargetKind.FOOD:
        # food_item herda user_id pelo food_record; join implícito via food_record
        from app.models import FoodRecord

        stmt = (
            select(FoodItem)
            .join(FoodRecord, FoodRecord.id == FoodItem.food_record_id)
            .where(FoodItem.id == entity_id, FoodRecord.user_id == user_id)
        )
        entity = (await session.execute(stmt)).scalar_one_or_none()
        if entity is not None:
            entity.day_log_id = (
                await session.get(FoodRecord, entity.food_record_id)
            ).day_log_id
        return entity
    stmt = select(model).where(
        model.id == entity_id, model.user_id == user_id
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def _resolve_day_log_id(
    session: AsyncSession, entity: Any, kind: TargetKind
) -> uuid.UUID:
    if kind == TargetKind.FOOD:
        # FoodItem não tem day_log_id direto — está em FoodRecord.
        # Alguns paths (delete_by_id via REST) já pré-populam entity.day_log_id;
        # senão resolve via food_record_id.
        cached = getattr(entity, "day_log_id", None)
        # Alguns paths pré-populam entity.day_log_id (delete_by_id no REST);
        # se veio como UUID válido, usa direto.
        if isinstance(cached, uuid.UUID):
            return cached
        from app.models import FoodRecord

        record = await session.get(FoodRecord, entity.food_record_id)
        assert record is not None
        return record.day_log_id
    return entity.day_log_id


def _entity_type_for_audit(kind: TargetKind) -> str:
    return {
        TargetKind.FOOD: "food_item",
        TargetKind.WATER: "water_record",
        TargetKind.BEVERAGE: "beverage_record",
        TargetKind.ACTIVITY: "activity_record",
    }[kind]
