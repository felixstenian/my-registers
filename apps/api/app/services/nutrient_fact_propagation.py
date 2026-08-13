"""NutrientFactPropagationService — SP-163 / INV-14.

Ao editar um `NutrientFact` (PATCH /nutrient-facts/{id}), propaga os novos
valores por 100g/ml para todos os `food_items` e `beverage_records` vivos
(`deleted_at IS NULL`) que o referenciam via `catalog_ref_id`.

- Itens em dias **abertos**: recomputam macros via `NutritionCalculator`,
  snapshot do dia recomputado (Const. Art. III §10).
- Itens em dias **fechados**: pulam ( Const. Art. VIII §28 — dia fechado é
  imutável) e são listados em `propagation_skipped`.

Auditoria (Art. III §11): cada item propagado grava `audit_events` com
`action='propagate'`, `before`/`after` dos macros.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.nutrition.catalog import CatalogHit
from app.models import BeverageRecord, DayLog, FoodItem, FoodRecord, NutrientFact
from app.repositories.food import AuditEventRepository
from app.services.daily_recompute import DailyRecomputeService
from app.services.nutrition_calculator import NutritionCalculator

_MACRO_FIELDS = (
    "kcal",
    "protein_g",
    "carbs_g",
    "fat_g",
    "fiber_g",
    "sodium_mg",
    "calcium_mg",
    "iron_mg",
    "potassium_mg",
)


@dataclass(slots=True)
class PropagationResult:
    propagated_food_items: int = 0
    propagated_beverage_records: int = 0
    propagation_skipped: list[dict[str, Any]] = field(default_factory=list)
    recomputed_day_logs: list[str] = field(default_factory=list)


class NutrientFactPropagationService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.audit = AuditEventRepository(session)
        self.recompute = DailyRecomputeService(session)

    async def propagate(
        self,
        *,
        user_id: uuid.UUID,
        fact: NutrientFact,
    ) -> PropagationResult:
        hit = CatalogHit.from_model(fact)
        result = PropagationResult()
        affected_day_logs: set[uuid.UUID] = set()

        affected_day_logs |= await self._propagate_food_items(
            user_id=user_id,
            fact_id=fact.id,
            hit=hit,
            result=result,
        )
        affected_day_logs |= await self._propagate_beverage_records(
            user_id=user_id,
            fact_id=fact.id,
            hit=hit,
            result=result,
        )

        for day_log_id in affected_day_logs:
            await self.recompute.recompute(day_log_id)
            result.recomputed_day_logs.append(str(day_log_id))

        return result

    async def _propagate_food_items(
        self,
        *,
        user_id: uuid.UUID,
        fact_id: uuid.UUID,
        hit: CatalogHit,
        result: PropagationResult,
    ) -> set[uuid.UUID]:
        stmt = (
            select(FoodItem, FoodRecord, DayLog)
            .join(FoodRecord, FoodRecord.id == FoodItem.food_record_id)
            .join(DayLog, DayLog.id == FoodRecord.day_log_id)
            .where(
                FoodItem.catalog_ref_id == fact_id,
                FoodItem.deleted_at.is_(None),
                FoodRecord.user_id == user_id,
            )
        )
        rows = (await self.session.execute(stmt)).all()
        affected: set[uuid.UUID] = set()

        for item, food_record, day_log in rows:
            if day_log.status == "closed":
                result.propagation_skipped.append(
                    {
                        "entity_type": "food_item",
                        "entity_id": str(item.id),
                        "day_log_id": str(day_log.id),
                        "reason": "day_closed",
                    }
                )
                continue

            before = {f: _dec(getattr(item, f)) for f in _MACRO_FIELDS}
            computed = NutritionCalculator.compute(
                hit=hit, grams=item.grams, ml=item.ml
            )
            for f in _MACRO_FIELDS:
                setattr(item, f, getattr(computed, f))
            item.source = "user_corrected"
            await self.session.flush()

            after = {f: _dec(getattr(item, f)) for f in _MACRO_FIELDS}
            await self.audit.record(
                user_id=user_id,
                entity_type="food_item",
                entity_id=item.id,
                action="propagate",
                actor="user",
                message_id=None,
                before=before,
                after=after,
            )
            affected.add(food_record.day_log_id)
            result.propagated_food_items += 1

        return affected

    async def _propagate_beverage_records(
        self,
        *,
        user_id: uuid.UUID,
        fact_id: uuid.UUID,
        hit: CatalogHit,
        result: PropagationResult,
    ) -> set[uuid.UUID]:
        stmt = (
            select(BeverageRecord, DayLog)
            .join(DayLog, DayLog.id == BeverageRecord.day_log_id)
            .where(
                BeverageRecord.catalog_ref_id == fact_id,
                BeverageRecord.deleted_at.is_(None),
                BeverageRecord.user_id == user_id,
            )
        )
        rows = (await self.session.execute(stmt)).all()
        affected: set[uuid.UUID] = set()

        for record, day_log in rows:
            if day_log.status == "closed":
                result.propagation_skipped.append(
                    {
                        "entity_type": "beverage_record",
                        "entity_id": str(record.id),
                        "day_log_id": str(day_log.id),
                        "reason": "day_closed",
                    }
                )
                continue

            before = {f: _dec(getattr(record, f)) for f in _MACRO_FIELDS}
            computed = NutritionCalculator.compute(
                hit=hit, grams=None, ml=Decimal(str(record.volume_ml))
            )
            for f in _MACRO_FIELDS:
                setattr(record, f, getattr(computed, f))
            record.source = "user_corrected"
            await self.session.flush()

            after = {f: _dec(getattr(record, f)) for f in _MACRO_FIELDS}
            await self.audit.record(
                user_id=user_id,
                entity_type="beverage_record",
                entity_id=record.id,
                action="propagate",
                actor="user",
                message_id=None,
                before=before,
                after=after,
            )
            affected.add(record.day_log_id)
            result.propagated_beverage_records += 1

        return affected


def _dec(value: Decimal | None) -> float | None:
    return float(value) if value is not None else None