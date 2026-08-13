"""MealService — cria food_records + food_items a partir do envelope validado da LLM.

Cobre SP-20 (texto com quantidades explícitas), SP-21 (unidade doméstica),
SP-22 (foto sem texto → estimativa), SP-23 (não encontrado no catálogo),
SP-24 (confiança baixa → needs_confirmation), SP-25 (múltiplas fotos → 1
food_record), SP-26 (meal_slot indefinido → unspecified).

Regra de ouro (Const. Art. II §5, INV-1): a LLM entrega itens estruturados;
o cálculo nutricional é 100% deterministico neste service.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.nutrition.catalog import LookupQuery, NutritionCatalog
from app.integrations.nutrition.normalize import normalize_name
from app.models import FoodItem, FoodRecord, User
from app.repositories.food import (
    AuditEventRepository,
    FoodItemRepository,
    FoodRecordRepository,
)
from app.schemas.llm import FoodItemIn, LLMEnvelope
from app.services.nutrition_calculator import (
    NutritionCalculator,
)

LOW_CONFIDENCE_THRESHOLD = Decimal("0.5")


@dataclass(slots=True)
class MealResult:
    food_record: FoodRecord
    items: list[FoodItem]
    warnings: list[dict[str, Any]]


class MealService:
    def __init__(self, session: AsyncSession, catalog: NutritionCatalog) -> None:
        self.session = session
        self.catalog = catalog
        self.food_records = FoodRecordRepository(session)
        self.food_items = FoodItemRepository(session)
        self.audit = AuditEventRepository(session)

    async def create_from_llm(
        self,
        *,
        user: User,
        day_log_id: uuid.UUID,
        message_id: uuid.UUID | None,
        envelope: LLMEnvelope,
        occurred_at: datetime | None = None,
    ) -> MealResult:
        if not envelope.food_items:
            raise ValueError("envelope has no food_items")

        meal_slot = envelope.meal_slot or "unspecified"
        occurred = occurred_at or envelope.occurred_at_hint or datetime.now(UTC)

        record = await self.food_records.create(
            user_id=user.id,
            day_log_id=day_log_id,
            message_id=message_id,
            meal_slot=meal_slot,
            occurred_at=occurred,
        )

        created_items: list[FoodItem] = []
        warnings: list[dict[str, Any]] = []

        for entry in envelope.food_items:
            item, item_warnings = await self._create_item(record.id, entry)
            created_items.append(item)
            warnings.extend(item_warnings)

        await self.audit.record(
            user_id=user.id,
            entity_type="food_record",
            entity_id=record.id,
            action="create",
            actor="llm",
            message_id=message_id,
            after={
                "meal_slot": meal_slot,
                "occurred_at": occurred.isoformat(),
                "item_ids": [str(i.id) for i in created_items],
            },
        )

        return MealResult(food_record=record, items=created_items, warnings=warnings)

    async def _create_item(
        self, food_record_id: uuid.UUID, entry: FoodItemIn
    ) -> tuple[FoodItem, list[dict[str, Any]]]:
        normalized = normalize_name(entry.normalized_name or entry.detected_name)
        hit = await self.catalog.lookup(LookupQuery(name=normalized, brand=entry.brand))

        grams = _decimal_or_none(entry.grams_estimate)
        ml = _decimal_or_none(entry.ml_estimate)
        quantity = _decimal_or_none(entry.quantity)
        confidence = Decimal(str(entry.confidence))

        computed = NutritionCalculator.compute(hit=hit, grams=grams, ml=ml)

        # Bloco 5 revisão v1.12: `needs_confirmation` deixou de ser setado.
        # Sinal de "sem catálogo" no frontend passou a ser `has_catalog=false`
        # (derivado de catalog_ref_id IS NULL). SP-24a e todo o fluxo de
        # "confirmação de item" foram removidos. Campo permanece no schema
        # (não muda migration) mas é sempre False daqui pra frente.
        item = await self.food_items.create(
            food_record_id=food_record_id,
            detected_name=entry.detected_name,
            normalized_name=normalized,
            brand=entry.brand,
            quantity=quantity,
            unit=entry.unit,
            grams=grams,
            ml=ml,
            source="llm",
            confidence=confidence,
            is_estimate=entry.is_estimate,
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

        item_warnings: list[dict[str, Any]] = []
        if hit is None:
            item_warnings.append(
                {
                    "code": "no_catalog_hit",
                    "item_id": str(item.id),
                    "detected_name": entry.detected_name,
                }
            )
        if confidence < LOW_CONFIDENCE_THRESHOLD:
            item_warnings.append(
                {
                    "code": "low_confidence_item",
                    "item_id": str(item.id),
                    "confidence": float(confidence),
                }
            )
        for reason in computed.reasons:
            if reason.startswith("missing_"):
                item_warnings.append({"code": reason, "item_id": str(item.id)})
        return item, item_warnings


def _decimal_or_none(value: float | None) -> Decimal | None:
    if value is None:
        return None
    return Decimal(str(value))
